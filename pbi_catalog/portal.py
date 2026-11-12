"""
Static HTML Catalog, Workspaces & Reports Map, Interactive Live Lineage Explorer,
and Executive Semantic Model Documentation Generator.
100% offline-capable, zero external CDN dependencies, vendor-neutral, and designed for effortless reading.
"""

from __future__ import annotations

import base64
import collections
import datetime
import json
import re
from pathlib import Path

from .analyzer import analyze_model
from .security import esc, mask_secrets, slugify
from .store import CatalogStore


def _load_mermaid_bytes() -> bytes:
    """Decode embedded offline mermaid.min.js from root mermaid_js.py if available."""
    try:
        import sys

        root_dir = str(Path(__file__).resolve().parent.parent)
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
        from mermaid_js import MERMAID_B64  # type: ignore

        return base64.b64decode(MERMAID_B64)
    except Exception:
        return b"/* mermaid runtime unavailable */"


def format_dax_pretty(expr: str) -> str:
    """
    Auto-format cramped single-line DAX expressions into clean, readable multi-line DAX,
    while preserving expressions that the model author already indented across multiple lines.
    """
    raw = (expr or "").replace("\r\n", "\n").strip()
    if not raw:
        return ""
    lines = [ln.replace("\t", "    ") for ln in raw.split("\n")]
    if len(lines) >= 3 and any(ln.startswith("  ") for ln in lines[1:]):
        return "\n".join(lines)
    if len(raw) < 68 and "VAR " not in raw.upper() and "RETURN" not in raw.upper():
        return raw

    # Tokenize strings and bracket/table refs safely while formatting parens, commas, VAR, and RETURN
    out: list[str] = []
    indent = 0
    paren_stack: list[bool] = []
    i = 0
    n = len(raw)
    in_str = False
    in_sq = False
    in_br = False

    def _newline(ind: int) -> None:
        while out and out[-1] == " ":
            out.pop()
        out.append("\n" + ("    " * max(0, ind)))

    while i < n:
        ch = raw[i]
        if in_str:
            out.append(ch)
            if ch == '"':
                if i + 1 < n and raw[i + 1] == '"':
                    out.append('"')
                    i += 2
                    continue
                in_str = False
            i += 1
            continue
        if in_sq:
            out.append(ch)
            if ch == "'":
                if i + 1 < n and raw[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                in_sq = False
            i += 1
            continue
        if in_br:
            out.append(ch)
            if ch == "]":
                in_br = False
            i += 1
            continue

        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "'":
            in_sq = True
            out.append(ch)
            i += 1
            continue
        if ch == "[":
            in_br = True
            out.append(ch)
            i += 1
            continue

        # Check VAR / RETURN keywords at word boundaries
        prev_ok = i == 0 or not (raw[i - 1].isalnum() or raw[i - 1] == "_")
        if prev_ok:
            m_kw = re.match(r"(?i)^(VAR|RETURN)\b", raw[i:])
            if m_kw:
                kw = m_kw.group(1).upper()
                if out and out[-1] != "\n":
                    _newline(indent)
                out.append(kw)
                i += len(kw)
                if kw == "RETURN":
                    _newline(indent + 1)
                    while i < n and raw[i].isspace():
                        i += 1
                continue

        if ch == "(":
            # Look ahead to find matching ')' length; keep short simple calls inline like SUM('Fact'[Amt])
            depth = 1
            j = i + 1
            q_s = q_sq = q_b = False
            has_comma = False
            while j < n and depth > 0:
                cj = raw[j]
                if q_s:
                    if cj == '"':
                        q_s = False
                elif q_sq:
                    if cj == "'":
                        q_sq = False
                elif q_b:
                    if cj == "]":
                        q_b = False
                else:
                    if cj == '"':
                        q_s = True
                    elif cj == "'":
                        q_sq = True
                    elif cj == "[":
                        q_b = True
                    elif cj == "(":
                        depth += 1
                    elif cj == ")":
                        depth -= 1
                    elif cj == "," and depth == 1:
                        has_comma = True
                j += 1
            span = j - i
            out.append("(")
            if has_comma and span > 44:
                paren_stack.append(True)
                indent += 1
                _newline(indent)
                i += 1
                while i < n and raw[i].isspace():
                    i += 1
                continue
            paren_stack.append(False)
            i += 1
            continue

        if ch == ",":
            out.append(",")
            if paren_stack and paren_stack[-1]:
                _newline(indent)
                i += 1
                while i < n and raw[i].isspace():
                    i += 1
                continue
            i += 1
            continue

        if ch == ")":
            is_ml = paren_stack.pop() if paren_stack else False
            if is_ml:
                indent = max(0, indent - 1)
                _newline(indent)
            out.append(")")
            i += 1
            continue

        if ch in ("\n", "\r", "\t"):
            if out and out[-1] not in (" ", "\n"):
                out.append(" ")
            i += 1
            continue

        if ch == " " and out and out[-1] in (" ", "\n"):
            i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out).strip()


def extract_m_steps(m_code: str) -> list[dict[str, str]]:
    """Extract ordered Power Query `let ... in` steps with human-readable operation summaries."""
    if not m_code:
        return []
    steps: list[dict[str, str]] = []
    # Match top-level step assignments inside `let ... in`
    step_re = re.compile(r'^\s*(?:#"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*=\s*(.+?)\s*,?\s*$', re.MULTILINE)
    fn_re = re.compile(r"\b([A-Z][A-Za-z0-9]*\.[A-Za-z0-9]+)\s*\(")
    for m in step_re.finditer(m_code):
        raw_name = (m.group(1) or m.group(2) or "").strip()
        if raw_name.lower() in ("let", "in", "section", "shared"):
            continue
        rhs = m.group(3)
        fn_match = fn_re.search(rhs)
        op = fn_match.group(1) if fn_match else ("Expression" if not rhs.startswith("{") else "List")
        steps.append({"name": raw_name, "op": op})
    return steps[:24]


PORTAL_CSS = r"""
:root {
  --bg: #f5f7fb;
  --surface: #ffffff;
  --surface-alt: #eef3f9;
  --fg: #0f172a;
  --fg-muted: #526077;
  --border: #dce3ee;
  --accent: #0b63ce;
  --accent-soft: #e7f0fd;
  --fact: #0b63ce;
  --fact-soft: #e8f1fd;
  --dim: #0f766e;
  --dim-soft: #e6f6f4;
  --ok: #15803d;
  --ok-bg: #dcfce7;
  --warn: #b45309;
  --warn-bg: #fef3c7;
  --bad: #b91c1c;
  --bad-bg: #fee2e2;
  --code-bg: #0f172a;
  --code-fg: #e2e8f0;
  --shadow: 0 2px 10px rgba(15, 23, 42, 0.05);
  --radius: 12px;
}

[data-theme="dark"] {
  --bg: #0b1120;
  --surface: #111827;
  --surface-alt: #1e293b;
  --fg: #e5e7eb;
  --fg-muted: #94a3b8;
  --border: #283548;
  --accent: #60a5fa;
  --accent-soft: #172554;
  --fact: #60a5fa;
  --fact-soft: #172554;
  --dim: #2dd4bf;
  --dim-soft: #134e4a;
  --ok: #4ade80;
  --ok-bg: #052e16;
  --warn: #fbbf24;
  --warn-bg: #451a03;
  --bad: #f87171;
  --bad-bg: #450a0a;
  --code-bg: #090d16;
  --code-fg: #e2e8f0;
  --shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body {
  margin: 0;
  font-family: "Segoe UI", Inter, -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
  background: var(--bg);
  color: var(--fg);
  line-height: 1.58;
  font-size: 14px;
}
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code, pre {
  font-family: "Cascadia Code", Consolas, "SFMono-Regular", Menlo, monospace;
}

/* Catalog Topbar */
.topbar {
  background: linear-gradient(135deg, #072854 0%, #0b63ce 100%);
  color: #fff;
  padding: 24px 32px 0 32px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.14);
}
.topbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  max-width: 1560px;
  margin: 0 auto;
}
.topbar h1 { margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.015em; }
.topbar p { margin: 4px 0 0 0; opacity: 0.9; font-size: 13px; }
.top-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  max-width: 1560px;
  margin: 18px auto 0 auto;
}
.top-tab {
  background: rgba(255,255,255,0.12);
  color: #fff;
  border: none;
  padding: 10px 18px;
  border-radius: 10px 10px 0 0;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s;
}
.top-tab:hover { background: rgba(255,255,255,0.22); }
.top-tab.active {
  background: var(--bg);
  color: var(--fg);
}
.btn-ghost {
  background: rgba(255,255,255,0.15);
  color: #fff;
  border: 1px solid rgba(255,255,255,0.28);
  border-radius: 8px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.btn-ghost:hover { background: rgba(255,255,255,0.25); text-decoration: none; }

.catalog-wrap {
  max-width: 1560px;
  margin: 0 auto;
  padding: 24px 32px 56px 32px;
}
.tab-pane { display: none; }
.tab-pane.active { display: block; }

/* Model Page Layout */
.doc-shell {
  display: grid;
  grid-template-columns: 276px minmax(0, 1fr);
  min-height: 100vh;
}
.doc-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.doc-back {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  padding: 7px 11px;
  border-radius: 8px;
  background: var(--accent-soft);
}
.doc-brand h2 {
  font-size: 16.5px;
  margin: 0;
  line-height: 1.3;
  word-break: break-word;
}
.doc-brand .sub {
  font-size: 12px;
  color: var(--fg-muted);
  margin-top: 4px;
}
.doc-search {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-alt);
  color: var(--fg);
  font-size: 12.5px;
}
.toc-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.toc-list a {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 10px;
  border-radius: 8px;
  color: var(--fg);
  font-size: 13px;
  font-weight: 500;
}
.toc-list a:hover, .toc-list a.active {
  background: var(--accent-soft);
  color: var(--accent);
  text-decoration: none;
}
.toc-count {
  font-size: 11px;
  color: var(--fg-muted);
  background: var(--surface-alt);
  padding: 1px 7px;
  border-radius: 999px;
}
.doc-main {
  padding: 30px 40px 68px 40px;
  max-width: 1400px;
  min-width: 0;
}

/* Sections & KPIs */
.section {
  margin-bottom: 38px;
  scroll-margin-top: 20px;
}
.section-header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border);
  padding-bottom: 10px;
}
.section-header h2 {
  margin: 0;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.01em;
}
.section-header .hint {
  font-size: 12.5px;
  color: var(--fg-muted);
}

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}
.kpi-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 15px 17px;
  box-shadow: var(--shadow);
}
.kpi-card .val {
  font-size: 25px;
  font-weight: 750;
  color: var(--accent);
  line-height: 1.15;
}
.kpi-card .lbl {
  font-size: 12px;
  color: var(--fg-muted);
  margin-top: 4px;
  font-weight: 500;
}

.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 20px;
  box-shadow: var(--shadow);
}

/* Badges */
.badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  background: var(--surface-alt);
  color: var(--fg);
  border: 1px solid var(--border);
  white-space: nowrap;
}
.badge-accent { background: var(--accent-soft); color: var(--accent); border-color: transparent; }
.badge-fact { background: var(--fact-soft); color: var(--fact); border-color: transparent; }
.badge-dim { background: var(--dim-soft); color: var(--dim); border-color: transparent; }
.badge-ok { background: var(--ok-bg); color: var(--ok); border-color: transparent; }
.badge-warn { background: var(--warn-bg); color: var(--warn); border-color: transparent; }
.badge-bad { background: var(--bad-bg); color: var(--bad); border-color: transparent; }

/* Findings */
.finding-list { display: grid; gap: 8px; }
.finding {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 11px 15px;
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface);
}
.finding.bad { border-left: 4px solid var(--bad); background: var(--bad-bg); }
.finding.warn { border-left: 4px solid var(--warn); background: var(--warn-bg); }
.finding.ok { border-left: 4px solid var(--ok); background: var(--ok-bg); }
.finding strong { display: block; font-size: 13.5px; }
.finding span { font-size: 12.5px; color: var(--fg-muted); }

/* Filter Bar & Cards */
.filter-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  margin-bottom: 18px;
  background: var(--surface);
  padding: 12px 16px;
  border-radius: var(--radius);
  border: 1px solid var(--border);
  box-shadow: var(--shadow);
}
.filter-bar input[type="search"] {
  flex: 1 1 280px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-alt);
  color: var(--fg);
  font-size: 13.5px;
}
.chip-btn {
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--fg);
  padding: 6px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}
.chip-btn.active, .chip-btn:hover {
  background: var(--accent);
  color: #fff;
  border-color: var(--accent);
}
.model-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
  gap: 16px;
}
.model-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: transform 0.12s ease, border-color 0.12s ease;
}
.model-card:hover {
  transform: translateY(-2px);
  border-color: var(--accent);
}
.model-card h3 { margin: 0; font-size: 16px; }
.model-meta { display: flex; flex-wrap: wrap; gap: 6px; }
.model-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 6px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  font-size: 12px;
  color: var(--fg-muted);
}
.model-stats b { color: var(--fg); font-size: 14px; display: block; }
.card-eyebrow {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 10.5px;
  font-weight: 750;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--fg-muted);
}
.eyebrow-type {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--accent);
  background: var(--accent-soft);
  padding: 2px 8px;
  border-radius: 6px;
}
.card-footer-meta {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11.5px;
  color: var(--fg-muted);
  padding-top: 6px;
}
.app-switcher {
  display: inline-flex;
  background: rgba(255,255,255,0.12);
  padding: 4px;
  border-radius: 11px;
  border: 1px solid rgba(255,255,255,0.24);
  gap: 4px;
  align-items: center;
}
.app-switcher a, .app-switcher span {
  padding: 6px 12px;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 650;
  text-decoration: none;
  color: #fff;
}
.app-switcher .active-seg {
  background: #fff;
  color: #072854;
  font-weight: 700;
}
.view-toggle {
  display: inline-flex;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 3px;
  gap: 2px;
}
.view-btn {
  border: none;
  background: transparent;
  color: var(--fg-muted);
  padding: 5px 11px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.view-btn.active {
  background: var(--surface);
  color: var(--accent);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
}
.sort-select {
  padding: 6px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--fg);
  font-size: 12px;
  font-weight: 600;
}
.ws-group-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 16px;
  overflow: hidden;
  box-shadow: var(--shadow);
}
.ws-group-card > summary {
  padding: 13px 18px;
  cursor: pointer;
  background: var(--surface-alt);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-weight: 700;
  font-size: 14px;
  list-style: none;
}
.ws-group-card > summary::-webkit-details-marker { display: none; }
.ws-group-body { padding: 14px 16px; }
th.sortable-th { cursor: pointer; user-select: none; }
th.sortable-th:hover { color: var(--accent); }

/* Tables */
.table-scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
table.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
table.data-table th {
  text-align: left;
  padding: 10px 13px;
  background: var(--surface-alt);
  color: var(--fg);
  font-weight: 650;
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
table.data-table td {
  padding: 9px 13px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
table.data-table tr:last-child td { border-bottom: none; }
table.data-table tr:hover td { background: rgba(11, 99, 206, 0.03); }

/* Visual Power Query Pipeline Ribbon */
.pq-pipeline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 10px 12px;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  border-radius: 9px;
  margin: 10px 0;
}
.pq-step {
  display: inline-flex;
  flex-direction: column;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 7px;
  padding: 4px 9px;
  font-size: 11.5px;
  line-height: 1.25;
}
.pq-step b { color: var(--fg); font-weight: 650; }
.pq-step small { color: var(--fg-muted); font-size: 10px; font-family: "Cascadia Code", Consolas, monospace; }
.pq-arrow { color: var(--fg-muted); font-size: 12px; font-weight: 700; }

details.m-script-toggle {
  margin-top: 8px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  overflow: hidden;
}
details.m-script-toggle > summary {
  padding: 8px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  color: var(--accent);
  background: var(--surface-alt);
}

/* Structured DAX Measure Cards */
.dax-table-group {
  margin-bottom: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
}
.dax-table-group > summary {
  padding: 13px 18px;
  cursor: pointer;
  font-weight: 700;
  font-size: 14.5px;
  background: var(--surface-alt);
  display: flex;
  align-items: center;
  justify-content: space-between;
  list-style: none;
}
.dax-table-group > summary::-webkit-details-marker { display: none; }
.dax-folder {
  padding: 16px 18px;
  border-top: 1px solid var(--border);
}
.dax-folder-title {
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--fg-muted);
  margin: 0 0 10px 0;
}
.dax-tier-label {
  font-size: 12.5px;
  font-weight: 650;
  color: var(--accent);
  margin: 12px 0 8px 0;
}
.measure-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(420px, 1fr));
  gap: 12px;
}
.measure-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 13px 15px;
  background: var(--surface);
  scroll-margin-top: 24px;
  display: flex;
  flex-direction: column;
}
.measure-card:target {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.measure-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.measure-name { font-weight: 700; font-size: 14px; color: var(--fg); }
.measure-desc { font-size: 12.5px; color: var(--fg-muted); margin: 2px 0 8px 0; }
.code-block {
  position: relative;
  background: var(--code-bg);
  color: var(--code-fg);
  border-radius: 8px;
  padding: 11px 14px;
  overflow-x: auto;
  font-size: 12.5px;
  line-height: 1.52;
  margin: 4px 0;
}
.code-block pre { margin: 0; white-space: pre-wrap; word-break: break-word; }
.copy-btn {
  position: absolute;
  top: 7px;
  right: 8px;
  background: rgba(255,255,255,0.12);
  color: #cbd5e1;
  border: 1px solid rgba(255,255,255,0.2);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
}
.copy-btn:hover { background: rgba(255,255,255,0.24); color: #fff; }
.kw { color: #93c5fd; font-weight: 600; }
.fn { color: #fde68a; }
.str { color: #86efac; }
.cmt { color: #94a3b8; font-style: italic; }

.dep-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 11.5px;
  color: var(--fg-muted);
}
.dep-chip {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--surface-alt);
  border: 1px solid var(--border);
  color: var(--fg);
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 11px;
}
.dep-chip:hover { border-color: var(--accent); color: var(--accent); text-decoration: none; }

/* Expandable Table Blueprints */
details.table-blueprint {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  margin-bottom: 10px;
  overflow: hidden;
  box-shadow: var(--shadow);
}
details.table-blueprint > summary {
  padding: 12px 16px;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-weight: 650;
  background: var(--surface);
}
details.table-blueprint[open] > summary {
  background: var(--surface-alt);
  border-bottom: 1px solid var(--border);
}
.blueprint-body { padding: 14px 16px; }

/* 3-Panel Interactive Live Lineage Explorer */
.lineage-app {
  display: grid;
  grid-template-columns: 225px minmax(0, 1fr) 265px;
  height: 560px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.lin-left {
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--surface-alt);
}
.lin-left-top {
  padding: 10px;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.lin-left-top input {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
  color: var(--fg);
  font-size: 12px;
}
.lin-layer-pills { display: flex; flex-wrap: wrap; gap: 4px; }
.lin-pill {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--fg-muted);
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.lin-pill.active { background: var(--accent); color: #fff; border-color: var(--accent); }
.lin-nav-list {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.lin-nav-item {
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  color: var(--fg);
  padding: 7px 9px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.lin-nav-item:hover { background: var(--surface); border-color: var(--border); }
.lin-nav-item.active {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}
.lin-nav-item small { color: var(--fg-muted); font-size: 10.5px; }

.lin-center {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: var(--bg);
}
.lin-toolbar {
  padding: 8px 14px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}
.lin-toolbar-actions { display: flex; gap: 6px; align-items: center; }
.lin-btn {
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--fg);
  border-radius: 6px;
  padding: 4px 9px;
  font-size: 11.5px;
  font-weight: 600;
  cursor: pointer;
}
.lin-btn.active, .lin-btn:hover { border-color: var(--accent); color: var(--accent); }
.lin-canvas-scroll { position: relative; flex: 1 1 auto; overflow: auto; padding: 14px 16px; }
.lin-columns {
  position: relative;
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(115px, 1fr);
  gap: 20px;
  width: 100%;
  min-width: 0;
  z-index: 2;
}
.lin-col { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.lin-col-hdr {
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--fg-muted);
  padding-bottom: 5px;
  border-bottom: 2px solid var(--border);
  margin-bottom: 3px;
}
.lin-node {
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 8px;
  padding: 7px 9px;
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(15,23,42,0.05);
  transition: transform 0.1s, border-color 0.12s, opacity 0.15s;
  font-size: 11.5px;
}
.lin-node:hover { border-color: var(--accent); transform: translateY(-1px); }
.lin-node .n-title { font-weight: 650; word-break: break-word; line-height: 1.25; }
.lin-node .n-sub { font-size: 10.5px; color: var(--fg-muted); margin-top: 2px; }
.lin-node.is-focus {
  border-color: var(--accent);
  background: var(--accent-soft);
  box-shadow: 0 0 0 3px rgba(11, 99, 206, 0.18);
}
.lin-node.is-upstream { border-left: 4px solid #0f766e; }
.lin-node.is-downstream { border-left: 4px solid #7c3aed; }
.lin-node.is-muted { opacity: 0.22; }
svg.lin-svg { position: absolute; top: 0; left: 0; pointer-events: none; z-index: 1; }

.lin-right {
  border-left: 1px solid var(--border);
  padding: 14px 16px;
  overflow-y: auto;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: 10px;
  font-size: 12.5px;
}
.lin-right h4 { margin: 0; font-size: 14.5px; word-break: break-word; }
.lin-kv { font-size: 12px; color: var(--fg-muted); }
.lin-list { display: flex; flex-wrap: wrap; gap: 5px; }

/* Interactive Mermaid Relationship Shell (@jakubpokusa PR #10) */
.mermaid-shell {
  margin: 8px 0;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  overflow: hidden;
  box-shadow: var(--shadow);
}
.mermaid-shell.is-fallback-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 9999;
  border-radius: 0;
  display: flex;
  flex-direction: column;
}
body.mermaid-fallback-fullscreen { overflow: hidden; }
.mermaid-toolbar {
  position: sticky;
  top: 0;
  z-index: 2;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--fg-muted);
  font-size: 12px;
}
.mermaid-toolbar .mermaid-hint { margin-right: auto; }
.mermaid-toolbar button {
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--fg);
  padding: 4px 9px;
  font-size: 12px;
  cursor: pointer;
}
.mermaid-toolbar button:hover { border-color: var(--accent); color: var(--accent); }
.mermaid-viewport {
  width: 100%;
  max-height: 62vh;
  overflow: auto;
  padding: 18px;
  cursor: grab;
}
.mermaid-viewport.is-panning { cursor: grabbing; user-select: none; }
.mermaid-viewport pre.mermaid { margin: 0; background: transparent; border: 0; padding: 0; }
.mermaid-viewport svg { display: block; max-width: none !important; height: auto !important; }
svg.mermaid-interactive .node,
svg.mermaid-interactive .edgePath,
svg.mermaid-interactive .edgeLabel,
svg.mermaid-interactive .flowchart-link {
  cursor: pointer;
  transition: opacity 0.15s ease;
}
svg.mermaid-interactive.is-dimmed .node,
svg.mermaid-interactive.is-dimmed .edgePath,
svg.mermaid-interactive.is-dimmed .edgeLabel,
svg.mermaid-interactive.is-dimmed .flowchart-link { opacity: 0.18; }
svg.mermaid-interactive.is-dimmed .node.is-related,
svg.mermaid-interactive.is-dimmed .node.is-selected,
svg.mermaid-interactive.is-dimmed .edgePath.is-related,
svg.mermaid-interactive.is-dimmed .edgePath.is-selected,
svg.mermaid-interactive.is-dimmed .edgeLabel.is-related,
svg.mermaid-interactive.is-dimmed .edgeLabel.is-selected,
svg.mermaid-interactive.is-dimmed .flowchart-link.is-related,
svg.mermaid-interactive.is-dimmed .flowchart-link.is-selected { opacity: 1; }
svg.mermaid-interactive .node.is-selected rect { stroke: var(--accent) !important; stroke-width: 3px !important; }

@media (max-width: 1100px) {
  .doc-shell { grid-template-columns: 1fr; }
  .doc-sidebar { position: relative; height: auto; border-right: none; border-bottom: 1px solid var(--border); }
  .lineage-app { grid-template-columns: 1fr; height: auto; }
  .measure-grid { grid-template-columns: 1fr; }
}
"""


INTERACTIVE_MERMAID_JS = r"""
(function () {
    function ready(fn) {
        if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", fn);
        else fn();
    }
    function decodeHtml(value) {
        var txt = document.createElement("textarea");
        txt.innerHTML = value || "";
        return txt.value;
    }
    function norm(value) {
        return decodeHtml(value || "").replace(/\s+/g, " ").replace(/^['"]|['"]$/g, "").trim();
    }
    function parseMermaidSource(source) {
        var nodes = new Map();
        var edges = [];
        String(source || "").split(/\r?\n/).forEach(function (raw) {
            var line = raw.replace(/%%.*$/, "").trim();
            if (!line || /^(graph|flowchart|classDef|class\s|style\s|linkStyle\s|subgraph\b|end\b)/i.test(line)) return;
            var edgeMatch = line.match(/^([A-Za-z0-9_]+)\s*(?:-->|---|-\.->|==>|--x|--o|<-->|<--|--)\s*(?:\|\s*["']?([^|"']*?)["']?\s*\|\s*)?([A-Za-z0-9_]+)/);
            if (edgeMatch) {
                var from = edgeMatch[1], label = norm(edgeMatch[2] || ""), to = edgeMatch[3];
                if (!nodes.has(from)) nodes.set(from, { id: from, label: from });
                if (!nodes.has(to)) nodes.set(to, { id: to, label: to });
                edges.push({ key: from + "->" + to + "#" + edges.length, index: edges.length, from: from, to: to, label: label });
                return;
            }
            var nodeMatch = line.match(/^([A-Za-z0-9_]+)\s*\[\s*["']?([^\]"']+?)["']?\s*\]/);
            if (nodeMatch) {
                nodes.set(nodeMatch[1], { id: nodeMatch[1], label: norm(nodeMatch[2] || nodeMatch[1]) });
            }
        });
        return { nodes: Array.from(nodes.values()), edges: edges };
    }
    function prepareShells() {
        var pres = Array.from(document.querySelectorAll("pre.mermaid"));
        pres.forEach(function (pre, index) {
            if (pre.closest(".mermaid-shell")) return;
            pre.dataset.mermaidSource = pre.textContent || pre.innerText || "";
            var shell = document.createElement("div");
            shell.className = "mermaid-shell";
            var toolbar = document.createElement("div");
            toolbar.className = "mermaid-toolbar";
            toolbar.innerHTML = '<span class="mermaid-hint">Hover to preview relationships. Click a table to pin connected paths; drag canvas to pan.</span>' +
                '<button type="button" data-action="zoom-out" title="Zoom out">-</button>' +
                '<button type="button" data-action="zoom-reset" title="Fit to width">Fit</button>' +
                '<button type="button" data-action="zoom-in" title="Zoom in">+</button>' +
                '<button type="button" data-action="fullscreen" title="Toggle fullscreen">Fullscreen</button>' +
                '<button type="button" data-action="clear" title="Clear pinned tables">Reset highlight</button>';
            var viewport = document.createElement("div");
            viewport.className = "mermaid-viewport";
            viewport.dataset.diagramIndex = String(index);
            pre.parentNode.insertBefore(shell, pre);
            shell.appendChild(toolbar);
            shell.appendChild(viewport);
            viewport.appendChild(pre);
        });
        return pres;
    }
    function findNodeElement(svg, node) {
        var candidates = Array.from(svg.querySelectorAll("g.node, g[class*='node']"));
        var match = candidates.find(function (el) {
            var id = el.id || "";
            return id.indexOf("flowchart-" + node.id + "-") !== -1 || id === node.id;
        });
        if (match) return match;
        var expected = norm(node.label || node.id);
        return candidates.find(function (el) { return norm(el.textContent).indexOf(expected) !== -1; }) || null;
    }
    function findEdgeElements(svg, edge) {
        var fromClass = "LS-" + edge.from, toClass = "LE-" + edge.to;
        var edgeCandidates = Array.from(svg.querySelectorAll("g.edgePath, .edgePath, path.flowchart-link, .flowchart-link"));
        var labelCandidates = Array.from(svg.querySelectorAll("g.edgeLabel"));
        var paths = edgeCandidates.filter(function (el) { return el.classList && el.classList.contains(fromClass) && el.classList.contains(toClass); });
        var labels = labelCandidates.filter(function (el) { return el.classList && el.classList.contains(fromClass) && el.classList.contains(toClass); });
        if (!paths.length) {
            paths = edgeCandidates.filter(function (el) {
                var id = el.id || "", cls = el.getAttribute("class") || "";
                return (id.indexOf(edge.from) !== -1 && id.indexOf(edge.to) !== -1) || (cls.indexOf(edge.from) !== -1 && cls.indexOf(edge.to) !== -1);
            });
        }
        if (!labels.length && typeof edge.index === "number" && labelCandidates[edge.index]) labels = [labelCandidates[edge.index]];
        return {
            paths: Array.from(new Set(paths.map(function (el) { return el.closest("g.edgePath") || el; }))),
            labels: Array.from(new Set(labels))
        };
    }
    function setBaseSvgSize(svg, viewport) {
        var vb = (svg.getAttribute("viewBox") || "").split(/\s+/).map(Number);
        var baseWidth = vb.length === 4 && vb[2] ? vb[2] : (svg.getBoundingClientRect().width || 900);
        svg.dataset.baseWidth = String(baseWidth);
        var fit = Math.max(0.55, Math.min(1.15, (viewport.clientWidth - 40) / baseWidth));
        svg.dataset.zoom = String(fit);
        svg.style.width = Math.max(300, baseWidth * fit) + "px";
    }
    function applyZoom(svg, factor) {
        var baseWidth = Number(svg.dataset.baseWidth || 900);
        var zoom = Math.max(0.35, Math.min(3.0, Number(svg.dataset.zoom || "1") * factor));
        svg.dataset.zoom = String(zoom);
        svg.style.width = Math.max(260, baseWidth * zoom) + "px";
    }
    function enablePanning(viewport) {
        var dragging = false, sx = 0, sy = 0, sl = 0, st = 0;
        viewport.addEventListener("mousedown", function (e) {
            if (e.button !== 0 || (e.target.closest && e.target.closest(".node, .edgePath, .edgeLabel, button"))) return;
            dragging = true; sx = e.pageX; sy = e.pageY; sl = viewport.scrollLeft; st = viewport.scrollTop;
            viewport.classList.add("is-panning"); e.preventDefault();
        });
        window.addEventListener("mousemove", function (e) {
            if (!dragging) return;
            viewport.scrollLeft = sl - (e.pageX - sx);
            viewport.scrollTop = st - (e.pageY - sy);
        });
        window.addEventListener("mouseup", function () { dragging = false; viewport.classList.remove("is-panning"); });
    }
    function setupDiagram(shell) {
        if (!shell || shell.dataset.ready === "1") return;
        var pre = shell.querySelector("pre.mermaid"), viewport = shell.querySelector(".mermaid-viewport"), toolbar = shell.querySelector(".mermaid-toolbar"), svg = shell.querySelector("svg");
        if (!pre || !viewport || !toolbar || !svg) return;
        shell.dataset.ready = "1";
        svg.classList.add("mermaid-interactive");
        setBaseSvgSize(svg, viewport);
        enablePanning(viewport);
        var graph = parseMermaidSource(pre.dataset.mermaidSource || "");
        var nodeById = new Map(), edgeByKey = new Map(), selectedNodes = new Set(), selectedEdges = new Set(), hoverNode = null, hoverEdge = null;
        graph.nodes.forEach(function (n) {
            var el = findNodeElement(svg, n);
            if (!el) return;
            n.el = el; nodeById.set(n.id, n);
        });
        graph.edges.forEach(function (e) {
            e.elements = findEdgeElements(svg, e);
            edgeByKey.set(e.key, e);
        });
        function updateView() {
            svg.querySelectorAll(".is-selected, .is-related").forEach(function (el) { el.classList.remove("is-selected", "is-related"); });
            var aNodes = new Set(Array.from(selectedNodes)), aEdges = new Set(Array.from(selectedEdges));
            if (hoverNode) aNodes.add(hoverNode);
            if (hoverEdge) aEdges.add(hoverEdge);
            aNodes.forEach(function (nid) {
                graph.edges.forEach(function (e) { if (e.from === nid || e.to === nid) aEdges.add(e.key); });
            });
            var relNodes = new Set(Array.from(aNodes));
            aEdges.forEach(function (ek) {
                var e = edgeByKey.get(ek);
                if (e) { relNodes.add(e.from); relNodes.add(e.to); }
            });
            var hasActive = aNodes.size > 0 || aEdges.size > 0;
            svg.classList.toggle("is-dimmed", hasActive);
            relNodes.forEach(function (nid) {
                var n = nodeById.get(nid);
                if (n && n.el) n.el.classList.add(aNodes.has(nid) ? "is-selected" : "is-related");
            });
            aEdges.forEach(function (ek) {
                var e = edgeByKey.get(ek);
                if (e) e.elements.paths.concat(e.elements.labels).forEach(function (el) { el.classList.add(selectedEdges.has(ek) ? "is-selected" : "is-related"); });
            });
        }
        nodeById.forEach(function (n) {
            n.el.addEventListener("mouseenter", function () { hoverNode = n.id; updateView(); });
            n.el.addEventListener("mouseleave", function () { hoverNode = null; updateView(); });
            n.el.addEventListener("click", function (ev) {
                ev.preventDefault(); ev.stopPropagation();
                if (selectedNodes.has(n.id)) selectedNodes.delete(n.id); else selectedNodes.add(n.id);
                updateView();
            });
        });
        toolbar.addEventListener("click", function (ev) {
            var btn = ev.target.closest("button[data-action]");
            if (!btn) return;
            var act = btn.dataset.action;
            if (act === "zoom-in") applyZoom(svg, 1.2);
            if (act === "zoom-out") applyZoom(svg, 1 / 1.2);
            if (act === "zoom-reset") setBaseSvgSize(svg, viewport);
            if (act === "fullscreen") {
                shell.classList.toggle("is-fallback-fullscreen");
                document.body.classList.toggle("mermaid-fallback-fullscreen", shell.classList.contains("is-fallback-fullscreen"));
                setBaseSvgSize(svg, viewport);
            }
            if (act === "clear") { selectedNodes.clear(); selectedEdges.clear(); hoverNode = null; hoverEdge = null; updateView(); }
        });
    }
    ready(function () {
        if (typeof mermaid === "undefined") return;
        var nodes = prepareShells();
        if (!nodes.length) return;
        mermaid.initialize({ startOnLoad: false, theme: "neutral", securityLevel: "strict", flowchart: { useMaxWidth: false, htmlLabels: true, curve: "basis" } });
        var done = function () { window.requestAnimationFrame(function () { document.querySelectorAll(".mermaid-shell").forEach(setupDiagram); }); };
        if (typeof mermaid.run === "function") mermaid.run({ nodes: nodes, suppressErrors: true }).then(done).catch(done);
        else if (typeof mermaid.init === "function") mermaid.init(undefined, nodes, done);
    });
})();
"""


LINEAGE_WIDGET_JS = r"""
(function () {
    function escHtml(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    function initLineageApp(container) {
        var scriptId = container.getAttribute("data-lineage-id");
        var dataEl = document.getElementById(scriptId);
        if (!dataEl) return;
        var graph;
        try { graph = JSON.parse(dataEl.textContent || "{}"); } catch (e) { return; }
        var nodes = graph.nodes || [];
        var edges = graph.edges || [];
        var layers = graph.layers || [];
        if (!nodes.length) {
            container.innerHTML = '<div style="padding:24px;color:var(--fg-muted)">No lineage objects available for this view.</div>';
            return;
        }

        var nodeMap = new Map();
        var outMap = new Map();
        var inMap = new Map();
        nodes.forEach(function (n) {
            nodeMap.set(n.id, n);
            outMap.set(n.id, []);
            inMap.set(n.id, []);
        });
        edges.forEach(function (e) {
            if (outMap.has(e.from) && inMap.has(e.to)) {
                outMap.get(e.from).push(e.to);
                inMap.get(e.to).push(e.from);
            }
        });

        var state = {
            focusId: graph.defaultFocus || (nodes[0] && nodes[0].id) || null,
            layerFilter: "all",
            search: "",
            connectedOnly: true
        };

        container.innerHTML =
            '<div class="lin-left">' +
              '<div class="lin-left-top">' +
                '<input type="search" class="lin-search" placeholder="Search sources, tables, DAX, reports...">' +
                '<div class="lin-layer-pills"></div>' +
              '</div>' +
              '<div class="lin-nav-list"></div>' +
            '</div>' +
            '<div class="lin-center">' +
              '<div class="lin-toolbar">' +
                '<span class="lin-status"></span>' +
                '<div class="lin-toolbar-actions">' +
                  '<button type="button" class="lin-btn lin-toggle-conn"></button>' +
                  '<button type="button" class="lin-btn lin-show-all">Show full graph</button>' +
                '</div>' +
              '</div>' +
              '<div class="lin-canvas-scroll">' +
                '<svg class="lin-svg"></svg>' +
                '<div class="lin-columns"></div>' +
              '</div>' +
            '</div>' +
            '<div class="lin-right"></div>';

        var searchInput = container.querySelector(".lin-search");
        var pillsWrap = container.querySelector(".lin-layer-pills");
        var navList = container.querySelector(".lin-nav-list");
        var statusEl = container.querySelector(".lin-status");
        var btnConn = container.querySelector(".lin-toggle-conn");
        var btnAll = container.querySelector(".lin-show-all");
        var scrollBox = container.querySelector(".lin-canvas-scroll");
        var svgEl = container.querySelector("svg.lin-svg");
        var colsEl = container.querySelector(".lin-columns");
        var rightEl = container.querySelector(".lin-right");

        function traceSet(startId, adj) {
            var visited = new Set();
            if (!startId || !adj.has(startId)) return visited;
            var queue = (adj.get(startId) || []).slice();
            while (queue.length) {
                var cur = queue.shift();
                if (visited.has(cur) || cur === startId) continue;
                visited.add(cur);
                (adj.get(cur) || []).forEach(function (nxt) {
                    if (!visited.has(nxt)) queue.push(nxt);
                });
            }
            return visited;
        }

        function renderPills() {
            var html = '<button type="button" class="lin-pill ' + (state.layerFilter === "all" ? "active" : "") + '" data-layer="all">All (' + nodes.length + ')</button>';
            layers.forEach(function (l) {
                var cnt = nodes.filter(function (n) { return n.layer === l.id; }).length;
                if (!cnt) return;
                html += '<button type="button" class="lin-pill ' + (state.layerFilter === l.id ? "active" : "") + '" data-layer="' + escHtml(l.id) + '">' + escHtml(l.label) + ' (' + cnt + ')</button>';
            });
            pillsWrap.innerHTML = html;
        }

        function renderNav() {
            var q = state.search.toLowerCase();
            var filtered = nodes.filter(function (n) {
                if (state.layerFilter !== "all" && n.layer !== state.layerFilter) return false;
                if (q && (n.label + " " + (n.sub || "") + " " + (n.detail || "")).toLowerCase().indexOf(q) === -1) return false;
                return true;
            });
            navList.innerHTML = filtered.slice(0, 250).map(function (n) {
                var deg = (inMap.get(n.id) || []).length + (outMap.get(n.id) || []).length;
                return '<button type="button" class="lin-nav-item ' + (state.focusId === n.id ? "active" : "") + '" data-id="' + escHtml(n.id) + '">' +
                    '<span>' + escHtml(n.label) + '</span>' +
                    '<small>' + escHtml(n.layerLabel || n.layer) + (n.sub ? " - " + escHtml(n.sub) : "") + ' (' + deg + ' links)</small>' +
                '</button>';
            }).join("");
        }

        function drawEdges(upstreamSet, downstreamSet) {
            var boxRect = scrollBox.getBoundingClientRect();
            var width = Math.max(scrollBox.scrollWidth, scrollBox.clientWidth);
            var height = Math.max(scrollBox.scrollHeight, scrollBox.clientHeight);
            svgEl.setAttribute("width", String(width));
            svgEl.setAttribute("height", String(height));

            var domNodes = new Map();
            colsEl.querySelectorAll(".lin-node[data-id]").forEach(function (el) {
                domNodes.set(el.getAttribute("data-id"), el);
            });

            var paths = [];
            edges.forEach(function (e) {
                if (!domNodes.has(e.from) || !domNodes.has(e.to)) return;
                var a = domNodes.get(e.from).getBoundingClientRect();
                var b = domNodes.get(e.to).getBoundingClientRect();
                var x1 = a.right - boxRect.left + scrollBox.scrollLeft;
                var y1 = a.top + a.height / 2 - boxRect.top + scrollBox.scrollTop;
                var x2 = b.left - boxRect.left + scrollBox.scrollLeft;
                var y2 = b.top + b.height / 2 - boxRect.top + scrollBox.scrollTop;
                if (x2 < x1) {
                    x1 = a.left - boxRect.left + scrollBox.scrollLeft;
                    x2 = b.right - boxRect.left + scrollBox.scrollLeft;
                }
                var dx = Math.max(28, Math.abs(x2 - x1) * 0.45);
                var active = !state.focusId ||
                    (e.from === state.focusId || e.to === state.focusId) ||
                    (upstreamSet.has(e.from) && (upstreamSet.has(e.to) || e.to === state.focusId)) ||
                    (downstreamSet.has(e.to) && (downstreamSet.has(e.from) || e.from === state.focusId));
                var stroke = active ? (upstreamSet.has(e.from) || e.to === state.focusId ? "#0f766e" : "#0b63ce") : "rgba(148,163,184,0.22)";
                var sw = active && state.focusId ? "2.1" : "1.2";
                paths.push('<path d="M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' C ' + (x1 + dx).toFixed(1) + ' ' + y1.toFixed(1) + ', ' + (x2 - dx).toFixed(1) + ' ' + y2.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + '" fill="none" stroke="' + stroke + '" stroke-width="' + sw + '"/>');
            });
            svgEl.innerHTML = paths.join("");
        }

        function renderCanvasAndInspector() {
            var up = traceSet(state.focusId, inMap);
            var down = traceSet(state.focusId, outMap);
            var connected = new Set([state.focusId]);
            up.forEach(function (x) { connected.add(x); });
            down.forEach(function (x) { connected.add(x); });

            btnConn.textContent = state.connectedOnly ? "Filter: Connected path" : "Filter: All objects";
            btnConn.classList.toggle("active", state.connectedOnly);

            if (state.focusId && nodeMap.has(state.focusId)) {
                var fn = nodeMap.get(state.focusId);
                statusEl.innerHTML = 'Focused: <b>' + escHtml(fn.label) + '</b> (' + up.size + ' upstream, ' + down.size + ' downstream)';
            } else {
                statusEl.textContent = "Showing full lineage map (" + nodes.length + " objects, " + edges.length + " links)";
            }

            var colsHtml = [];
            layers.forEach(function (layer) {
                var colNodes = nodes.filter(function (n) {
                    if (n.layer !== layer.id) return false;
                    if (state.focusId && state.connectedOnly && !connected.has(n.id)) return false;
                    return true;
                });
                if (!colNodes.length) return;
                var cards = colNodes.slice(0, 80).map(function (n) {
                    var cls = "lin-node";
                    if (state.focusId) {
                        if (n.id === state.focusId) cls += " is-focus";
                        else if (up.has(n.id)) cls += " is-upstream";
                        else if (down.has(n.id)) cls += " is-downstream";
                        else cls += " is-muted";
                    }
                    return '<div class="' + cls + '" data-id="' + escHtml(n.id) + '">' +
                        '<div class="n-title">' + escHtml(n.label) + '</div>' +
                        (n.sub ? '<div class="n-sub">' + escHtml(n.sub) + '</div>' : '') +
                    '</div>';
                }).join("");
                colsHtml.push('<div class="lin-col"><div class="lin-col-hdr">' + escHtml(layer.label) + ' (' + colNodes.length + ')</div>' + cards + '</div>');
            });
            colsEl.innerHTML = colsHtml.join("");

            if (state.focusId && nodeMap.has(state.focusId)) {
                var cur = nodeMap.get(state.focusId);
                var directIn = (inMap.get(cur.id) || []).map(function (id) { return nodeMap.get(id); }).filter(Boolean);
                var directOut = (outMap.get(cur.id) || []).map(function (id) { return nodeMap.get(id); }).filter(Boolean);
                var insp = '<span class="badge badge-accent">' + escHtml(cur.layerLabel || cur.layer) + '</span>' +
                    '<h4>' + escHtml(cur.label) + '</h4>';
                if (cur.sub) insp += '<div class="lin-kv">' + escHtml(cur.sub) + '</div>';
                if (cur.detail) insp += '<div style="font-size:12px">' + escHtml(cur.detail) + '</div>';
                if (cur.href) {
                    insp += '<a class="dep-chip" style="border-color:var(--accent);color:var(--accent);font-weight:600;padding:5px 10px" href="' + escHtml(cur.href) + '">' + escHtml(cur.hrefLabel || "Jump to documentation") + ' -></a>';
                }
                if (cur.code) {
                    insp += '<div class="code-block" style="font-size:11.5px;padding:8px 10px"><pre>' + escHtml(cur.code) + '</pre></div>';
                }
                insp += '<div class="lin-kv" style="margin-top:4px"><b>Direct Upstream (' + directIn.length + ')</b></div><div class="lin-list">' +
                    (directIn.length ? directIn.map(function (x) { return '<button type="button" class="dep-chip lin-jump" data-id="' + escHtml(x.id) + '">' + escHtml(x.label) + '</button>'; }).join("") : '<span class="lin-kv">None (root source)</span>') +
                    '</div>';
                insp += '<div class="lin-kv" style="margin-top:4px"><b>Direct Downstream (' + directOut.length + ')</b></div><div class="lin-list">' +
                    (directOut.length ? directOut.map(function (x) { return '<button type="button" class="dep-chip lin-jump" data-id="' + escHtml(x.id) + '">' + escHtml(x.label) + '</button>'; }).join("") : '<span class="lin-kv">None (leaf consumer)</span>') +
                    '</div>';
                rightEl.innerHTML = insp;
            } else {
                rightEl.innerHTML = '<h4>Interactive Live Lineage</h4><div class="lin-kv">Click any source, table, column, DAX measure, or report to trace its upstream origins and downstream impact in real time.</div>';
            }

            window.requestAnimationFrame(function () { drawEdges(up, down); });
        }

        function refreshAll() { renderPills(); renderNav(); renderCanvasAndInspector(); }

        searchInput.addEventListener("input", function () { state.search = searchInput.value || ""; renderNav(); });
        pillsWrap.addEventListener("click", function (e) {
            var b = e.target.closest("button[data-layer]");
            if (!b) return;
            state.layerFilter = b.getAttribute("data-layer");
            renderPills(); renderNav();
        });
        navList.addEventListener("click", function (e) {
            var b = e.target.closest("button[data-id]");
            if (!b) return;
            state.focusId = b.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        colsEl.addEventListener("click", function (e) {
            var card = e.target.closest(".lin-node[data-id]");
            if (!card) return;
            state.focusId = card.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        rightEl.addEventListener("click", function (e) {
            var b = e.target.closest(".lin-jump[data-id]");
            if (!b) return;
            state.focusId = b.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        btnConn.addEventListener("click", function () { state.connectedOnly = !state.connectedOnly; renderCanvasAndInspector(); });
        btnAll.addEventListener("click", function () { state.focusId = null; state.connectedOnly = false; renderNav(); renderCanvasAndInspector(); });
        scrollBox.addEventListener("scroll", function () { drawEdges(traceSet(state.focusId, inMap), traceSet(state.focusId, outMap)); });
        window.addEventListener("resize", function () { drawEdges(traceSet(state.focusId, inMap), traceSet(state.focusId, outMap)); });

        container._lineageRedraw = refreshAll;
        refreshAll();
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".lineage-app[data-lineage-id]").forEach(initLineageApp);
    });
    window.PbiLineageRedrawAll = function () {
        document.querySelectorAll(".lineage-app").forEach(function (el) {
            if (typeof el._lineageRedraw === "function") el._lineageRedraw();
        });
    };
})();
"""


PORTAL_COMMON_JS = r"""
(function () {
    var saved = localStorage.getItem("pbidoc-v1-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);

    // Reveal "Back to Scanner & Setup" switcher only when served by the local Studio HTTP server
    document.addEventListener("DOMContentLoaded", function () {
        var isLocalStudio = (location.protocol === "http:" || location.protocol === "https:") &&
            (location.hostname === "127.0.0.1" || location.hostname === "localhost");
        if (isLocalStudio) {
            document.querySelectorAll(".studio-only-link").forEach(function (el) {
                el.style.display = "";
            });
        }
    });

    document.addEventListener("click", function (e) {
        var expBtn = e.target.closest("[data-details-toggle]");
        if (expBtn) {
            var scopeId = expBtn.getAttribute("data-details-toggle");
            var shouldOpen = expBtn.getAttribute("data-open") === "1";
            var root = document.getElementById(scopeId) || document;
            root.querySelectorAll("details").forEach(function (d) { d.open = shouldOpen; });
            return;
        }
        var daxViewBtn = e.target.closest("[data-dax-view]");
        if (daxViewBtn) {
            var v = daxViewBtn.getAttribute("data-dax-view");
            document.querySelectorAll("[data-dax-view]").forEach(function (b) { b.classList.toggle("active", b === daxViewBtn); });
            var cardsBox = document.getElementById("daxCardsContainer");
            var listBox = document.getElementById("daxListContainer");
            if (cardsBox && listBox) {
                cardsBox.style.display = (v === "cards") ? "" : "none";
                listBox.style.display = (v === "list") ? "" : "none";
            }
            return;
        }
        var themeBtn = e.target.closest("[data-toggle-theme]");
        if (themeBtn) {
            var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", cur);
            localStorage.setItem("pbidoc-v1-theme", cur);
            return;
        }
        var copyBtn = e.target.closest(".copy-btn[data-copy]");
        if (copyBtn) {
            var pre = copyBtn.parentElement && copyBtn.parentElement.querySelector("pre");
            if (pre && navigator.clipboard) {
                navigator.clipboard.writeText(pre.innerText || pre.textContent || "");
                var old = copyBtn.textContent;
                copyBtn.textContent = "Copied!";
                setTimeout(function () { copyBtn.textContent = old; }, 1200);
            }
            return;
        }
        var tabBtn = e.target.closest(".top-tab[data-tab]");
        if (tabBtn) {
            var target = tabBtn.getAttribute("data-tab");
            document.querySelectorAll(".top-tab").forEach(function (b) { b.classList.toggle("active", b === tabBtn); });
            document.querySelectorAll(".tab-pane").forEach(function (p) { p.classList.toggle("active", p.id === target); });
            if (window.PbiLineageRedrawAll) setTimeout(window.PbiLineageRedrawAll, 40);
        }
    });

    document.addEventListener("keydown", function (e) {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            var search = document.querySelector("[data-quick-search]");
            if (search) { e.preventDefault(); search.focus(); search.select(); }
        }
    });
})();
"""


DAX_KEYWORDS = {
    "VAR", "RETURN", "CALCULATE", "CALCULATETABLE", "FILTER", "ALL", "ALLEXCEPT", "ALLSELECTED",
    "REMOVEFILTERS", "KEEPFILTERS", "VALUES", "DISTINCT", "SUM", "SUMX", "AVERAGE", "AVERAGEX",
    "MIN", "MAX", "COUNT", "COUNTA", "COUNTROWS", "DISTINCTCOUNT", "DIVIDE", "IF", "SWITCH",
    "TRUE", "FALSE", "BLANK", "ISBLANK", "COALESCE", "SELECTEDVALUE", "HASONEVALUE", "RELATED",
    "RELATEDTABLE", "USERELATIONSHIP", "CROSSFILTER", "TREATAS", "DATESYTD", "SAMEPERIODLASTYEAR",
    "DATEADD", "TOTALYTD", "DATESINPERIOD", "FORMAT", "NOT", "IN", "AND", "OR",
}

M_KEYWORDS = {
    "let", "in", "each", "if", "then", "else", "try", "otherwise", "section", "shared",
    "true", "false", "null", "type", "table", "record", "list", "number", "text", "date", "datetime",
}


def _highlight_dax(code: str, auto_pretty: bool = True) -> str:
    formatted = format_dax_pretty(code) if auto_pretty else (code or "")
    safe = esc(mask_secrets(formatted))

    def _tok(match: re.Match) -> str:
        tok = match.group(0)
        if tok.startswith("//") or tok.startswith("--"):
            return f'<span class="cmt">{tok}</span>'
        if tok.startswith('"') or tok.startswith("&quot;"):
            return f'<span class="str">{tok}</span>'
        if tok.upper() in DAX_KEYWORDS:
            return f'<span class="kw">{tok}</span>'
        return tok

    pattern = re.compile(r"(//[^\n]*|--[^\n]*|&quot;.*?&quot;|\b[A-Za-z_][A-Za-z0-9_.]*\b)")
    return pattern.sub(_tok, safe)


def _highlight_m(code: str) -> str:
    safe = esc(mask_secrets(code or ""))

    def _tok(match: re.Match) -> str:
        tok = match.group(0)
        if tok.startswith("//"):
            return f'<span class="cmt">{tok}</span>'
        if tok.startswith("&quot;"):
            return f'<span class="str">{tok}</span>'
        if tok in M_KEYWORDS:
            return f'<span class="kw">{tok}</span>'
        if "." in tok and tok[0].isupper():
            return f'<span class="fn">{tok}</span>'
        return tok

    pattern = re.compile(r"(//[^\n]*|&quot;.*?&quot;|\b[A-Z][A-Za-z0-9]*\.[A-Za-z0-9]+\b|\b[a-z]+\b)")
    return pattern.sub(_tok, safe)


def _measure_anchor(table_name: str, measure_name: str) -> str:
    return "m-" + slugify(f"{table_name}-{measure_name}")


def _table_anchor(table_name: str) -> str:
    return "t-" + slugify(table_name)


def _compute_measure_depths(lineage: dict) -> dict[str, int]:
    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def depth(m_key: str) -> int:
        if m_key in memo:
            return memo[m_key]
        if m_key in visiting:
            return 1
        visiting.add(m_key)
        deps = (lineage.get(m_key) or {}).get("upstream_measures") or []
        d = 0 if not deps else 1 + max((depth(dep) for dep in deps), default=0)
        visiting.remove(m_key)
        memo[m_key] = d
        return d

    for k in lineage:
        depth(k)
    return memo


def _build_star_schema_mermaid(analysis: dict) -> tuple[str, set[str], set[str]]:
    rels = analysis["parsed"]["relationships"]
    tables = [t for t in analysis["table_summaries"] if not t["hidden"] or any(r["from_table"] == t["name"] or r["to_table"] == t["name"] for r in rels)]
    many_side: set[str] = set()
    one_side: set[str] = set()
    for r in rels:
        f_many = r["cardinality"].startswith("many")
        t_many = r["cardinality"].endswith("many")
        if f_many:
            many_side.add(r["from_table"])
        else:
            one_side.add(r["from_table"])
        if t_many:
            many_side.add(r["to_table"])
        else:
            one_side.add(r["to_table"])

    facts = {t for t in many_side if t not in one_side} or set(many_side)
    dims = (many_side | one_side) - facts

    id_map: dict[str, str] = {}
    for idx, t in enumerate(tables, 1):
        id_map[t["name"]] = f"T{idx}"
    for r in rels:
        for tname in (r["from_table"], r["to_table"]):
            if tname not in id_map:
                id_map[tname] = f"T{len(id_map) + 1}"

    lines = ["flowchart LR"]
    lines.append("    classDef factNode fill:#e8f1fd,stroke:#0b63ce,stroke-width:2px,color:#0f172a;")
    lines.append("    classDef dimNode fill:#e6f6f4,stroke:#0f766e,stroke-width:1.5px,color:#0f172a;")
    lines.append("    classDef standaloneNode fill:#f8fafc,stroke:#94a3b8,stroke-width:1px,color:#334155;")

    t_lookup = {t["name"]: t for t in analysis["table_summaries"]}
    for tname, nid in id_map.items():
        ts = t_lookup.get(tname)
        role_tag = "FACT" if tname in facts else ("DIM" if tname in dims else "KPI / TABLE")
        stats_txt = f" ({ts['columns_count']} cols, {ts['measures_count']} meas)" if ts else ""
        safe_lbl = tname.replace('"', "'")
        lines.append(f'    {nid}["[{role_tag}] {safe_lbl}{stats_txt}"]')

    for r in rels:
        fid = id_map[r["from_table"]]
        tid = id_map[r["to_table"]]
        fc = "*" if r["cardinality"].startswith("many") else "1"
        tc = "*" if r["cardinality"].endswith("many") else "1"
        arrow = "<-->" if r["bidirectional"] else ("-.->" if not r["active"] else "-->")
        col_lbl = f"{r['from_column']} = {r['to_column']} ({fc}:{tc})".replace('"', "'").replace("|", "/")
        lines.append(f'    {fid} {arrow}|"{col_lbl}"| {tid}')

    for tname, nid in id_map.items():
        cls = "factNode" if tname in facts else ("dimNode" if tname in dims else "standaloneNode")
        lines.append(f"    class {nid} {cls};")

    return "\n".join(lines), facts, dims


def _build_model_lineage_json(analysis: dict) -> dict:
    layers = [
        {"id": "source", "label": "1. Data Sources"},
        {"id": "table", "label": "2. Model Tables"},
        {"id": "column", "label": "3. Referenced Columns"},
        {"id": "base_measure", "label": "4. Base Measures"},
        {"id": "kpi_measure", "label": "5. Derived KPIs & Reports"},
    ]
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()

    def add_node(nid: str, label: str, layer: str, layer_lbl: str, sub: str = "", detail: str = "", href: str = "", code: str = ""):
        if nid in seen_nodes:
            return
        seen_nodes.add(nid)
        nodes.append(
            {
                "id": nid,
                "label": label,
                "layer": layer,
                "layerLabel": layer_lbl,
                "sub": sub,
                "detail": detail,
                "href": href,
                "hrefLabel": "Jump to section",
                "code": format_dax_pretty(code) if code else "",
            }
        )

    for ts in analysis["table_summaries"]:
        tid = f"tbl:{ts['name']}"
        src_label = ", ".join(ts["source_types"]) or ts["mode"]
        add_node(
            tid,
            ts["name"],
            "table",
            "Model Table",
            sub=f"{ts['mode'].upper()} - {ts['columns_count']} cols, {ts['measures_count']} measures",
            detail=ts["description"] or f"Power Query steps: {ts['pq_steps']}",
            href=f"#{_table_anchor(ts['name'])}",
        )
        endpoints = ts["details"] or ts["source_types"] or ["Internal / Calculated"]
        for ep in endpoints:
            sid = f"src:{ep}"
            add_node(sid, ep, "source", "External Data Source", sub=src_label, detail="Upstream connection or source object read by Power Query.")
            edges.append({"from": sid, "to": tid})
        for obj in ts["objects"][:6]:
            oid = f"srcobj:{endpoints[0]}:{obj}"
            add_node(oid, obj, "source", "Source View / Object", sub=", ".join(ts["source_types"]), detail=f"Loaded into table '{ts['name']}'.")
            edges.append({"from": oid, "to": tid})

    lin_measures = analysis["lineage"] or {}
    depths = _compute_measure_depths(lin_measures)
    # Build metadata lookup from parsed tables
    m_meta_map: dict[str, dict] = {}
    for tbl in analysis["parsed"]["tables"]:
        for m in tbl["measures"]:
            m_meta_map[f"{tbl['name']}[{m['name']}]"] = m

    default_focus = None
    best_score = -1

    for m_key, m_info in lin_measures.items():
        m_name = m_info["name"]
        m_raw = m_meta_map.get(m_key) or {}
        d = depths.get(m_key, 0)
        is_base = d == 0
        mid = f"meas:{m_key}"
        layer_id = "base_measure" if is_base else "kpi_measure"
        layer_lbl = "Base Measure" if is_base else f"Derived KPI (Tier {d})"
        anchor = f"#{_measure_anchor(m_info['table'], m_name)}"
        add_node(
            mid,
            m_name,
            layer_id,
            layer_lbl,
            sub=f"{m_info['table']}" + (f" / {m_raw['folder']}" if m_raw.get("folder") else ""),
            detail=m_raw.get("description") or (f"Format: {m_raw['format']}" if m_raw.get("format") else ""),
            href=anchor,
            code=m_info.get("expr", ""),
        )
        score = len(m_info.get("upstream_measures", [])) + len(m_info.get("downstream_measures", [])) * 2 + len(m_info.get("upstream_columns", []))
        if score > best_score:
            best_score = score
            default_focus = mid

        if not m_info.get("upstream_columns") and is_base:
            edges.append({"from": f"tbl:{m_info['table']}", "to": mid})

        for col_ref in m_info.get("upstream_columns", []):
            cid = f"col:{col_ref}"
            tbl_part = col_ref.split("[", 1)[0]
            add_node(cid, col_ref, "column", "Table Column", sub=f"Table: {tbl_part}", href=f"#{_table_anchor(tbl_part)}")
            if f"tbl:{tbl_part}" in seen_nodes:
                edges.append({"from": f"tbl:{tbl_part}", "to": cid})
            edges.append({"from": cid, "to": mid})

        for upstream_m in m_info.get("upstream_measures", []):
            edges.append({"from": f"meas:{upstream_m}", "to": mid})

    for rep in analysis.get("reports") or []:
        rid = f"rep:{rep['id']}"
        add_node(rid, rep["name"], "kpi_measure", "Power BI Report", sub=f"Workspace: {rep.get('workspace', '')}", detail="Downstream report bound to this semantic model.")
        if lin_measures:
            for m_key, m_info in list(lin_measures.items())[:25]:
                if not m_info.get("downstream_measures"):
                    edges.append({"from": f"meas:{m_key}", "to": rid})
        else:
            for ts in analysis["table_summaries"][:10]:
                edges.append({"from": f"tbl:{ts['name']}", "to": rid})

    if not default_focus and nodes:
        default_focus = nodes[0]["id"]

    return {"layers": layers, "nodes": nodes, "edges": edges, "defaultFocus": default_focus}


def _build_workspace_lineage_json(analyses: list[tuple[str, dict]]) -> dict:
    layers = [
        {"id": "source", "label": "1. Source Systems"},
        {"id": "object", "label": "2. Views / Databases"},
        {"id": "model", "label": "3. Semantic Models"},
        {"id": "kpi", "label": "4. Core KPIs"},
        {"id": "report", "label": "5. Power BI Reports"},
    ]
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()

    def add_node(nid: str, label: str, layer: str, layer_lbl: str, sub: str = "", detail: str = "", href: str = "", href_lbl: str = ""):
        if nid in seen_nodes:
            return
        seen_nodes.add(nid)
        nodes.append(
            {
                "id": nid,
                "label": label,
                "layer": layer,
                "layerLabel": layer_lbl,
                "sub": sub,
                "detail": detail,
                "href": href,
                "hrefLabel": href_lbl or "Open model documentation",
            }
        )

    def add_edge(u: str, v: str):
        if (u, v) not in seen_edges:
            seen_edges.add((u, v))
            edges.append({"from": u, "to": v})

    default_focus = None
    best_deg = -1

    for slug, a in analyses:
        mid = f"mdl:{slug}"
        stats = a["stats"]
        href = f"models/{slug}.html"
        add_node(
            mid,
            a["name"],
            "model",
            "Semantic Model",
            sub=f"{a['workspace']} - {stats['tables']} tables, {stats['measures']} measures",
            detail=f"Sources: {', '.join(a['source_types']) or 'Internal'}",
            href=href,
        )

        deg = len(a["source_endpoints"]) + len(a["reports"]) + stats["measures"]
        if deg > best_deg:
            best_deg = deg
            default_focus = mid

        for stype in a["source_types"]:
            sid = f"sys:{stype}"
            add_node(sid, stype, "source", "Source Platform", sub="Connector technology")
            matched_ep = False
            for ep in a["source_endpoints"]:
                if ep["type"] == stype:
                    matched_ep = True
                    ep_lbl = ep["object"] or ep["endpoint"] or stype
                    oid = f"ep:{stype}:{ep_lbl}"
                    add_node(oid, ep_lbl, "object", "Source Endpoint / Object", sub=f"{stype} ({ep['endpoint']})" if ep["endpoint"] else stype, detail=f"Read by table '{ep['table']}'")
                    add_edge(sid, oid)
                    add_edge(oid, mid)
            if not matched_ep:
                add_edge(sid, mid)

        lin_m = a["lineage"] or {}
        ranked_m = sorted(lin_m.items(), key=lambda kv: (len(kv[1].get("downstream_measures", [])), len(kv[1].get("upstream_measures", []))), reverse=True)[:5]
        kpi_ids = []
        for m_key, m_info in ranked_m:
            m_name = m_info["name"]
            kid = f"kpi:{slug}:{m_key}"
            kpi_ids.append(kid)
            add_node(
                kid,
                m_name,
                "kpi",
                "DAX KPI Measure",
                sub=f"{a['name']} ({m_info['table']})",
                detail="",
                href=f"{href}#{_measure_anchor(m_info['table'], m_name)}",
                href_lbl="Inspect DAX formula",
            )
            add_edge(mid, kid)

        for rep in a["reports"]:
            rid = f"rep:{rep['id']}"
            cross_ws = rep.get("workspace") and rep.get("workspace") != a["workspace"]
            ws_note = f"Workspace: {rep.get('workspace', a['workspace'])}" + (" (Cross-Workspace)" if cross_ws else "")
            add_node(rid, rep["name"], "report", "Power BI Report", sub=ws_note, href=href)
            if kpi_ids:
                for kid in kpi_ids:
                    add_edge(kid, rid)
            else:
                add_edge(mid, rid)

    return {"layers": layers, "nodes": nodes, "edges": edges, "defaultFocus": default_focus}


def render_model_html(analysis: dict, slug: str, anonymous: bool = False) -> str:
    """Render an effortless-to-read, logically structured HTML documentation page for one Semantic Model."""
    stats = analysis["stats"]
    parsed = analysis["parsed"]
    findings = analysis["findings"]
    owner_txt = "Anonymized" if anonymous else (analysis["owner"] or "Not specified")
    ref = analysis.get("last_refresh") or {}
    ref_status = ref.get("status") or "Unknown"
    ref_badge = "badge-ok" if ref_status in ("Completed", "Local") else ("badge-bad" if ref_status == "Failed" else "badge-warn")

    # 1. Findings HTML
    if findings:
        findings_html = '<div class="finding-list">' + "".join(
            f'<div class="finding {esc(f["severity"])}"><div><strong>{esc(f["title"])}</strong><span>{esc(f["detail"])}</span></div></div>'
            for f in findings
        ) + "</div>"
    else:
        findings_html = '<div class="finding ok"><div><strong>Healthy model architecture</strong><span>Zero refresh errors, non-production endpoints, bidirectional filter traps, or local file dependencies detected.</span></div></div>'

    # 2. Star-Schema Mermaid + Relationships Table
    mermaid_src, facts, dims = _build_star_schema_mermaid(analysis)
    rels = parsed["relationships"]
    rel_key_cols: dict[str, set[str]] = collections.defaultdict(set)
    for r in rels:
        rel_key_cols[r["from_table"]].add(r["from_column"])
        rel_key_cols[r["to_table"]].add(r["to_column"])

    if rels:
        rel_rows = "".join(
            f"<tr>"
            f"<td><b>{esc(r['from_table'])}</b>.<code>{esc(r['from_column'])}</code></td>"
            f"<td><code>{'*' if r['cardinality'].startswith('many') else '1'} : {'*' if r['cardinality'].endswith('many') else '1'}</code></td>"
            f"<td><b>{esc(r['to_table'])}</b>.<code>{esc(r['to_column'])}</code></td>"
            f"<td><span class='badge {'badge-warn' if r['bidirectional'] else ''}'>{'Both (Bidirectional)' if r['bidirectional'] else 'Single'}</span></td>"
            f"<td><span class='badge {'badge-ok' if r['active'] else 'badge-warn'}'>{'Active' if r['active'] else 'Inactive (USERELATIONSHIP)'}</span></td>"
            f"</tr>"
            for r in rels
        )
        rel_table_html = (
            '<div class="table-scroll" style="margin-top:14px"><table class="data-table">'
            "<thead><tr><th>Many / Fact Side</th><th>Cardinality</th><th>One / Dimension Side</th><th>Filter Direction</th><th>State</th></tr></thead>"
            f"<tbody>{rel_rows}</tbody></table></div>"
        )
    else:
        rel_table_html = '<p style="color:var(--fg-muted)">Single-table or standalone model (0 relationships defined).</p>'

    # 3. Data Sources & Tables Blueprint (Summary Matrix + Expandable Blueprints with Visual PQ Pipeline!)
    summary_rows = []
    for ts in analysis["table_summaries"]:
        role_badge = (
            '<span class="badge badge-fact">Fact</span>'
            if ts["name"] in facts
            else ('<span class="badge badge-dim">Dimension</span>' if ts["name"] in dims else '<span class="badge">KPI / Table</span>')
        )
        sql_badge = f' <span class="badge badge-warn">{len(ts["native_queries"])} Native SQL</span>' if ts["native_queries"] else ""
        summary_rows.append(
            f"<tr>"
            f'<td><a href="#{_table_anchor(ts["name"])}"><b>{esc(ts["name"])}</b></a>{" <span class=\"badge\">Hidden</span>" if ts["hidden"] else ""}</td>'
            f"<td>{role_badge}</td>"
            f"<td><code>{esc(ts['mode'])}</code></td>"
            f"<td>{esc(', '.join(ts['source_types']) or 'Calculated / Measures')}{sql_badge}</td>"
            f"<td>{esc(', '.join(ts['details'][:2]) or '-')}</td>"
            f"<td>{esc(ts['description'] or '-')}</td>"
            f"<td>{ts['columns_count']}</td>"
            f"<td>{ts['measures_count']}</td>"
            f"<td>{ts['pq_steps']}</td>"
            f"</tr>"
        )

    raw_tables_by_name = {t["name"]: t for t in parsed["tables"] if not re.match(r"^'?(LocalDateTable|DateTableTemplate)_", t["name"])}
    blueprint_cards = []
    for idx_t, ts in enumerate(analysis["table_summaries"]):
        raw_t = raw_tables_by_name.get(ts["name"])
        if not raw_t:
            continue
        key_set = rel_key_cols.get(ts["name"], set())
        col_rows = "".join(
            f"<tr>"
            f"<td><b>{esc(c['name'])}</b>"
            f"{' <span class=\"badge badge-accent\">Key</span>' if c['name'] in key_set else ''}"
            f"{' <span class=\"badge\">Hidden</span>' if c['hidden'] else ''}</td>"
            f"<td><code>{esc(c['type'] or '-')}</code></td>"
            f"<td>{esc(c['source'] or ('Calculated DAX' if c['expr'] else '-'))}</td>"
            f"<td>{esc(c['format'] or '-')}</td>"
            f"<td>{esc(c['description'] or '-')}</td>"
            f"</tr>"
            for c in raw_t["columns"]
        )
        cols_html = (
            '<div class="table-scroll"><table class="data-table">'
            "<thead><tr><th>Column</th><th>Data Type</th><th>Origin / Source Column</th><th>Format</th><th>Description</th></tr></thead>"
            f"<tbody>{col_rows}</tbody></table></div>"
            if col_rows
            else '<p style="margin:0;color:var(--fg-muted)">Measure-only container table (0 physical columns).</p>'
        )

        calc_col_blocks = "".join(
            f'<div style="margin-top:12px"><b>Calculated Column: <code>{esc(c["name"])}</code></b>'
            f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy DAX</button><pre>{_highlight_dax(c["expr"])}</pre></div></div>'
            for c in raw_t["columns"]
            if c["expr"]
        )

        part_blocks = []
        for p in raw_t["partitions"]:
            if p["code"]:
                if p["kind"] == "m":
                    steps = extract_m_steps(p["code"])
                    pipeline_html = ""
                    if steps:
                        pills = '<span class="pq-arrow">&rarr;</span>'.join(
                            f'<span class="pq-step"><b>{i}. {esc(st["name"])}</b><small>{esc(st["op"])}</small></span>'
                            for i, st in enumerate(steps, 1)
                        )
                        pipeline_html = f'<div style="margin-top:12px;font-size:12px;font-weight:650">Power Query Transformation Pipeline ({len(steps)} steps)</div><div class="pq-pipeline">{pills}</div>'
                    part_blocks.append(
                        f"{pipeline_html}"
                        f'<details class="m-script-toggle"><summary>View Power Query M Script - Partition {esc(p["name"])} ({esc(p["mode"])})</summary>'
                        f'<div style="padding:8px 10px"><div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy M</button><pre>{_highlight_m(p["code"])}</pre></div></div></details>'
                    )
                else:
                    part_blocks.append(
                        f'<div style="margin-top:12px"><b>Calculated Table Expression (<code>{esc(p["name"])}</code>)</b>'
                        f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy DAX</button><pre>{_highlight_dax(p["code"])}</pre></div></div>'
                    )

        hier_html = ""
        if raw_t["hierarchies"]:
            hier_items = "".join(f"<li><b>{esc(h['name'])}</b>: {' &rarr; '.join(esc(lv) for lv in h['levels'])}</li>" for h in raw_t["hierarchies"])
            hier_html = f'<div style="margin-top:10px"><b>Drill-Down Hierarchies:</b><ul style="margin:4px 0">{hier_items}</ul></div>'

        open_attr = " open" if idx_t == 0 else ""
        role_txt = "Fact" if ts["name"] in facts else ("Dimension" if ts["name"] in dims else "Table")
        blueprint_cards.append(
            f'<details class="table-blueprint" id="{_table_anchor(ts["name"])}"{open_attr} data-searchable="{esc((ts["name"] + " " + ts["description"]).lower())}">'
            f"<summary><span>{esc(ts['name'])}"
            + (f' <span style="font-weight:400;color:var(--fg-muted)">: {esc(ts["description"])}</span>' if ts["description"] else "")
            + f'</span><div class="model-meta"><span class="badge badge-accent">{role_txt}</span><span class="badge">{ts["columns_count"]} cols</span><span class="badge">{ts["pq_steps"]} PQ steps</span></div></summary>'
            f'<div class="blueprint-body">{cols_html}{hier_html}{calc_col_blocks}{"".join(part_blocks)}</div>'
            f"</details>"
        )

    expr_html = ""
    if parsed["expressions"]:
        expr_items = "".join(
            f'<div style="margin-bottom:10px"><b><code>{esc(ex["name"])}</code></b>'
            + (f' <span style="color:var(--fg-muted)">({esc(ex["description"])})</span>' if ex["description"] else "")
            + f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy M</button><pre>{_highlight_m(ex["code"])}</pre></div></div>'
            for ex in parsed["expressions"]
        )
        expr_html = f'<div class="card" style="margin-top:16px"><h3 style="margin-top:0;font-size:15px">Shared Power Query Parameters &amp; Functions ({len(parsed["expressions"])})</h3>{expr_items}</div>'

    # 4. Structured DAX Library (Auto-Pretty Formatted!)
    lin_measures = analysis["lineage"] or {}
    depths = _compute_measure_depths(lin_measures)
    dax_groups_html: list[str] = []

    for tbl in sorted(parsed["tables"], key=lambda x: x["name"].lower()):
        if not tbl["measures"]:
            continue
        by_folder: dict[str, list[dict]] = collections.defaultdict(list)
        for m in tbl["measures"]:
            folder = (m.get("folder") or "General Measures").strip()
            by_folder[folder].append(m)

        folder_blocks: list[str] = []
        for folder_name in sorted(by_folder.keys(), key=lambda f: ("" if f == "General Measures" else f.lower())):
            ms = by_folder[folder_name]
            base_ms = sorted([m for m in ms if depths.get(f"{tbl['name']}[{m['name']}]", 0) == 0], key=lambda x: x["name"].lower())
            derived_ms = sorted(
                [m for m in ms if depths.get(f"{tbl['name']}[{m['name']}]", 0) > 0],
                key=lambda x: (depths.get(f"{tbl['name']}[{x['name']}]", 1), x["name"].lower()),
            )

            def _render_m_card(m: dict) -> str:
                m_name = m["name"]
                m_key = f"{tbl['name']}[{m_name}]"
                anchor = _measure_anchor(tbl["name"], m_name)
                li = lin_measures.get(m_key) or {}
                d_val = depths.get(m_key, 0)
                tier_badge = '<span class="badge badge-dim">Base Measure</span>' if d_val == 0 else f'<span class="badge badge-accent">Derived KPI (Tier {d_val})</span>'
                fmt_badge = f'<span class="badge">Format: {esc(m["format"])}</span>' if m.get("format") else ""
                hid_badge = '<span class="badge badge-warn">Hidden</span>' if m.get("hidden") else ""
                desc_html = f'<div class="measure-desc">{esc(m["description"])}</div>' if m.get("description") else ""

                up_chips = []
                for um_key in li.get("upstream_measures", []):
                    um_info = lin_measures.get(um_key) or {"table": tbl["name"], "name": um_key}
                    up_chips.append(f'<a class="dep-chip" href="#{_measure_anchor(um_info["table"], um_info["name"])}">[{esc(um_info["name"])}]</a>')
                for uc in li.get("upstream_columns", []):
                    uc_tbl = uc.split("[", 1)[0]
                    up_chips.append(f'<a class="dep-chip" href="#{_table_anchor(uc_tbl)}">{esc(uc)}</a>')

                down_chips = []
                for dm_key in li.get("downstream_measures", []):
                    dm_info = lin_measures.get(dm_key) or {"table": tbl["name"], "name": dm_key}
                    down_chips.append(f'<a class="dep-chip" href="#{_measure_anchor(dm_info["table"], dm_info["name"])}">[{esc(dm_info["name"])}]</a>')

                deps_html = ""
                if up_chips:
                    deps_html += f'<div class="dep-row"><span>Reads:</span>{"".join(up_chips)}</div>'
                if down_chips:
                    deps_html += f'<div class="dep-row"><span>Used by:</span>{"".join(down_chips)}</div>'

                return (
                    f'<div class="measure-card" id="{anchor}" data-searchable="{esc((m_name + " " + m.get("description", "") + " " + m.get("expr", "")).lower())}">'
                    f'<div class="measure-head"><span class="measure-name">{esc(m_name)}</span><div class="model-meta">{tier_badge}{fmt_badge}{hid_badge}</div></div>'
                    f"{desc_html}"
                    f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy DAX</button><pre>{_highlight_dax(m.get("expr", ""), auto_pretty=True)}</pre></div>'
                    f"{deps_html}"
                    f"</div>"
                )

            tier_sections = []
            if base_ms:
                tier_sections.append(f'<div class="dax-tier-label">Tier 1: Base Aggregations ({len(base_ms)})</div><div class="measure-grid">' + "".join(_render_m_card(m) for m in base_ms) + "</div>")
            if derived_ms:
                tier_sections.append(f'<div class="dax-tier-label">Tier 2+: Derived &amp; Time-Intelligence KPIs ({len(derived_ms)})</div><div class="measure-grid">' + "".join(_render_m_card(m) for m in derived_ms) + "</div>")

            folder_blocks.append(
                f'<div class="dax-folder"><div class="dax-folder-title">Display Folder: {esc(folder_name)} ({len(ms)})</div>'
                + "".join(tier_sections)
                + "</div>"
            )

        dax_groups_html.append(
            f'<details class="dax-table-group" open>'
            f'<summary><span>Measure Host Table: {esc(tbl["name"])}</span><span class="badge badge-accent">{len(tbl["measures"])} measures</span></summary>'
            + "".join(folder_blocks)
            + "</details>"
        )

    dax_list_rows: list[str] = []
    for tbl in sorted(parsed["tables"], key=lambda x: x["name"].lower()):
        for m in sorted(tbl["measures"], key=lambda x: ((x.get("folder") or "").lower(), x["name"].lower())):
            m_key = f"{tbl['name']}[{m['name']}]"
            d_val = depths.get(m_key, 0)
            tier_txt = "Base" if d_val == 0 else f"Tier {d_val}"
            li = lin_measures.get(m_key) or {}
            reads_cnt = len(li.get("upstream_measures", [])) + len(li.get("upstream_columns", []))
            used_cnt = len(li.get("downstream_measures", []))
            one_line = re.sub(r"\s+", " ", m.get("expr", "")).strip()
            preview = (one_line[:110] + "...") if len(one_line) > 110 else one_line
            anchor = _measure_anchor(tbl["name"], m["name"])
            dax_list_rows.append(
                f'<tr data-searchable="{esc((m["name"] + " " + tbl["name"] + " " + (m.get("folder") or "") + " " + one_line).lower())}">'
                f'<td><a href="#{anchor}" onclick="document.querySelector(\'[data-dax-view=cards]\').click()"><b>{esc(m["name"])}</b></a></td>'
                f"<td>{esc(tbl['name'])}</td>"
                f"<td>{esc(m.get('folder') or 'General')}</td>"
                f"<td><span class='badge {'badge-dim' if d_val == 0 else 'badge-accent'}'>{tier_txt}</span></td>"
                f"<td><code>{esc(m.get('format') or '-')}</code></td>"
                f"<td>{reads_cnt}</td>"
                f"<td>{used_cnt}</td>"
                f"<td><code style='font-size:11.5px'>{esc(preview)}</code></td>"
                f"</tr>"
            )

    if dax_groups_html:
        dax_section_body = (
            f'<div id="daxCardsContainer">{"".join(dax_groups_html)}</div>'
            f'<div id="daxListContainer" style="display:none"><div class="table-scroll"><table class="data-table">'
            f"<thead><tr><th>Measure</th><th>Host Table</th><th>Display Folder</th><th>Tier</th><th>Format</th><th>Reads</th><th>Used By</th><th>DAX Preview</th></tr></thead>"
            f'<tbody>{"".join(dax_list_rows)}</tbody></table></div></div>'
        )
    else:
        dax_section_body = '<div class="card"><p style="margin:0;color:var(--fg-muted)">No DAX measures are defined in this semantic model.</p></div>'

    # 5. Model Live Lineage JSON
    lineage_json = json.dumps(_build_model_lineage_json(analysis), ensure_ascii=False).replace("</", "<\\/")

    # 6. RLS, Downstream Reports & Governance
    rls_blocks = []
    for role in parsed["roles"]:
        filt_rows = "".join(
            f'<div style="margin-top:8px"><b>Table <code>{esc(tp["table"])}</code></b>'
            f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy DAX</button><pre>{_highlight_dax(tp["filter_dax"] or "TRUE()")}</pre></div></div>'
            for tp in role["filters"]
        )
        rls_blocks.append(f'<div class="card" style="margin-bottom:10px"><b>RLS Role: {esc(role["name"])}</b> <span class="badge">{esc(role["permission"])}</span>{filt_rows or "<p>No table filter expressions</p>"}</div>')
    rls_html = "".join(rls_blocks) if rls_blocks else '<div class="card"><p style="margin:0;color:var(--fg-muted)">No Row-Level Security (RLS) roles defined in this model.</p></div>'

    reports_html = ""
    if analysis["reports"]:
        r_rows = []
        for r in analysis["reports"]:
            cross = r.get("workspace") and r.get("workspace") != analysis["workspace"]
            cross_badge = ' <span class="badge badge-accent">Cross-Workspace Thin Report</span>' if cross else ""
            r_rows.append(
                f"<tr><td><b>{esc(r['name'])}</b>{cross_badge}</td><td>{esc(r.get('workspace', ''))}</td><td><code>{esc(r.get('report_type', 'PowerBIReport'))}</code></td></tr>"
            )
        reports_html = (
            '<div class="table-scroll" style="margin-top:14px"><table class="data-table">'
            "<thead><tr><th>Downstream Report</th><th>Report Workspace</th><th>Report Type</th></tr></thead>"
            f"<tbody>{''.join(r_rows)}</tbody></table></div>"
        )

    access_html = ""
    if not anonymous and (analysis["permissions"] or analysis["workspace_users"]):
        p_rows = "".join(
            f"<tr><td>{esc(u.get('displayName') or u.get('identifier') or '-')}</td>"
            f"<td><code>{esc(u.get('principalType', '-'))}</code></td>"
            f"<td><span class='badge badge-accent'>{esc(u.get('datasetUserAccessRight') or u.get('groupUserAccessRight') or '-')}</span></td></tr>"
            for u in (analysis["permissions"] or analysis["workspace_users"])[:60]
        )
        access_html = (
            '<div class="table-scroll" style="margin-top:14px"><table class="data-table">'
            "<thead><tr><th>Principal</th><th>Type</th><th>Access Right</th></tr></thead>"
            f"<tbody>{p_rows}</tbody></table></div>"
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(analysis['name'])} - Semantic Model Documentation</title>
  <link rel="stylesheet" href="../assets/portal.css">
</head>
<body>
<div class="doc-shell">
  <aside class="doc-sidebar">
    <a class="doc-back studio-only-link" href="/" style="display:none;margin-bottom:6px">&larr; 1. Scanner &amp; Setup</a>
    <a class="doc-back" href="../index.html">&larr; Catalog Home (All Models)</a>
    <div class="doc-brand">
      <h2>{esc(analysis['name'])}</h2>
      <div class="sub">Workspace: <b>{esc(analysis['workspace'])}</b></div>
    </div>
    <input type="search" class="doc-search" data-quick-search="1" id="modelQuickFilter" placeholder="Filter measures &amp; tables (Ctrl+K)">
    <ul class="toc-list">
      <li><a href="#sec-overview"><span>1. Overview &amp; Health</span><span class="toc-count">{len(findings)}</span></a></li>
      <li><a href="#sec-schema"><span>2. Data Model &amp; Star Schema</span><span class="toc-count">{stats['relationships']}</span></a></li>
      <li><a href="#sec-tables"><span>3. Sources &amp; Tables</span><span class="toc-count">{stats['tables']}</span></a></li>
      <li><a href="#sec-dax"><span>4. DAX Measure Catalog</span><span class="toc-count">{stats['measures']}</span></a></li>
      <li><a href="#sec-lineage"><span>5. Live Lineage Explorer</span><span class="toc-count">Interactive</span></a></li>
      <li><a href="#sec-security"><span>6. Security &amp; Reports</span><span class="toc-count">{len(analysis['reports'])}</span></a></li>
    </ul>
    <div style="margin-top:auto;padding-top:12px;border-top:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;font-size:11.5px;color:var(--fg-muted)">
      <span>PBI Doc Generator v1.0</span>
      <button type="button" class="lin-btn" data-toggle-theme="1">Theme</button>
    </div>
  </aside>

  <main class="doc-main">
    <section class="section" id="sec-overview">
      <div class="section-header">
        <div>
          <h2>1. Executive Overview &amp; Health Summary</h2>
          <div class="hint">Owner: <b>{esc(owner_txt)}</b> &bull; Upstream Connectors: <b>{esc(', '.join(analysis['source_types']) or 'Internal')}</b></div>
        </div>
        <span class="badge {ref_badge}">Refresh: {esc(ref_status)}</span>
      </div>

      <div class="kpi-grid">
        <div class="kpi-card"><div class="val">{stats['tables']}</div><div class="lbl">Tables ({stats['import_tables']} Import / {stats['directquery_tables']} DQ)</div></div>
        <div class="kpi-card"><div class="val">{stats['columns']}</div><div class="lbl">Columns ({stats['calc_columns']} Calculated)</div></div>
        <div class="kpi-card"><div class="val">{stats['measures']}</div><div class="lbl">DAX Measures</div></div>
        <div class="kpi-card"><div class="val">{stats['relationships']}</div><div class="lbl">Relationships ({stats['bidirectional_relationships']} Bi-Di)</div></div>
        <div class="kpi-card"><div class="val">{stats['pq_steps']}</div><div class="lbl">Power Query Steps</div></div>
        <div class="kpi-card"><div class="val">{len(analysis['reports'])}</div><div class="lbl">Bound Reports</div></div>
      </div>

      {findings_html}
    </section>

    <section class="section" id="sec-schema">
      <div class="section-header">
        <h2>2. Data Model &amp; Star Schema</h2>
        <span class="hint">Fact tables (blue) vs. Dimension tables (teal) &bull; Hover or click any table to highlight relationships</span>
      </div>
      <pre class="mermaid">{esc(mermaid_src)}</pre>
      {rel_table_html}
    </section>

    <section class="section" id="sec-tables">
      <div class="section-header">
        <div>
          <h2>3. Data Sources &amp; Tables Blueprint</h2>
          <div class="hint">Storage modes, source endpoints, business descriptions, visual Power Query pipelines, and column definitions</div>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          <button type="button" class="lin-btn" data-details-toggle="tablesBlueprintContainer" data-open="1">Expand All</button>
          <button type="button" class="lin-btn" data-details-toggle="tablesBlueprintContainer" data-open="0">Collapse All</button>
        </div>
      </div>
      <div class="table-scroll" style="margin-bottom:18px">
        <table class="data-table">
          <thead>
            <tr><th>Table</th><th>Role</th><th>Mode</th><th>Connector</th><th>Endpoint / Database</th><th>Description</th><th>Cols</th><th>Measures</th><th>PQ Steps</th></tr>
          </thead>
          <tbody>{''.join(summary_rows)}</tbody>
        </table>
      </div>
      <div id="tablesBlueprintContainer">{''.join(blueprint_cards)}</div>
      {expr_html}
    </section>

    <section class="section" id="sec-dax">
      <div class="section-header">
        <div>
          <h2>4. DAX Measure Catalog</h2>
          <div class="hint">Auto-formatted &amp; organized by Table &rarr; Display Folder &rarr; Base Aggregations first, Derived KPIs second</div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
          <div class="view-toggle">
            <button type="button" class="view-btn active" data-dax-view="cards">Formatted Cards</button>
            <button type="button" class="view-btn" data-dax-view="list">Compact Table</button>
          </div>
          <button type="button" class="lin-btn" data-details-toggle="daxCardsContainer" data-open="1">Expand All</button>
          <button type="button" class="lin-btn" data-details-toggle="daxCardsContainer" data-open="0">Collapse All</button>
        </div>
      </div>
      {dax_section_body}
    </section>

    <section class="section" id="sec-lineage">
      <div class="section-header">
        <h2>5. Interactive End-to-End Live Lineage</h2>
        <span class="hint">Click any source, table, column, DAX measure, or report to trace live upstream &amp; downstream impact</span>
      </div>
      <div class="lineage-app" data-lineage-id="modelLineageData"></div>
      <script type="application/json" id="modelLineageData">{lineage_json}</script>
    </section>

    <section class="section" id="sec-security">
      <div class="section-header">
        <h2>6. Row-Level Security (RLS), Downstream Reports &amp; Access</h2>
        <span class="hint">{stats['rls_roles']} RLS role(s) &bull; {len(analysis['reports'])} bound report(s)</span>
      </div>
      {rls_html}
      {reports_html}
      {access_html}
    </section>
  </main>
</div>

<script src="../assets/mermaid.min.js"></script>
<script src="../assets/portal_common.js"></script>
<script src="../assets/interactive_mermaid.js"></script>
<script src="../assets/lineage_widget.js"></script>
<script>
(function () {{
  var input = document.getElementById("modelQuickFilter");
  if (!input) return;
  input.addEventListener("input", function () {{
    var q = (input.value || "").toLowerCase().trim();
    document.querySelectorAll("[data-searchable]").forEach(function (el) {{
      var match = !q || (el.getAttribute("data-searchable") || "").indexOf(q) !== -1;
      el.style.display = match ? "" : "none";
      if (q && match && el.tagName === "DETAILS") el.open = true;
    }});
  }});
}})();
</script>
</body>
</html>
"""


def generate_portal(store: CatalogStore, output_dir: str | Path | None = None, anonymous: bool = False) -> Path:
    """Generate the complete 4-tab Power BI Workspace, Report, Semantic Model & Lineage Portal."""
    out_root = Path(output_dir) if output_dir else (store.root / "portal")
    assets_dir = out_root / "assets"
    models_dir = out_root / "models"
    assets_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    (assets_dir / "portal.css").write_text(PORTAL_CSS, encoding="utf-8")
    (assets_dir / "interactive_mermaid.js").write_text(INTERACTIVE_MERMAID_JS, encoding="utf-8")
    (assets_dir / "lineage_widget.js").write_text(LINEAGE_WIDGET_JS, encoding="utf-8")
    (assets_dir / "portal_common.js").write_text(PORTAL_COMMON_JS, encoding="utf-8")
    (assets_dir / "mermaid.min.js").write_bytes(_load_mermaid_bytes())

    state = store.load()
    reports_by_ds: dict[str, list[dict]] = collections.defaultdict(list)
    for rep in state["reports"].values():
        ds_id = rep.get("dataset_id")
        if ds_id:
            reports_by_ds[ds_id].append(rep)

    analyses: list[tuple[str, dict]] = []
    slug_by_ds_id: dict[str, str] = {}
    used_slugs: set[str] = set()

    for ds_id, m_meta in sorted(state["models"].items(), key=lambda kv: (kv[1].get("workspace", "").lower(), kv[1].get("name", "").lower())):
        bundle = store.read_tmdl_bundle(m_meta["name"], ds_id)
        if not bundle:
            continue
        base_slug = slugify(f"{m_meta.get('workspace', '')}-{m_meta['name']}") if len(state["workspaces"]) > 1 else slugify(m_meta["name"])
        slug = base_slug
        idx = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{idx}"
            idx += 1
        used_slugs.add(slug)
        slug_by_ds_id[ds_id] = slug

        analysis = analyze_model(m_meta, bundle, reports=reports_by_ds.get(ds_id, []))
        analyses.append((slug, analysis))
        model_html = render_model_html(analysis, slug=slug, anonymous=anonymous)
        (models_dir / f"{slug}.html").write_text(model_html, encoding="utf-8")

    # Summary KPIs
    total_ws = len(state["workspaces"]) or len({a["workspace"] for _, a in analyses})
    total_tables = sum(a["stats"]["tables"] for _, a in analyses)
    total_measures = sum(a["stats"]["measures"] for _, a in analyses)
    total_reports = len(state["reports"]) or sum(len(a["reports"]) for _, a in analyses)
    all_sources = sorted({s for _, a in analyses for s in a["source_types"]})
    total_findings = sum(len(a["findings"]) for _, a in analyses)

    portfolio_lineage_json = json.dumps(_build_workspace_lineage_json(analyses), ensure_ascii=False).replace("</", "<\\/")

    # Build Workspaces & Reports Map (Tab 2)
    ws_rows = []
    for ws_id, ws in sorted(state["workspaces"].items(), key=lambda kv: kv[1].get("name", "").lower()):
        ws_models = [m for m in state["models"].values() if m.get("workspace_id") == ws_id]
        ws_reports = [r for r in state["reports"].values() if r.get("workspace_id") == ws_id]
        ws_dfs = [d for d in state["dataflows"].values() if d.get("workspace_id") == ws_id]
        sku = ws.get("capacity_sku") or ("Dedicated" if ws.get("is_dedicated") else "Shared (Pro)")
        sku_cls = "badge-accent" if ws.get("is_dedicated") else ""
        ws_rows.append(
            f"<tr>"
            f"<td><b>{esc(ws.get('name', ''))}</b></td>"
            f"<td><span class='badge {sku_cls}'>{esc(sku)}</span></td>"
            f"<td><b>{len(ws_models)}</b></td>"
            f"<td><b>{len(ws_reports)}</b></td>"
            f"<td>{len(ws_dfs)}</td>"
            f"<td>{len(ws.get('users') or []) if not anonymous else 'Redacted'}</td>"
            f"</tr>"
        )

    report_map_rows = []
    for rep in sorted(state["reports"].values(), key=lambda r: (r.get("workspace", "").lower(), r.get("name", "").lower())):
        ds_id = rep.get("dataset_id", "")
        ds_meta = state["models"].get(ds_id) or {}
        ds_name = ds_meta.get("name") or (f"External Model ({ds_id[:8]})" if ds_id else "Unbound")
        ds_ws = ds_meta.get("workspace") or rep.get("workspace", "")
        slug = slug_by_ds_id.get(ds_id)
        ds_link = f'<a href="models/{slug}.html"><b>{esc(ds_name)}</b></a>' if slug else esc(ds_name)
        cross = ds_ws and rep.get("workspace") and ds_ws != rep.get("workspace")
        arch_badge = (
            '<span class="badge badge-accent">Cross-Workspace Shared Dataset</span>'
            if cross
            else '<span class="badge badge-ok">Same-Workspace Model</span>'
        )
        report_map_rows.append(
            f"<tr>"
            f"<td><b>{esc(rep.get('name', ''))}</b></td>"
            f"<td>{esc(rep.get('workspace', ''))}</td>"
            f"<td>{ds_link}</td>"
            f"<td>{esc(ds_ws)}</td>"
            f"<td>{arch_badge}</td>"
            f"</tr>"
        )

    orphan_models = [(slug, a) for slug, a in analyses if len(a["reports"]) == 0]
    orphan_html = ""
    if orphan_models:
        o_items = "".join(
            f'<li><a href="models/{slug}.html"><b>{esc(a["name"])}</b></a> (Workspace: {esc(a["workspace"])}) - 0 bound reports</li>'
            for slug, a in orphan_models
        )
        orphan_html = f'<div class="card" style="margin-top:16px"><h3 style="margin-top:0;font-size:15px">Models Without Bound Reports ({len(orphan_models)})</h3><p style="font-size:12.5px;color:var(--fg-muted);margin-top:0">Semantic models with zero reports in scanned workspaces (shared core datasets consumed via Excel/XMLA, or candidates for cleanup):</p><ul style="margin:0">{o_items}</ul></div>'

    def _short_format_label(raw_fmt: str) -> str:
        low = (raw_fmt or "").lower()
        if "pbip" in low or "tmdl" in low:
            return "PBIP / TMDL"
        if "pbix" in low:
            return "Local .pbix"
        if "xlsx" in low or "excel" in low or "powerpivot" in low:
            return "Excel PowerPivot"
        if raw_fmt and raw_fmt != "Power BI Service":
            return f"Service ({raw_fmt})"
        return "Power BI Service"

    # Semantic Model Cards, Compact List Rows, By-Workspace Groups & Health Rows
    cards_html: list[str] = []
    list_rows_html: list[str] = []
    cards_by_ws: dict[str, list[tuple[str, dict, str]]] = collections.defaultdict(list)
    health_rows: list[str] = []

    for slug, a in analyses:
        st = a["stats"]
        bad_cnt = sum(1 for f in a["findings"] if f["severity"] == "bad")
        warn_cnt = sum(1 for f in a["findings"] if f["severity"] == "warn")
        status_cls = "bad" if bad_cnt else ("warn" if warn_cnt else "ok")
        sev_rank = 2 if bad_cnt else (1 if warn_cnt else 0)
        status_badge = (
            f'<span class="badge badge-bad">{bad_cnt} critical</span>'
            if bad_cnt
            else (f'<span class="badge badge-warn">{warn_cnt} warning(s)</span>' if warn_cnt else '<span class="badge badge-ok">Healthy</span>')
        )
        fmt_short = _short_format_label(a.get("storage_mode", ""))
        src_badges = "".join(f'<span class="badge badge-accent">{esc(s)}</span>' for s in a["source_types"][:4])
        owner_val = "Redacted" if anonymous else (a.get("configured_by") or "Local / Unassigned")
        last_ref = a["refresh"][0] if a.get("refresh") else None
        ref_txt = last_ref.get("status", "Completed") if last_ref else "Snapshot"
        search_blob = f"{a['name']} {a['workspace']} {fmt_short} {' '.join(a['source_types'])} {' '.join(t['name'] for t in a['table_summaries'])}".lower()

        data_attrs = (
            f'data-status="{status_cls}" '
            f'data-ws="{esc(a["workspace"].lower())}" '
            f'data-search="{esc(search_blob)}" '
            f'data-name="{esc(a["name"].lower())}" '
            f'data-measures="{st["measures"]}" '
            f'data-tables="{st["tables"]}" '
            f'data-columns="{st["columns"]}" '
            f'data-rels="{st["relationships"]}" '
            f'data-reports="{len(a["reports"])}" '
            f'data-sev="{sev_rank}"'
        )

        card_markup = (
            f'<a class="model-card" href="models/{slug}.html" data-model-item="card" {data_attrs} style="color:inherit;text-decoration:none">'
            f'<div class="card-eyebrow"><span class="eyebrow-type">Semantic Model</span><span>{esc(fmt_short)}</span></div>'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px"><h3>{esc(a["name"])}</h3>{status_badge}</div>'
            f'<div style="font-size:12px;color:var(--fg-muted)">Workspace: <b>{esc(a["workspace"])}</b></div>'
            f'<div class="model-meta">{src_badges or "<span class=\"badge\">Internal</span>"}</div>'
            f'<div class="model-stats">'
            f'<div><b>{st["tables"]}</b>Tables</div>'
            f'<div><b>{st["measures"]}</b>Measures</div>'
            f'<div><b>{st["relationships"]}</b>Rels</div>'
            f'<div><b>{len(a["reports"])}</b>Reports</div>'
            f"</div>"
            f'<div class="card-footer-meta"><span>Owner: {esc(owner_val)}</span><span>Refresh: {esc(ref_txt)}</span></div>'
            f"</a>"
        )
        cards_html.append(card_markup)
        cards_by_ws[a["workspace"]].append((slug, a, card_markup))

        list_rows_html.append(
            f'<tr data-model-item="row" {data_attrs}>'
            f'<td><a href="models/{slug}.html"><b>{esc(a["name"])}</b></a></td>'
            f"<td>{esc(a['workspace'])}</td>"
            f"<td><span class='badge'>{esc(fmt_short)}</span></td>"
            f"<td>{src_badges or '<span class=\"badge\">Internal</span>'}</td>"
            f"<td><b>{st['tables']}</b></td>"
            f"<td>{st['columns']}</td>"
            f"<td><b>{st['measures']}</b></td>"
            f"<td>{st['relationships']}</td>"
            f"<td>{len(a['reports'])}</td>"
            f"<td>{status_badge}</td>"
            f"</tr>"
        )

        for f in a["findings"]:
            b_cls = "badge-bad" if f["severity"] == "bad" else "badge-warn"
            health_rows.append(
                f"<tr>"
                f'<td><a href="models/{slug}.html"><b>{esc(a["name"])}</b></a></td>'
                f"<td>{esc(a['workspace'])}</td>"
                f"<td><span class='badge {b_cls}'>{esc(f['severity'].upper())}</span></td>"
                f"<td><b>{esc(f['title'])}</b></td>"
                f"<td>{esc(f['detail'])}</td>"
                f"</tr>"
            )

    ws_groups_html: list[str] = []
    for ws_name in sorted(cards_by_ws.keys(), key=lambda s: s.lower()):
        ws_items = cards_by_ws[ws_name]
        ws_rep_cnt = sum(len(item_a["reports"]) for _, item_a, _ in ws_items)
        ws_meas_cnt = sum(item_a["stats"]["measures"] for _, item_a, _ in ws_items)
        ws_cards_joined = "".join(c_html.replace('data-model-item="card"', 'data-model-item="wscard"') for _, _, c_html in ws_items)
        ws_groups_html.append(
            f'<details class="ws-group-card" data-ws-group="{esc(ws_name.lower())}" open>'
            f"<summary>"
            f'<span>Workspace: <b>{esc(ws_name)}</b></span>'
            f'<span style="display:flex;gap:8px;align-items:center">'
            f'<span class="badge badge-accent">{len(ws_items)} semantic model(s)</span>'
            f'<span class="badge">{ws_meas_cnt} DAX measures</span>'
            f'<span class="badge">{ws_rep_cnt} report(s)</span>'
            f"</span>"
            f"</summary>"
            f'<div class="ws-group-body"><div class="model-grid">{ws_cards_joined}</div></div>'
            f"</details>"
        )

    ws_chips = "".join(
        f'<button type="button" class="chip-btn" data-ws-chip="{esc(ws.lower())}">Workspace: {esc(ws)}</button>'
        for ws in sorted({a["workspace"] for _, a in analyses})
    )

    gen_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    index_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Power BI Documentation &amp; Live Lineage Portal</title>
  <link rel="stylesheet" href="assets/portal.css">
</head>
<body>
<header class="topbar">
  <div class="topbar-row">
    <div>
      <h1>Power BI Documentation &amp; Live Lineage Portal</h1>
      <p>{total_ws} Workspaces &bull; {len(analyses)} Semantic Models &bull; {total_reports} Reports &bull; Generated {esc(gen_ts)}</p>
    </div>
    <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
      <div class="app-switcher studio-only-link" style="display:none">
        <a href="/">&larr; 1. Scanner &amp; Setup</a>
        <span class="active-seg">2. Documentation Portal</span>
      </div>
      <button type="button" class="btn-ghost" data-toggle-theme="1">Switch Light / Dark</button>
    </div>
  </div>
  <nav class="top-tabs">
    <button type="button" class="top-tab active" data-tab="tab-portfolio">1. Semantic Models ({len(analyses)})</button>
    <button type="button" class="top-tab" data-tab="tab-workspaces">2. Workspaces &amp; Reports ({total_reports})</button>
    <button type="button" class="top-tab" data-tab="tab-lineage">3. Live Lineage Explorer</button>
    <button type="button" class="top-tab" data-tab="tab-health">4. Governance &amp; Health ({total_findings})</button>
  </nav>
</header>

<main class="catalog-wrap">
  <div class="kpi-grid">
    <div class="kpi-card"><div class="val">{total_ws}</div><div class="lbl">Workspaces</div></div>
    <div class="kpi-card"><div class="val">{len(analyses)}</div><div class="lbl">Semantic Models</div></div>
    <div class="kpi-card"><div class="val">{total_reports}</div><div class="lbl">Power BI Reports</div></div>
    <div class="kpi-card"><div class="val">{total_tables}</div><div class="lbl">Model Tables</div></div>
    <div class="kpi-card"><div class="val">{total_measures}</div><div class="lbl">DAX Measures</div></div>
    <div class="kpi-card"><div class="val">{len(all_sources)}</div><div class="lbl">Source Connectors</div></div>
  </div>

  <section class="tab-pane active" id="tab-portfolio">
    <div class="filter-bar" style="justify-content:space-between">
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;flex:1;min-width:260px">
        <input type="search" id="catalogSearch" data-quick-search="1" placeholder="Search semantic models, workspaces, source connectors, or tables (Ctrl+K)...">
        <button type="button" class="chip-btn active" data-status-chip="all">All ({len(analyses)})</button>
        <button type="button" class="chip-btn" data-status-chip="ok">Healthy</button>
        <button type="button" class="chip-btn" data-status-chip="warn">Warnings</button>
        <button type="button" class="chip-btn" data-status-chip="bad">Critical</button>
        {ws_chips}
      </div>
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center">
        <select id="catalogSort" class="sort-select" aria-label="Sort semantic models">
          <option value="name">Sort: Name (A-Z)</option>
          <option value="measures">Sort: Most DAX Measures</option>
          <option value="tables">Sort: Most Tables</option>
          <option value="ws">Sort: Workspace (A-Z)</option>
          <option value="sev">Sort: Health / Warnings First</option>
        </select>
        <div class="view-toggle" role="group" aria-label="Catalog layout view">
          <button type="button" class="view-btn active" data-catalog-view="grid">Grid</button>
          <button type="button" class="view-btn" data-catalog-view="list">List</button>
          <button type="button" class="view-btn" data-catalog-view="workspace">By Workspace</button>
        </div>
      </div>
    </div>

    <div style="display:flex;justify-content:space-between;align-items:center;margin:-6px 2px 12px 2px;font-size:12.5px;color:var(--fg-muted)">
      <span id="catalogCountLabel">Showing <b>{len(analyses)}</b> of <b>{len(analyses)}</b> semantic models</span>
      <button type="button" id="catalogResetBtn" class="lin-btn" style="display:none">Reset filters</button>
    </div>

    <div class="model-grid" id="modelGrid">
      {''.join(cards_html) or '<div class="card">No semantic models documented yet. Open 1. Scanner &amp; Setup to connect or import a local model.</div>'}
    </div>

    <div class="table-scroll" id="modelListWrap" style="display:none">
      <table class="data-table" id="modelListTable">
        <thead>
          <tr>
            <th class="sortable-th" data-sort-col="name">Semantic Model &updownarrow;</th>
            <th class="sortable-th" data-sort-col="ws">Workspace &updownarrow;</th>
            <th>Format</th>
            <th>Connectors</th>
            <th class="sortable-th" data-sort-col="tables">Tables &updownarrow;</th>
            <th class="sortable-th" data-sort-col="columns">Cols &updownarrow;</th>
            <th class="sortable-th" data-sort-col="measures">DAX Measures &updownarrow;</th>
            <th class="sortable-th" data-sort-col="rels">Rels &updownarrow;</th>
            <th class="sortable-th" data-sort-col="reports">Reports &updownarrow;</th>
            <th class="sortable-th" data-sort-col="sev">Health &updownarrow;</th>
          </tr>
        </thead>
        <tbody id="modelListBody">
          {''.join(list_rows_html) or '<tr><td colspan="10">No semantic models documented yet.</td></tr>'}
        </tbody>
      </table>
    </div>

    <div id="modelWsGroups" style="display:none">
      {''.join(ws_groups_html) or '<div class="card">No workspaces documented yet.</div>'}
    </div>
  </section>

  <section class="tab-pane" id="tab-workspaces">
    <h3 style="margin:0 0 10px 0;font-size:16px">Workspace Inventory &amp; Capacity Overview</h3>
    <div class="table-scroll" style="margin-bottom:24px">
      <table class="data-table">
        <thead>
          <tr><th>Workspace</th><th>Capacity / SKU</th><th>Semantic Models</th><th>Reports</th><th>Dataflows</th><th>Principals</th></tr>
        </thead>
        <tbody>
          {''.join(ws_rows) or '<tr><td colspan="6">No workspaces recorded.</td></tr>'}
        </tbody>
      </table>
    </div>

    <h3 style="margin:0 0 10px 0;font-size:16px">Reports to Semantic Model Mapping (Including Cross-Workspace Shared Datasets)</h3>
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr><th>Power BI Report</th><th>Report Workspace</th><th>Underlying Semantic Model</th><th>Model Workspace</th><th>Binding Architecture</th></tr>
        </thead>
        <tbody>
          {''.join(report_map_rows) or '<tr><td colspan="5">No reports recorded in scanned workspaces.</td></tr>'}
        </tbody>
      </table>
    </div>
    {orphan_html}
  </section>

  <section class="tab-pane" id="tab-lineage">
    <div style="margin-bottom:12px;color:var(--fg-muted);font-size:13px">
      Trace data end-to-end from upstream platforms and database views through semantic models and core DAX KPIs into downstream Power BI reports across workspaces.
    </div>
    <div class="lineage-app" data-lineage-id="portfolioLineageData"></div>
    <script type="application/json" id="portfolioLineageData">{portfolio_lineage_json}</script>
  </section>

  <section class="tab-pane" id="tab-health">
    <div class="table-scroll">
      <table class="data-table">
        <thead>
          <tr><th>Semantic Model</th><th>Workspace</th><th>Severity</th><th>Finding</th><th>Recommended Action</th></tr>
        </thead>
        <tbody>
          {''.join(health_rows) or '<tr><td colspan="5">Zero governance or refresh warnings across all documented models.</td></tr>'}
        </tbody>
      </table>
    </div>
  </section>
</main>

<script src="assets/portal_common.js"></script>
<script src="assets/lineage_widget.js"></script>
<script>
(function () {{
  var search = document.getElementById("catalogSearch");
  var sortSelect = document.getElementById("catalogSort");
  var countLbl = document.getElementById("catalogCountLabel");
  var resetBtn = document.getElementById("catalogResetBtn");
  var gridWrap = document.getElementById("modelGrid");
  var listWrap = document.getElementById("modelListWrap");
  var listBody = document.getElementById("modelListBody");
  var wsWrap = document.getElementById("modelWsGroups");

  var activeStatus = "all";
  var activeWs = "all";
  var activeView = localStorage.getItem("pbidoc-v1-catalog-view") || "grid";
  var sortDir = 1;
  var totalCount = {len(analyses)};

  function setCatalogView(v) {{
    if (["grid", "list", "workspace"].indexOf(v) === -1) v = "grid";
    activeView = v;
    localStorage.setItem("pbidoc-v1-catalog-view", v);
    document.querySelectorAll("[data-catalog-view]").forEach(function (b) {{
      b.classList.toggle("active", b.getAttribute("data-catalog-view") === v);
    }});
    if (gridWrap) gridWrap.style.display = (v === "grid") ? "" : "none";
    if (listWrap) listWrap.style.display = (v === "list") ? "" : "none";
    if (wsWrap) wsWrap.style.display = (v === "workspace") ? "" : "none";
  }}

  function compareItems(a, b, key, dir) {{
    var numCols = ["measures", "tables", "columns", "rels", "reports", "sev"];
    if (numCols.indexOf(key) !== -1) {{
      var na = parseFloat(a.getAttribute("data-" + key) || "0");
      var nb = parseFloat(b.getAttribute("data-" + key) || "0");
      if (na !== nb) return (nb - na) * dir;
    }} else {{
      var sa = (a.getAttribute("data-" + key) || "");
      var sb = (b.getAttribute("data-" + key) || "");
      if (sa !== sb) return sa.localeCompare(sb) * dir;
    }}
    return (a.getAttribute("data-name") || "").localeCompare(b.getAttribute("data-name") || "");
  }}

  function applySort(key, dir) {{
    var d = dir || 1;
    if (gridWrap) {{
      Array.from(gridWrap.querySelectorAll('[data-model-item="card"]'))
        .sort(function (a, b) {{ return compareItems(a, b, key, d); }})
        .forEach(function (el) {{ gridWrap.appendChild(el); }});
    }}
    if (listBody) {{
      Array.from(listBody.querySelectorAll('[data-model-item="row"]'))
        .sort(function (a, b) {{ return compareItems(a, b, key, d); }})
        .forEach(function (el) {{ listBody.appendChild(el); }});
    }}
    if (wsWrap) {{
      wsWrap.querySelectorAll(".model-grid").forEach(function (wg) {{
        Array.from(wg.querySelectorAll('[data-model-item="wscard"]'))
          .sort(function (a, b) {{ return compareItems(a, b, key, d); }})
          .forEach(function (el) {{ wg.appendChild(el); }});
      }});
    }}
  }}

  function matchesFilter(el, q) {{
    var okStatus = activeStatus === "all" || el.getAttribute("data-status") === activeStatus;
    var okWs = activeWs === "all" || el.getAttribute("data-ws") === activeWs;
    var okQ = !q || (el.getAttribute("data-search") || "").indexOf(q) !== -1;
    return okStatus && okWs && okQ;
  }}

  function applyFilters() {{
    var q = (search && search.value || "").toLowerCase().trim();
    var shown = 0;
    document.querySelectorAll('[data-model-item="card"]').forEach(function (el) {{
      var ok = matchesFilter(el, q);
      el.style.display = ok ? "" : "none";
      if (ok) shown++;
    }});
    document.querySelectorAll('[data-model-item="row"]').forEach(function (el) {{
      el.style.display = matchesFilter(el, q) ? "" : "none";
    }});
    document.querySelectorAll('[data-model-item="wscard"]').forEach(function (el) {{
      el.style.display = matchesFilter(el, q) ? "" : "none";
    }});
    document.querySelectorAll("[data-ws-group]").forEach(function (grp) {{
      var hasVisible = Array.from(grp.querySelectorAll('[data-model-item="wscard"]')).some(function (c) {{ return c.style.display !== "none"; }});
      grp.style.display = hasVisible ? "" : "none";
    }});
    if (countLbl) {{
      countLbl.innerHTML = "Showing <b>" + shown + "</b> of <b>" + totalCount + "</b> semantic models";
    }}
    if (resetBtn) {{
      resetBtn.style.display = (q || activeStatus !== "all" || activeWs !== "all") ? "" : "none";
    }}
  }}

  setCatalogView(activeView);
  if (search) search.addEventListener("input", applyFilters);
  if (sortSelect) {{
    sortSelect.addEventListener("change", function () {{
      sortDir = 1;
      applySort(sortSelect.value, 1);
    }});
  }}
  if (resetBtn) {{
    resetBtn.addEventListener("click", function () {{
      if (search) search.value = "";
      activeStatus = "all";
      activeWs = "all";
      document.querySelectorAll("[data-status-chip]").forEach(function (b) {{ b.classList.toggle("active", b.getAttribute("data-status-chip") === "all"); }});
      document.querySelectorAll("[data-ws-chip]").forEach(function (b) {{ b.classList.remove("active"); }});
      applyFilters();
    }});
  }}

  document.addEventListener("click", function (e) {{
    var vb = e.target.closest("[data-catalog-view]");
    if (vb) {{
      setCatalogView(vb.getAttribute("data-catalog-view"));
      return;
    }}
    var th = e.target.closest("[data-sort-col]");
    if (th) {{
      var col = th.getAttribute("data-sort-col");
      if (sortSelect && ["name", "measures", "tables", "ws", "sev"].indexOf(col) !== -1) {{
        if (sortSelect.value === col) sortDir = -sortDir; else sortDir = 1;
        sortSelect.value = col;
      }} else {{
        sortDir = -sortDir;
      }}
      applySort(col, sortDir);
      return;
    }}
    var sb = e.target.closest("[data-status-chip]");
    if (sb) {{
      activeStatus = sb.getAttribute("data-status-chip");
      document.querySelectorAll("[data-status-chip]").forEach(function (b) {{ b.classList.toggle("active", b === sb); }});
      applyFilters();
      return;
    }}
    var wb = e.target.closest("[data-ws-chip]");
    if (wb) {{
      var val = wb.getAttribute("data-ws-chip");
      activeWs = (activeWs === val) ? "all" : val;
      document.querySelectorAll("[data-ws-chip]").forEach(function (b) {{ b.classList.toggle("active", b.getAttribute("data-ws-chip") === activeWs); }});
      applyFilters();
    }}
  }});
}})();
</script>
</body>
</html>
"""
    index_path = out_root / "index.html"
    index_path.write_text(index_html, encoding="utf-8")
    return index_path
