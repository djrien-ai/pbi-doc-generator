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
import urllib.parse
from pathlib import Path
from typing import Any

from .analyzer import analyze_model
from .dataflows import parse_dataflow_definition
from .e2e_lineage import build_e2e_graph
from .portal_widgets import (
    STAR_SCHEMA_WIDGET_JS,
    V11_WIDGETS_CSS,
    XRAY_DRAWER_JS,
    build_dataflow_xray_entry,
    build_report_xray_entry,
    build_star_schema_json,
    middle_truncate,
    render_model_access_html,
    render_model_reports_html,
    render_pq_partition_block,
    render_upstream_dataflows_banner,
)
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


MULTILINE_DAX_FUNCS = {
    "CALCULATE", "CALCULATETABLE", "DIVIDE", "SWITCH", "IF", "FILTER",
    "SUMX", "AVERAGEX", "MINX", "MAXX", "COUNTX", "RANKX", "TOPN",
    "ADDCOLUMNS", "SUMMARIZE", "SUMMARIZECOLUMNS", "SELECTCOLUMNS",
    "TREATAS", "USERELATIONSHIP", "CROSSFILTER", "COALESCE", "KEEPFILTERS",
}


def format_dax_pretty(expr: str) -> str:
    """
    Auto-format single-line or inconsistently spaced DAX into clean, SQLBI-style multi-line DAX,
    while preserving expressions that the model author already indented across multiple lines.
    """
    raw = (expr or "").replace("\r\n", "\n").strip()
    if not raw:
        return ""
    lines = [ln.replace("\t", "    ") for ln in raw.split("\n")]
    if len(lines) >= 3 and any(ln.startswith("  ") for ln in lines[1:]):
        return "\n".join(lines)

    upper_raw = raw.upper()
    has_var_return = bool(re.search(r"\b(VAR|RETURN)\b", upper_raw))
    has_ml_func = any(re.search(rf"\b{fn}\s*\(", upper_raw) for fn in MULTILINE_DAX_FUNCS)
    if len(raw) < 52 and not has_var_return and not has_ml_func:
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
                if out and not out[-1].endswith("\n") and not out[-1].endswith("    "):
                    _newline(indent)
                out.append(kw)
                i += len(kw)
                if kw == "RETURN":
                    _newline(indent + 1)
                    while i < n and raw[i].isspace():
                        i += 1
                continue

            # Uppercase DAX function calls and break complex `VAR x = CALCULATE(...)` onto indented line
            m_fn = re.match(r"^([A-Za-z_][A-Za-z0-9_.]*)\s*(?=\()", raw[i:])
            if m_fn:
                fn_raw = m_fn.group(1)
                fn_up = fn_raw.upper()
                if fn_up in DAX_KEYWORDS or fn_up in MULTILINE_DAX_FUNCS:
                    out.append(fn_up)
                else:
                    out.append(fn_raw)
                i += len(m_fn.group(0))
                continue

        if ch == "(":
            # Look ahead to find matching ')' length and whether top-level commas exist
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
            prev_word_m = re.search(r"([A-Za-z_][A-Za-z0-9_.]*)$", "".join(out[-6:]).strip())
            caller_fn = prev_word_m.group(1).upper() if prev_word_m else ""
            out.append("(")
            if has_comma and (caller_fn in MULTILINE_DAX_FUNCS or span > 36):
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
  --code-bg: #f8fafc;
  --code-fg: #1e293b;
  --code-border: #dce4f0;
  --code-accent-bar: #93c5fd;
  --tok-kw: #0550ae;
  --tok-fn: #6d28d9;
  --tok-str: #116329;
  --tok-cmt: #64748b;
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
  --code-bg: #172235;
  --code-fg: #e2e8f0;
  --code-border: #2b3b54;
  --code-accent-bar: #3b82f6;
  --tok-kw: #7dd3fc;
  --tok-fn: #c4b5fd;
  --tok-str: #6ee7b7;
  --tok-cmt: #94a3b8;
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
.theme-icon-btn {
  width: 34px;
  height: 34px;
  border-radius: 9px;
  background: rgba(255,255,255,0.14);
  border: 1px solid rgba(255,255,255,0.26);
  color: #fff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  padding: 0;
  flex-shrink: 0;
}
.theme-icon-btn:hover { background: rgba(255,255,255,0.26); }
.theme-icon-btn.surface-btn {
  background: var(--surface-alt);
  border-color: var(--border);
  color: var(--fg);
  width: 30px;
  height: 30px;
  border-radius: 8px;
}
.theme-icon-btn.surface-btn:hover { border-color: var(--accent); color: var(--accent); background: var(--accent-soft); }
.theme-icon-btn .icon-sun { display: none; }
[data-theme="dark"] .theme-icon-btn .icon-moon { display: none; }
[data-theme="dark"] .theme-icon-btn .icon-sun { display: block; }

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
  grid-template-columns: 256px minmax(0, 1fr);
  min-height: 100vh;
}
.doc-sidebar {
  position: sticky;
  top: 0;
  height: 100vh;
  overflow-y: auto;
  overflow-x: hidden;
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
  overflow-wrap: anywhere;
  word-break: break-word;
}
.doc-brand .sub {
  font-size: 12px;
  color: var(--fg-muted);
  margin-top: 4px;
  overflow-wrap: anywhere;
  word-break: break-word;
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
  padding: 28px 32px 68px 32px;
  max-width: 100%;
  min-width: 0;
  overflow-x: hidden;
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
.table-scroll {
  width: 100%;
  overflow-x: hidden;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.sticky-table-scroll {
  max-height: 460px;
  overflow-y: auto;
}
.sticky-table-scroll table.data-table thead th {
  position: sticky;
  top: 0;
  z-index: 3;
  box-shadow: 0 1px 0 var(--border);
}
table.data-table {
  width: 100%;
  table-layout: auto;
  border-collapse: collapse;
  font-size: 12.5px;
}
table.data-table th {
  text-align: left;
  padding: 9px 10px;
  background: var(--surface-alt);
  color: var(--fg);
  font-weight: 650;
  border-bottom: 1px solid var(--border);
  line-height: 1.25;
}
table.data-table td {
  padding: 8px 10px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
  overflow-wrap: anywhere;
  word-break: break-word;
}
table.data-table td code,
table.data-table td b,
table.data-table td a {
  overflow-wrap: anywhere;
  word-break: break-word;
}
table.data-table td .badge {
  white-space: nowrap;
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
  border: 1px solid var(--code-border);
  border-left: 3px solid var(--code-accent-bar);
  border-radius: 8px;
  padding: 11px 74px 11px 14px;
  overflow-x: hidden;
  font-size: 12.5px;
  line-height: 1.56;
  margin: 4px 0;
}
.code-block pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; word-break: break-word; }
.copy-btn {
  position: absolute;
  top: 7px;
  right: 8px;
  background: var(--surface);
  color: var(--fg-muted);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
}
.copy-btn:hover { background: var(--accent-soft); border-color: var(--accent); color: var(--accent); }
.kw { color: var(--tok-kw); font-weight: 650; }
.fn { color: var(--tok-fn); font-weight: 550; }
.str { color: var(--tok-str); }
.cmt { color: var(--tok-cmt); font-style: italic; }

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
  grid-template-columns: 220px minmax(0, 1fr) 310px;
  height: 610px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  overflow: hidden;
}
.lineage-app.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 9985;
  height: 100vh;
  border-radius: 0;
}
body.lin-fullscreen-lock { overflow: hidden; }
.lin-left {
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-width: 0;
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
  overflow-x: hidden;
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
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.lin-nav-item:hover { background: var(--surface); border-color: var(--border); }
.lin-nav-item.active {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 600;
}
.lin-nav-item small { color: var(--fg-muted); font-size: 10.5px; overflow-wrap: anywhere; word-break: break-word; }

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
  flex-wrap: wrap;
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
.lin-canvas-scroll { position: relative; flex: 1 1 auto; overflow-y: auto; overflow-x: hidden; padding: 12px; }
.lin-columns {
  position: relative;
  display: grid;
  grid-auto-flow: column;
  grid-auto-columns: minmax(0, 1fr);
  gap: 12px;
  width: 100%;
  min-width: 0;
  z-index: 2;
}
.lin-columns.is-vertical {
  display: flex;
  flex-direction: column;
  gap: 22px;
}
.lin-col { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.lin-columns.is-vertical .lin-col {
  flex-direction: row;
  flex-wrap: wrap;
  align-items: stretch;
  gap: 8px;
  background: rgba(148, 163, 184, 0.05);
  border: 1px dashed var(--border);
  border-radius: 10px;
  padding: 10px 12px;
}
.lin-col-hdr {
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--fg-muted);
  padding-bottom: 5px;
  border-bottom: 2px solid var(--border);
  margin-bottom: 3px;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.lin-columns.is-vertical .lin-col-hdr {
  flex: 0 0 100%;
  margin-bottom: 4px;
}
.lin-columns.is-vertical .lin-node {
  flex: 0 1 215px;
}
.lin-scope-badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 2px 8px;
  border-radius: 6px;
  font-size: 10px;
  font-weight: 750;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  background: var(--accent-soft);
  color: var(--accent);
}
.lin-filter-select {
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--fg);
  font-size: 11.5px;
  font-weight: 600;
  max-width: 190px;
}
.publish-top-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 13px;
  border-radius: 8px;
  font-size: 12.5px;
  font-weight: 700;
  cursor: pointer;
  border: 1px solid var(--accent);
  background: var(--accent);
  color: #fff;
  transition: filter 0.12s ease, transform 0.1s ease;
}
.publish-top-btn:hover { filter: brightness(1.08); }
.topbar .publish-top-btn {
  background: #ffffff;
  color: #072854;
  border-color: #ffffff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.16);
}
[data-standalone-model="1"] .doc-sidebar .doc-back,
[data-standalone-model="1"] .doc-topbar .model-switcher-select,
[data-standalone-model="1"] .doc-crumbs a[href*="index.html"],
[data-standalone-model="1"] .doc-crumbs .crumb-sep:first-of-type {
  display: none !important;
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
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.lin-node:hover { border-color: var(--accent); transform: translateY(-1px); }
.lin-node .n-title { font-weight: 650; overflow-wrap: anywhere; word-break: break-word; line-height: 1.25; }
.lin-node .n-sub { font-size: 10.5px; color: var(--fg-muted); margin-top: 2px; overflow-wrap: anywhere; word-break: break-word; }
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
  overflow-x: hidden;
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
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
  overflow: hidden;
  padding: 16px;
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

@media screen and (max-width: 1100px) {
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
        var avail = Math.max(260, viewport.clientWidth - 36);
        var fit = Math.max(0.15, Math.min(1.0, avail / baseWidth));
        svg.dataset.zoom = String(fit);
        svg.style.width = Math.max(220, Math.floor(baseWidth * fit)) + "px";
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
        var allNodes = graph.nodes || [];
        var allEdges = graph.edges || [];
        var layers = graph.layers || [];
        if (!allNodes.length) {
            container.innerHTML = '<div style="padding:24px;color:var(--fg-muted)">No lineage objects available for this view.</div>';
            return;
        }

        var isPortfolio = (scriptId === "portfolioLineageData") || (graph.scope === "portfolio");
        var wsOptions = graph.workspaces || [];
        var mdlOptions = graph.models || [];
        var savedOrient = (window.PbiStorage && window.PbiStorage.get("pbidoc-v11-lin-orient")) || "horizontal";

        var state = {
            focusId: graph.defaultFocus || (allNodes[0] && allNodes[0].id) || null,
            hoverId: null,
            layerFilter: "all",
            search: "",
            connectedOnly: true,
            showKpis: !isPortfolio,
            orientation: (savedOrient === "vertical") ? "vertical" : "horizontal",
            wsFilter: "all",
            modelFilter: "all",
            expandedCols: {}
        };

        // Smart default: if portfolio is small (<= 3 models), show full clean estate map right away; if larger, focus primary model cleanly
        if (isPortfolio && mdlOptions.length > 0 && mdlOptions.length <= 4) {
            state.focusId = null;
            state.connectedOnly = false;
        }

        var scopeBadgeHtml = isPortfolio
            ? '<span class="lin-scope-badge" title="High-level cross-workspace architecture">Macro &bull; Portfolio Architecture</span>'
            : '<span class="lin-scope-badge" title="Granular table, column, Power Query, Native SQL &amp; DAX lineage">Micro &bull; Model SQL &amp; DAX Lineage</span>';

        var scopeSelectsHtml = "";
        if (isPortfolio && wsOptions.length > 1) {
            scopeSelectsHtml += '<select class="lin-filter-select lin-ws-select" aria-label="Filter by workspace"><option value="all">All Workspaces (' + wsOptions.length + ')</option>' +
                wsOptions.map(function (w) { return '<option value="' + escHtml(w) + '">' + escHtml(w) + '</option>'; }).join("") + '</select>';
        }
        if (isPortfolio && mdlOptions.length > 1) {
            scopeSelectsHtml += '<select class="lin-filter-select lin-mdl-select" aria-label="Filter by semantic model"><option value="all">All Models (' + mdlOptions.length + ')</option>' +
                mdlOptions.map(function (m) { return '<option value="' + escHtml(m.slug) + '">' + escHtml(m.name) + '</option>'; }).join("") + '</select>';
        }
        var kpiToggleHtml = isPortfolio
            ? '<button type="button" class="lin-btn lin-toggle-kpis" title="Toggle intermediate DAX KPI nodes between Semantic Models and Reports">+ Core KPIs</button>'
            : '';

        container.innerHTML =
            '<div class="lin-left">' +
              '<div class="lin-left-top">' +
                '<input type="search" class="lin-search" placeholder="Search SQL, dataflows, tables, DAX, reports...">' +
                '<div class="lin-layer-pills"></div>' +
              '</div>' +
              '<div class="lin-nav-list"></div>' +
            '</div>' +
            '<div class="lin-center">' +
              '<div class="lin-toolbar">' +
                '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
                  scopeBadgeHtml +
                  '<span class="lin-status"></span>' +
                '</div>' +
                '<div class="lin-toolbar-actions" style="flex-wrap:wrap">' +
                  scopeSelectsHtml +
                  kpiToggleHtml +
                  '<button type="button" class="lin-btn lin-toggle-orient" title="Switch between Horizontal (Left-to-Right) and Vertical (Top-to-Bottom) swimlanes"></button>' +
                  '<button type="button" class="lin-btn lin-toggle-conn"></button>' +
                  '<button type="button" class="lin-btn lin-show-all">Show full map</button>' +
                  '<button type="button" class="lin-btn lin-toggle-fs">Fullscreen</button>' +
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
        var btnFs = container.querySelector(".lin-toggle-fs");
        var btnOrient = container.querySelector(".lin-toggle-orient");
        var btnKpis = container.querySelector(".lin-toggle-kpis");
        var selWs = container.querySelector(".lin-ws-select");
        var selMdl = container.querySelector(".lin-mdl-select");
        var scrollBox = container.querySelector(".lin-canvas-scroll");
        var svgEl = container.querySelector("svg.lin-svg");
        var colsEl = container.querySelector(".lin-columns");
        var rightEl = container.querySelector(".lin-right");

        var e2eIndex = new Map();
        allNodes.forEach(function (n) {
            if (n.e2eId) e2eIndex.set(n.e2eId, n.id);
        });

        var activeNodes = [];
        var activeEdges = [];
        var nodeMap = new Map();
        var outMap = new Map();
        var inMap = new Map();

        function rebuildActiveGraph() {
            var baseNodes = allNodes.filter(function (n) {
                if (isPortfolio && !state.showKpis && n.kpiDetail && n.id !== state.focusId) return false;
                return true;
            });
            var baseIds = new Set(baseNodes.map(function (n) { return n.id; }));
            var baseEdges = allEdges.filter(function (e) {
                if (!baseIds.has(e.from) || !baseIds.has(e.to)) return false;
                if (isPortfolio && state.showKpis && e.directModelEdge) return false;
                return true;
            });

            // Apply optional Workspace / Model scope filter while preserving upstream/downstream context of matching models
            if (isPortfolio && (state.wsFilter !== "all" || state.modelFilter !== "all")) {
                var tmpOut = new Map();
                var tmpIn = new Map();
                baseNodes.forEach(function (n) { tmpOut.set(n.id, []); tmpIn.set(n.id, []); });
                baseEdges.forEach(function (e) {
                    tmpOut.get(e.from).push(e.to);
                    tmpIn.get(e.to).push(e.from);
                });
                var seeds = baseNodes.filter(function (n) {
                    if (state.modelFilter !== "all") return n.modelSlug === state.modelFilter || n.id === ("mdl:" + state.modelFilter);
                    if (state.wsFilter !== "all") return (n.workspace || "") === state.wsFilter;
                    return true;
                });
                var keep = new Set();
                seeds.forEach(function (s) {
                    keep.add(s.id);
                    var q1 = (tmpIn.get(s.id) || []).slice();
                    while (q1.length) {
                        var u = q1.shift();
                        if (!keep.has(u)) { keep.add(u); (tmpIn.get(u) || []).forEach(function (p) { q1.push(p); }); }
                    }
                    var q2 = (tmpOut.get(s.id) || []).slice();
                    while (q2.length) {
                        var v = q2.shift();
                        if (!keep.has(v)) { keep.add(v); (tmpOut.get(v) || []).forEach(function (nx) { q2.push(nx); }); }
                    }
                });
                activeNodes = baseNodes.filter(function (n) { return keep.has(n.id); });
                activeEdges = baseEdges.filter(function (e) { return keep.has(e.from) && keep.has(e.to); });
            } else {
                activeNodes = baseNodes;
                activeEdges = baseEdges;
            }

            nodeMap = new Map();
            outMap = new Map();
            inMap = new Map();
            activeNodes.forEach(function (n) {
                nodeMap.set(n.id, n);
                outMap.set(n.id, []);
                inMap.set(n.id, []);
            });
            activeEdges.forEach(function (e) {
                if (outMap.has(e.from) && inMap.has(e.to)) {
                    outMap.get(e.from).push(e.to);
                    inMap.get(e.to).push(e.from);
                }
            });
            if (state.focusId && !nodeMap.has(state.focusId)) {
                state.focusId = null;
            }
        }

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
            var html = '<button type="button" class="lin-pill ' + (state.layerFilter === "all" ? "active" : "") + '" data-layer="all">All (' + activeNodes.length + ')</button>';
            layers.forEach(function (l) {
                var cnt = activeNodes.filter(function (n) { return n.layer === l.id; }).length;
                if (!cnt) return;
                html += '<button type="button" class="lin-pill ' + (state.layerFilter === l.id ? "active" : "") + '" data-layer="' + escHtml(l.id) + '">' + escHtml(l.label) + ' (' + cnt + ')</button>';
            });
            pillsWrap.innerHTML = html;
        }

        function renderNav() {
            var q = state.search.toLowerCase();
            var filtered = activeNodes.filter(function (n) {
                if (state.layerFilter !== "all" && n.layer !== state.layerFilter) return false;
                if (q && (n.label + " " + (n.sub || "") + " " + (n.detail || "") + " " + (n.sqlCode || "")).toLowerCase().indexOf(q) === -1) return false;
                return true;
            });
            navList.innerHTML = filtered.slice(0, 300).map(function (n) {
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

            var activeTarget = state.focusId || state.hoverId;
            var hovUp = (!state.focusId && state.hoverId) ? traceSet(state.hoverId, inMap) : upstreamSet;
            var hovDown = (!state.focusId && state.hoverId) ? traceSet(state.hoverId, outMap) : downstreamSet;
            var denseUnfocused = !activeTarget && domNodes.size > 34;

            var paths = [];
            var isVert = state.orientation === "vertical";
            activeEdges.forEach(function (e) {
                if (!domNodes.has(e.from) || !domNodes.has(e.to)) return;
                var a = domNodes.get(e.from).getBoundingClientRect();
                var b = domNodes.get(e.to).getBoundingClientRect();

                var active = !activeTarget ||
                    (e.from === activeTarget || e.to === activeTarget) ||
                    (hovUp.has(e.from) && (hovUp.has(e.to) || e.to === activeTarget)) ||
                    (hovDown.has(e.to) && (hovDown.has(e.from) || e.from === activeTarget));

                var stroke;
                var sw;
                if (activeTarget) {
                    stroke = active ? (hovUp.has(e.from) || e.to === activeTarget ? "#0f766e" : "#0b63ce") : "rgba(148,163,184,0.14)";
                    sw = active ? "2.1" : "1.0";
                } else if (denseUnfocused) {
                    stroke = "rgba(148,163,184,0.13)";
                    sw = "1.0";
                } else {
                    stroke = "rgba(11,99,206,0.34)";
                    sw = "1.35";
                }

                var dAttr;
                if (isVert) {
                    var vx1 = a.left + a.width / 2 - boxRect.left + scrollBox.scrollLeft;
                    var vy1 = a.bottom - boxRect.top + scrollBox.scrollTop;
                    var vx2 = b.left + b.width / 2 - boxRect.left + scrollBox.scrollLeft;
                    var vy2 = b.top - boxRect.top + scrollBox.scrollTop;
                    if (vy2 < vy1) {
                        vy1 = a.top - boxRect.top + scrollBox.scrollTop;
                        vy2 = b.bottom - boxRect.top + scrollBox.scrollTop;
                    }
                    var dy = Math.max(22, Math.abs(vy2 - vy1) * 0.45);
                    dAttr = 'M ' + vx1.toFixed(1) + ' ' + vy1.toFixed(1) + ' C ' + vx1.toFixed(1) + ' ' + (vy1 + dy).toFixed(1) + ', ' + vx2.toFixed(1) + ' ' + (vy2 - dy).toFixed(1) + ', ' + vx2.toFixed(1) + ' ' + vy2.toFixed(1);
                } else {
                    var x1 = a.right - boxRect.left + scrollBox.scrollLeft;
                    var y1 = a.top + a.height / 2 - boxRect.top + scrollBox.scrollTop;
                    var x2 = b.left - boxRect.left + scrollBox.scrollLeft;
                    var y2 = b.top + b.height / 2 - boxRect.top + scrollBox.scrollTop;
                    if (x2 < x1) {
                        x1 = a.left - boxRect.left + scrollBox.scrollLeft;
                        x2 = b.right - boxRect.left + scrollBox.scrollLeft;
                    }
                    var dx = Math.max(28, Math.abs(x2 - x1) * 0.45);
                    dAttr = 'M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' C ' + (x1 + dx).toFixed(1) + ' ' + y1.toFixed(1) + ', ' + (x2 - dx).toFixed(1) + ' ' + y2.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1);
                }
                paths.push('<path d="' + dAttr + '" fill="none" stroke="' + stroke + '" stroke-width="' + sw + '"/>');
            });
            svgEl.innerHTML = paths.join("");
        }

        function renderCanvasAndInspector() {
            var up = traceSet(state.focusId, inMap);
            var down = traceSet(state.focusId, outMap);
            var connected = new Set([state.focusId]);
            up.forEach(function (x) { connected.add(x); });
            down.forEach(function (x) { connected.add(x); });

            colsEl.classList.toggle("is-vertical", state.orientation === "vertical");
            if (btnOrient) {
                btnOrient.textContent = state.orientation === "vertical" ? "Layout: Vertical" : "Layout: Horizontal";
                btnOrient.classList.toggle("active", state.orientation === "vertical");
            }
            if (btnKpis) {
                btnKpis.textContent = state.showKpis ? "Hide Core KPIs" : "+ Show Core KPIs";
                btnKpis.classList.toggle("active", state.showKpis);
            }
            var hasFocus = !!(state.focusId && nodeMap.has(state.focusId));
            btnConn.textContent = state.connectedOnly ? "Filter: Connected path" : "Filter: All objects";
            btnConn.classList.toggle("active", hasFocus && state.connectedOnly);
            btnConn.disabled = !hasFocus;
            btnConn.title = hasFocus ? "Toggle between connected path and all objects" : "Click any node first to filter its connected path";
            btnAll.disabled = !hasFocus && !state.connectedOnly;

            if (hasFocus) {
                var fn = nodeMap.get(state.focusId);
                statusEl.innerHTML = 'Focused: <b>' + escHtml(fn.label) + '</b> (' + up.size + ' upstream, ' + down.size + ' downstream) ' +
                    '<button type="button" class="lin-btn lin-clear-focus" style="padding:1px 7px;font-size:11px;margin-left:4px">&times; Clear</button>';
            } else {
                statusEl.textContent = activeNodes.length + " objects, " + activeEdges.length + " links (hover or click any card to trace)";
            }

            var capPerCol = state.focusId ? 85 : 18;
            var colsHtml = [];
            layers.forEach(function (layer) {
                var colNodes = activeNodes.filter(function (n) {
                    if (n.layer !== layer.id) return false;
                    if (state.focusId && state.connectedOnly && !connected.has(n.id)) return false;
                    return true;
                });
                if (!colNodes.length) return;
                var isExp = !!state.expandedCols[layer.id];
                var shownNodes = isExp ? colNodes.slice(0, 120) : colNodes.slice(0, capPerCol);
                var cards = shownNodes.map(function (n) {
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
                var moreBtn = "";
                if (!isExp && colNodes.length > capPerCol) {
                    moreBtn = '<button type="button" class="lin-btn" style="margin-top:2px;text-align:center" data-expand-col="' + escHtml(layer.id) + '">+ Show ' + (colNodes.length - capPerCol) + ' more</button>';
                } else if (isExp && colNodes.length > capPerCol) {
                    moreBtn = '<button type="button" class="lin-btn" style="margin-top:2px;text-align:center" data-collapse-col="' + escHtml(layer.id) + '">Show fewer</button>';
                }
                colsHtml.push('<div class="lin-col"><div class="lin-col-hdr">' + escHtml(layer.label) + ' (' + colNodes.length + ')</div>' + cards + moreBtn + '</div>');
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
                if (cur.href || cur.xrayId || cur.e2eMeasureId) {
                    insp += '<div style="display:flex;flex-wrap:wrap;gap:6px;align-items:center">';
                    if (cur.href) {
                        insp += '<a class="dep-chip" style="border-color:var(--accent);color:var(--accent);font-weight:600;padding:4px 9px" href="' + escHtml(cur.href) + '">' + escHtml(cur.hrefLabel || "Jump to documentation") + ' &rarr;</a>';
                    }
                    if (cur.xrayId) {
                        insp += '<button type="button" class="xray-trigger-btn" data-open-xray="' + escHtml(cur.xrayId) + '">' + escHtml(cur.xrayLabel || "Inspect Layout") + ' &rarr;</button>';
                    }
                    if (cur.e2eMeasureId) {
                        insp += '<button type="button" class="lin-btn" data-export-measure-md="' + escHtml(cur.e2eMeasureId) + '" title="Download full Measure-to-SQL lineage spec as Markdown">Measure Doc (.md)</button>';
                        insp += '<button type="button" class="lin-btn" data-export-measure-doc="' + escHtml(cur.e2eMeasureId) + '" title="Download formatted Word specification">Word (.doc)</button>';
                    }
                    insp += '</div>';
                }
                if (cur.sqlCode) {
                    insp += '<div class="lin-kv" style="margin-top:2px"><b>Formatted Native SQL</b></div>' +
                        '<div class="code-block" style="font-size:11px;padding:8px 54px 8px 10px"><button type="button" class="copy-btn" data-copy="1">Copy</button><pre>' + escHtml(cur.sqlCode) + '</pre></div>';
                }
                if (cur.stepsSummary && cur.stepsSummary.length) {
                    insp += '<div class="lin-kv" style="margin-top:2px"><b>Power Query Steps (' + cur.stepsSummary.length + ')</b></div>' +
                        '<div style="display:flex;flex-direction:column;gap:3px;font-size:11px">' +
                        cur.stepsSummary.slice(0, 8).map(function (st, idx) {
                            return '<div style="padding:3px 6px;border-radius:5px;background:var(--surface-alt);border:1px solid var(--border)"><b>' + (idx + 1) + '. ' + escHtml(st.name) + '</b>: ' + escHtml(st.summary) + '</div>';
                        }).join("") + '</div>';
                }
                if (cur.code) {
                    insp += '<div class="code-block" style="font-size:11.5px;padding:8px 54px 8px 10px"><button type="button" class="copy-btn" data-copy="1">Copy</button><pre>' + escHtml(cur.code) + '</pre></div>';
                }
                insp += '<div class="lin-kv" style="margin-top:4px"><b>Direct Upstream (' + directIn.length + ')</b></div><div class="lin-list">' +
                    (directIn.length ? directIn.map(function (x) { return '<button type="button" class="dep-chip lin-jump" data-id="' + escHtml(x.id) + '">' + escHtml(x.label) + '</button>'; }).join("") : '<span class="lin-kv">None (root source)</span>') +
                    '</div>';
                insp += '<div class="lin-kv" style="margin-top:4px"><b>Direct Downstream (' + directOut.length + ')</b></div><div class="lin-list">' +
                    (directOut.length ? directOut.map(function (x) { return '<button type="button" class="dep-chip lin-jump" data-id="' + escHtml(x.id) + '">' + escHtml(x.label) + '</button>'; }).join("") : '<span class="lin-kv">None (leaf consumer)</span>') +
                    '</div>';
                rightEl.innerHTML = insp;
            } else {
                var hintScope = isPortfolio
                    ? "Portfolio Architecture view hides intermediate DAX KPIs by default so cross-workspace Source &rarr; Dataflow &rarr; Semantic Model &rarr; Report chains stay clean. Click any model or toggle <b>+ Show Core KPIs</b> to drill deeper."
                    : "Click any source, SQL query, dataflow Gen1/Gen2 entity, table, column, DAX measure, or thin report to trace its upstream origins and downstream impact in real time.";
                rightEl.innerHTML = '<h4>Interactive Live Lineage</h4><div class="lin-kv">' + hintScope + '</div>';
            }

            window.requestAnimationFrame(function () { drawEdges(up, down); });
        }

        function refreshAll() {
            rebuildActiveGraph();
            renderPills();
            renderNav();
            renderCanvasAndInspector();
        }

        container._focusNode = function (targetId) {
            var resolved = e2eIndex.get(targetId) || targetId;
            var rawMatch = allNodes.some(function (n) { return n.id === resolved; });
            if (!rawMatch) return false;
            var targetObj = allNodes.find(function (n) { return n.id === resolved; });
            if (targetObj && targetObj.kpiDetail && !state.showKpis) {
                state.showKpis = true;
            }
            state.wsFilter = "all";
            state.modelFilter = "all";
            if (selWs) selWs.value = "all";
            if (selMdl) selMdl.value = "all";
            state.focusId = resolved;
            state.connectedOnly = true;
            state.layerFilter = "all";
            refreshAll();
            return true;
        };

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
            var expCol = e.target.closest("[data-expand-col]");
            if (expCol) {
                state.expandedCols[expCol.getAttribute("data-expand-col")] = true;
                renderCanvasAndInspector();
                return;
            }
            var colCol = e.target.closest("[data-collapse-col]");
            if (colCol) {
                state.expandedCols[colCol.getAttribute("data-collapse-col")] = false;
                renderCanvasAndInspector();
                return;
            }
            var card = e.target.closest(".lin-node[data-id]");
            if (!card) return;
            state.focusId = card.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        colsEl.addEventListener("mouseover", function (e) {
            if (state.focusId) return;
            var card = e.target.closest(".lin-node[data-id]");
            var nid = card ? card.getAttribute("data-id") : null;
            if (nid !== state.hoverId) {
                state.hoverId = nid;
                drawEdges(new Set(), new Set());
            }
        });
        colsEl.addEventListener("mouseleave", function () {
            if (!state.focusId && state.hoverId) {
                state.hoverId = null;
                drawEdges(new Set(), new Set());
            }
        });
        rightEl.addEventListener("click", function (e) {
            var b = e.target.closest(".lin-jump[data-id]");
            if (!b) return;
            state.focusId = b.getAttribute("data-id");
            renderNav(); renderCanvasAndInspector();
        });
        statusEl.addEventListener("click", function (e) {
            if (e.target.closest(".lin-clear-focus")) {
                state.focusId = null;
                state.connectedOnly = false;
                renderNav();
                renderCanvasAndInspector();
            }
        });
        btnConn.addEventListener("click", function () { if (!state.focusId) return; state.connectedOnly = !state.connectedOnly; renderCanvasAndInspector(); });
        btnAll.addEventListener("click", function () { state.focusId = null; state.connectedOnly = false; renderNav(); renderCanvasAndInspector(); });
        if (btnOrient) {
            btnOrient.addEventListener("click", function () {
                state.orientation = (state.orientation === "vertical") ? "horizontal" : "vertical";
                if (window.PbiStorage) window.PbiStorage.set("pbidoc-v11-lin-orient", state.orientation);
                renderCanvasAndInspector();
            });
        }
        if (btnKpis) {
            btnKpis.addEventListener("click", function () {
                state.showKpis = !state.showKpis;
                refreshAll();
            });
        }
        if (selWs) {
            selWs.addEventListener("change", function () {
                state.wsFilter = selWs.value || "all";
                state.focusId = null;
                refreshAll();
            });
        }
        if (selMdl) {
            selMdl.addEventListener("change", function () {
                state.modelFilter = selMdl.value || "all";
                state.focusId = (state.modelFilter !== "all") ? ("mdl:" + state.modelFilter) : null;
                state.connectedOnly = (state.modelFilter !== "all");
                refreshAll();
            });
        }
        btnFs.addEventListener("click", function () {
            var isFs = container.classList.toggle("is-fullscreen");
            document.body.classList.toggle("lin-fullscreen-lock", isFs);
            btnFs.textContent = isFs ? "Exit Fullscreen" : "Fullscreen";
            setTimeout(refreshAll, 35);
        });
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
    window.PbiFocusLineage = function (targetId) {
        if (!targetId) return;
        var tabBtn = document.querySelector('.top-tab[data-tab="tab-lineage"]');
        if (tabBtn && !tabBtn.classList.contains("active")) {
            tabBtn.click();
        }
        var secLin = document.getElementById("sec-lineage");
        var matched = false;
        document.querySelectorAll(".lineage-app").forEach(function (el) {
            if (!matched && typeof el._focusNode === "function") {
                matched = el._focusNode(targetId);
                if (matched) {
                    setTimeout(function () {
                        (secLin || el).scrollIntoView({ behavior: "smooth", block: "start" });
                    }, 40);
                }
            }
        });
    };
})();
"""


PORTAL_COMMON_JS = r"""
(function () {
    function safeGet(k) {
        try { return window.localStorage.getItem(k); } catch (e) { return null; }
    }
    function safeSet(k, v) {
        try { window.localStorage.setItem(k, v); } catch (e) { /* sandboxed */ }
    }
    window.PbiStorage = { get: safeGet, set: safeSet };

    window.PbiNavigate = function (href) {
        if (!href) return;
        if (window.PBIDOC_SHELL && typeof window.PBIDOC_SHELL.nav === "function" && !/^(#|[a-z][a-z0-9+.-]*:)/i.test(href)) {
            var k = href.indexOf("#");
            window.PBIDOC_SHELL.nav(k < 0 ? href : href.slice(0, k), k < 0 ? "" : href.slice(k + 1));
            return;
        }
        window.location.href = href;
    };

    var saved = safeGet("pbidoc-v1-theme");
    if (saved) document.documentElement.setAttribute("data-theme", saved);

    function triggerDownload(filename, mime, content) {
        var blob = new Blob([content], { type: mime });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 250);
    }

    function slugFile(s) {
        return String(s || "export").replace(/[^A-Za-z0-9_.-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "export";
    }

    function buildMeasureMarkdown(rootId) {
        var g = window.PBI_E2E_GRAPH;
        if (!g || !g.nodes || !g.nodes[rootId]) return null;
        var nodes = g.nodes;
        var adj = {};
        (g.edges || []).forEach(function (e) {
            if (!adj[e.from]) adj[e.from] = [];
            adj[e.from].push(e);
        });
        var visited = {};
        var order = [];
        var queue = [rootId];
        visited[rootId] = 0;
        while (queue.length) {
            var cur = queue.shift();
            order.push(cur);
            (adj[cur] || []).forEach(function (e) {
                if (visited[e.to] === undefined) {
                    visited[e.to] = visited[cur] + 1;
                    queue.push(e.to);
                }
            });
        }
        var root = nodes[rootId];
        var byKind = { source: [], dataflow_query: [], expression: [], table: [], calc_table: [], calc_column: [], measure: [] };
        order.forEach(function (id) {
            var n = nodes[id];
            if (n && byKind[n.kind]) byKind[n.kind].push(n);
        });

        var lines = [
            "# Measure End-to-End Lineage Specification: [" + root.name + "]",
            "",
            "- **Semantic Model:** " + (root.model || "-") + " (Workspace: " + (root.workspace || "-") + ")",
            "- **Host Table:** `" + (root.table || "-") + "`" + (root.folder ? " | **Folder:** `" + root.folder + "`" : "") + (root.format ? " | **Format:** `" + root.format + "`" : ""),
            root.report ? ("- **Report Scope:** Thin-Report Measure in `" + root.report + "`") : "- **Scope:** Shared Semantic Model Measure",
            ""
        ];
        if (root.description) {
            lines.push("> " + root.description, "");
        }
        lines.push("## 1. Primary DAX Formula", "", "```dax", (root.code || ""), "```", "");

        lines.push("## 2. Physical Data Sources & Native SQL (" + byKind.source.length + ")", "");
        if (!byKind.source.length) {
            lines.push("_No external physical source dependencies detected._", "");
        } else {
            byKind.source.forEach(function (s, idx) {
                lines.push("### 2." + (idx + 1) + " " + s.name + " (" + (s.source_type || "Source") + ")");
                if (s.server) lines.push("- **Server / Endpoint:** `" + s.server + "`");
                if (s.database) lines.push("- **Database:** `" + s.database + "`");
                if (s.code) {
                    lines.push("", "```sql", s.code, "```");
                }
                lines.push("");
            });
        }

        lines.push("## 3. Upstream Dataflow Transformations (Gen1 & Gen2) (" + byKind.dataflow_query.length + ")", "");
        if (!byKind.dataflow_query.length) {
            lines.push("_This measure does not traverse any upstream Dataflow._", "");
        } else {
            byKind.dataflow_query.forEach(function (q, idx) {
                lines.push("### 3." + (idx + 1) + " " + (q.group || "Dataflow") + " -> `" + q.name + "` (" + (q.generation || "Gen1") + ")");
                lines.push("- **Workspace:** " + (q.workspace || "-"));
                if (q.destination && q.destination.table) {
                    lines.push("- **OneLake Destination:** " + (q.destination.kind || "Lakehouse") + " `" + q.destination.table + "`");
                }
                if (q.step_items && q.step_items.length) {
                    lines.push("- **Transformation Steps:**");
                    q.step_items.forEach(function (st, si) {
                        lines.push("  " + (si + 1) + ". **" + st.name + "** (`" + (st.op || "M") + "`): " + (st.summary || ""));
                    });
                }
                if (q.code) lines.push("", "```powerquery", q.code, "```");
                lines.push("");
            });
        }

        var pqNodes = byKind.expression.concat(byKind.table).concat(byKind.calc_table);
        lines.push("## 4. Semantic Model Tables & Power Query (" + pqNodes.length + ")", "");
        pqNodes.forEach(function (t, idx) {
            lines.push("### 4." + (idx + 1) + " `" + t.name + "` (" + (t.storage_mode || t.kind) + ")");
            if (t.step_items && t.step_items.length) {
                t.step_items.forEach(function (st, si) {
                    lines.push("- Step " + (si + 1) + " **" + st.name + "**: " + (st.summary || st.op || ""));
                });
            }
            if (t.code) lines.push("", "```" + (t.lang || "powerquery"), t.code, "```");
            lines.push("");
        });

        if (byKind.measure.length > 1) {
            lines.push("## 5. Referenced DAX Measure Chain (" + byKind.measure.length + ")", "");
            byKind.measure.slice().reverse().forEach(function (m, idx) {
                lines.push("### 5." + (idx + 1) + " `[" + m.name + "]` (Table: `" + (m.table || "-") + "`)");
                lines.push("", "```dax", (m.code || ""), "```", "");
            });
        }
        return { name: root.name, markdown: lines.join("\n") };
    }

    function exportMeasureSpec(rootId, asWordDoc) {
        var res = buildMeasureMarkdown(rootId);
        if (!res) return;
        var base = "Measure_Lineage_" + slugFile(res.name);
        if (!asWordDoc) {
            triggerDownload(base + ".md", "text/markdown;charset=utf-8", res.markdown);
            return;
        }
        var esc = function (s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); };
        var htmlBody = res.markdown
            .replace(/```([a-z]*)\n([\s\S]*?)```/g, function (_, lang, code) {
                return '<pre style="background:#f1f5f9;border:1px solid #cbd5e1;padding:10px;font-family:Consolas,monospace;font-size:10pt;white-space:pre-wrap">' + esc(code) + '</pre>';
            })
            .replace(/^### (.+)$/gm, "<h3>$1</h3>")
            .replace(/^## (.+)$/gm, "<h2>$1</h2>")
            .replace(/^# (.+)$/gm, "<h1>$1</h1>")
            .replace(/^- (.+)$/gm, "<p style='margin:2px 0'>&bull; $1</p>")
            .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
            .replace(/`([^`]+)`/g, "<code>$1</code>");
        var wordHtml = '<!DOCTYPE html><html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>' +
            esc(res.name) + '</title><style>body{font-family:Segoe UI,Calibri,sans-serif;font-size:11pt;color:#0f172a}h1{color:#072854}h2{color:#0b63ce;border-bottom:1px solid #cbd5e1;padding-bottom:4px;margin-top:18px}code{font-family:Consolas,monospace;background:#eef2f7;padding:1px 4px}</style></head><body>' +
            htmlBody + '</body></html>';
        triggerDownload(base + ".doc", "application/msword;charset=utf-8", wordHtml);
    }

    function csvEscape(v) {
        var s = String(v == null ? "" : v).replace(/\r?\n/g, " ").trim();
        if (/[",\n;]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
        return s;
    }

    function getPageModelMeta() {
        var slugEl = document.querySelector('meta[name="pbi-model-slug"]');
        var nameEl = document.querySelector('meta[name="pbi-model-name"]');
        var idEl = document.querySelector('meta[name="pbi-model-id"]');
        var wsEl = document.querySelector('meta[name="pbi-model-ws"]');
        return {
            isModelPage: !!(slugEl && slugEl.content),
            slug: slugEl ? slugEl.content : "",
            name: nameEl ? nameEl.content : "",
            id: idEl ? idEl.content : "",
            workspace: wsEl ? wsEl.content : ""
        };
    }

    function isStudioServer() {
        return (location.protocol === "http:" || location.protocol === "https:") &&
            (location.hostname === "127.0.0.1" || location.hostname === "localhost");
    }

    function buildModelSpecFromGraph(modelId, modelName, modelWs) {
        var g = window.PBI_E2E_GRAPH || {};
        var nodes = g.nodes || {};
        var tables = [];
        var measures = [];
        var sources = [];
        var dataflows = [];
        Object.keys(nodes).forEach(function (k) {
            var n = nodes[k];
            if (!n) return;
            if (modelId && n.model_id && n.model_id !== modelId) return;
            if (!modelId && modelName && n.model && n.model !== modelName) return;
            if (n.kind === "table" || n.kind === "calc_table") tables.push(n);
            else if (n.kind === "measure" && !n.report) measures.push(n);
        });
        // Collect upstream sources/dataflows linked to this model's nodes
        var modelNodeSet = new Set();
        tables.forEach(function (t) { modelNodeSet.add(t.id); });
        measures.forEach(function (m) { modelNodeSet.add(m.id); });
        var adj = {};
        (g.edges || []).forEach(function (e) {
            if (!adj[e.from]) adj[e.from] = [];
            adj[e.from].push(e.to);
        });
        var q = Array.from(modelNodeSet);
        var vis = new Set(q);
        while (q.length) {
            var cur = q.shift();
            (adj[cur] || []).forEach(function (nx) {
                if (!vis.has(nx)) { vis.add(nx); q.push(nx); }
            });
        }
        vis.forEach(function (id) {
            var n = nodes[id];
            if (!n) return;
            if (n.kind === "source") sources.push(n);
            else if (n.kind === "dataflow_query") dataflows.push(n);
        });

        tables.sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || "")); });
        measures.sort(function (a, b) { return String(a.name || "").localeCompare(String(b.name || "")); });

        var md = [
            "# Semantic Model Technical Blueprint: " + (modelName || "Model"),
            "",
            "- **Workspace:** " + (modelWs || "-"),
            "- **Tables:** " + tables.length + " | **DAX Measures:** " + measures.length + " | **Upstream Sources:** " + sources.length,
            ""
        ];
        if (sources.length) {
            md.push("## 1. Data Sources & Native SQL (" + sources.length + ")", "");
            sources.forEach(function (s) {
                md.push("- **" + (s.name || "Source") + "** (" + (s.source_type || "Connector") + ")" + (s.database ? " - DB: `" + s.database + "`" : ""));
                if (s.code) md.push("", "```sql", s.code, "```", "");
            });
            md.push("");
        }
        if (dataflows.length) {
            md.push("## 2. Upstream Dataflow Entities (" + dataflows.length + ")", "");
            dataflows.forEach(function (d) {
                md.push("- **" + (d.group || "Dataflow") + "** -> `" + (d.name || "") + "` (" + (d.generation || "Gen1") + ", Workspace: " + (d.workspace || "-") + ")");
            });
            md.push("");
        }
        md.push("## 3. Model Tables & Columns (" + tables.length + ")", "");
        tables.forEach(function (t) {
            md.push("### Table: `" + t.name + "` (" + (t.storage_mode || t.kind || "Table") + ")");
            var cols = t.columns || [];
            if (cols.length) {
                cols.forEach(function (c) {
                    var cname = typeof c === "string" ? c : (c.name || "");
                    var ctype = (typeof c === "object" && c.type) ? " (`" + c.type + "`)" : "";
                    md.push("- `" + cname + "`" + ctype);
                });
            }
            if (t.code) md.push("", "```" + (t.lang || "powerquery"), t.code, "```");
            md.push("");
        });
        md.push("## 4. DAX Measure Catalog (" + measures.length + ")", "");
        measures.forEach(function (m) {
            md.push("### `[" + m.name + "]` (Table: `" + (m.table || "-") + "`" + (m.folder ? ", Folder: `" + m.folder + "`" : "") + ")");
            if (m.description) md.push("> " + m.description);
            md.push("", "```dax", (m.code || ""), "```", "");
        });

        var csvRows = ["ObjectType,Table,Name,DataTypeOrFolder,Format,StorageOrSource,Expression"];
        tables.forEach(function (t) {
            (t.columns || []).forEach(function (c) {
                var cname = typeof c === "string" ? c : (c.name || "");
                var ctype = typeof c === "object" ? (c.type || "") : "";
                var cfmt = typeof c === "object" ? (c.format || "") : "";
                var csrc = typeof c === "object" ? (c.source || "") : (t.storage_mode || "");
                var cexpr = typeof c === "object" ? (c.expr || "") : "";
                csvRows.push(["Column", t.name, cname, ctype, cfmt, csrc, cexpr].map(csvEscape).join(","));
            });
        });
        measures.forEach(function (m) {
            csvRows.push(["Measure", m.table || "", m.name || "", m.folder || "General", m.format || "", "DAX", m.code || ""].map(csvEscape).join(","));
        });
        // Also harvest DOM columns if graph columns are compact strings
        if (tables.length === 0 && document.querySelectorAll("details.table-blueprint").length) {
            document.querySelectorAll("details.table-blueprint").forEach(function (det) {
                var tTitle = (det.querySelector("summary span") && det.querySelector("summary span").textContent || "Table").split(":")[0].trim();
                det.querySelectorAll("tbody tr").forEach(function (tr) {
                    var tds = tr.querySelectorAll("td");
                    if (tds.length >= 4) {
                        csvRows.push(["Column", tTitle, tds[0].textContent, tds[1].textContent, tds[3].textContent, tds[2].textContent, tds[4] ? tds[4].textContent : ""].map(csvEscape).join(","));
                    }
                });
            });
        }

        return {
            markdown: md.join("\n"),
            csv: "\uFEFF" + csvRows.join("\r\n")
        };
    }

    function exportModelHandover(modelSlug, fmt) {
        var meta = getPageModelMeta();
        var g = window.PBI_E2E_GRAPH || {};
        var models = g.models || [];
        var mEntry = models.find(function (m) { return m.slug === modelSlug || m.id === meta.id || m.name === meta.name; }) || {};
        var mId = (meta.isModelPage && meta.slug === modelSlug && meta.id) ? meta.id : (mEntry.id || "");
        var mName = mEntry.name || meta.name || modelSlug || "Model";
        var mWs = mEntry.workspace || meta.workspace || "";
        var built = buildModelSpecFromGraph(mId, mName, mWs);
        var base = slugFile(mName);
        if (fmt === "csv") {
            triggerDownload(base + "_Data_Dictionary.csv", "text/csv;charset=utf-8", built.csv);
            return;
        }
        if (fmt === "md") {
            triggerDownload(base + "_Blueprint.md", "text/markdown;charset=utf-8", built.markdown);
            return;
        }
        var esc = function (s) { return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); };
        var htmlBody = built.markdown
            .replace(/```([a-z]*)\n([\s\S]*?)```/g, function (_, _l, code) {
                return '<pre style="background:#f1f5f9;border:1px solid #cbd5e1;padding:10px;font-family:Consolas,monospace;font-size:9.5pt;white-space:pre-wrap">' + esc(code) + '</pre>';
            })
            .replace(/^### (.+)$/gm, "<h3>$1</h3>")
            .replace(/^## (.+)$/gm, "<h2>$1</h2>")
            .replace(/^# (.+)$/gm, "<h1>$1</h1>")
            .replace(/^- (.+)$/gm, "<p style='margin:2px 0'>&bull; $1</p>")
            .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
            .replace(/`([^`]+)`/g, "<code>$1</code>");
        var wordHtml = '<!DOCTYPE html><html xmlns:o="urn:schemas-microsoft-com:office:office" xmlns:w="urn:schemas-microsoft-com:office:word"><head><meta charset="utf-8"><title>' +
            esc(mName) + '</title><style>body{font-family:Segoe UI,Calibri,sans-serif;font-size:10.5pt;color:#0f172a}h1{color:#072854}h2{color:#0b63ce;border-bottom:1px solid #cbd5e1;padding-bottom:4px;margin-top:18px}code{font-family:Consolas,monospace;background:#eef2f7;padding:1px 4px}</style></head><body>' +
            htmlBody + '</body></html>';
        triggerDownload(base + "_Handover_Spec.doc", "application/msword;charset=utf-8", wordHtml);
    }

    function exportGovernanceCsv() {
        var rows = ["SemanticModel,Workspace,Severity,Finding,RecommendedAction"];
        document.querySelectorAll("#tab-health tbody tr[data-health-sev]").forEach(function (tr) {
            var tds = tr.querySelectorAll("td");
            if (tds.length >= 5) {
                rows.push([tds[0].textContent, tds[1].textContent, tds[2].textContent, tds[3].textContent, tds[4].textContent].map(csvEscape).join(","));
            }
        });
        if (rows.length === 1) {
            rows.push('"All Models","-","OK","Healthy","Zero governance warnings detected"');
        }
        triggerDownload("PBI_Governance_Remediation_Backlog.csv", "text/csv;charset=utf-8", "\uFEFF" + rows.join("\r\n"));
    }

    var _ctrlPOpened = [];
    window.addEventListener("beforeprint", function () {
        document.querySelectorAll("details.dax-folder-details, details.dax-table-group, details.principals-details, #tab-workspaces.active details.section-accordion").forEach(function (d) {
            if (!d.open) { d.open = true; _ctrlPOpened.push(d); }
        });
    });
    window.addEventListener("afterprint", function () {
        while (_ctrlPOpened.length) {
            var d = _ctrlPOpened.pop();
            try { d.open = false; } catch (e) {}
        }
    });

    function runCleanPrint(preset) {
        var prevTheme = document.documentElement.getAttribute("data-theme");
        document.documentElement.setAttribute("data-theme", "light");
        var openedDetails = [];
        var alwaysOpenSel = "details.dax-folder-details, details.dax-table-group, details.principals-details, #tab-workspaces.active details.section-accordion";
        var fullOpenSel = "details.table-blueprint, details.dax-folder-details, details.dax-table-group, details.section-accordion, details.principals-details";
        document.querySelectorAll(preset === "full" ? fullOpenSel : alwaysOpenSel).forEach(function (d) {
            if (!d.open) { d.open = true; openedDetails.push(d); }
        });
        var modal = document.getElementById("pbiPublishModal");
        if (modal) modal.classList.remove("is-open");

        var restored = false;
        function restoreAfterPrint() {
            if (restored) return;
            restored = true;
            if (prevTheme) document.documentElement.setAttribute("data-theme", prevTheme);
            else document.documentElement.removeAttribute("data-theme");
            openedDetails.forEach(function (d) { d.open = false; });
            document.querySelectorAll(".section[data-print-hide]").forEach(function (s) { s.removeAttribute("data-print-hide"); });
            window.removeEventListener("afterprint", restoreAfterPrint);
        }
        window.addEventListener("afterprint", restoreAfterPrint);
        setTimeout(function () {
            if (window.PBIDOC_SHELL && typeof window.PBIDOC_SHELL.print === "function") {
                window.PBIDOC_SHELL.print();
            } else {
                window.print();
            }
            setTimeout(restoreAfterPrint, 1200);
        }, 80);
    }

    function openPublishModal(initialMode) {
        var meta = getPageModelMeta();
        var g = window.PBI_E2E_GRAPH || {};
        var models = g.models || [];
        var studio = isStudioServer();

        var modal = document.getElementById("pbiPublishModal");
        if (!modal) {
            modal = document.createElement("div");
            modal.id = "pbiPublishModal";
            modal.className = "pbi-modal-backdrop";
            document.body.appendChild(modal);
        }

        var scope = (initialMode === "model" || meta.isModelPage) ? "model" : "catalog";
        if (scope === "model" && !meta.slug && models.length) {
            meta.slug = models[0].slug || "";
            meta.name = models[0].name || "";
        }
        var savedSpUrl = safeGet("pbidoc-v11-sp-url") || "";

        function renderModalBody() {
            var curSlug = meta.slug || (models[0] && models[0].slug) || "";
            var curModelObj = models.find(function (m) { return m.slug === curSlug; }) || { name: meta.name || curSlug, workspace: meta.workspace || "" };
            var curModelLabel = curModelObj.name || meta.name || "Selected Model";
            var modelPickerHtml = "";
            if (scope === "model" && models.length > 1) {
                modelPickerHtml = '<select id="pubModelSelect" class="sort-select" style="max-width:210px;padding:4px 8px;font-size:11.5px" aria-label="Choose semantic model">' +
                    models.map(function (m) {
                        var sl = m.slug || "";
                        var sel = (sl === curSlug) ? " selected" : "";
                        return '<option value="' + sl.replace(/"/g, "&quot;") + '"' + sel + '>' + (m.workspace ? m.workspace + " - " : "") + m.name + '</option>';
                    }).join("") + '</select>';
            }

            var chaptersHtml = "";
            if (scope === "model" && meta.isModelPage && curSlug === getPageModelMeta().slug) {
                chaptersHtml =
                    '<div class="print-chap-pills">' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-overview" checked> 1. Overview</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-schema" checked> 2. Star Schema</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-tables" checked> 3. Tables &amp; SQL</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-dax" checked> 4. DAX Catalog</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-lineage"> 5. Lineage</label>' +
                      '<label><input type="checkbox" class="pub-ch-chk" value="sec-security" checked> 6. RLS &amp; Reports</label>' +
                    '</div>';
            }

            var validInitialSp = /^https:\/\//i.test((savedSpUrl || "").trim());
            var spCardBody = studio
                ? ('<input type="url" id="pubSpUrlInput" value="' + savedSpUrl.replace(/"/g, "&quot;") + '" placeholder="https://contoso.sharepoint.com/sites/BI/Shared%20Documents/Portal" style="width:100%;padding:7px 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--fg);font-size:12px">' +
                   '<div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap">' +
                     '<label style="font-size:11.5px;color:var(--fg-muted);display:inline-flex;align-items:center;gap:5px"><input type="checkbox" id="pubSpAspxChk"> Use <code>.aspx</code> extension (strict SharePoint tenants)</label>' +
                   '</div>' +
                   '<div id="pubSpStatus" style="display:none;font-size:12px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:var(--surface)"></div>' +
                   '<div class="publish-card-actions">' +
                     '<button type="button" class="publish-top-btn" id="btnDirectPublishSp"' + (validInitialSp ? '' : ' disabled title="Paste a https:// SharePoint Document Library URL above first"') + '>Publish Directly to SharePoint &rarr;</button>' +
                     '<button type="button" class="lin-btn" id="btnDownloadSpFile">Download SharePoint File</button>' +
                   '</div>')
                : ('<p>Downloads a SharePoint-hardened single file (sandboxed storage safe, zero external assets). Upload to any SharePoint Document Library, or run <code>pbi-catalog studio</code> for 1-click direct URL publishing.</p>' +
                   '<div class="publish-card-actions">' +
                     '<button type="button" class="publish-top-btn" id="btnDownloadSpFile">Download SharePoint File (.html)</button>' +
                   '</div>');

            modal.innerHTML =
                '<div class="pbi-modal" role="dialog" aria-modal="true" aria-labelledby="pubModalTitle">' +
                  '<div class="pbi-modal-hdr">' +
                    '<div>' +
                      '<h3 id="pubModalTitle">Export &amp; Publish Documentation</h3>' +
                      '<div style="font-size:12px;color:var(--fg-muted);margin-top:2px">' +
                        (scope === "model"
                          ? ('Scope: <b>Single Semantic Model</b> (' + curModelLabel.replace(/</g, "&lt;") + ') - isolated without other models')
                          : ('Scope: <b>Entire Documentation Catalog</b> (' + (models.length || 1) + ' model' + (models.length === 1 ? '' : 's') + ')')) +
                      '</div>' +
                    '</div>' +
                    '<button type="button" class="xray-close-btn" data-close-publish="1" aria-label="Close modal">&times; Close</button>' +
                  '</div>' +
                  '<div class="pbi-modal-body">' +
                    '<div class="publish-scope-bar">' +
                      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
                        '<div class="view-toggle" role="group" aria-label="Export scope">' +
                          (models.length > 0 || meta.isModelPage
                            ? '<button type="button" class="view-btn ' + (scope === "model" ? "active" : "") + '" data-pub-scope="model">This Semantic Model</button>'
                            : '') +
                          '<button type="button" class="view-btn ' + (scope === "catalog" ? "active" : "") + '" data-pub-scope="catalog">Entire Catalog (' + (models.length || 1) + ')</button>' +
                        '</div>' +
                        modelPickerHtml +
                      '</div>' +
                      '<label style="font-size:12px;display:inline-flex;align-items:center;gap:6px;cursor:pointer">' +
                        '<input type="checkbox" id="pubAnonChk"> Anonymize owners &amp; emails' +
                      '</label>' +
                    '</div>' +

                    '<div class="publish-grid">' +
                      '<div class="publish-card">' +
                        '<h4>1. Print or Save as Clean PDF</h4>' +
                        '<p>' + (scope === "model"
                          ? "A4 print-optimized layout (hides navigation chrome, switches to crisp light ink, prevents split code/tables)."
                          : "Prints the active catalog view cleanly as an executive PDF inventory.") + '</p>' +
                        chaptersHtml +
                        '<div class="publish-card-actions">' +
                          (scope === "model"
                            ? ('<button type="button" class="publish-top-btn" data-pub-print="exec">Print Executive Summary PDF</button>' +
                               '<button type="button" class="lin-btn" data-pub-print="full">Print Full Technical Blueprint</button>')
                            : '<button type="button" class="publish-top-btn" data-pub-print="catalog">Print Current Catalog View</button>') +
                        '</div>' +
                      '</div>' +

                      '<div class="publish-card">' +
                        '<h4>2. Standalone HTML or Offline .zip</h4>' +
                        '<p>' + (scope === "model"
                          ? "Self-contained interactive HTML file for <b>" + curModelLabel.replace(/</g, "&lt;") + "</b> (Star Schema, formatted DAX, SQL &amp; Report X-Ray wireframes in 1 file)."
                          : "Share the complete multi-model portal by email, network drive, or static web server.") + '</p>' +
                        '<div class="publish-card-actions">' +
                          (scope === "model"
                            ? '<button type="button" class="publish-top-btn" data-pub-html="model-single">Download Standalone Model (.html)</button>'
                            : ('<button type="button" class="publish-top-btn" data-pub-html="catalog-single">Single-File Portal (.html)</button>' +
                               (studio ? '<button type="button" class="lin-btn" data-pub-html="catalog-zip">Offline Site Bundle (.zip)</button>' : ''))) +
                        '</div>' +
                      '</div>' +

                      '<div class="publish-card">' +
                        '<h4>3. SharePoint Online</h4>' +
                        '<p>Publish ' + (scope === "model" ? ('<b>' + curModelLabel.replace(/</g, "&lt;") + '</b>') : 'the <b>Entire Catalog</b>') + ' to a SharePoint Document Library using your Windows / Edge session.</p>' +
                        spCardBody +
                      '</div>' +

                      '<div class="publish-card">' +
                        '<h4>' + (scope === "model" ? "4. Editable Spec &amp; Data Dictionary" : "4. Portfolio Inventory &amp; Governance Backlog") + '</h4>' +
                        '<p>' + (scope === "model"
                          ? "Generate handover files for Confluence, Word, Git, or Excel governance reviews."
                          : "Export portfolio inventory &amp; prioritized governance findings.") + '</p>' +
                        '<div class="publish-card-actions">' +
                          (scope === "model"
                            ? ('<button type="button" class="lin-btn" data-pub-spec="doc">Word Spec (.doc)</button>' +
                               '<button type="button" class="lin-btn" data-pub-spec="md">Markdown (.md)</button>' +
                               '<button type="button" class="lin-btn" data-pub-spec="csv">Data Dictionary (.csv)</button>')
                            : ('<button type="button" class="lin-btn" data-export-catalog-md="1">Catalog Inventory (.md)</button>' +
                               '<button type="button" class="lin-btn" data-pub-gov-csv="1">Governance Backlog (.csv)</button>')) +
                        '</div>' +
                      '</div>' +
                    '</div>' +
                  '</div>' +
                '</div>';

            var selEl = modal.querySelector("#pubModelSelect");
            if (selEl) {
                selEl.addEventListener("change", function () {
                    meta.slug = selEl.value;
                    var mFound = models.find(function (m) { return m.slug === meta.slug; });
                    if (mFound) meta.name = mFound.name;
                    renderModalBody();
                });
            }
            var spInpEl = modal.querySelector("#pubSpUrlInput");
            var spBtnEl = modal.querySelector("#btnDirectPublishSp");
            if (spInpEl && spBtnEl) {
                spInpEl.addEventListener("input", function () {
                    var okUrl = /^https:\/\//i.test((spInpEl.value || "").trim());
                    spBtnEl.disabled = !okUrl;
                    spBtnEl.title = okUrl ? "" : "Paste a https:// SharePoint Document Library URL above first";
                });
            }
        }

        renderModalBody();
        modal.classList.add("is-open");

        modal.onclick = function (ev) {
            if (ev.target === modal || ev.target.closest("[data-close-publish]")) {
                modal.classList.remove("is-open");
                return;
            }
            var scBtn = ev.target.closest("[data-pub-scope]");
            if (scBtn) {
                scope = scBtn.getAttribute("data-pub-scope");
                if (scope === "model" && !meta.slug && models.length) {
                    meta.slug = models[0].slug || "";
                    meta.name = models[0].name || "";
                }
                renderModalBody();
                return;
            }
            var anonFlag = (modal.querySelector("#pubAnonChk") && modal.querySelector("#pubAnonChk").checked) ? "1" : "0";
            var curSlug = (modal.querySelector("#pubModelSelect") && modal.querySelector("#pubModelSelect").value) || meta.slug || "";

            var prBtn = ev.target.closest("[data-pub-print]");
            if (prBtn) {
                var pMode = prBtn.getAttribute("data-pub-print");
                if (pMode === "catalog") {
                    runCleanPrint("exec");
                    return;
                }
                var pageMeta = getPageModelMeta();
                if (!pageMeta.isModelPage || (curSlug && pageMeta.slug !== curSlug)) {
                    var targetHref = (pageMeta.isModelPage ? (curSlug + ".html") : ("models/" + curSlug + ".html")) + "?autoprint=" + pMode;
                    modal.classList.remove("is-open");
                    window.PbiNavigate(targetHref);
                    return;
                }
                var chChecks = modal.querySelectorAll(".pub-ch-chk");
                if (chChecks.length) {
                    chChecks.forEach(function (chk) {
                        var sec = document.getElementById(chk.value);
                        if (!sec) return;
                        if (!chk.checked) sec.setAttribute("data-print-hide", "1");
                        else sec.removeAttribute("data-print-hide");
                    });
                }
                runCleanPrint(pMode);
                return;
            }

            var htmlBtn = ev.target.closest("[data-pub-html]");
            if (htmlBtn) {
                var hKind = htmlBtn.getAttribute("data-pub-html");
                if (studio) {
                    if (hKind === "model-single") {
                        window.location.href = "/api/export-site?format=single&model=" + encodeURIComponent(curSlug) + "&anonymous=" + anonFlag;
                    } else if (hKind === "catalog-zip") {
                        window.location.href = "/api/export-site?format=zip&anonymous=" + anonFlag;
                    } else {
                        window.location.href = "/api/export-site?format=single&anonymous=" + anonFlag;
                    }
                } else {
                    var clone = document.documentElement.cloneNode(true);
                    var mRem = clone.querySelector("#pbiPublishModal");
                    if (mRem) mRem.remove();
                    if (hKind === "model-single") clone.setAttribute("data-standalone-model", "1");
                    triggerDownload(slugFile(hKind === "model-single" ? (curSlug + "_Documentation") : "PBI_Portal") + ".html", "text/html;charset=utf-8", "<!DOCTYPE html>\n" + clone.outerHTML);
                }
                return;
            }

            var dlSpBtn = ev.target.closest("#btnDownloadSpFile");
            if (dlSpBtn) {
                var useAspx = (modal.querySelector("#pubSpAspxChk") && modal.querySelector("#pubSpAspxChk").checked) ? "1" : "0";
                if (studio) {
                    var qModel = (scope === "model" && curSlug) ? ("&model=" + encodeURIComponent(curSlug)) : "";
                    window.location.href = "/api/export-site?format=single&aspx=" + useAspx + "&anonymous=" + anonFlag + qModel;
                } else {
                    var cloneSp = document.documentElement.cloneNode(true);
                    var mRem2 = cloneSp.querySelector("#pbiPublishModal");
                    if (mRem2) mRem2.remove();
                    if (scope === "model") cloneSp.setAttribute("data-standalone-model", "1");
                    var ext = useAspx === "1" ? ".aspx" : ".html";
                    triggerDownload(slugFile(scope === "model" ? (curSlug + "_SharePoint") : "PBI_Portal_SharePoint") + ext, "text/html;charset=utf-8", "<!DOCTYPE html>\n" + cloneSp.outerHTML);
                }
                return;
            }

            var pubSpBtn = ev.target.closest("#btnDirectPublishSp");
            if (pubSpBtn) {
                var urlInp = modal.querySelector("#pubSpUrlInput");
                var statusBox = modal.querySelector("#pubSpStatus");
                var spTarget = (urlInp && urlInp.value || "").trim();
                if (!spTarget) {
                    if (statusBox) {
                        statusBox.style.display = "block";
                        statusBox.style.color = "var(--bad)";
                        statusBox.innerHTML = "Paste a SharePoint Document Library folder URL first (e.g. <code>https://tenant.sharepoint.com/sites/BI/Shared%20Documents</code>).";
                    }
                    return;
                }
                safeSet("pbidoc-v11-sp-url", spTarget);
                savedSpUrl = spTarget;
                var aspxBool = !!(modal.querySelector("#pubSpAspxChk") && modal.querySelector("#pubSpAspxChk").checked);
                pubSpBtn.disabled = true;
                if (statusBox) {
                    statusBox.style.display = "block";
                    statusBox.style.color = "var(--fg)";
                    statusBox.innerHTML = "Authenticating via Windows / Edge SSO &amp; uploading to SharePoint Online...";
                }
                fetch("/api/publish-sharepoint", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        target_url: spTarget,
                        scope: scope,
                        model_slug: (scope === "model" ? curSlug : ""),
                        anonymous: anonFlag === "1",
                        aspx: aspxBool
                    })
                }).then(function (r) { return r.json(); }).then(function (res) {
                    pubSpBtn.disabled = false;
                    if (!statusBox) return;
                    if (res.ok) {
                        statusBox.style.color = "var(--ok)";
                        statusBox.innerHTML = "<b>Published to SharePoint!</b> (" + (res.size_kb || 0) + " KB) &bull; <a href='" + String(res.web_url || spTarget).replace(/'/g, "%27") + "' target='_blank' rel='noopener' style='font-weight:700;color:var(--accent)'>Open on SharePoint &rarr;</a>";
                    } else {
                        statusBox.style.color = "var(--bad)";
                        statusBox.innerHTML = "<b>SharePoint upload failed:</b> " + String(res.error || "Unknown error").replace(/</g, "&lt;");
                    }
                }).catch(function (err) {
                    pubSpBtn.disabled = false;
                    if (statusBox) {
                        statusBox.style.color = "var(--bad)";
                        statusBox.textContent = "Network error: " + err;
                    }
                });
                return;
            }

            var specBtn = ev.target.closest("[data-pub-spec]");
            if (specBtn) {
                exportModelHandover(curSlug, specBtn.getAttribute("data-pub-spec"));
                return;
            }

            var govCsvBtn = ev.target.closest("[data-pub-gov-csv]");
            if (govCsvBtn) {
                exportGovernanceCsv();
                return;
            }
        };
    }

    // Reveal Studio-only links only when served by local Studio HTTP server, and support ?autoprint=exec|full
    document.addEventListener("DOMContentLoaded", function () {
        if (isStudioServer()) {
            document.querySelectorAll(".studio-only-link").forEach(function (el) {
                el.style.display = "";
            });
        }
        try {
            var params = new URLSearchParams(location.search || "");
            var ap = params.get("autoprint");
            if (ap === "exec" || ap === "full") {
                if (window.history && typeof window.history.replaceState === "function") {
                    params.delete("autoprint");
                    var cleanQs = params.toString();
                    window.history.replaceState({}, document.title, location.pathname + (cleanQs ? ("?" + cleanQs) : "") + location.hash);
                }
                setTimeout(function () { runCleanPrint(ap); }, 260);
            }
        } catch (e) {}
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") {
            var m = document.getElementById("pbiPublishModal");
            if (m && m.classList.contains("is-open")) m.classList.remove("is-open");
        }
    });

    document.addEventListener("change", function (e) {
        var sw = e.target.closest("select.model-switcher-select");
        if (sw && sw.value) {
            window.PbiNavigate(sw.value);
        }
    });

    document.addEventListener("click", function (e) {
        var openPub = e.target.closest("[data-open-publish-modal]");
        if (openPub) {
            e.preventDefault();
            openPublishModal(openPub.getAttribute("data-open-publish-modal") || "");
            return;
        }
        var dlGov = e.target.closest("[data-export-gov-csv]");
        if (dlGov) {
            e.preventDefault();
            exportGovernanceCsv();
            return;
        }
        var expMenuBtn = e.target.closest("[data-toggle-export-menu]");
        if (expMenuBtn) {
            e.stopPropagation();
            var menu = expMenuBtn.parentElement && expMenuBtn.parentElement.querySelector(".export-dropdown-menu");
            if (menu) menu.classList.toggle("is-open");
            return;
        }
        document.querySelectorAll(".export-dropdown-menu.is-open").forEach(function (m) { m.classList.remove("is-open"); });

        var traceBtn = e.target.closest("[data-trace-e2e]");
        if (traceBtn && !traceBtn.closest(".xray-drawer")) {
            e.preventDefault();
            if (window.PbiFocusLineage) window.PbiFocusLineage(traceBtn.getAttribute("data-trace-e2e"));
            return;
        }
        var mdBtn = e.target.closest("[data-export-measure-md]");
        if (mdBtn) {
            e.preventDefault();
            exportMeasureSpec(mdBtn.getAttribute("data-export-measure-md"), false);
            return;
        }
        var docBtn = e.target.closest("[data-export-measure-doc]");
        if (docBtn) {
            e.preventDefault();
            exportMeasureSpec(docBtn.getAttribute("data-export-measure-doc"), true);
            return;
        }
        var catMdBtn = e.target.closest("[data-export-catalog-md]");
        if (catMdBtn) {
            e.preventDefault();
            var g = window.PBI_E2E_GRAPH || {};
            var mList = g.models || [];
            var dfList = g.dataflows || [];
            var out = ["# Power BI Documentation Catalog Summary", "", "## Semantic Models (" + mList.length + ")", ""];
            mList.forEach(function (m) {
                out.push("- **" + m.name + "** (Workspace: `" + (m.workspace || "-") + "`): " + m.tables + " tables, " + m.measures + " DAX measures");
            });
            if (dfList.length) {
                out.push("", "## Dataflows Gen1 & Gen2 (" + dfList.length + ")", "");
                dfList.forEach(function (d) {
                    out.push("- **" + d.name + "** (" + (d.generation || "Gen1") + ", Workspace: `" + (d.workspace || "-") + "`): " + d.queries + " entities/queries");
                });
            }
            triggerDownload("PBI_Catalog_Summary.md", "text/markdown;charset=utf-8", out.join("\n") + "\n");
            return;
        }

        var expBtn = e.target.closest("[data-details-toggle]");
        if (expBtn) {
            var scopeId = expBtn.getAttribute("data-details-toggle");
            var shouldOpen = expBtn.getAttribute("data-open") === "1";
            var root = document.getElementById(scopeId) || document;
            if (scopeId === "daxCardsContainer") {
                var cBtn = document.querySelector('[data-dax-view="cards"]');
                if (cBtn && !cBtn.classList.contains("active")) cBtn.click();
                var folderDets = root.querySelectorAll("details.dax-folder-details");
                if (folderDets.length) {
                    root.querySelectorAll("details.dax-table-group").forEach(function (g) { g.open = true; });
                    folderDets.forEach(function (d) { d.open = shouldOpen; });
                    return;
                }
            }
            root.querySelectorAll("details").forEach(function (d) { d.open = shouldOpen; });
            return;
        }
        var measureJump = e.target.closest('a[href^="#m-"], a[href^="#measure-"]');
        if (measureJump) {
            var cardsBtn = document.querySelector('[data-dax-view="cards"]');
            if (cardsBtn && !cardsBtn.classList.contains("active")) {
                cardsBtn.click();
            }
            var targetHref = measureJump.getAttribute("href") || "";
            if (targetHref.length > 1) {
                var mEl = document.getElementById(targetHref.slice(1));
                if (mEl) {
                    var fDet = mEl.closest("details.dax-folder-details");
                    if (fDet) fDet.open = true;
                    var tDet = mEl.closest("details.dax-table-group");
                    if (tDet) tDet.open = true;
                }
            }
        }
        var tableJump = e.target.closest('a[href^="#t-"]');
        if (tableJump) {
            var tHref = tableJump.getAttribute("href") || "";
            if (tHref.length > 1) {
                var tEl = document.getElementById(tHref.slice(1));
                if (tEl && tEl.tagName === "DETAILS") tEl.open = true;
            }
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
        var daxUsageBtn = e.target.closest("[data-dax-usage]");
        if (daxUsageBtn) {
            var mode = daxUsageBtn.getAttribute("data-dax-usage");
            document.querySelectorAll("[data-dax-usage]").forEach(function (b) { b.classList.toggle("active", b === daxUsageBtn); });
            document.querySelectorAll("[data-measure-usage]").forEach(function (el) {
                var u = el.getAttribute("data-measure-usage");
                var show = (mode === "all") || (u === mode);
                el.style.display = show ? "" : "none";
            });
            document.querySelectorAll("details.dax-folder-details").forEach(function (f) {
                var anyVis = Array.from(f.querySelectorAll(".measure-card[data-measure-usage]")).some(function (c) { return c.style.display !== "none"; });
                f.style.display = anyVis ? "" : "none";
                if (mode !== "all" && anyVis) f.open = true;
            });
            return;
        }
        var themeBtn = e.target.closest("[data-toggle-theme]");
        if (themeBtn) {
            var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", cur);
            safeSet("pbidoc-v1-theme", cur);
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
        if (e.key === "Escape") {
            document.querySelectorAll(".lineage-app.is-fullscreen").forEach(function (el) {
                el.classList.remove("is-fullscreen");
                document.body.classList.remove("lin-fullscreen-lock");
                var fb = el.querySelector(".lin-toggle-fs");
                if (fb) fb.textContent = "Fullscreen";
                if (typeof el._lineageRedraw === "function") el._lineageRedraw();
            });
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


def _build_model_lineage_json(analysis: dict) -> dict:
    ds_id = analysis.get("dataset_id", "")
    layers = [
        {"id": "source", "label": "1. Sources, SQL & Dataflows"},
        {"id": "table", "label": "2. Model Tables & PQ"},
        {"id": "column", "label": "3. Referenced Columns"},
        {"id": "base_measure", "label": "4. Base Measures"},
        {"id": "kpi_measure", "label": "5. Derived KPIs & Reports"},
    ]
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str]] = set()

    def add_node(
        nid: str,
        label: str,
        layer: str,
        layer_lbl: str,
        sub: str = "",
        detail: str = "",
        href: str = "",
        code: str = "",
        sql_code: str = "",
        steps_summary: list[dict] | None = None,
        xray_id: str = "",
        xray_lbl: str = "",
        e2e_id: str = "",
        e2e_measure_id: str = "",
    ):
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
                "sqlCode": sql_code,
                "stepsSummary": steps_summary or [],
                "xrayId": xray_id,
                "xrayLabel": xray_lbl,
                "e2eId": e2e_id,
                "e2eMeasureId": e2e_measure_id,
            }
        )

    def add_edge(u: str, v: str):
        if (u, v) not in seen_edges:
            seen_edges.add((u, v))
            edges.append({"from": u, "to": v})

    df_ids_present = {str(df.get("id", "")).lower(): f"df:{df['id']}" for df in (analysis.get("upstream_dataflows") or []) if df.get("id")}

    for ts in analysis["table_summaries"]:
        tid = f"tbl:{ts['name']}"
        src_label = ", ".join(ts["source_types"]) or ts["mode"]
        tbl_sql = "\n\n".join(sq.get("sql", "") for sq in (ts.get("native_sql") or []) if sq.get("sql"))
        tbl_steps = [
            {"name": st.get("name", ""), "summary": st.get("summary") or st.get("op") or ""}
            for st in (ts.get("step_items") or [])
        ]
        add_node(
            tid,
            ts["name"],
            "table",
            "Model Table",
            sub=f"{ts['mode'].upper()} - {ts['columns_count']} cols, {ts['measures_count']} measures",
            detail=ts["description"] or f"Power Query steps: {ts['pq_steps']}",
            href=f"#{_table_anchor(ts['name'])}",
            sql_code=tbl_sql,
            steps_summary=tbl_steps,
            e2e_id=f"t:{ds_id}:{ts['name']}" if ds_id else "",
        )
        endpoints = [d for d in (ts["details"] or []) if d]
        if not endpoints and not any("Dataflow" in st for st in ts["source_types"]):
            endpoints = ts["source_types"] or ["Internal / Calculated"]
        for ep in endpoints:
            sid = f"src:{ep}"
            add_node(
                sid,
                ep,
                "source",
                "External Data Source",
                sub=src_label,
                detail="Upstream connection or Native SQL endpoint read by Power Query / Direct Lake.",
                sql_code=tbl_sql,
            )
            add_edge(sid, tid)
        for obj in ts["objects"][:6]:
            ep_key = endpoints[0] if endpoints else "source"
            oid = f"srcobj:{ep_key}:{obj}"
            add_node(oid, obj, "source", "Source View / Object", sub=", ".join(ts["source_types"]), detail=f"Loaded into table '{ts['name']}'.")
            add_edge(oid, tid)

    for df in analysis.get("upstream_dataflows") or []:
        df_nid = f"df:{df['id']}"
        gen_lbl = "Gen2" if str(df.get("generation", 1)).replace("Gen", "") == "2" else "Gen1"
        layer_num = int(df.get("layer") or 1)
        ents = df.get("queries") or df.get("entities") or []
        df_sql = "\n\n".join(
            sq.get("sql", "")
            for ent in ents
            for sq in (ent.get("native_sql") or [])
            if sq.get("sql")
        )
        df_steps = [
            {"name": f"{ent.get('name', '')}.{st.get('name', '')}", "summary": st.get("summary") or st.get("op") or ""}
            for ent in ents[:3]
            for st in (ent.get("step_items") or [])[:5]
        ]
        add_node(
            df_nid,
            df.get("name", "Dataflow"),
            "source",
            f"Dataflow {gen_lbl} (Layer L{layer_num})",
            sub=f"Workspace: {df.get('workspace', '')}",
            detail=df.get("description") or f"Feeds: {', '.join(df.get('feeds_tables') or [])}",
            sql_code=df_sql,
            steps_summary=df_steps,
            xray_id=f"df:{df['id']}",
            xray_lbl="Inspect Dataflow",
        )
        for fed_tbl in df.get("feeds_tables") or []:
            if f"tbl:{fed_tbl}" in seen_nodes:
                add_edge(df_nid, f"tbl:{fed_tbl}")
        for ent in ents:
            for ref in ent.get("dataflow_refs") or []:
                up_df_low = str(ref.get("dataflow_id") or "").lower()
                if up_df_low in df_ids_present and df_ids_present[up_df_low] != df_nid:
                    add_edge(df_ids_present[up_df_low], df_nid)
            for ep in ent.get("endpoints") or []:
                srv = ep.get("server") or ep.get("label") or ""
                if srv:
                    sid = f"src:{srv}"
                    add_node(sid, srv, "source", ep.get("label", "Database Source"), sub=ep.get("database", ""), sql_code=df_sql)
                    add_edge(sid, df_nid)

    lin_measures = analysis["lineage"] or {}
    depths = _compute_measure_depths(lin_measures)
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
        e2e_mid = f"m:{ds_id}:{m_key}" if ds_id else ""
        add_node(
            mid,
            m_name,
            layer_id,
            layer_lbl,
            sub=f"{m_info['table']}" + (f" / {m_raw['folder']}" if m_raw.get("folder") else ""),
            detail=m_raw.get("description") or (f"Format: {m_raw['format']}" if m_raw.get("format") else ""),
            href=anchor,
            code=m_info.get("expr", ""),
            e2e_id=e2e_mid,
            e2e_measure_id=e2e_mid,
        )
        score = len(m_info.get("upstream_measures", [])) + len(m_info.get("downstream_measures", [])) * 2 + len(m_info.get("upstream_columns", []))
        if score > best_score:
            best_score = score
            default_focus = mid

        if not m_info.get("upstream_columns") and is_base:
            add_edge(f"tbl:{m_info['table']}", mid)

        for col_ref in m_info.get("upstream_columns", []):
            cid = f"col:{col_ref}"
            tbl_part = col_ref.split("[", 1)[0]
            add_node(
                cid,
                col_ref,
                "column",
                "Table Column",
                sub=f"Table: {tbl_part}",
                href=f"#{_table_anchor(tbl_part)}",
                e2e_id=f"c:{ds_id}:{col_ref}" if ds_id else "",
            )
            if f"tbl:{tbl_part}" in seen_nodes:
                add_edge(f"tbl:{tbl_part}", cid)
            add_edge(cid, mid)

        for upstream_m in m_info.get("upstream_measures", []):
            add_edge(f"meas:{upstream_m}", mid)

    bare_to_mkey = {m_info["name"].lower(): mk for mk, m_info in lin_measures.items()}

    for rep in analysis.get("reports") or []:
        rid = f"rep:{rep['id']}"
        pg_cnt = rep.get("pages_count") or 0
        vis_cnt = rep.get("visuals_count") or 0
        det_txt = f"{pg_cnt} page(s), {vis_cnt} visual(s) bound to this semantic model." if pg_cnt else "Downstream report bound to this semantic model."
        add_node(
            rid,
            rep["name"],
            "kpi_measure",
            "Power BI Report",
            sub=f"Workspace: {rep.get('workspace', '')}",
            detail=det_txt,
            xray_id=f"rep:{rep['id']}",
            xray_lbl="Inspect Report Layout",
        )
        rep_layout = rep.get("layout") or {}
        for rm in rep_layout.get("report_measures") or []:
            rm_name = rm.get("name", "")
            rm_tbl = rm.get("table", "")
            rm_nid = f"rmeas:{rep['id']}:{rm_tbl}[{rm_name}]"
            rm_e2e = f"m:{ds_id}:rpt:{rep['id']}:{rm_tbl}[{rm_name}]" if ds_id else ""
            add_node(
                rm_nid,
                rm_name,
                "kpi_measure",
                "Thin-Report DAX Measure",
                sub=f"Report: {rep['name']} ({rm_tbl})",
                code=rm.get("expr", ""),
                xray_id=f"rep:{rep['id']}",
                xray_lbl="Inspect Report",
                e2e_id=rm_e2e,
                e2e_measure_id=rm_e2e,
            )
            add_edge(rm_nid, rid)
            for ref_br in re.findall(r"\[([^\]]+)\]", rm.get("expr") or ""):
                mk_hit = bare_to_mkey.get(ref_br.strip().lower())
                if mk_hit and f"meas:{mk_hit}" in seen_nodes:
                    add_edge(f"meas:{mk_hit}", rm_nid)

        exact_bound_measures = [
            m_key
            for m_key, m_info in lin_measures.items()
            if any(u.get("report_id") == rep.get("id") for u in (m_info.get("used_in_reports") or []))
        ]
        if exact_bound_measures:
            for m_key in exact_bound_measures:
                add_edge(f"meas:{m_key}", rid)
        elif lin_measures and not pg_cnt:
            for m_key, m_info in list(lin_measures.items())[:25]:
                if not m_info.get("downstream_measures"):
                    add_edge(f"meas:{m_key}", rid)
        else:
            for ts in analysis["table_summaries"][:10]:
                add_edge(f"tbl:{ts['name']}", rid)

    if not default_focus and nodes:
        default_focus = nodes[0]["id"]

    return {"layers": layers, "nodes": nodes, "edges": edges, "defaultFocus": default_focus}


def _build_workspace_lineage_json(analyses: list[tuple[str, dict]], e2e_graph: dict | None = None) -> dict:
    layers = [
        {"id": "source", "label": "1. Sources & Native SQL"},
        {"id": "object", "label": "2. Views & Dataflows (L2/L1)"},
        {"id": "model", "label": "3. Semantic Models"},
        {"id": "kpi", "label": "4. Core DAX KPIs"},
        {"id": "report", "label": "5. Power BI Reports"},
    ]
    nodes: list[dict] = []
    edges: list[dict] = []
    seen_nodes: set[str] = set()
    seen_edges: set[tuple[str, str, bool]] = set()
    ws_names: set[str] = set()
    mdl_list: list[dict] = []

    def add_node(
        nid: str,
        label: str,
        layer: str,
        layer_lbl: str,
        sub: str = "",
        detail: str = "",
        href: str = "",
        href_lbl: str = "",
        code: str = "",
        sql_code: str = "",
        steps_summary: list[dict] | None = None,
        xray_id: str = "",
        xray_lbl: str = "",
        e2e_id: str = "",
        e2e_measure_id: str = "",
        workspace: str = "",
        model_slug: str = "",
        kpi_detail: bool = False,
    ):
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
                "code": format_dax_pretty(code) if code else "",
                "sqlCode": sql_code,
                "stepsSummary": steps_summary or [],
                "xrayId": xray_id,
                "xrayLabel": xray_lbl,
                "e2eId": e2e_id,
                "e2eMeasureId": e2e_measure_id,
                "workspace": workspace,
                "modelSlug": model_slug,
                "kpiDetail": kpi_detail,
            }
        )

    def add_edge(u: str, v: str, direct_model_edge: bool = False):
        key = (u, v, direct_model_edge)
        if key not in seen_edges:
            seen_edges.add(key)
            ep: dict[str, Any] = {"from": u, "to": v}
            if direct_model_edge:
                ep["directModelEdge"] = True
            edges.append(ep)

    default_focus = None
    best_deg = -1
    all_df_nodes: dict[str, str] = {}

    for slug, a in analyses:
        ds_id = a.get("dataset_id", "")
        ws_val = a.get("workspace") or ""
        if ws_val:
            ws_names.add(ws_val)
        mdl_list.append({"slug": slug, "name": a["name"], "workspace": ws_val})
        mid = f"mdl:{slug}"
        stats = a["stats"]
        href = f"models/{slug}.html"
        add_node(
            mid,
            a["name"],
            "model",
            "Semantic Model",
            sub=f"{ws_val} - {stats['tables']} tables, {stats['measures']} measures",
            detail=f"Sources: {', '.join(a['source_types']) or 'Internal'}",
            href=href,
            workspace=ws_val,
            model_slug=slug,
        )

        deg = len(a["source_endpoints"]) + len(a["reports"]) + stats["measures"]
        if deg > best_deg:
            best_deg = deg
            default_focus = mid

        for df in a.get("upstream_dataflows") or []:
            df_nid = f"df:{df['id']}"
            all_df_nodes[str(df.get("id", "")).lower()] = df_nid
            gen_lbl = "Gen2" if str(df.get("generation", 1)).replace("Gen", "") == "2" else "Gen1"
            layer_num = int(df.get("layer") or 1)
            ents = df.get("queries") or df.get("entities") or []
            df_sql = "\n\n".join(
                sq.get("sql", "")
                for ent in ents
                for sq in (ent.get("native_sql") or [])
                if sq.get("sql")
            )
            df_steps = [
                {"name": f"{ent.get('name', '')}.{st.get('name', '')}", "summary": st.get("summary") or st.get("op") or ""}
                for ent in ents[:3]
                for st in (ent.get("step_items") or [])[:5]
            ]
            sys_id = "sys:Fabric Dataflows" if gen_lbl == "Gen2" else "sys:Power BI Dataflows"
            add_node(sys_id, "Fabric Dataflow Gen2" if gen_lbl == "Gen2" else "Power BI Dataflows", "source", "Source Platform", sub="Managed Power Query ETL")
            add_node(
                df_nid,
                df.get("name", "Dataflow"),
                "object",
                f"Dataflow {gen_lbl} (Layer L{layer_num})",
                sub=f"Workspace: {df.get('workspace', '')}",
                detail=f"Feeds: {', '.join(df.get('feeds_tables') or [])}",
                sql_code=df_sql,
                steps_summary=df_steps,
                xray_id=f"df:{df['id']}",
                xray_lbl="Inspect Dataflow",
                workspace=df.get("workspace", "") or ws_val,
            )
            if layer_num == 1:
                add_edge(df_nid, mid)
            else:
                add_edge(sys_id, df_nid)
            for ent in ents:
                for ep in ent.get("endpoints") or []:
                    srv = ep.get("server") or ep.get("label") or ""
                    if srv:
                        sid = f"src:{srv}"
                        add_node(sid, srv, "source", ep.get("label", "Database Source"), sub=ep.get("database", ""), sql_code=df_sql)
                        add_edge(sid, df_nid)
            if layer_num == 1 and not any(ent.get("endpoints") for ent in ents):
                add_edge(sys_id, df_nid)

        for df in a.get("upstream_dataflows") or []:
            df_nid = f"df:{df['id']}"
            for ent in (df.get("queries") or df.get("entities") or []):
                for ref in ent.get("dataflow_refs") or []:
                    up_low = str(ref.get("dataflow_id") or "").lower()
                    if up_low in all_df_nodes and all_df_nodes[up_low] != df_nid:
                        add_edge(all_df_nodes[up_low], df_nid)

        sql_by_tbl = {
            ts["name"]: "\n\n".join(sq.get("sql", "") for sq in (ts.get("native_sql") or []) if sq.get("sql"))
            for ts in a["table_summaries"]
        }
        for stype in a["source_types"]:
            if stype == "Power BI Dataflow":
                continue
            sid = f"sys:{stype}"
            add_node(sid, stype, "source", "Source Platform", sub="Connector technology")
            matched_ep = False
            for ep in a["source_endpoints"]:
                if ep["type"] == stype:
                    matched_ep = True
                    ep_lbl = ep["object"] or ep["endpoint"] or stype
                    oid = f"ep:{stype}:{ep_lbl}"
                    add_node(
                        oid,
                        ep_lbl,
                        "object",
                        "Source Endpoint / Object",
                        sub=f"{stype} ({ep['endpoint']})" if ep["endpoint"] else stype,
                        detail=f"Read by table '{ep['table']}'",
                        sql_code=sql_by_tbl.get(ep["table"], ""),
                    )
                    add_edge(sid, oid)
                    add_edge(oid, mid)
            if not matched_ep:
                add_edge(sid, mid)

        lin_m = a["lineage"] or {}
        ranked_m = sorted(
            lin_m.items(),
            key=lambda kv: (
                len(kv[1].get("used_in_reports") or []),
                len(kv[1].get("downstream_measures", [])),
                len(kv[1].get("upstream_measures", [])),
            ),
            reverse=True,
        )[:12]
        kpi_ids = []
        kpi_by_mkey: dict[str, str] = {}
        for m_key, m_info in ranked_m:
            m_name = m_info["name"]
            kid = f"kpi:{slug}:{m_key}"
            e2e_mid = f"m:{ds_id}:{m_key}" if ds_id else ""
            kpi_ids.append(kid)
            kpi_by_mkey[m_key] = kid
            add_node(
                kid,
                m_name,
                "kpi",
                "DAX KPI Measure",
                sub=f"{a['name']} ({m_info['table']})",
                detail="",
                href=f"{href}#{_measure_anchor(m_info['table'], m_name)}",
                href_lbl="Inspect DAX formula",
                code=m_info.get("expr", ""),
                e2e_id=e2e_mid,
                e2e_measure_id=e2e_mid,
                workspace=ws_val,
                model_slug=slug,
                kpi_detail=True,
            )
            add_edge(mid, kid)

        for m_key, kid in kpi_by_mkey.items():
            for up_m in (lin_m.get(m_key) or {}).get("upstream_measures") or []:
                if up_m in kpi_by_mkey and kpi_by_mkey[up_m] != kid:
                    add_edge(kpi_by_mkey[up_m], kid)

        for rep in a["reports"]:
            rid = f"rep:{rep['id']}"
            rep_ws = rep.get("workspace") or ws_val
            if rep_ws:
                ws_names.add(rep_ws)
            cross_ws = rep_ws and ws_val and rep_ws != ws_val
            ws_note = f"Workspace: {rep_ws}" + (" (Cross-Workspace)" if cross_ws else "")
            add_node(
                rid,
                rep["name"],
                "report",
                "Power BI Report",
                sub=ws_note,
                href=href,
                xray_id=f"rep:{rep['id']}",
                xray_lbl="Inspect Report Layout",
                workspace=rep_ws,
                model_slug=slug,
            )
            # Always emit a direct Estate Architecture edge (used when + Show Core KPIs is hidden)
            add_edge(mid, rid, direct_model_edge=True)

            rep_layout = rep.get("layout") or {}
            for rm in rep_layout.get("report_measures") or []:
                rm_nm = rm.get("name", "")
                rm_tbl = rm.get("table", "")
                rm_nid = f"rmeas:{rep['id']}:{rm_tbl}[{rm_nm}]"
                rm_e2e = f"m:{ds_id}:rpt:{rep['id']}:{rm_tbl}[{rm_nm}]" if ds_id else ""
                add_node(
                    rm_nid,
                    rm_nm,
                    "kpi",
                    "Thin-Report DAX Measure",
                    sub=f"Report: {rep['name']}",
                    code=rm.get("expr", ""),
                    xray_id=f"rep:{rep['id']}",
                    xray_lbl="Inspect Report",
                    e2e_id=rm_e2e,
                    e2e_measure_id=rm_e2e,
                    workspace=rep_ws,
                    model_slug=slug,
                    kpi_detail=True,
                )
                add_edge(mid, rm_nid)
                add_edge(rm_nid, rid)

            bound_kids = [
                kpi_by_mkey[mk]
                for mk, minfo in lin_m.items()
                if mk in kpi_by_mkey and any(u.get("report_id") == rep.get("id") for u in (minfo.get("used_in_reports") or []))
            ]
            if bound_kids:
                for kid in bound_kids:
                    add_edge(kid, rid)
            elif kpi_ids:
                for kid in kpi_ids[:5]:
                    add_edge(kid, rid)
            else:
                add_edge(mid, rid)

    return {
        "scope": "portfolio",
        "layers": layers,
        "nodes": nodes,
        "edges": edges,
        "defaultFocus": default_focus,
        "workspaces": sorted(ws_names, key=lambda x: x.lower()),
        "models": sorted(mdl_list, key=lambda x: x["name"].lower()),
    }


def render_model_html(
    analysis: dict,
    slug: str,
    anonymous: bool = False,
    all_models_nav: list[tuple[str, str, str]] | None = None,
    e2e_graph: dict | None = None,
) -> str:
    """Render an effortless-to-read, logically structured HTML documentation page for one Semantic Model."""
    stats = analysis["stats"]
    parsed = analysis["parsed"]
    findings = analysis["findings"]
    owner_txt = "Anonymized" if anonymous else (analysis["owner"] or "Not specified")
    ref = analysis.get("last_refresh") or {}
    ref_status = ref.get("status") or "Unknown"
    ref_badge = "badge-ok" if ref_status in ("Completed", "Local") else ("badge-bad" if ref_status == "Failed" else "badge-warn")

    # Sticky Breadcrumb & Quick Model Switcher options
    switcher_html = ""
    if all_models_nav and len(all_models_nav) > 1:
        opt_items = []
        for s_item, ws_item, nm_item in all_models_nav:
            sel_attr = " selected" if s_item == slug else ""
            lbl_item = f"{ws_item} - {middle_truncate(nm_item, 36)}" if ws_item else middle_truncate(nm_item, 42)
            opt_items.append(f'<option value="{esc(s_item)}.html"{sel_attr}>{esc(lbl_item)}</option>')
        switcher_html = (
            '<select class="model-switcher-select" aria-label="Switch semantic model">'
            + "".join(opt_items)
            + "</select>"
        )

    # 1. Findings HTML
    if findings:
        findings_html = '<div class="finding-list">' + "".join(
            f'<div class="finding {esc(f["severity"])}"><div><strong>{esc(f["title"])}</strong><span>{esc(f["detail"])}</span></div></div>'
            for f in findings
        ) + "</div>"
    else:
        findings_html = '<div class="finding ok"><div><strong>Healthy model architecture</strong><span>Zero refresh errors, non-production endpoints, bidirectional filter traps, broken report bindings, or local file dependencies detected.</span></div></div>'

    # 2. Modern HTML+SVG Star-Schema Explorer + Relationships Table
    star_payload, facts, dims = build_star_schema_json(analysis)
    star_json = json.dumps(star_payload, ensure_ascii=False).replace("</", "<\\/")
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
        rel_open = " open" if len(rels) <= 12 else ""
        bidi_cnt = stats["bidirectional_relationships"]
        bidi_badge = f'<span class="badge badge-warn">{bidi_cnt} Bi-Di</span>' if bidi_cnt else '<span class="badge badge-ok">Single-direction clean</span>'
        rel_table_html = (
            f'<details class="section-accordion" style="margin-top:14px"{rel_open}>'
            f'<summary><span class="acc-title"><span class="acc-chev">&#9656;</span> Relationship Join Matrix</span>'
            f'<span style="display:flex;gap:6px;align-items:center"><span class="badge badge-accent">{len(rels)} joins</span>{bidi_badge}</span></summary>'
            f'<div class="accordion-body"><div class="table-scroll sticky-table-scroll"><table class="data-table">'
            f"<thead><tr><th>Many / Fact Side</th><th>Cardinality</th><th>One / Dimension Side</th><th>Filter Direction</th><th>State</th></tr></thead>"
            f"<tbody>{rel_rows}</tbody></table></div></div></details>"
        )
    else:
        rel_table_html = '<p style="color:var(--fg-muted)">Single-table or standalone model (0 relationships defined).</p>'

    # 3. Data Sources, Upstream Dataflows & Tables Blueprint
    upstream_df_html = render_upstream_dataflows_banner(analysis)
    summary_rows = []
    for ts in analysis["table_summaries"]:
        role_badge = (
            '<span class="badge badge-fact">Fact</span>'
            if ts["name"] in facts
            else ('<span class="badge badge-dim">Dimension</span>' if ts["name"] in dims else '<span class="badge">KPI / Table</span>')
        )
        sql_badge = f' <span class="badge badge-warn">{len(ts["native_queries"])} Native SQL</span>' if ts["native_queries"] else ""
        hid_tbl_badge = ' <span class="badge">Hidden</span>' if ts["hidden"] else ""
        summary_rows.append(
            f"<tr>"
            f'<td><a href="#{_table_anchor(ts["name"])}"><b>{esc(ts["name"])}</b></a>{hid_tbl_badge}</td>'
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
    consistent_tbl_open = " open" if len(analysis["table_summaries"]) <= 3 else ""
    for ts in analysis["table_summaries"]:
        raw_t = raw_tables_by_name.get(ts["name"])
        if not raw_t:
            continue
        key_set = rel_key_cols.get(ts["name"], set())
        key_badge_html = ' <span class="badge badge-accent">Key</span>'
        hid_col_badge_html = ' <span class="badge">Hidden</span>'
        col_rows = "".join(
            f"<tr>"
            f"<td><b>{esc(c['name'])}</b>"
            f"{key_badge_html if c['name'] in key_set else ''}"
            f"{hid_col_badge_html if c['hidden'] else ''}</td>"
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
            if p["kind"] == "entity":
                ent_schema = p.get("schema_name") or "dbo"
                ent_name = p.get("entity_name") or ts["name"]
                exp_src = p.get("expression_source") or "DatabaseQuery"
                part_blocks.append(
                    f'<div style="margin-top:12px;padding:10px 12px;border:1px solid var(--border);border-radius:8px;background:var(--surface-alt);font-size:12.5px">'
                    f'<b>Direct Lake OneLake Binding (<code>{esc(p["name"])}</code>)</b>: '
                    f'Delta Table <code>{esc(ent_schema)}.{esc(ent_name)}</code> via expression <code>{esc(exp_src)}</code>'
                    f"</div>"
                )
            elif p["code"]:
                if p["kind"] == "m":
                    single_part = len(raw_t["partitions"]) == 1
                    part_blocks.append(
                        render_pq_partition_block(
                            m_code=p["code"],
                            highlight_m_fn=_highlight_m,
                            script_title=f"View Power Query M Script - Partition {p['name']} ({p['mode']})",
                            native_sql_items=ts.get("native_sql") if single_part else None,
                            step_items=ts.get("step_items") if single_part else None,
                        )
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

        role_txt = "Fact" if ts["name"] in facts else ("Dimension" if ts["name"] in dims else "Table")
        desc_suffix = f' <span style="font-weight:400;color:var(--fg-muted)">: {esc(ts["description"])}</span>' if ts["description"] else ""
        blueprint_cards.append(
            f'<details class="table-blueprint" id="{_table_anchor(ts["name"])}"{consistent_tbl_open} data-searchable="{esc((ts["name"] + " " + ts["description"]).lower())}">'
            f"<summary><span>{esc(ts['name'])}{desc_suffix}</span>"
            f'<div class="model-meta"><span class="badge badge-accent">{role_txt}</span><span class="badge">{ts["columns_count"]} cols</span><span class="badge">{ts["pq_steps"]} PQ steps</span></div></summary>'
            f'<div class="blueprint-body">{cols_html}{hier_html}{calc_col_blocks}{"".join(part_blocks)}</div>'
            f"</details>"
        )

    expr_html = ""
    if parsed["expressions"]:
        expr_items = []
        for ex in parsed["expressions"]:
            ex_desc = f' <span style="color:var(--fg-muted)">({esc(ex["description"])})</span>' if ex["description"] else ""
            expr_items.append(
                f'<div style="margin-bottom:10px"><b><code>{esc(ex["name"])}</code></b>{ex_desc}'
                f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy M</button><pre>{_highlight_m(ex["code"])}</pre></div></div>'
            )
        expr_html = f'<div class="card" style="margin-top:16px"><h3 style="margin-top:0;font-size:15px">Shared Power Query Parameters &amp; Functions ({len(parsed["expressions"])})</h3>{"".join(expr_items)}</div>'

    # 4. Structured DAX Library (100% SQLBI-Style Formatted + Consistent Display Folders!)
    lin_measures = analysis["lineage"] or {}
    depths = _compute_measure_depths(lin_measures)
    has_layouts = bool(analysis.get("has_parsed_layouts"))
    consistent_folder_open = " open" if stats["measures"] <= 30 else ""
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
                is_used_any = bool(li.get("is_used_any", True))
                usage_attr = "used" if is_used_any else "unused"
                unused_badge = '<span class="badge">Unused in scanned reports</span>' if (has_layouts and not is_used_any) else ""
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

                rep_chips = []
                for ru in li.get("used_in_reports") or []:
                    r_lbl = middle_truncate(ru.get("report_name", "Report"), 32)
                    v_cnt = ru.get("visual_count", 1)
                    rep_chips.append(
                        f'<button type="button" class="dep-chip xray-chip" data-open-xray="rep:{esc(ru.get("report_id", ""))}" '
                        f'title="Click to inspect report layout">{esc(r_lbl)} ({v_cnt} vis)</button>'
                    )

                deps_html = ""
                if up_chips:
                    deps_html += f'<div class="dep-row"><span>Reads:</span>{"".join(up_chips)}</div>'
                if down_chips:
                    deps_html += f'<div class="dep-row"><span>Used by:</span>{"".join(down_chips)}</div>'
                if rep_chips:
                    deps_html += f'<div class="dep-row"><span>Reports:</span>{"".join(rep_chips)}</div>'

                ds_id_str = analysis.get("dataset_id") or ""
                e2e_mid = f"m:{ds_id_str}:{m_key}" if ds_id_str else ""
                actions_html = ""
                if e2e_mid:
                    actions_html = (
                        f'<div class="measure-actions-row">'
                        f'<button type="button" class="lin-btn" data-trace-e2e="{esc(e2e_mid)}">Trace to SQL &rarr;</button>'
                        f'<button type="button" class="lin-btn" data-export-measure-md="{esc(e2e_mid)}">Measure Doc (.md)</button>'
                        f'<button type="button" class="lin-btn" data-export-measure-doc="{esc(e2e_mid)}">Word (.doc)</button>'
                        f"</div>"
                    )

                return (
                    f'<div class="measure-card" id="{anchor}" data-measure-usage="{usage_attr}" data-searchable="{esc((m_name + " " + m.get("description", "") + " " + m.get("expr", "")).lower())}">'
                    f'<div class="measure-head"><span class="measure-name">{esc(m_name)}</span><div class="model-meta">{tier_badge}{fmt_badge}{hid_badge}{unused_badge}</div></div>'
                    f"{desc_html}"
                    f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy DAX</button><pre>{_highlight_dax(m.get("expr", ""), auto_pretty=True)}</pre></div>'
                    f"{deps_html}"
                    f"{actions_html}"
                    f"</div>"
                )

            tier_sections = []
            if base_ms:
                tier_sections.append(f'<div class="dax-tier-label">Tier 1: Base Aggregations ({len(base_ms)})</div><div class="measure-grid">' + "".join(_render_m_card(m) for m in base_ms) + "</div>")
            if derived_ms:
                tier_sections.append(f'<div class="dax-tier-label">Tier 2+: Derived &amp; Time-Intelligence KPIs ({len(derived_ms)})</div><div class="measure-grid">' + "".join(_render_m_card(m) for m in derived_ms) + "</div>")

            folder_blocks.append(
                f'<details class="dax-folder-details"{consistent_folder_open}>'
                f'<summary><span>Display Folder: {esc(folder_name)}</span><span class="badge">{len(ms)} measure{"s" if len(ms) != 1 else ""}</span></summary>'
                f'<div class="dax-folder-body">{"".join(tier_sections)}</div>'
                f"</details>"
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
            used_cnt = len(li.get("downstream_measures", [])) + len(li.get("used_in_reports") or [])
            is_used_any = bool(li.get("is_used_any", True))
            usage_attr = "used" if is_used_any else "unused"
            one_line = re.sub(r"\s+", " ", m.get("expr", "")).strip()
            preview = (one_line[:110] + "...") if len(one_line) > 110 else one_line
            anchor = _measure_anchor(tbl["name"], m["name"])
            dax_list_rows.append(
                f'<tr data-measure-usage="{usage_attr}" data-searchable="{esc((m["name"] + " " + tbl["name"] + " " + (m.get("folder") or "") + " " + one_line).lower())}">'
                f'<td><a href="#{anchor}"><b>{esc(m["name"])}</b></a></td>'
                f"<td>{esc(tbl['name'])}</td>"
                f"<td>{esc(m.get('folder') or 'General')}</td>"
                f"<td><span class='badge {'badge-dim' if d_val == 0 else 'badge-accent'}'>{tier_txt}</span></td>"
                f"<td><code>{esc(m.get('format') or '-')}</code></td>"
                f"<td>{reads_cnt}</td>"
                f"<td>{used_cnt}</td>"
                f"<td><code style='font-size:11.5px'>{esc(preview)}</code></td>"
                f"</tr>"
            )

    dax_usage_pills_html = ""
    if has_layouts and stats["measures"] > 0:
        dax_usage_pills_html = (
            f'<div class="view-toggle" role="group" aria-label="Filter measures by report usage">'
            f'<button type="button" class="view-btn active" data-dax-usage="all">All ({stats["measures"]})</button>'
            f'<button type="button" class="view-btn" data-dax-usage="used">Used in Reports ({stats["used_measures"]})</button>'
            f'<button type="button" class="view-btn" data-dax-usage="unused">Unused ({stats["unused_measures"]})</button>'
            f"</div>"
        )

    if dax_groups_html:
        dax_scroll_cls = "table-scroll sticky-table-scroll" if len(dax_list_rows) > 12 else "table-scroll"
        dax_section_body = (
            f'<div id="daxListContainer"><div class="{dax_scroll_cls}"><table class="data-table">'
            f"<thead><tr><th>Measure</th><th>Host Table</th><th>Display Folder</th><th>Tier</th><th>Format</th><th>Reads</th><th>Used By</th><th>DAX Preview</th></tr></thead>"
            f'<tbody>{"".join(dax_list_rows)}</tbody></table></div></div>'
            f'<div id="daxCardsContainer" style="display:none">{"".join(dax_groups_html)}</div>'
        )
    else:
        dax_section_body = '<div class="card"><p style="margin:0;color:var(--fg-muted)">No DAX measures are defined in this semantic model.</p></div>'

    # 5. Model Live Lineage JSON
    lineage_json = json.dumps(_build_model_lineage_json(analysis), ensure_ascii=False).replace("</", "<\\/")

    # 6. RLS, Downstream Reports & Governance (Overflow-Safe & Proportioned)
    rls_blocks = []
    for role in parsed["roles"]:
        filt_rows = "".join(
            f'<div style="margin-top:8px"><b>Table <code>{esc(tp["table"])}</code></b>'
            f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy DAX</button><pre>{_highlight_dax(tp["filter_dax"] or "TRUE()")}</pre></div></div>'
            for tp in role["filters"]
        )
        rls_blocks.append(f'<div class="card" style="margin-bottom:10px"><b>RLS Role: {esc(role["name"])}</b> <span class="badge">{esc(role["permission"])}</span>{filt_rows or "<p>No table filter expressions</p>"}</div>')
    rls_html = "".join(rls_blocks) if rls_blocks else '<div class="card"><p style="margin:0;color:var(--fg-muted)">No Row-Level Security (RLS) roles defined in this model.</p></div>'

    reports_html = render_model_reports_html(analysis)
    access_html = render_model_access_html(analysis, anonymous=anonymous)

    # Build Slide-Over X-Ray Registry for bound Reports & Upstream Dataflows
    xray_items: dict[str, Any] = {}
    report_order: list[str] = []
    for rep in analysis.get("reports") or []:
        rid = f"rep:{rep['id']}"
        report_order.append(rid)
        xray_items[rid] = build_report_xray_entry(
            rep=rep,
            model_name=analysis["name"],
            model_slug=slug,
            model_workspace=analysis["workspace"],
            highlight_dax_fn=lambda expr: _highlight_dax(expr, auto_pretty=True),
            from_index=False,
            anonymous=anonymous,
            e2e_graph=e2e_graph,
            dataset_id=analysis.get("dataset_id") or "",
        )
    for df in analysis.get("upstream_dataflows") or []:
        did = f"df:{df['id']}"
        xray_items[did] = build_dataflow_xray_entry(df, _highlight_m, extract_m_steps)

    xray_json = json.dumps({"items": xray_items, "reportOrder": report_order}, ensure_ascii=False).replace("</", "<\\/")

    tbl_scroll_cls = "table-scroll sticky-table-scroll" if len(summary_rows) > 10 else "table-scroll"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="pbi-model-slug" content="{esc(slug)}">
  <meta name="pbi-model-name" content="{esc(analysis['name'])}">
  <meta name="pbi-model-id" content="{esc(analysis.get('dataset_id') or '')}">
  <meta name="pbi-model-ws" content="{esc(analysis.get('workspace') or '')}">
  <title>{esc(analysis['name'])} - Semantic Model Documentation</title>
  <link rel="stylesheet" href="../assets/portal.css">
</head>
<body>
<div class="doc-shell">
  <aside class="doc-sidebar">
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
      <span><a href="https://github.com/djrien-ai/pbi-doc-generator" target="_blank" rel="noopener" style="color:inherit;text-decoration:none;font-weight:600">PBI Doc Generator v1.1</a> &bull; <a href="https://www.linkedin.com/in/rienscheerlinck/" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none">Rien Scheerlinck</a></span>
    </div>
  </aside>

  <main class="doc-main">
    <div class="print-only-doc-banner">
      <div>
        <div style="font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#0b63ce;margin-bottom:2px">Power BI Semantic Model Blueprint</div>
        <div style="font-size:19px;font-weight:800;color:#0f172a;line-height:1.2">{esc(analysis['name'])}</div>
        <div style="font-size:11px;color:#475569;margin-top:3px">Workspace: <b>{esc(analysis['workspace'])}</b> &bull; Owner: <b>{esc(owner_txt)}</b></div>
      </div>
      <div style="text-align:right;font-size:10.5px;color:#475569;white-space:nowrap">
        <div><b>{stats['tables']}</b> Tables &bull; <b>{stats['measures']}</b> Measures &bull; <b>{stats['relationships']}</b> Rels</div>
        <div style="margin-top:2px">PBI Doc Generator v1.1</div>
      </div>
    </div>
    <div class="doc-topbar">
      <nav class="doc-crumbs" aria-label="Breadcrumb">
        <a href="../index.html">Catalog Home</a>
        <span class="crumb-sep">/</span>
        <a href="../index.html?ws={urllib.parse.quote(analysis['workspace'])}">{esc(analysis['workspace'])}</a>
        <span class="crumb-sep">/</span>
        <span class="crumb-current" title="{esc(analysis['name'])}">{esc(middle_truncate(analysis['name'], 48))}</span>
      </nav>
      <div class="doc-topbar-actions">
        <a class="lin-btn studio-only-link" href="/" style="display:none;text-decoration:none">&larr; 1. Scanner &amp; Setup</a>
        {switcher_html}
        <button type="button" class="publish-top-btn" data-open-publish-modal="model" title="Export PDF, standalone HTML, SharePoint page, or Data Dictionary for this model">Export / Publish</button>
        <button type="button" class="theme-icon-btn surface-btn" data-toggle-theme="1" title="Toggle Light / Dark theme" aria-label="Toggle Light / Dark theme">
          <svg class="icon-moon" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          <svg class="icon-sun" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
        </button>
      </div>
    </div>

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
        <div>
          <h2>2. Data Model &amp; Star Schema</h2>
          <div class="hint">Switch between Focused Stars per Fact table or All Tables &bull; Click any table card to isolate its join keys</div>
        </div>
      </div>
      <div class="star-shell" data-star-id="starSchemaData"></div>
      <script type="application/json" id="starSchemaData">{star_json}</script>
      {rel_table_html}
    </section>

    <section class="section" id="sec-tables">
      <div class="section-header">
        <div>
          <h2>3. Data Sources &amp; Tables Blueprint</h2>
          <div class="hint">Storage modes, source endpoints, upstream Dataflows, visual Power Query pipelines, and column definitions</div>
        </div>
        {('<div style="display:flex;gap:6px;flex-wrap:wrap"><button type="button" class="lin-btn" data-details-toggle="tablesBlueprintContainer" data-open="1">Expand All</button><button type="button" class="lin-btn" data-details-toggle="tablesBlueprintContainer" data-open="0">Collapse All</button></div>') if blueprint_cards else ''}
      </div>
      {upstream_df_html}
      <div class="{tbl_scroll_cls}" style="margin-bottom:18px">
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
          <div class="hint">Auto-formatted in SQLBI style &bull; Organized by Table &rarr; Collapsible Display Folder &rarr; Base vs. Derived KPIs</div>
        </div>
        {('<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">' + dax_usage_pills_html + '<div class="view-toggle"><button type="button" class="view-btn active" data-dax-view="list">Compact Table</button><button type="button" class="view-btn" data-dax-view="cards">Formatted Cards</button></div><button type="button" class="lin-btn" data-details-toggle="daxCardsContainer" data-open="1">Expand All</button><button type="button" class="lin-btn" data-details-toggle="daxCardsContainer" data-open="0">Collapse All</button></div>') if stats['measures'] > 0 else ''}
      </div>
      {dax_section_body}
    </section>

    <section class="section" id="sec-lineage">
      <div class="section-header">
        <h2>5. Interactive End-to-End Live Lineage</h2>
        <span class="hint">Click any source, dataflow, table, column, DAX measure, or report to trace live upstream &amp; downstream impact</span>
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

<script type="application/json" id="xrayRegistryData">{xray_json}</script>
<script src="../assets/e2e_graph.js"></script>
<script src="../assets/portal_common.js"></script>
<script src="../assets/star_schema_widget.js"></script>
<script src="../assets/lineage_widget.js"></script>
<script src="../assets/xray_drawer.js"></script>
<script>
(function () {{
  var input = document.getElementById("modelQuickFilter");
  if (input) {{
    input.addEventListener("input", function () {{
      var q = (input.value || "").toLowerCase().trim();
      document.querySelectorAll("[data-searchable]").forEach(function (el) {{
        var match = !q || (el.getAttribute("data-searchable") || "").indexOf(q) !== -1;
        el.style.display = match ? "" : "none";
        if (q && match && el.tagName === "DETAILS") el.open = true;
      }});
      if (q) {{
        document.querySelectorAll("details.dax-folder-details").forEach(function (f) {{
          var anyMatch = Array.from(f.querySelectorAll(".measure-card[data-searchable]")).some(function (c) {{ return c.style.display !== "none"; }});
          f.style.display = anyMatch ? "" : "none";
          if (anyMatch) f.open = true;
        }});
      }} else {{
        document.querySelectorAll("details.dax-folder-details").forEach(function (f) {{ f.style.display = ""; }});
      }}
    }});
  }}

  var repSearch = document.getElementById("boundReportsSearch");
  if (repSearch) {{
    repSearch.addEventListener("input", function () {{
      var rq = (repSearch.value || "").toLowerCase().trim();
      document.querySelectorAll("#boundReportsBody tr[data-report-row]").forEach(function (row) {{
        row.style.display = (!rq || (row.getAttribute("data-report-row") || "").indexOf(rq) !== -1) ? "" : "none";
      }});
    }});
  }}

  var pSearch = document.getElementById("principalsSearchInput");
  if (pSearch) {{
    pSearch.addEventListener("input", function () {{
      var pq = (pSearch.value || "").toLowerCase().trim();
      document.querySelectorAll("#principalsTableBody tr[data-principal-row]").forEach(function (row) {{
        row.style.display = (!pq || (row.getAttribute("data-principal-row") || "").indexOf(pq) !== -1) ? "" : "none";
      }});
    }});
  }}
}})();
</script>
</body>
</html>
"""


def _atomic_write_text(dest: Path, content: str) -> None:
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(dest)


def generate_portal(store: CatalogStore, output_dir: str | Path | None = None, anonymous: bool = False) -> Path:
    """Generate the complete 4-tab Power BI Workspace, Report, Semantic Model & Lineage Portal."""
    out_root = Path(output_dir) if output_dir else (store.root / "portal")
    assets_dir = out_root / "assets"
    models_dir = out_root / "models"
    assets_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=True)

    _atomic_write_text(assets_dir / "portal.css", PORTAL_CSS + "\n" + V11_WIDGETS_CSS)
    _atomic_write_text(assets_dir / "star_schema_widget.js", STAR_SCHEMA_WIDGET_JS)
    _atomic_write_text(assets_dir / "lineage_widget.js", LINEAGE_WIDGET_JS)
    _atomic_write_text(assets_dir / "portal_common.js", PORTAL_COMMON_JS)
    _atomic_write_text(assets_dir / "xray_drawer.js", XRAY_DRAWER_JS)

    state = store.load_scoped()
    portal_warnings: list[str] = list(state.get("errors") or [])
    enriched_dataflows: dict[str, dict] = {}
    for df_id, df_meta in (state.get("dataflows") or {}).items():
        df_copy = dict(df_meta)
        try:
            raw_def = store.read_dataflow_definition(df_id)
            if raw_def:
                parsed_df = parse_dataflow_definition(df_copy, raw_def)
                for k in ("queries", "entities", "description", "generation", "source_types"):
                    if parsed_df.get(k) or k not in df_copy:
                        df_copy[k] = parsed_df.get(k)
        except Exception as exc:
            portal_warnings.append(f"[ERR_DATAFLOW_PARSE] Dataflow '{df_meta.get('name') or df_id}': {mask_secrets(str(exc))}")
        enriched_dataflows[df_id] = df_copy

    reports_by_ds: dict[str, list[dict]] = collections.defaultdict(list)
    for rep in state["reports"].values():
        rep_with_layout = dict(rep)
        layout_obj = store.read_report_layout(rep.get("id", ""))
        if layout_obj:
            rep_with_layout["layout"] = layout_obj
        ds_id = rep.get("dataset_id")
        if ds_id:
            reports_by_ds[ds_id].append(rep_with_layout)

    analyses: list[tuple[str, dict]] = []
    slug_by_ds_id: dict[str, str] = {}
    used_slugs: set[str] = set()

    for ds_id, m_meta in sorted(
        state["models"].items(),
        key=lambda kv: ((kv[1].get("workspace") or "").lower(), (kv[1].get("name") or "").lower()),
    ):
        bundle = store.read_tmdl_bundle(m_meta.get("name") or "", ds_id)
        if not bundle:
            continue
        base_slug = slugify(f"{m_meta.get('workspace') or ''}-{m_meta.get('name') or ''}") if len(state["workspaces"]) > 1 else slugify(m_meta.get("name") or "")
        slug = base_slug
        idx = 2
        while slug in used_slugs:
            slug = f"{base_slug}-{idx}"
            idx += 1
        try:
            analysis = analyze_model(
                m_meta,
                bundle,
                reports=reports_by_ds.get(ds_id, []),
                dataflows=enriched_dataflows,
                fabric_items=state.get("fabric_items"),
                dataset_dataflow_links=(state.get("dataset_dataflow_links") or {}).get(ds_id, []),
            )
        except Exception as exc:
            portal_warnings.append(f"[ERR_MODEL_ANALYZE] Semantic model '{m_meta.get('name') or ds_id}': {mask_secrets(str(exc))}")
            continue
        used_slugs.add(slug)
        slug_by_ds_id[ds_id] = slug
        analyses.append((slug, analysis))

    try:
        e2e_graph = build_e2e_graph(store, [a for _, a in analyses])
    except Exception as exc:
        portal_warnings.append(f"[ERR_E2E_GRAPH] End-to-end lineage graph fallback triggered: {mask_secrets(str(exc))}")
        e2e_graph = {"nodes": [], "edges": [], "models": []}
    for m_entry in e2e_graph.get("models") or []:
        if isinstance(m_entry, dict) and m_entry.get("id") in slug_by_ds_id:
            m_entry["slug"] = slug_by_ds_id[m_entry["id"]]
    e2e_js_payload = json.dumps(e2e_graph, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    _atomic_write_text(assets_dir / "e2e_graph.js", f"window.PBI_E2E_GRAPH = {e2e_js_payload};\n")

    all_models_nav = [(s, a["workspace"], a["name"]) for s, a in analyses]
    written_model_files: set[str] = set()
    rendered_analyses: list[tuple[str, dict]] = []
    for slug, analysis in analyses:
        try:
            model_html = render_model_html(
                analysis,
                slug=slug,
                anonymous=anonymous,
                all_models_nav=all_models_nav,
                e2e_graph=e2e_graph,
            )
            fname = f"{slug}.html"
            written_model_files.add(fname)
            _atomic_write_text(models_dir / fname, model_html)
            rendered_analyses.append((slug, analysis))
        except Exception as exc:
            portal_warnings.append(f"[ERR_MODEL_RENDER] Semantic model '{analysis.get('name') or slug}': {mask_secrets(str(exc))}")
    analyses = rendered_analyses
    state["errors"] = portal_warnings

    # Summary KPIs
    total_ws = len(state["workspaces"]) or len({a["workspace"] for _, a in analyses})
    total_tables = sum(a["stats"]["tables"] for _, a in analyses)
    total_measures = sum(a["stats"]["measures"] for _, a in analyses)
    total_reports = len(state["reports"]) or sum(len(a["reports"]) for _, a in analyses)
    all_sources = sorted({s for _, a in analyses for s in a["source_types"]})
    total_findings = sum(len(a["findings"]) for _, a in analyses)

    portfolio_lineage_json = json.dumps(
        _build_workspace_lineage_json(analyses, e2e_graph=e2e_graph),
        ensure_ascii=False,
    ).replace("</", "<\\/")

    # Build Catalog-Level Slide-Over X-Ray Registry (Reports + Dataflows)
    catalog_xray_items: dict[str, Any] = {}
    catalog_report_order: list[str] = []
    enriched_rep_by_id: dict[str, tuple[dict, str, str, str]] = {}
    for slug, a in analyses:
        for r in a["reports"]:
            enriched_rep_by_id[r["id"]] = (r, a["name"], slug, a["workspace"])

    for rep in sorted(state["reports"].values(), key=lambda r: ((r.get("workspace") or "").lower(), (r.get("name") or "").lower())):
        rid_raw = rep.get("id", "")
        rid = f"rep:{rid_raw}"
        catalog_report_order.append(rid)
        if rid_raw in enriched_rep_by_id:
            r_obj, m_nm, m_sl, m_ws = enriched_rep_by_id[rid_raw]
        else:
            r_obj = dict(rep)
            lo = store.read_report_layout(rid_raw)
            if lo:
                r_obj["layout"] = lo
            m_nm = "External / Unscanned Model"
            m_sl = ""
            m_ws = rep.get("workspace") or ""
        try:
            catalog_xray_items[rid] = build_report_xray_entry(
                rep=r_obj,
                model_name=m_nm,
                model_slug=m_sl,
                model_workspace=m_ws,
                highlight_dax_fn=lambda expr: _highlight_dax(expr, auto_pretty=True),
                from_index=True,
                anonymous=anonymous,
                e2e_graph=e2e_graph,
                dataset_id=r_obj.get("dataset_id") or "",
            )
        except Exception as exc:
            portal_warnings.append(f"[ERR_REPORT_XRAY] Report '{rep.get('name') or rid_raw}': {mask_secrets(str(exc))}")

    for df_id, df_obj in enriched_dataflows.items():
        try:
            catalog_xray_items[f"df:{df_id}"] = build_dataflow_xray_entry(df_obj, _highlight_m, extract_m_steps)
        except Exception as exc:
            portal_warnings.append(f"[ERR_DATAFLOW_XRAY] Dataflow '{df_obj.get('name') or df_id}': {mask_secrets(str(exc))}")

    catalog_xray_json = json.dumps({"items": catalog_xray_items, "reportOrder": catalog_report_order}, ensure_ascii=False).replace("</", "<\\/")

    # Build Workspaces & Reports Map (Tab 2 - Collapsible Scannable Accordions)
    ws_rows = []
    for ws_id, ws in sorted(state["workspaces"].items(), key=lambda kv: (kv[1].get("name") or "").lower()):
        ws_models = [m for m in state["models"].values() if m.get("workspace_id") == ws_id]
        ws_reports = [r for r in state["reports"].values() if r.get("workspace_id") == ws_id]
        ws_dfs = [d for d in state["dataflows"].values() if d.get("workspace_id") == ws_id]
        sku = ws.get("capacity_sku") or ("Dedicated" if ws.get("is_dedicated") else "Shared (Pro)")
        sku_cls = "badge-accent" if ws.get("is_dedicated") else ""
        ws_nm = ws.get("name") or ""
        ws_rows.append(
            f'<tr data-wstab-row="1" data-wstab-search="{esc((ws_nm + " " + sku).lower())}" data-wstab-broken="0" data-wstab-cross="0">'
            f"<td><b>{esc(ws_nm)}</b></td>"
            f"<td><span class='badge {sku_cls}'>{esc(sku)}</span></td>"
            f"<td><b>{len(ws_models)}</b></td>"
            f"<td><b>{len(ws_reports)}</b></td>"
            f"<td>{len(ws_dfs)}</td>"
            f"<td>{len(ws.get('users') or []) if not anonymous else 'Redacted'}</td>"
            f"</tr>"
        )

    report_entries_raw = []
    broken_reports_total = 0
    cross_reports_total = 0
    for rep in state["reports"].values():
        rid_raw = rep.get("id", "")
        enr_tuple = enriched_rep_by_id.get(rid_raw)
        enr_rep = enr_tuple[0] if enr_tuple else rep
        br_c = len(enr_rep.get("broken_refs") or [])
        report_entries_raw.append((rep, enr_rep, br_c))

    report_entries_raw.sort(
        key=lambda item: (-item[2], (item[0].get("workspace") or "").lower(), (item[0].get("name") or "").lower())
    )

    report_map_rows = []
    for rep, enr_rep, br_c in report_entries_raw:
        rid_raw = rep.get("id", "")
        ds_id = rep.get("dataset_id", "")
        ds_meta = state["models"].get(ds_id) or {}
        ds_name = ds_meta.get("name") or (f"External Model ({ds_id[:8]})" if ds_id else "Unbound")
        ds_ws = ds_meta.get("workspace") or rep.get("workspace") or ""
        slug = slug_by_ds_id.get(ds_id)
        ds_link = f'<a href="models/{slug}.html"><b>{esc(ds_name)}</b></a>' if slug else esc(ds_name)
        cross = bool(ds_ws and rep.get("workspace") and ds_ws != rep.get("workspace"))
        if cross:
            cross_reports_total += 1
        if br_c:
            broken_reports_total += 1
        arch_badge = (
            '<span class="badge badge-accent">Cross-Workspace Shared Dataset</span>'
            if cross
            else '<span class="badge badge-ok">Same-Workspace Model</span>'
        )
        pg_c = enr_rep.get("pages_count") or len((store.read_report_layout(rid_raw) or {}).get("pages", []))
        vis_c = enr_rep.get("visuals_count") or sum(len(p.get("visuals", [])) for p in (store.read_report_layout(rid_raw) or {}).get("pages", []))
        struct_cell = f"{pg_c} page(s) &bull; {vis_c} visual(s)" if pg_c else f"<code>{esc(rep.get('report_type', 'PowerBIReport'))}</code>"
        br_pill = (
            f'<button type="button" class="badge badge-bad badge-bad-btn" data-open-xray="rep:{esc(rid_raw)}" data-xray-jump-broken="0" title="Jump directly to broken visual binding">! {br_c} broken</button> '
            if br_c
            else ""
        )
        insp_btn = f'<button type="button" class="xray-trigger-btn" data-open-xray="rep:{esc(rid_raw)}">Inspect Layout &rarr;</button>'
        rep_nm = rep.get("name") or ""
        rep_ws = rep.get("workspace") or ""
        report_map_rows.append(
            f'<tr data-wstab-row="1" data-wstab-search="{esc((rep_nm + " " + rep_ws + " " + ds_name).lower())}" data-wstab-broken="{"1" if br_c else "0"}" data-wstab-cross="{"1" if cross else "0"}">'
            f"<td><b>{esc(middle_truncate(rep_nm, 48))}</b></td>"
            f"<td>{esc(rep_ws)}</td>"
            f"<td>{ds_link}</td>"
            f"<td>{struct_cell}</td>"
            f"<td>{arch_badge}</td>"
            f'<td style="text-align:right;white-space:nowrap">{br_pill}{insp_btn}</td>'
            f"</tr>"
        )

    # Auto-detected Dataflows & Upstream Fabric Items Accordion (shown ONLY when workspace contains them!)
    dataflows_map = enriched_dataflows
    fabric_map = state.get("fabric_items") or {}
    dataflows_section_html = ""
    if dataflows_map or fabric_map:
        df_rows = []
        for df_id, df in sorted(dataflows_map.items(), key=lambda kv: ((kv[1].get("workspace") or "").lower(), (kv[1].get("name") or "").lower())):
            ent_cnt = len(df.get("queries") or df.get("entities") or [])
            ent_lbl = f"{ent_cnt} entit{'ies' if ent_cnt != 1 else 'y'}" if ent_cnt else "Metadata scanned"
            gen_str = str(df.get("generation") or "1")
            is_gen2 = "2" in gen_str
            gen_badge = (
                '<span class="badge badge-accent">Fabric Dataflow Gen2</span>'
                if is_gen2
                else '<span class="badge badge-dim">Dataflow Gen1</span>'
            )
            df_nm = df.get("name") or ""
            df_ws = df.get("workspace") or ""
            df_rows.append(
                f'<tr data-wstab-row="1" data-wstab-search="{esc((df_nm + " " + df_ws + " dataflow").lower())}" data-wstab-broken="0" data-wstab-cross="0">'
                f"<td><b>{esc(df_nm)}</b></td>"
                f"<td>{gen_badge}</td>"
                f"<td>{esc(df_ws)}</td>"
                f"<td>{ent_lbl}</td>"
                f'<td style="text-align:right"><button type="button" class="xray-trigger-btn" data-open-xray="df:{esc(df_id)}">Inspect Dataflow &rarr;</button></td>'
                f"</tr>"
            )
        for fi_id, fi in sorted(fabric_map.items(), key=lambda kv: ((kv[1].get("workspace") or "").lower(), (kv[1].get("name") or "").lower())):
            if fi.get("type") in ("SemanticModel", "Report", "Dataset"):
                continue
            if fi_id in dataflows_map:
                continue
            fi_nm = fi.get("name") or ""
            fi_ws = fi.get("workspace") or ""
            fi_tp = fi.get("type") or "Fabric Item"
            df_rows.append(
                f'<tr data-wstab-row="1" data-wstab-search="{esc((fi_nm + " " + fi_ws + " " + fi_tp).lower())}" data-wstab-broken="0" data-wstab-cross="0">'
                f"<td><b>{esc(fi_nm)}</b></td>"
                f"<td><span class='badge badge-accent'>{esc(fi_tp)}</span></td>"
                f"<td>{esc(fi_ws)}</td>"
                f"<td>{esc(fi.get('description') or 'Auto-detected workspace item')}</td>"
                f'<td style="text-align:right"><span style="font-size:11.5px;color:var(--fg-muted)">Cataloged</span></td>'
                f"</tr>"
            )
        if df_rows:
            dataflows_section_html = (
                f'<details class="section-accordion">'
                f'<summary><span class="acc-title"><span class="acc-chev">&#9656;</span> 3. Dataflows &amp; Upstream Fabric Items (Gen1 &amp; Gen2)</span>'
                f'<span class="badge badge-accent">{len(df_rows)} item(s)</span></summary>'
                f'<div class="accordion-body"><div class="table-scroll sticky-table-scroll">'
                f'<table class="data-table fixed-table">'
                f'<colgroup><col style="width:30%"><col style="width:16%"><col style="width:20%"><col style="width:18%"><col style="width:16%"></colgroup>'
                f"<thead><tr><th>Item Name</th><th>Type</th><th>Workspace</th><th>Entities / Notes</th><th style='text-align:right'>Inspector</th></tr></thead>"
                f'<tbody>{"".join(df_rows)}</tbody></table></div></div></details>'
            )

    orphan_models = [(slug, a) for slug, a in analyses if len(a["reports"]) == 0]
    orphan_html = ""
    if orphan_models:
        o_rows = "".join(
            f'<tr data-wstab-row="1" data-wstab-search="{esc((a["name"] + " " + a["workspace"]).lower())}" data-wstab-broken="0" data-wstab-cross="0">'
            f'<td><a href="models/{slug}.html"><b>{esc(a["name"])}</b></a></td>'
            f"<td>{esc(a['workspace'])}</td>"
            f"<td>{a['stats']['tables']} tables &bull; {a['stats']['measures']} DAX measures</td>"
            f"<td><span class='badge'>0 bound reports in scanned workspaces</span></td>"
            f"</tr>"
            for slug, a in orphan_models
        )
        orphan_Step = "4" if dataflows_section_html else "3"
        orphan_html = (
            f'<details class="section-accordion">'
            f'<summary><span class="acc-title"><span class="acc-chev">&#9656;</span> {orphan_Step}. Semantic Models Without Bound Reports</span>'
            f'<span class="badge">{len(orphan_models)} model(s)</span></summary>'
            f'<div class="accordion-body">'
            f'<p style="font-size:12.5px;color:var(--fg-muted);margin:0 0 10px 0">Shared core datasets consumed via Excel / XMLA / external workspaces, or candidates for cleanup:</p>'
            f'<div class="table-scroll sticky-table-scroll"><table class="data-table">'
            f"<thead><tr><th>Semantic Model</th><th>Workspace</th><th>Structure</th><th>Status</th></tr></thead>"
            f"<tbody>{o_rows}</tbody></table></div></div></details>"
        )

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
    health_entries: list[tuple[int, int, str, str]] = []

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
        owner_val = "Redacted" if anonymous else (a.get("owner") or "Local / Unassigned")
        last_ref_dict = a.get("last_refresh") or {}
        ref_txt = last_ref_dict.get("status") or "Snapshot"
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

        internal_badge = '<span class="badge">Internal</span>'
        card_markup = (
            f'<a class="model-card" href="models/{slug}.html" data-model-item="card" {data_attrs} style="color:inherit;text-decoration:none">'
            f'<div class="card-eyebrow"><span class="eyebrow-type">Semantic Model</span><span>{esc(fmt_short)}</span></div>'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px"><h3>{esc(a["name"])}</h3>{status_badge}</div>'
            f'<div style="font-size:12px;color:var(--fg-muted)">Workspace: <b>{esc(a["workspace"])}</b></div>'
            f'<div class="model-meta">{src_badges or internal_badge}</div>'
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
            f"<td>{src_badges or internal_badge}</td>"
            f"<td><b>{st['tables']}</b></td>"
            f"<td>{st['columns']}</td>"
            f"<td><b>{st['measures']}</b></td>"
            f"<td>{st['relationships']}</td>"
            f"<td>{len(a['reports'])}</td>"
            f"<td>{status_badge}</td>"
            f"</tr>"
        )

        for f in a["findings"]:
            is_bad = f["severity"] == "bad"
            b_cls = "badge-bad" if is_bad else "badge-warn"
            sev_lbl = "CRITICAL" if is_bad else "WARN"
            h_search = f"{a['name']} {a['workspace']} {f['title']} {f['detail']}".lower()
            row_str = (
                f'<tr data-health-sev="{esc(f["severity"])}" data-health-search="{esc(h_search)}">'
                f'<td><a href="models/{slug}.html"><b>{esc(a["name"])}</b></a></td>'
                f"<td>{esc(a['workspace'])}</td>"
                f"<td><span class='badge {b_cls}'>{sev_lbl}</span></td>"
                f"<td><b>{esc(f['title'])}</b></td>"
                f"<td>{esc(f['detail'])}</td>"
                f"</tr>"
            )
            health_entries.append((0 if is_bad else 1, -len(a["reports"]), a["name"].lower(), row_str))

    for w_msg in portal_warnings:
        clean_w = mask_secrets(str(w_msg))
        w_search = f"catalog scan warning {clean_w}".lower()
        w_row = (
            f'<tr data-health-sev="warn" data-health-search="{esc(w_search)}">'
            f"<td><b>Catalog Scanner / Parser</b></td>"
            f"<td>Workspace / Local</td>"
            f"<td><span class='badge badge-warn'>WARN</span></td>"
            f"<td><b>Handled Item Warning</b></td>"
            f"<td>{esc(clean_w)}</td>"
            f"</tr>"
        )
        health_entries.append((1, 0, "zz_scanner", w_row))

    total_findings = len(health_entries)
    health_entries.sort(key=lambda t: (t[0], t[1], t[2]))
    health_rows = [t[3] for t in health_entries]
    crit_findings_cnt = sum(1 for t in health_entries if t[0] == 0)
    warn_findings_cnt = sum(1 for t in health_entries if t[0] == 1)

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

    ws_sorted_list = sorted({a["workspace"] for _, a in analyses})
    if len(ws_sorted_list) <= 4:
        ws_chips = "".join(
            f'<button type="button" class="chip-btn" data-ws-chip="{esc(ws.lower())}">Workspace: {esc(ws)}</button>'
            for ws in ws_sorted_list
        )
    else:
        ws_opts = "".join(f'<option value="{esc(ws.lower())}">{esc(ws)}</option>' for ws in ws_sorted_list)
        ws_chips = (
            f'<select id="catalogWsSelect" class="sort-select" aria-label="Filter by workspace">'
            f'<option value="all">All Workspaces ({len(ws_sorted_list)})</option>{ws_opts}</select>'
        )
    broken_chip_html = (
        f'<button type="button" class="chip-btn" data-wstab-chip="broken">Broken Bindings ({broken_reports_total})</button>'
        if broken_reports_total
        else ""
    )
    cross_chip_html = (
        f'<button type="button" class="chip-btn" data-wstab-chip="cross">Cross-Workspace ({cross_reports_total})</button>'
        if cross_reports_total
        else ""
    )
    rep_broken_summary_badge = (
        f'<span class="badge badge-bad">{broken_reports_total} with broken bindings</span>'
        if broken_reports_total
        else '<span class="badge badge-ok">All bindings healthy</span>'
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
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <div class="app-switcher studio-only-link" style="display:none">
        <a href="/">&larr; 1. Scanner &amp; Setup</a>
        <span class="active-seg">2. Documentation Portal</span>
      </div>
      <button type="button" class="publish-top-btn" data-open-publish-modal="catalog" aria-label="Export or Publish Documentation">Export / Publish</button>
      <button type="button" class="theme-icon-btn" data-toggle-theme="1" title="Toggle Light / Dark theme" aria-label="Toggle Light / Dark theme">
        <svg class="icon-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        <svg class="icon-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      </button>
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
  <div class="print-only-doc-banner">
    <div>
      <div style="font-size:9.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;color:#0b63ce;margin-bottom:2px">Power BI Portfolio &amp; Governance Summary</div>
      <div style="font-size:19px;font-weight:800;color:#0f172a;line-height:1.2">Power BI Documentation &amp; Live Lineage Portal</div>
      <div style="font-size:11px;color:#475569;margin-top:3px">Generated: <b>{esc(gen_ts)}</b></div>
    </div>
    <div style="text-align:right;font-size:10.5px;color:#475569;white-space:nowrap">
      <div><b>{total_ws}</b> Workspaces &bull; <b>{len(analyses)}</b> Models &bull; <b>{total_reports}</b> Reports</div>
      <div style="margin-top:2px">PBI Doc Generator v1.1</div>
    </div>
  </div>
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

    <div id="catalogEmptyMatch" class="card" style="display:none;text-align:center;padding:24px;color:var(--fg-muted)">
      No semantic models match the active search or filter.
      <button type="button" class="lin-btn" style="margin-left:8px" onclick="document.getElementById('catalogResetBtn').click()">Reset filters</button>
    </div>

    <div class="model-grid" id="modelGrid">
      {''.join(cards_html) or '<div class="card">No semantic models documented yet. Open 1. Scanner &amp; Setup to connect or import a local model.</div>'}
    </div>

    <div class="table-scroll sticky-table-scroll" id="modelListWrap" style="display:none">
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
    <div class="filter-bar" style="justify-content:space-between">
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;flex:1;min-width:240px">
        <input type="search" id="wsTabSearch" placeholder="Filter reports, workspaces, underlying semantic models, or dataflows...">
        <button type="button" class="chip-btn active" data-wstab-chip="all">All</button>
        {broken_chip_html}
        {cross_chip_html}
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <button type="button" class="lin-btn" data-details-toggle="tab-workspaces" data-open="1">Expand All</button>
        <button type="button" class="lin-btn" data-details-toggle="tab-workspaces" data-open="0">Collapse All</button>
      </div>
    </div>

    <details class="section-accordion">
      <summary>
        <span class="acc-title"><span class="acc-chev">&#9656;</span> 1. Workspace Inventory &amp; Capacity Overview</span>
        <span class="badge badge-accent">{len(ws_rows)} workspace(s)</span>
      </summary>
      <div class="accordion-body">
        <div class="table-scroll sticky-table-scroll">
          <table class="data-table fixed-table">
            <colgroup><col style="width:32%"><col style="width:20%"><col style="width:12%"><col style="width:12%"><col style="width:12%"><col style="width:12%"></colgroup>
            <thead>
              <tr><th>Workspace</th><th>Capacity / SKU</th><th>Semantic Models</th><th>Reports</th><th>Dataflows</th><th>Principals</th></tr>
            </thead>
            <tbody>
              {''.join(ws_rows) or '<tr><td colspan="6">No workspaces recorded.</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </details>

    <details class="section-accordion">
      <summary>
        <span class="acc-title"><span class="acc-chev">&#9656;</span> 2. Power BI Reports &amp; Semantic Model Mapping</span>
        <span style="display:flex;gap:6px;align-items:center">
          <span class="badge badge-accent">{len(report_map_rows)} report(s)</span>
          {rep_broken_summary_badge}
        </span>
      </summary>
      <div class="accordion-body">
        <div class="table-scroll sticky-table-scroll">
          <table class="data-table fixed-table">
            <colgroup><col style="width:24%"><col style="width:16%"><col style="width:22%"><col style="width:13%"><col style="width:11%"><col style="width:14%"></colgroup>
            <thead>
              <tr><th>Power BI Report</th><th>Report Workspace</th><th>Underlying Semantic Model</th><th>Pages &amp; Visuals</th><th>Binding</th><th style="text-align:right">Inspector</th></tr>
            </thead>
            <tbody>
              {''.join(report_map_rows) or '<tr><td colspan="6">No reports recorded in scanned workspaces.</td></tr>'}
            </tbody>
          </table>
        </div>
      </div>
    </details>

    {dataflows_section_html}
    {orphan_html}
  </section>

  <section class="tab-pane" id="tab-lineage">
    <div style="margin-bottom:12px;color:var(--fg-muted);font-size:13px">
      Trace data end-to-end across workspaces from upstream platforms, dataflows, and database views through semantic models into downstream Power BI reports. Toggle <b>+ Show Core KPIs</b> or switch between <b>Horizontal / Vertical</b> swimlanes in the toolbar.
    </div>
    <div class="lineage-app" data-lineage-id="portfolioLineageData"></div>
    <script type="application/json" id="portfolioLineageData">{portfolio_lineage_json}</script>
  </section>

  <section class="tab-pane" id="tab-health">
    <div class="filter-bar" style="justify-content:space-between">
      <div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;flex:1;min-width:240px">
        <input type="search" id="healthTabSearch" placeholder="Filter governance findings by model, workspace, or rule...">
        <button type="button" class="chip-btn active" data-health-chip="all">All ({total_findings})</button>
        <button type="button" class="chip-btn" data-health-chip="bad">Critical ({crit_findings_cnt})</button>
        <button type="button" class="chip-btn" data-health-chip="warn">Warnings ({warn_findings_cnt})</button>
      </div>
      <button type="button" class="lin-btn" data-export-gov-csv="1">Export Backlog (.csv)</button>
    </div>
    <div class="table-scroll sticky-table-scroll">
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

<footer style="max-width:1440px;margin:28px auto 14px auto;padding:14px 24px;border-top:1px solid var(--border);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:12px;color:var(--fg-muted)">
  <span>Generated locally with <a href="https://github.com/djrien-ai/pbi-doc-generator" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;font-weight:600">PBI Doc Generator v1.1</a> (MIT Open Source)</span>
  <span>Created by <a href="https://github.com/djrien-ai" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;font-weight:600">Rien Scheerlinck</a></span>
</footer>

<script type="application/json" id="xrayRegistryData">{catalog_xray_json}</script>
<script src="assets/e2e_graph.js"></script>
<script src="assets/portal_common.js"></script>
<script src="assets/lineage_widget.js"></script>
<script src="assets/xray_drawer.js"></script>
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
  var activeView = (window.PbiStorage ? window.PbiStorage.get("pbidoc-v1-catalog-view") : null) || "grid";
  var sortDir = 1;
  var totalCount = {len(analyses)};

  function setCatalogView(v) {{
    if (["grid", "list", "workspace"].indexOf(v) === -1) v = "grid";
    activeView = v;
    if (window.PbiStorage) window.PbiStorage.set("pbidoc-v1-catalog-view", v);
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
    var emptyMatchEl = document.getElementById("catalogEmptyMatch");
    if (emptyMatchEl && totalCount > 0) {{
      emptyMatchEl.style.display = shown === 0 ? "" : "none";
    }}
    if (resetBtn) {{
      resetBtn.style.display = (q || activeStatus !== "all" || activeWs !== "all") ? "" : "none";
    }}
  }}

  // Tab 2 (Workspaces & Reports) live filtering
  var wsTabSearch = document.getElementById("wsTabSearch");
  var wsTabChip = "all";
  function applyWsTabFilters() {{
    var wq = (wsTabSearch && wsTabSearch.value || "").toLowerCase().trim();
    document.querySelectorAll("#tab-workspaces tr[data-wstab-row]").forEach(function (tr) {{
      var okQ = !wq || (tr.getAttribute("data-wstab-search") || "").indexOf(wq) !== -1;
      var okC = wsTabChip === "all" ||
        (wsTabChip === "broken" && tr.getAttribute("data-wstab-broken") === "1") ||
        (wsTabChip === "cross" && tr.getAttribute("data-wstab-cross") === "1");
      tr.style.display = (okQ && okC) ? "" : "none";
    }});
    if (wq || wsTabChip !== "all") {{
      document.querySelectorAll("#tab-workspaces details.section-accordion").forEach(function (det) {{
        var hasMatch = Array.from(det.querySelectorAll("tr[data-wstab-row]")).some(function (r) {{ return r.style.display !== "none"; }});
        if (hasMatch) det.open = true;
      }});
    }}
  }}
  if (wsTabSearch) wsTabSearch.addEventListener("input", applyWsTabFilters);

  // Tab 4 (Governance & Health) live filtering
  var healthSearch = document.getElementById("healthTabSearch");
  var healthChip = "all";
  function applyHealthFilters() {{
    var hq = (healthSearch && healthSearch.value || "").toLowerCase().trim();
    document.querySelectorAll("#tab-health tr[data-health-sev]").forEach(function (tr) {{
      var okSev = healthChip === "all" || tr.getAttribute("data-health-sev") === healthChip;
      var okQ = !hq || (tr.getAttribute("data-health-search") || "").indexOf(hq) !== -1;
      tr.style.display = (okSev && okQ) ? "" : "none";
    }});
  }}
  if (healthSearch) healthSearch.addEventListener("input", applyHealthFilters);

  setCatalogView(activeView);
  if (search) search.addEventListener("input", applyFilters);
  if (sortSelect) {{
    sortSelect.addEventListener("change", function () {{
      sortDir = 1;
      applySort(sortSelect.value, 1);
    }});
  }}
  var wsSelect = document.getElementById("catalogWsSelect");
  if (wsSelect) {{
    wsSelect.addEventListener("change", function () {{
      activeWs = wsSelect.value || "all";
      applyFilters();
    }});
  }}
  if (resetBtn) {{
    resetBtn.addEventListener("click", function () {{
      if (search) search.value = "";
      activeStatus = "all";
      activeWs = "all";
      if (wsSelect) wsSelect.value = "all";
      document.querySelectorAll("[data-status-chip]").forEach(function (b) {{ b.classList.toggle("active", b.getAttribute("data-status-chip") === "all"); }});
      document.querySelectorAll("[data-ws-chip]").forEach(function (b) {{ b.classList.remove("active"); }});
      applyFilters();
    }});
  }}
  try {{
    var initWsParam = (new URLSearchParams(location.search || "").get("ws") || "").trim().toLowerCase();
    if (initWsParam) {{
      activeWs = initWsParam;
      if (wsSelect) wsSelect.value = initWsParam;
      document.querySelectorAll("[data-ws-chip]").forEach(function (b) {{ b.classList.toggle("active", b.getAttribute("data-ws-chip") === activeWs); }});
      applyFilters();
    }}
  }} catch (e) {{}}

  document.addEventListener("click", function (e) {{
    var wtb = e.target.closest("[data-wstab-chip]");
    if (wtb) {{
      wsTabChip = wtb.getAttribute("data-wstab-chip");
      document.querySelectorAll("[data-wstab-chip]").forEach(function (b) {{ b.classList.toggle("active", b === wtb); }});
      applyWsTabFilters();
      return;
    }}
    var hcb = e.target.closest("[data-health-chip]");
    if (hcb) {{
      healthChip = hcb.getAttribute("data-health-chip");
      document.querySelectorAll("[data-health-chip]").forEach(function (b) {{ b.classList.toggle("active", b === hcb); }});
      applyHealthFilters();
      return;
    }}
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
    _atomic_write_text(index_path, index_html)

    # Clean up stale model files ONLY after all replacement files have been written atomically
    for existing_html in models_dir.glob("*.html"):
        if existing_html.name not in written_model_files:
            try:
                existing_html.unlink()
            except OSError:
                pass

    return index_path
