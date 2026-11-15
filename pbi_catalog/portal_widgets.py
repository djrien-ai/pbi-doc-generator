"""
Modern Interactive Star-Schema Cards, Sticky Breadcrumb & Model Switcher,
Clickable Power Query M Step-Through & Native SQL Blocks, Overflow-Safe Governance Tables,
and In-Place Slide-Over X-Ray Drawer (Reports & Dataflow Gen1/Gen2) for PBI Doc Generator v1.1+.
"""

from __future__ import annotations

import collections
import json
import re
from typing import Any, Callable

from .mparse import extract_native_sql
from .pq_steps import interpret_query
from .report_parser import redact_report_layout_literals
from .security import esc, mask_secrets, slugify
from .sql_format import format_sql


def middle_truncate(text: str, max_len: int = 44) -> str:
    """Safely middle-truncate long unspaced enterprise identifiers while preserving prefix and suffix."""
    s = str(text or "")
    if len(s) <= max_len:
        return s
    keep = max(10, max_len - 3)
    head = int(keep * 0.56)
    tail = keep - head
    return f"{s[:head]}...{s[-tail:]}"


_SQL_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER", "CROSS",
    "ON", "AND", "OR", "NOT", "IN", "EXISTS", "IS", "NULL", "AS", "GROUP", "BY", "ORDER",
    "HAVING", "UNION", "ALL", "DISTINCT", "TOP", "LIMIT", "OFFSET", "WITH", "CASE", "WHEN",
    "THEN", "ELSE", "END", "CAST", "CONVERT", "COALESCE", "OVER", "PARTITION", "ASC", "DESC",
    "BETWEEN", "LIKE", "INTO", "VALUES", "DECLARE", "SET",
}


def highlight_sql(code: str) -> str:
    """Format and syntax-highlight Native SQL while masking credentials and highlighting {{PARAM}} tokens."""
    formatted = format_sql(mask_secrets(code or ""))
    safe = esc(formatted)

    def _tok(m: re.Match[str]) -> str:
        tok = m.group(0)
        if tok.startswith("--") or tok.startswith("/*"):
            return f'<span class="cmt">{tok}</span>'
        if tok.startswith("'") or tok.startswith("&#x27;"):
            return f'<span class="str">{tok}</span>'
        if tok.startswith("{{") and tok.endswith("}}"):
            return f'<span class="sql-param-pill">{tok}</span>'
        if tok.upper() in _SQL_KEYWORDS:
            return f'<span class="kw">{tok.upper()}</span>'
        return tok

    pat = re.compile(r"(--[^\n]*|/\*[\s\S]*?\*/|\{\{[^}]+\}\}|&#x27;(?:[^&]|&(?!#x27;))*&#x27;|'(?:[^']|'')*'|\b[A-Za-z_][A-Za-z0-9_]*\b)")
    return pat.sub(_tok, safe)


_PQ_BLOCK_SEQ = 0


def render_pq_partition_block(
    m_code: str,
    highlight_m_fn: Callable[[str], str],
    script_title: str = "View Power Query M Script",
    native_sql_items: list[dict[str, Any]] | None = None,
    step_items: list[dict[str, Any]] | None = None,
    destination: dict[str, Any] | None = None,
    linked_df_ref: dict[str, Any] | None = None,
) -> str:
    """
    Render Formatted Native SQL callout(s) + Clickable Power Query Step-Through Ribbon +
    Collapsible M Script viewer with UTF-16 step range highlighting.
    """
    global _PQ_BLOCK_SEQ
    _PQ_BLOCK_SEQ += 1
    uid = f"pqblk-{_PQ_BLOCK_SEQ}"

    parts: list[str] = []

    if destination and isinstance(destination, dict) and destination.get("table"):
        dkind = destination.get("kind") or "Lakehouse"
        dtbl = destination.get("table") or ""
        dschema = destination.get("schema") or ""
        dupd = destination.get("update_method") or ""
        full_dest = f"{dschema}.{dtbl}" if dschema and "." not in dtbl else dtbl
        upd_lbl = f" ({esc(str(dupd).capitalize())})" if dupd else ""
        parts.append(
            f'<div class="pq-dest-banner">'
            f'<span class="badge badge-accent">OneLake Destination</span> '
            f'Writes to <b>{esc(dkind)}</b> table <code>{esc(full_dest)}</code>{upd_lbl}'
            f"</div>"
        )

    if linked_df_ref and isinstance(linked_df_ref, dict) and linked_df_ref.get("dataflow_id"):
        up_df_id = str(linked_df_ref.get("dataflow_id") or "")
        up_ent = str(linked_df_ref.get("entity") or "")
        parts.append(
            f'<div class="pq-dest-banner">'
            f'<span class="badge badge-dim">Linked Entity</span> '
            f'Reads upstream entity <code>{esc(up_ent)}</code> '
            f'<button type="button" class="xray-trigger-btn" style="margin-left:6px;padding:2px 8px;font-size:11px" '
            f'data-open-xray="df:{esc(up_df_id)}">Inspect Upstream Dataflow &rarr;</button>'
            f"</div>"
        )

    clean_m = mask_secrets(m_code or "")
    if not clean_m.strip():
        return "".join(parts)

    sql_list = native_sql_items
    if sql_list is None:
        sql_list = []
        for sq in extract_native_sql(clean_m):
            raw_s = mask_secrets(sq.get("sql") or "")
            if raw_s.strip():
                sql_list.append(
                    {
                        "sql": format_sql(raw_s),
                        "via": sq.get("via", "Value.NativeQuery"),
                        "parameters": sq.get("parameters") or [],
                    }
                )

    for idx_s, sq in enumerate(sql_list, 1):
        sql_txt = sq.get("sql") or ""
        if not sql_txt.strip():
            continue
        via_txt = sq.get("via") or "Native SQL"
        conn_bits = [x for x in (sq.get("connector"), sq.get("server"), sq.get("database")) if x]
        conn_lbl = f" &bull; {esc(' / '.join(conn_bits))}" if conn_bits else ""
        params_arr = sq.get("parameters") or []
        param_lbl = (
            " &bull; Params: " + ", ".join(f"<code>{{{{{esc(p)}}}}}</code>" for p in params_arr)
            if params_arr
            else ""
        )
        hdr_s = f"Formatted Native SQL #{idx_s}" if len(sql_list) > 1 else "Formatted Native SQL"
        parts.append(
            f'<div class="sql-callout">'
            f'<div class="sql-callout-hdr">'
            f'<span><b>{hdr_s}</b> <span style="font-weight:400;color:var(--fg-muted)">(via <code>{esc(via_txt)}</code>{conn_lbl}{param_lbl})</span></span>'
            f"</div>"
            f'<div class="code-block" style="margin:0"><button type="button" class="copy-btn" data-copy="1">Copy SQL</button>'
            f"<pre>{highlight_sql(sql_txt)}</pre></div>"
            f"</div>"
        )

    steps = step_items if step_items is not None else interpret_query(clean_m)
    steps_payload: list[dict[str, Any]] = []
    if steps:
        pills: list[str] = []
        for i, st in enumerate(steps):
            nm = str(st.get("name") or f"Step {i + 1}")
            op = str(st.get("op") or st.get("kind") or "Step")
            summary = str(st.get("summary") or op)
            details = [str(d) for d in (st.get("details") or [])[:8]]
            start_off = st.get("start")
            end_off = st.get("end")
            steps_payload.append(
                {
                    "index": i + 1,
                    "name": nm,
                    "op": op,
                    "summary": summary,
                    "details": details,
                    "start": start_off if isinstance(start_off, int) else None,
                    "end": end_off if isinstance(end_off, int) else None,
                }
            )
            pills.append(
                f'<button type="button" class="pq-step pq-step-btn" data-pq-step="{i}" '
                f'title="{esc(summary)} (Click to inspect &amp; highlight M code)">'
                f"<b>{i + 1}. {esc(middle_truncate(nm, 28))}</b>"
                f"<small>{esc(middle_truncate(op, 28))}</small>"
                f"</button>"
            )
        joined_pills = '<span class="pq-arrow">&rarr;</span>'.join(pills)
        parts.append(
            f'<div class="pq-interactive-wrap" id="{uid}">'
            f'<div style="margin-top:12px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">'
            f'<span style="font-size:12px;font-weight:650">Power Query Transformation Pipeline ({len(steps)} steps)</span>'
            f'<span style="font-size:11px;color:var(--fg-muted)">Click any step pill to inspect logic &amp; highlight M expression</span>'
            f"</div>"
            f'<div class="pq-pipeline">{joined_pills}</div>'
            f'<div class="pq-step-inspector" style="display:none"></div>'
            f'<details class="m-script-toggle">'
            f"<summary>{esc(script_title)}</summary>"
            f'<div style="padding:8px 10px"><div class="code-block">'
            f'<button type="button" class="copy-btn" data-copy="1">Copy M</button>'
            f'<pre class="pq-m-pre">{highlight_m_fn(clean_m)}</pre>'
            f"</div></div></details>"
            f'<script type="application/json" class="pq-meta-json">'
            + json.dumps({"raw": clean_m, "steps": steps_payload}, ensure_ascii=False).replace("</", "<\\/")
            + "</script></div>"
        )
    else:
        parts.append(
            f'<details class="m-script-toggle">'
            f"<summary>{esc(script_title)}</summary>"
            f'<div style="padding:8px 10px"><div class="code-block">'
            f'<button type="button" class="copy-btn" data-copy="1">Copy M</button>'
            f"<pre>{highlight_m_fn(clean_m)}</pre>"
            f"</div></div></details>"
        )

    return "".join(parts)


V11_WIDGETS_CSS = r"""
/* Sticky Breadcrumb & Quick Model Switcher Bar */
.doc-topbar {
  position: sticky;
  top: 0;
  z-index: 40;
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 10px 32px;
  margin: -28px -32px 24px -32px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  box-shadow: 0 1px 6px rgba(15, 23, 42, 0.05);
}
.doc-crumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 7px;
  font-size: 12.5px;
  color: var(--fg-muted);
  min-width: 0;
}
.doc-crumbs a {
  color: var(--accent);
  font-weight: 600;
  text-decoration: none;
}
.doc-crumbs a:hover { text-decoration: underline; }
.doc-crumbs .crumb-sep { opacity: 0.55; font-size: 12px; }
.doc-crumbs .crumb-current {
  color: var(--fg);
  font-weight: 700;
}
.doc-topbar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.model-switcher-select {
  padding: 5px 10px;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  color: var(--fg);
  font-size: 12px;
  font-weight: 600;
  max-width: 280px;
  cursor: pointer;
}
.model-switcher-select:focus {
  outline: 2px solid var(--accent);
  border-color: var(--accent);
}

/* Native SQL Callout & Interactive Clickable M Step-Through */
.sql-callout {
  margin: 12px 0 10px 0;
  border: 1px solid var(--border);
  border-left: 4px solid var(--warn);
  border-radius: 9px;
  background: var(--surface);
  padding: 10px 12px;
}
.sql-callout-hdr {
  font-size: 12px;
  margin-bottom: 6px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sql-param-pill {
  display: inline-block;
  padding: 0 5px;
  border-radius: 4px;
  background: var(--warn-bg);
  color: var(--warn);
  font-weight: 700;
}
.pq-dest-banner {
  margin-top: 10px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-alt);
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
button.pq-step-btn {
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  transition: border-color 0.14s, background 0.14s, transform 0.1s;
}
button.pq-step-btn:hover {
  border-color: var(--accent);
  transform: translateY(-1px);
}
button.pq-step-btn.is-active {
  border-color: var(--accent);
  background: var(--accent-soft);
  box-shadow: 0 0 0 2px rgba(11, 99, 206, 0.18);
}
.pq-step-inspector {
  margin: 6px 0 8px 0;
  padding: 9px 12px;
  border-radius: 8px;
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  font-size: 12px;
}
mark.pq-span-mark {
  background: rgba(245, 158, 11, 0.28);
  color: inherit;
  border-bottom: 2px solid var(--warn);
  border-radius: 3px;
  padding: 1px 0;
}

/* Header Export Dropdown */
.export-dropdown-wrap {
  position: relative;
  display: inline-block;
}
.export-dropdown-menu {
  display: none;
  position: absolute;
  right: 0;
  top: calc(100% + 6px);
  min-width: 245px;
  background: var(--surface);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 10px;
  box-shadow: 0 10px 28px rgba(15, 23, 42, 0.22);
  padding: 6px;
  z-index: 900;
}
.export-dropdown-menu.is-open {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.export-menu-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 1px;
  width: 100%;
  text-align: left;
  padding: 7px 10px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: var(--fg);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  text-decoration: none;
}
.export-menu-item:hover {
  background: var(--accent-soft);
  color: var(--accent);
  text-decoration: none;
}
.export-menu-item small {
  font-size: 10.5px;
  font-weight: 400;
  color: var(--fg-muted);
}

/* Collapsible Section Accordions (Tab 2, Tab 4 & Long Model Tables) */
details.section-accordion {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
  margin-bottom: 14px;
  overflow: hidden;
}
details.section-accordion > summary {
  list-style: none;
  cursor: pointer;
  padding: 13px 18px;
  background: var(--surface);
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 14.5px;
  font-weight: 700;
  user-select: none;
  transition: background 0.14s;
}
details.section-accordion > summary::-webkit-details-marker { display: none; }
details.section-accordion > summary:hover { background: var(--surface-alt); }
details.section-accordion > summary .acc-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}
details.section-accordion > summary .acc-chev {
  display: inline-block;
  font-size: 11px;
  color: var(--fg-muted);
  transition: transform 0.16s ease;
}
details.section-accordion[open] > summary .acc-chev {
  transform: rotate(90deg);
}
details.section-accordion[open] > summary {
  border-bottom: 1px solid var(--border);
  background: var(--surface-alt);
}
.section-accordion-body, .accordion-body {
  padding: 14px 18px;
}

/* Clickable Broken Badge & Stepper in Report X-Ray */
.badge-bad-btn {
  background: var(--bad-bg);
  color: var(--bad);
  border: 1px solid rgba(185, 28, 28, 0.35);
  border-radius: 999px;
  padding: 2px 9px;
  font-size: 11.5px;
  font-weight: 700;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.badge-bad-btn:hover {
  filter: brightness(0.95);
}
.xray-broken-stepper {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  background: var(--bad-bg);
  color: var(--bad);
  border: 1px solid rgba(185, 28, 28, 0.38);
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 11.5px;
  font-weight: 700;
}
.xray-broken-stepper button {
  border: none;
  background: rgba(185, 28, 28, 0.12);
  color: var(--bad);
  border-radius: 999px;
  padding: 1px 7px;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
}
.xray-broken-stepper button:hover {
  background: rgba(185, 28, 28, 0.24);
}
@keyframes xrayPulseRed {
  0% { stroke-width: 2.5px; filter: drop-shadow(0 0 0 rgba(185, 28, 28, 0)); }
  45% { stroke-width: 5px; filter: drop-shadow(0 0 9px rgba(185, 28, 28, 0.65)); }
  100% { stroke-width: 3px; filter: drop-shadow(0 0 3px rgba(185, 28, 28, 0.35)); }
}
.xray-vis-group.is-broken-pulse .vis-box {
  animation: xrayPulseRed 1.1s ease-out 2;
}

/* Unified Context-Aware Export & Publish Modal */
.pbi-modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.52);
  backdrop-filter: blur(2px);
  z-index: 9950;
  display: none;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.pbi-modal-backdrop.is-open { display: flex; }
.pbi-modal, .pbi-modal-dialog {
  width: min(760px, calc(100vw - 32px));
  max-height: min(90vh, 720px);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--surface);
  color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.34);
  padding: 0;
}
.pbi-modal-hdr {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 12px 18px 10px 18px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}
.pbi-modal-hdr h3 { margin: 0; font-size: 16px; }
.pbi-modal-body {
  padding: 10px 18px 14px 18px;
  overflow-y: auto;
  flex: 1 1 auto;
}
.publish-scope-bar, .pbi-scope-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin: 0 0 10px 0;
  padding: 6px 10px;
  border-radius: 9px;
  background: var(--surface-alt);
  border: 1px solid var(--border);
}
.pbi-scope-seg {
  display: inline-flex;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 2px;
  gap: 2px;
}
.pbi-scope-seg button {
  border: none;
  background: transparent;
  color: var(--fg-muted);
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 650;
  cursor: pointer;
}
.pbi-scope-seg button.active {
  background: var(--accent);
  color: #fff;
}
.publish-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 11px;
}
@media screen and (max-width: 640px) {
  .publish-grid {
    grid-template-columns: 1fr;
  }
}
.publish-card {
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 11px 13px;
  background: var(--surface);
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.publish-card h4 {
  margin: 0;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.publish-card p {
  margin: 0;
  font-size: 11.5px;
  color: var(--fg-muted);
  line-height: 1.38;
}
.print-chap-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.print-chap-pills label {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 10.5px;
  padding: 2px 6px;
  border-radius: 5px;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  cursor: pointer;
}
.publish-card-actions, .publish-actions {
  margin-top: auto;
  padding-top: 4px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.publish-card-actions .publish-top-btn,
.publish-card-actions .lin-btn {
  padding: 5px 10px;
  font-size: 11.5px;
}
.publish-top-btn:disabled {
  opacity: 0.48;
  cursor: not-allowed;
  filter: none;
}
.sp-url-input {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface-alt);
  color: var(--fg);
  font-size: 12px;
}

.print-only-doc-banner,
.print-only-star-stack {
  display: none;
}

/* Clean A4 / Letter Print & PDF Stylesheet */
@media print {
  @page { margin: 12mm 10mm; }
  html, body {
    background: #ffffff !important;
    color: #0f172a !important;
    font-size: 11px !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .topbar, .doc-sidebar, .doc-topbar, .filter-bar, .xray-trigger-btn, .copy-btn,
  .measure-actions-row, .star-toolbar, .star-shell, .lin-toolbar, .lin-left, .lin-right,
  .pbi-modal-backdrop, .xray-backdrop, .xray-drawer, [data-print-hide="1"],
  .studio-only-link, [data-details-toggle], .view-toggle, .star-jump-link,
  #sec-schema .section-header .hint, #sec-dax .section-header .hint, #sec-lineage .section-header .hint,
  div:has(+ .pq-pipeline) > span:last-child,
  #boundReportsSearch, .principals-body > div:first-child,
  details.principals-details > summary span:last-child,
  details.table-blueprint:not([open]),
  table.data-table:has(#boundReportsBody) col:last-child,
  table.data-table:has(#boundReportsBody) th:last-child,
  table.data-table:has(#boundReportsBody) td:last-child {
    display: none !important;
  }
  table.data-table:has(#boundReportsBody) {
    table-layout: auto !important;
  }
  .lineage-app {
    display: block !important;
    height: auto !important;
    break-inside: avoid;
    page-break-inside: avoid;
  }
  .measure-grid {
    grid-template-columns: 1fr !important;
    gap: 10px !important;
  }
  .kpi-grid {
    grid-template-columns: repeat(6, minmax(0, 1fr)) !important;
    gap: 8px !important;
  }
  .kpi-card {
    padding: 9px 10px !important;
  }
  .kpi-card .val {
    font-size: 18px !important;
  }
  .section-header,
  h1, h2, h3, h4,
  details > summary {
    break-after: avoid !important;
    page-break-after: avoid !important;
  }
  details.section-accordion,
  details.table-blueprint {
    break-inside: avoid;
    page-break-inside: avoid;
  }
  .print-only-doc-banner {
    display: flex !important;
    justify-content: space-between;
    align-items: flex-end;
    gap: 16px;
    padding-bottom: 10px;
    margin-bottom: 16px;
    border-bottom: 2px solid #0b63ce;
  }
  .print-only-star-stack {
    display: block !important;
  }
  .print-star-diagram {
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    background: #ffffff;
    padding: 10px 12px 12px 12px;
    margin: 8px 0 14px 0;
    break-inside: avoid;
    page-break-inside: avoid;
  }
  .print-star-hdr {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11.5px;
    font-weight: 700;
    color: #0f172a;
    padding-bottom: 8px;
    margin-bottom: 8px;
    border-bottom: 1px solid #e2e8f0;
  }
  .print-star-hdr span:last-child {
    font-weight: 600;
    font-size: 10.5px;
    color: #475569;
  }
  #daxListContainer {
    display: none !important;
  }
  #daxCardsContainer {
    display: block !important;
  }
  .measure-card .code-block pre {
    max-height: none !important;
    overflow: visible !important;
  }
  .doc-shell {
    display: block !important;
  }
  .doc-main, .catalog-wrap {
    padding: 0 !important;
    max-width: 100% !important;
    overflow: visible !important;
  }
  .sticky-table-scroll, .table-scroll, .star-canvas-scroll, .star-viewport, .lin-canvas-scroll {
    max-height: none !important;
    overflow: visible !important;
    border-color: #cbd5e1 !important;
  }
  .sticky-table-scroll table.data-table thead th,
  table.data-table th {
    position: static !important;
    box-shadow: none !important;
  }
  table.data-table td,
  table.data-table td code,
  table.data-table td b,
  table.data-table td a {
    overflow-wrap: break-word !important;
    word-break: normal !important;
  }
  .measure-card, .finding, .kpi-card, .card {
    break-inside: avoid;
    page-break-inside: avoid;
    box-shadow: none !important;
  }
}

/* Measure Card Quick Actions */
.measure-actions-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-top: 7px;
  border-top: 1px dashed var(--border);
}

/* Modern HTML+SVG Interactive Star-Schema Explorer (Replaces Legacy Mermaid) */
.star-shell {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  box-shadow: var(--shadow);
  overflow: hidden;
  margin: 8px 0 14px 0;
}
.star-shell.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 9990;
  border-radius: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
}
body.star-fullscreen-lock { overflow: hidden; }
.star-toolbar {
  padding: 10px 14px;
  background: var(--surface-alt);
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.star-focus-pills {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.star-pill {
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--fg);
  border-radius: 999px;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.star-pill:hover {
  border-color: var(--accent);
  color: var(--accent);
}
.star-pill.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.star-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.star-search-input {
  padding: 4px 9px;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: var(--surface);
  color: var(--fg);
  font-size: 12px;
  width: 175px;
}
.star-viewport {
  position: relative;
  background: var(--bg);
  padding: 22px 24px;
  overflow: auto;
  max-height: 620px;
}
.star-shell.is-fullscreen .star-viewport {
  flex: 1 1 auto;
  max-height: none;
}
.star-stage {
  position: relative;
  max-width: 1120px;
  margin: 0 auto;
  transform-origin: top center;
}
svg.star-svg {
  position: absolute;
  top: 0;
  left: 0;
  pointer-events: none;
  z-index: 1;
}
.star-grid {
  position: relative;
  z-index: 2;
  display: grid;
  grid-template-columns: minmax(210px, 1fr) minmax(250px, 1.18fr) minmax(210px, 1fr);
  gap: 54px;
  align-items: center;
}
.star-grid.two-col {
  grid-template-columns: minmax(220px, 1fr) minmax(260px, 1.15fr);
  max-width: 780px;
  margin: 0 auto;
}
.star-grid.one-col {
  grid-template-columns: minmax(260px, 420px);
  justify-content: center;
}
.star-col {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}
.star-col-label {
  font-size: 10.5px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--fg-muted);
  margin-bottom: 2px;
}
.star-card {
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 10px;
  padding: 11px 13px;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.05);
  cursor: pointer;
  transition: border-color 0.14s, transform 0.12s, opacity 0.15s, box-shadow 0.14s;
  min-width: 0;
}
.star-card.is-fact {
  border-top: 3.5px solid var(--fact);
  padding: 14px 15px;
}
.star-card.is-dim {
  border-top: 3px solid var(--dim);
}
.star-card:hover {
  border-color: var(--accent);
  transform: translateY(-1px);
}
.star-card.is-active {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}
.star-card.is-muted {
  opacity: 0.25;
}
.star-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin-bottom: 5px;
}
.star-card-title {
  font-weight: 700;
  font-size: 13.5px;
  color: var(--fg);
  line-height: 1.28;
  overflow-wrap: anywhere;
  word-break: break-word;
}
.star-card.is-fact .star-card-title {
  font-size: 14.5px;
}
.star-card-keys {
  margin-top: 7px;
  padding-top: 6px;
  border-top: 1px dashed var(--border);
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 11px;
  color: var(--fg-muted);
}
.star-key-item {
  display: flex;
  align-items: center;
  gap: 5px;
  font-family: "Cascadia Code", Consolas, monospace;
  font-size: 11px;
  color: var(--fg);
}
.star-key-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  flex-shrink: 0;
}
.star-card-foot {
  margin-top: 8px;
  padding-top: 6px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--fg-muted);
}
.star-jump-link {
  font-size: 11px;
  font-weight: 600;
  color: var(--accent);
}

/* Collapsible DAX Display Folders & Bounded Code Scroll */
details.dax-folder-details {
  border-top: 1px solid var(--border);
  background: var(--surface);
}
details.dax-folder-details > summary {
  padding: 11px 18px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12.5px;
  font-weight: 700;
  color: var(--fg);
  background: var(--surface);
  list-style: none;
}
details.dax-folder-details > summary::-webkit-details-marker { display: none; }
details.dax-folder-details > summary:hover { background: var(--surface-alt); }
.dax-folder-body {
  padding: 8px 18px 16px 18px;
}
.measure-card .code-block pre {
  max-height: 240px;
  overflow-y: auto;
}

/* Logical Fixed Column Proportions & Bounded Sticky Scroll Tables */
.sticky-table-scroll {
  width: 100%;
  max-height: 380px;
  overflow-y: auto;
  overflow-x: hidden;
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
}
.sticky-table-scroll.compact-scroll {
  max-height: 300px;
}
.sticky-table-scroll table.data-table thead th {
  position: sticky;
  top: 0;
  z-index: 3;
  background: var(--surface-alt);
  box-shadow: 0 1px 0 var(--border);
}
table.fixed-table {
  table-layout: fixed;
  width: 100%;
}

/* Collapsible Workspace Principals Bar */
details.principals-details {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: var(--surface);
  overflow: hidden;
  margin-top: 14px;
  box-shadow: var(--shadow);
}
details.principals-details > summary {
  padding: 11px 16px;
  cursor: pointer;
  background: var(--surface-alt);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
  font-weight: 650;
  list-style: none;
}
details.principals-details > summary::-webkit-details-marker { display: none; }
.principals-body {
  padding: 12px 14px;
}

/* Action Button for Opening Report / Dataflow X-Ray Drawer */
.xray-trigger-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border-radius: 7px;
  border: 1px solid var(--accent);
  background: var(--accent-soft);
  color: var(--accent);
  font-size: 11.5px;
  font-weight: 650;
  cursor: pointer;
  white-space: nowrap;
}
.xray-trigger-btn:hover {
  background: var(--accent);
  color: #fff;
  text-decoration: none;
}
.dep-chip.xray-chip {
  cursor: pointer;
  border-color: var(--accent);
  color: var(--accent);
}
.dep-chip.xray-chip:hover {
  background: var(--accent-soft);
}

/* Upstream Dataflows Banner in Chapter 3 */
.upstream-df-banner {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 4px solid var(--dim);
  border-radius: 10px;
  padding: 13px 16px;
  margin-bottom: 16px;
  box-shadow: var(--shadow);
}
.upstream-df-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 8px;
}
.upstream-df-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface-alt);
  font-size: 12.5px;
}

/* In-Place Slide-Over X-Ray Drawer (Reports & Dataflows) */
.xray-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.46);
  z-index: 9500;
  display: none;
  opacity: 0;
  transition: opacity 0.16s ease;
}
.xray-backdrop.is-open {
  display: block;
  opacity: 1;
}
.xray-drawer {
  position: fixed;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(1090px, 95vw);
  background: var(--bg);
  border-left: 1px solid var(--border);
  box-shadow: -8px 0 32px rgba(15, 23, 42, 0.25);
  z-index: 9510;
  display: none;
  flex-direction: column;
  overflow: hidden;
}
.xray-drawer.is-open {
  display: flex;
}
body.xray-open-lock {
  overflow: hidden;
}
.xray-header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 14px 20px;
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.xray-header h3 {
  margin: 2px 0 4px 0;
  font-size: 17px;
  line-height: 1.25;
}
.xray-header-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}
.xray-body {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 18px 20px 32px 20px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.xray-explorer {
  display: grid;
  grid-template-columns: 205px minmax(0, 1fr) 280px;
  min-height: 410px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  box-shadow: var(--shadow);
}
.xray-pages-pane {
  border-right: 1px solid var(--border);
  background: var(--surface-alt);
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.xray-pages-hdr {
  padding: 9px 10px;
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--fg-muted);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.xray-pages-hdr input {
  width: 100%;
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--fg);
  font-size: 11.5px;
}
.xray-pages-list {
  flex: 1 1 auto;
  overflow-y: auto;
  max-height: 450px;
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.xray-page-btn {
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  color: var(--fg);
  padding: 7px 9px;
  border-radius: 7px;
  cursor: pointer;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.xray-page-btn:hover { background: var(--surface); border-color: var(--border); }
.xray-page-btn.active {
  background: var(--accent-soft);
  border-color: var(--accent);
  color: var(--accent);
  font-weight: 650;
}
.xray-canvas-pane {
  padding: 14px;
  background: var(--bg);
  display: flex;
  flex-direction: column;
  justify-content: center;
  min-width: 0;
}
.xray-canvas-caption {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 11.5px;
  color: var(--fg-muted);
  margin-bottom: 8px;
}
.xray-svg-wrap {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(15, 23, 42, 0.06);
}
.xray-svg-wrap svg {
  display: block;
  width: 100%;
  height: auto;
}
.xray-vis-group { cursor: pointer; }
.xray-vis-group:hover rect.vis-box { stroke-width: 2.5px; }
.xray-vis-group.is-selected rect.vis-box {
  stroke: var(--accent) !important;
  stroke-width: 3px !important;
}
.xray-inspector-pane {
  border-left: 1px solid var(--border);
  padding: 13px 14px;
  background: var(--surface);
  overflow-y: auto;
  max-height: 490px;
  font-size: 12px;
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.xray-inspector-pane h4 {
  margin: 0;
  font-size: 13.5px;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.xray-field-item {
  padding: 6px 8px;
  border-radius: 7px;
  border: 1px solid var(--border);
  background: var(--surface-alt);
  font-size: 11.5px;
  overflow-wrap: anywhere;
}
.xray-field-item.is-broken {
  border-color: var(--bad);
  background: var(--bad-bg);
}
.xray-explorer.single-page {
  grid-template-columns: minmax(0, 1fr) 295px;
}

@media screen and (max-width: 1100px) {
  .doc-topbar { margin: -20px -18px 18px -18px; padding: 10px 18px; }
  .star-grid, .star-grid.two-col { grid-template-columns: 1fr; gap: 16px; }
  svg.star-svg { display: none; }
  .xray-explorer, .xray-explorer.single-page { grid-template-columns: 1fr; }
  .xray-pages-pane { border-right: none; border-bottom: 1px solid var(--border); }
  .xray-inspector-pane { border-left: none; border-top: 1px solid var(--border); }
}
"""


STAR_SCHEMA_WIDGET_JS = r"""
(function () {
    function escHtml(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
    function midTrunc(s, maxLen) {
        s = String(s || "");
        if (s.length <= maxLen) return s;
        var keep = Math.max(10, maxLen - 3);
        var head = Math.floor(keep * 0.56);
        return s.slice(0, head) + "..." + s.slice(-(keep - head));
    }

    function initStarApp(shell) {
        var scriptId = shell.getAttribute("data-star-id");
        var dataEl = document.getElementById(scriptId);
        if (!dataEl) return;
        var model;
        try { model = JSON.parse(dataEl.textContent || "{}"); } catch (e) { return; }
        var tables = model.tables || [];
        var rels = model.relationships || [];
        var facts = model.facts || [];
        if (!tables.length) {
            shell.innerHTML = '<div style="padding:18px;color:var(--fg-muted)">No tables available in this model.</div>';
            return;
        }

        var tblByName = new Map();
        tables.forEach(function (t) { tblByName.set(t.name, t); });

        var defaultFocus = "all";
        if (facts.length > 0 && (facts.length > 1 || tables.length > 10)) {
            defaultFocus = "fact:" + facts[0];
        } else if (facts.length === 1 && rels.length > 0) {
            defaultFocus = "fact:" + facts[0];
        }

        var state = {
            mode: defaultFocus,
            activeTable: null,
            search: "",
            zoom: 1.0
        };

        shell.innerHTML =
            '<div class="star-toolbar">' +
              '<div class="star-focus-pills"></div>' +
              '<div class="star-actions">' +
                '<input type="search" class="star-search-input" placeholder="Filter tables..." style="display:none">' +
                '<button type="button" class="lin-btn" data-zoom="0.9">90%</button>' +
                '<button type="button" class="lin-btn active" data-zoom="1">100%</button>' +
                '<button type="button" class="lin-btn" data-zoom="1.12">112%</button>' +
                '<button type="button" class="lin-btn" data-star-fs="1">Fullscreen</button>' +
              '</div>' +
            '</div>' +
            '<div class="star-viewport">' +
              '<div class="star-stage">' +
                '<svg class="star-svg"></svg>' +
                '<div class="star-grid"></div>' +
              '</div>' +
            '</div>';

        var pillsEl = shell.querySelector(".star-focus-pills");
        var searchEl = shell.querySelector(".star-search-input");
        var viewportEl = shell.querySelector(".star-viewport");
        var stageEl = shell.querySelector(".star-stage");
        var svgEl = shell.querySelector("svg.star-svg");
        var gridEl = shell.querySelector(".star-grid");

        function dimNeighborsForFact(factName) {
            var set = new Set();
            rels.forEach(function (r) {
                if (r.from_table === factName) set.add(r.to_table);
                else if (r.to_table === factName) set.add(r.from_table);
            });
            return Array.from(set);
        }

        function renderToolbar() {
            var html = "";
            facts.forEach(function (fn) {
                var dimsCnt = dimNeighborsForFact(fn).length;
                var key = "fact:" + fn;
                html += '<button type="button" class="star-pill ' + (state.mode === key ? "active" : "") + '" data-mode="' + escHtml(key) + '" title="Focused Star around ' + escHtml(fn) + '">' +
                    '<span>Star: ' + escHtml(midTrunc(fn, 28)) + '</span>' +
                    '<span style="opacity:0.8;font-size:11px">(' + dimsCnt + ' dim' + (dimsCnt === 1 ? "" : "s") + ')</span>' +
                '</button>';
            });
            html += '<button type="button" class="star-pill ' + (state.mode === "all" ? "active" : "") + '" data-mode="all">All Tables (' + tables.length + ')</button>';
            pillsEl.innerHTML = html;
            searchEl.style.display = (state.mode === "all" && tables.length > 8) ? "" : "none";
        }

        function cardHtml(t, visibleRels) {
            var keyCols = [];
            visibleRels.forEach(function (r) {
                if (r.from_table === t.name && keyCols.indexOf(r.from_column) === -1) keyCols.push(r.from_column);
                if (r.to_table === t.name && keyCols.indexOf(r.to_column) === -1) keyCols.push(r.to_column);
            });
            var roleCls = t.role === "Fact" ? "is-fact" : (t.role === "Dimension" ? "is-dim" : "");
            var badgeCls = t.role === "Fact" ? "badge-fact" : (t.role === "Dimension" ? "badge-dim" : "");
            var keysMarkup = "";
            if (keyCols.length) {
                keysMarkup = '<div class="star-card-keys">' + keyCols.slice(0, 5).map(function (kc) {
                    return '<div class="star-key-item" title="Join column: ' + escHtml(kc) + '"><span class="star-key-dot"></span><span>' + escHtml(midTrunc(kc, 34)) + '</span></div>';
                }).join("") + (keyCols.length > 5 ? '<div style="font-size:10.5px">+' + (keyCols.length - 5) + ' more join key(s)</div>' : '') + '</div>';
            }
            return '<div class="star-card ' + roleCls + '" data-tname="' + escHtml(t.name) + '">' +
                '<div class="star-card-top">' +
                  '<span class="badge ' + badgeCls + '">' + escHtml(t.role) + '</span>' +
                  '<span style="font-size:11px;color:var(--fg-muted);font-family:Consolas,monospace">' + escHtml(t.mode) + '</span>' +
                '</div>' +
                '<div class="star-card-title" title="' + escHtml(t.name) + '">' + escHtml(midTrunc(t.name, 38)) + '</div>' +
                keysMarkup +
                '<div class="star-card-foot">' +
                  '<span>' + t.columns + ' cols' + (t.measures ? ' &bull; <b>' + t.measures + '</b> DAX' : '') + '</span>' +
                  '<a class="star-jump-link" href="#' + escHtml(t.anchor) + '" data-blueprint-jump="' + escHtml(t.anchor) + '">Blueprint &darr;</a>' +
                '</div>' +
            '</div>';
        }

        function drawLines(visibleRels) {
            var stageRect = stageEl.getBoundingClientRect();
            var z = state.zoom || 1.0;
            var w = Math.max(stageEl.scrollWidth, Math.round(stageRect.width / z));
            var h = Math.max(stageEl.scrollHeight, Math.round(stageRect.height / z));
            svgEl.setAttribute("width", String(w));
            svgEl.setAttribute("height", String(h));

            var cardMap = new Map();
            gridEl.querySelectorAll(".star-card[data-tname]").forEach(function (el) {
                cardMap.set(el.getAttribute("data-tname"), el);
            });

            var relatedTables = new Set();
            if (state.activeTable) {
                relatedTables.add(state.activeTable);
                visibleRels.forEach(function (r) {
                    if (r.from_table === state.activeTable) relatedTables.add(r.to_table);
                    if (r.to_table === state.activeTable) relatedTables.add(r.from_table);
                });
            }
            cardMap.forEach(function (el, name) {
                el.classList.toggle("is-active", state.activeTable === name);
                el.classList.toggle("is-muted", Boolean(state.activeTable && !relatedTables.has(name)));
            });

            var parts = [];
            visibleRels.forEach(function (r) {
                var aEl = cardMap.get(r.from_table);
                var bEl = cardMap.get(r.to_table);
                if (!aEl || !bEl) return;
                var a = aEl.getBoundingClientRect();
                var b = bEl.getBoundingClientRect();
                var aCx = (a.left + a.width / 2 - stageRect.left) / z;
                var bCx = (b.left + b.width / 2 - stageRect.left) / z;

                var x1, x2;
                if (aCx <= bCx) {
                    x1 = (a.right - stageRect.left) / z;
                    x2 = (b.left - stageRect.left) / z;
                } else {
                    x1 = (a.left - stageRect.left) / z;
                    x2 = (b.right - stageRect.left) / z;
                }
                var y1 = (a.top + a.height / 2 - stageRect.top) / z;
                var y2 = (b.top + b.height / 2 - stageRect.top) / z;
                var dx = Math.max(32, Math.abs(x2 - x1) * 0.45);
                var c1x = aCx <= bCx ? x1 + dx : x1 - dx;
                var c2x = aCx <= bCx ? x2 - dx : x2 + dx;

                var isHighlighted = !state.activeTable || r.from_table === state.activeTable || r.to_table === state.activeTable;
                var stroke = !isHighlighted ? "rgba(148,163,184,0.22)" : (r.bidirectional ? "#d97706" : "#0b63ce");
                var sw = isHighlighted && state.activeTable ? "2.4" : "1.7";
                var dash = r.active ? "" : ' stroke-dasharray="5,4"';
                parts.push('<path d="M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' C ' + c1x.toFixed(1) + ' ' + y1.toFixed(1) + ', ' + c2x.toFixed(1) + ' ' + y2.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + '" fill="none" stroke="' + stroke + '" stroke-width="' + sw + '"' + dash + '/>');

                if (isHighlighted) {
                    var mx = (x1 + x2) / 2;
                    var my = (y1 + y2) / 2;
                    var fCard = r.cardinality.indexOf("many") === 0 ? "*" : "1";
                    var tCard = r.cardinality.slice(-4) === "many" ? "*" : "1";
                    var arrowTxt = r.bidirectional ? "<->" : "->";
                    var lbl = (aCx <= bCx) ? (fCard + " " + arrowTxt + " " + tCard) : (tCard + " " + arrowTxt + " " + fCard);
                    var pillW = r.bidirectional ? 52 : 44;
                    parts.push(
                        '<g transform="translate(' + (mx - pillW / 2).toFixed(1) + ',' + (my - 10).toFixed(1) + ')">' +
                          '<title>' + escHtml(r.from_table + "." + r.from_column + " (" + fCard + ") = " + r.to_table + "." + r.to_column + " (" + tCard + ")") + '</title>' +
                          '<rect width="' + pillW + '" height="20" rx="10" fill="var(--surface)" stroke="' + stroke + '" stroke-width="1.2"/>' +
                          '<text x="' + (pillW / 2) + '" y="13.5" text-anchor="middle" font-size="10.5" font-weight="700" font-family="Consolas,monospace" fill="var(--fg)">' + escHtml(lbl) + '</text>' +
                        '</g>'
                    );
                }
            });
            svgEl.innerHTML = parts.join("");
        }

        function renderDiagram() {
            stageEl.style.transform = state.zoom === 1 ? "" : ("scale(" + state.zoom + ")");
            var visibleRels = rels.slice();
            gridEl.classList.remove("two-col", "one-col");

            if (state.mode.indexOf("fact:") === 0) {
                var fName = state.mode.slice(5);
                var factTbl = tblByName.get(fName);
                if (!factTbl) { state.mode = "all"; return renderDiagram(); }
                var neighborNames = dimNeighborsForFact(fName);
                visibleRels = rels.filter(function (r) { return r.from_table === fName || r.to_table === fName; });

                var neighborTbls = neighborNames.map(function (n) { return tblByName.get(n); }).filter(Boolean);
                if (!neighborTbls.length) {
                    gridEl.classList.add("one-col");
                    gridEl.innerHTML = '<div class="star-col"><div class="star-col-label">Fact Table</div>' + cardHtml(factTbl, visibleRels) + '</div>';
                } else if (neighborTbls.length === 1) {
                    gridEl.classList.add("two-col");
                    gridEl.innerHTML =
                        '<div class="star-col"><div class="star-col-label">Linked Dimension (1)</div>' + cardHtml(neighborTbls[0], visibleRels) + '</div>' +
                        '<div class="star-col"><div class="star-col-label">Central Fact Table</div>' + cardHtml(factTbl, visibleRels) + '</div>';
                } else {
                    var half = Math.ceil(neighborTbls.length / 2);
                    var leftDims = neighborTbls.slice(0, half);
                    var rightDims = neighborTbls.slice(half);
                    gridEl.innerHTML =
                        '<div class="star-col"><div class="star-col-label">Dimensions (' + leftDims.length + ')</div>' + leftDims.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>' +
                        '<div class="star-col"><div class="star-col-label">Central Fact Table</div>' + cardHtml(factTbl, visibleRels) + '</div>' +
                        '<div class="star-col"><div class="star-col-label">Dimensions (' + rightDims.length + ')</div>' + rightDims.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>';
                }
            } else {
                var q = state.search.toLowerCase().trim();
                var filtered = tables.filter(function (t) {
                    return !q || t.name.toLowerCase().indexOf(q) !== -1 || t.role.toLowerCase().indexOf(q) !== -1;
                });
                var fSet = new Set(filtered.map(function (t) { return t.name; }));
                visibleRels = rels.filter(function (r) { return fSet.has(r.from_table) && fSet.has(r.to_table); });

                var factCol = filtered.filter(function (t) { return t.role === "Fact"; });
                var dimCol = filtered.filter(function (t) { return t.role === "Dimension"; });
                var otherCol = filtered.filter(function (t) { return t.role !== "Fact" && t.role !== "Dimension"; });

                if (!factCol.length && !dimCol.length) {
                    gridEl.innerHTML = '<div class="star-col"><div class="star-col-label">Tables (' + otherCol.length + ')</div>' + otherCol.map(function (t) { return cardHtml(t, visibleRels); }).join("") + '</div>';
                    gridEl.classList.add("one-col");
                } else {
                    var halfD = Math.ceil(dimCol.length / 2);
                    var leftD = dimCol.slice(0, halfD);
                    var rightD = dimCol.slice(halfD).concat(otherCol);
                    if (!rightD.length) {
                        gridEl.classList.add("two-col");
                        gridEl.innerHTML =
                            '<div class="star-col"><div class="star-col-label">Dimensions (' + leftD.length + ')</div>' + leftD.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>' +
                            '<div class="star-col"><div class="star-col-label">Fact Tables (' + factCol.length + ')</div>' + factCol.map(function (f) { return cardHtml(f, visibleRels); }).join("") + '</div>';
                    } else {
                        gridEl.innerHTML =
                            '<div class="star-col"><div class="star-col-label">Dimensions (' + leftD.length + ')</div>' + leftD.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>' +
                            '<div class="star-col"><div class="star-col-label">Fact Tables (' + factCol.length + ')</div>' + factCol.map(function (f) { return cardHtml(f, visibleRels); }).join("") + '</div>' +
                            '<div class="star-col"><div class="star-col-label">Dimensions &amp; KPI Tables (' + rightD.length + ')</div>' + rightD.map(function (d) { return cardHtml(d, visibleRels); }).join("") + '</div>';
                    }
                }
            }

            window.requestAnimationFrame(function () { drawLines(visibleRels); });
            shell._currentVisibleRels = visibleRels;
        }

        pillsEl.addEventListener("click", function (e) {
            var b = e.target.closest("button[data-mode]");
            if (!b) return;
            state.mode = b.getAttribute("data-mode");
            state.activeTable = null;
            renderToolbar();
            renderDiagram();
        });

        searchEl.addEventListener("input", function () {
            state.search = searchEl.value || "";
            renderDiagram();
        });

        shell.querySelector(".star-actions").addEventListener("click", function (e) {
            var zb = e.target.closest("button[data-zoom]");
            if (zb) {
                state.zoom = parseFloat(zb.getAttribute("data-zoom") || "1");
                shell.querySelectorAll("button[data-zoom]").forEach(function (btn) { btn.classList.toggle("active", btn === zb); });
                renderDiagram();
                return;
            }
            var fs = e.target.closest("button[data-star-fs]");
            if (fs) {
                var isFs = shell.classList.toggle("is-fullscreen");
                document.body.classList.toggle("star-fullscreen-lock", isFs);
                fs.textContent = isFs ? "Exit Fullscreen" : "Fullscreen";
                setTimeout(function () { drawLines(shell._currentVisibleRels || []); }, 40);
            }
        });

        gridEl.addEventListener("click", function (e) {
            var jump = e.target.closest("[data-blueprint-jump]");
            if (jump) {
                var targetId = jump.getAttribute("data-blueprint-jump");
                var det = document.getElementById(targetId);
                if (det && det.tagName === "DETAILS") det.open = true;
                if (shell.classList.contains("is-fullscreen")) {
                    shell.classList.remove("is-fullscreen");
                    document.body.classList.remove("star-fullscreen-lock");
                }
                return;
            }
            var card = e.target.closest(".star-card[data-tname]");
            if (!card) return;
            var nm = card.getAttribute("data-tname");
            state.activeTable = (state.activeTable === nm) ? null : nm;
            drawLines(shell._currentVisibleRels || []);
        });

        viewportEl.addEventListener("scroll", function () { drawLines(shell._currentVisibleRels || []); });
        window.addEventListener("resize", function () { drawLines(shell._currentVisibleRels || []); });

        renderToolbar();
        renderDiagram();

        function buildSvgStarBlock(titleLeft, titleRight, leftTbls, centerTbls, rightTbls, blockRels) {
            var W = 920;
            var colW = 248;
            var xLeft = 12, xCenter = 336, xRight = 660;
            var topY = 26;
            var gapY = 14;

            function keysForTable(tName) {
                var ks = [];
                blockRels.forEach(function (r) {
                    if (r.from_table === tName && ks.indexOf(r.from_column) === -1) ks.push(r.from_column);
                    if (r.to_table === tName && ks.indexOf(r.to_column) === -1) ks.push(r.to_column);
                });
                return ks;
            }

            function measureCard(t) {
                var ks = keysForTable(t.name);
                var shown = ks.slice(0, 5);
                var extra = ks.length > 5 ? (ks.length - 5) : 0;
                var h = 68 + (shown.length ? (8 + shown.length * 16 + (extra ? 14 : 0)) : 0);
                return { t: t, keys: shown, extra: extra, h: h };
            }

            function layoutColumn(items, x) {
                var measured = items.map(measureCard);
                var total = measured.reduce(function (acc, m) { return acc + m.h; }, 0) + Math.max(0, measured.length - 1) * gapY;
                return { items: measured, totalH: total, x: x };
            }

            var cL = layoutColumn(leftTbls, xLeft);
            var cC = layoutColumn(centerTbls, xCenter);
            var cR = layoutColumn(rightTbls, xRight);
            var bodyH = Math.max(cL.totalH, cC.totalH, cR.totalH, 90);
            var H = topY + bodyH + 10;

            var posMap = new Map();
            function placeCol(col, label) {
                var out = [];
                if (!col.items.length) return "";
                var startY = topY + Math.round((bodyH - col.totalH) / 2);
                out.push('<text x="' + col.x + '" y="' + Math.max(14, startY - 8) + '" font-size="9.5" font-weight="700" fill="#64748b" font-family="Segoe UI,Arial,sans-serif" letter-spacing="0.5">' + escHtml(label.toUpperCase()) + '</text>');
                var curY = startY;
                col.items.forEach(function (m) {
                    var t = m.t;
                    var isFact = t.role === "Fact";
                    var accent = isFact ? "#0b63ce" : (t.role === "Dimension" ? "#0f766e" : "#475569");
                    var pillBg = isFact ? "#dbeafe" : (t.role === "Dimension" ? "#ccfbf1" : "#f1f5f9");
                    var pillFg = isFact ? "#1d4ed8" : (t.role === "Dimension" ? "#0f766e" : "#334155");
                    posMap.set(t.name, { x: col.x, y: curY, w: colW, h: m.h });

                    out.push('<g transform="translate(' + col.x + ',' + curY + ')">');
                    out.push('<rect width="' + colW + '" height="' + m.h + '" rx="8" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.2"/>');
                    out.push('<path d="M 2 7 Q 2 1 8 1 L ' + (colW - 8) + ' 1 Q ' + (colW - 2) + ' 1 ' + (colW - 2) + ' 7 L ' + (colW - 2) + ' 4 L 2 4 Z" fill="' + accent + '"/>');
                    out.push('<rect x="1" y="1" width="' + (colW - 2) + '" height="3.5" rx="2" fill="' + accent + '"/>');
                    // Role badge + storage mode
                    var roleTxt = String(t.role || "Table");
                    var rw = Math.max(42, roleTxt.length * 6.5 + 14);
                    out.push('<rect x="10" y="10" width="' + rw.toFixed(0) + '" height="17" rx="8.5" fill="' + pillBg + '"/>');
                    out.push('<text x="' + (10 + rw / 2).toFixed(1) + '" y="21.5" text-anchor="middle" font-size="9.5" font-weight="700" fill="' + pillFg + '" font-family="Segoe UI,Arial,sans-serif">' + escHtml(roleTxt) + '</text>');
                    out.push('<text x="' + (colW - 10) + '" y="21.5" text-anchor="end" font-size="9.5" fill="#64748b" font-family="Consolas,monospace">' + escHtml(t.mode || "") + '</text>');
                    // Table Name
                    out.push('<text x="10" y="41" font-size="12" font-weight="700" fill="#0f172a" font-family="Segoe UI,Arial,sans-serif">' + escHtml(midTrunc(t.name, 31)) + '</text>');
                    var ky = 50;
                    if (m.keys.length) {
                        out.push('<line x1="10" y1="' + ky + '" x2="' + (colW - 10) + '" y2="' + ky + '" stroke="#e2e8f0" stroke-dasharray="3,2"/>');
                        m.keys.forEach(function (k, ki) {
                            var ry = ky + 13 + ki * 16;
                            out.push('<circle cx="14" cy="' + (ry - 3.5) + '" r="2.5" fill="' + accent + '"/>');
                            out.push('<text x="21" y="' + ry + '" font-size="10" fill="#1e293b" font-family="Consolas,monospace">' + escHtml(midTrunc(k, 29)) + '</text>');
                        });
                        if (m.extra) {
                            out.push('<text x="21" y="' + (ky + 12 + m.keys.length * 16) + '" font-size="9.5" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">+' + m.extra + ' more join key(s)</text>');
                        }
                    }
                    // Footer
                    var fy = m.h - 8;
                    out.push('<line x1="10" y1="' + (m.h - 22) + '" x2="' + (colW - 10) + '" y2="' + (m.h - 22) + '" stroke="#f1f5f9"/>');
                    var footTxt = t.columns + " cols" + (t.measures ? ("  |  " + t.measures + " DAX") : "");
                    out.push('<text x="10" y="' + fy + '" font-size="9.5" fill="#64748b" font-family="Segoe UI,Arial,sans-serif">' + escHtml(footTxt) + '</text>');
                    out.push('</g>');
                    curY += m.h + gapY;
                });
                return out.join("");
            }

            var cardsSvg =
                placeCol(cL, leftTbls.length ? ("Dimensions (" + leftTbls.length + ")") : "") +
                placeCol(cC, centerTbls.length === 1 && centerTbls[0].role === "Fact" ? "Central Fact Table" : ("Tables (" + centerTbls.length + ")")) +
                placeCol(cR, rightTbls.length ? ("Dimensions (" + rightTbls.length + ")") : "");

            var linesSvg = [];
            blockRels.forEach(function (r) {
                var a = posMap.get(r.from_table);
                var b = posMap.get(r.to_table);
                if (!a || !b) return;
                var aCx = a.x + a.w / 2;
                var bCx = b.x + b.w / 2;
                var x1 = aCx <= bCx ? (a.x + a.w) : a.x;
                var x2 = aCx <= bCx ? b.x : (b.x + b.w);
                var y1 = a.y + a.h / 2;
                var y2 = b.y + b.h / 2;
                var dx = Math.max(28, Math.abs(x2 - x1) * 0.45);
                var c1x = aCx <= bCx ? x1 + dx : x1 - dx;
                var c2x = aCx <= bCx ? x2 - dx : x2 + dx;
                var stroke = r.bidirectional ? "#d97706" : "#0b63ce";
                var dash = r.active ? "" : ' stroke-dasharray="5,3"';
                linesSvg.push('<path d="M ' + x1.toFixed(1) + ' ' + y1.toFixed(1) + ' C ' + c1x.toFixed(1) + ' ' + y1.toFixed(1) + ', ' + c2x.toFixed(1) + ' ' + y2.toFixed(1) + ', ' + x2.toFixed(1) + ' ' + y2.toFixed(1) + '" fill="none" stroke="' + stroke + '" stroke-width="1.6"' + dash + '/>');

                var mx = (x1 + x2) / 2;
                var my = (y1 + y2) / 2;
                var fCard = r.cardinality.indexOf("many") === 0 ? "*" : "1";
                var tCard = r.cardinality.slice(-4) === "many" ? "*" : "1";
                var arrowTxt = r.bidirectional ? "<->" : "->";
                var lbl = (aCx <= bCx) ? (fCard + " " + arrowTxt + " " + tCard) : (tCard + " " + arrowTxt + " " + fCard);
                var pw = r.bidirectional ? 50 : 42;
                linesSvg.push(
                    '<g transform="translate(' + (mx - pw / 2).toFixed(1) + ',' + (my - 9).toFixed(1) + ')">' +
                      '<rect width="' + pw + '" height="18" rx="9" fill="#ffffff" stroke="' + stroke + '" stroke-width="1.1"/>' +
                      '<text x="' + (pw / 2) + '" y="12.5" text-anchor="middle" font-size="9.5" font-weight="700" font-family="Consolas,monospace" fill="#0f172a">' + escHtml(lbl) + '</text>' +
                    '</g>'
                );
            });

            return '<div class="print-star-diagram">' +
                '<div class="print-star-hdr"><span>' + escHtml(titleLeft) + '</span><span>' + escHtml(titleRight) + '</span></div>' +
                '<svg viewBox="0 0 ' + W + ' ' + H + '" style="width:100%;height:auto;display:block" role="img" aria-label="' + escHtml(titleLeft) + '">' +
                  linesSvg.join("") + cardsSvg +
                '</svg>' +
            '</div>';
        }

        try {
            var existingStack = shell.parentNode && shell.parentNode.querySelector(".print-only-star-stack");
            if (existingStack) existingStack.remove();
            var stackDiv = document.createElement("div");
            stackDiv.className = "print-only-star-stack";
            var blocks = [];
            if (facts.length > 0) {
                facts.forEach(function (fn, idx) {
                    var fTbl = tblByName.get(fn);
                    if (!fTbl) return;
                    var dNames = dimNeighborsForFact(fn);
                    var dTbls = dNames.map(function (n) { return tblByName.get(n); }).filter(Boolean);
                    var fRels = rels.filter(function (r) { return r.from_table === fn || r.to_table === fn; });
                    var prefix = facts.length > 1 ? ("Focused Star " + (idx + 1) + " of " + facts.length + ": " + fn) : ("Star Schema: " + fn);
                    if (!dTbls.length) {
                        blocks.push(buildSvgStarBlock(prefix, "Standalone Fact Table", [], [fTbl], [], []));
                    } else {
                        var chunkSize = 8;
                        var totalParts = Math.ceil(dTbls.length / chunkSize);
                        for (var p = 0; p < totalParts; p++) {
                            var slice = dTbls.slice(p * chunkSize, (p + 1) * chunkSize);
                            var sSet = new Set(slice.map(function (x) { return x.name; }));
                            sSet.add(fn);
                            var sRels = fRels.filter(function (r) { return sSet.has(r.from_table) && sSet.has(r.to_table); });
                            var half = Math.ceil(slice.length / 2);
                            var pTitle = totalParts > 1 ? (prefix + " (Part " + (p + 1) + "/" + totalParts + ")") : prefix;
                            blocks.push(buildSvgStarBlock(pTitle, slice.length + " connected table(s) | " + sRels.length + " relationship(s)", slice.slice(0, half), [fTbl], slice.slice(half), sRels));
                        }
                    }
                });
            } else {
                var cSize = 9;
                for (var i = 0; i < tables.length; i += cSize) {
                    var grp = tables.slice(i, i + cSize);
                    var gSet = new Set(grp.map(function (t) { return t.name; }));
                    var gRels = rels.filter(function (r) { return gSet.has(r.from_table) && gSet.has(r.to_table); });
                    blocks.push(buildSvgStarBlock("Data Model Tables", grp.length + " table(s)", grp.slice(0, 3), grp.slice(3, 6), grp.slice(6, 9), gRels));
                }
            }
            stackDiv.innerHTML = blocks.join("");
            shell.insertAdjacentElement("afterend", stackDiv);
        } catch (printErr) {}
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll(".star-shell[data-star-id]").forEach(initStarApp);
    });
})();
"""


XRAY_DRAWER_JS = r"""
(function () {
    function escHtml(s) {
        return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }
    function midTrunc(s, maxLen) {
        s = String(s || "");
        if (s.length <= maxLen) return s;
        var keep = Math.max(8, maxLen - 3);
        var head = Math.floor(keep * 0.56);
        return s.slice(0, head) + "..." + s.slice(-(keep - head));
    }

    var registry = {};
    var reportOrder = [];
    var activeItemId = null;
    var activePageIdx = 0;
    var activeVisIdx = 0;
    var activeBrokenCursor = -1;
    var pulseBrokenOnce = false;
    var showHiddenVisuals = false;
    var pageFilter = "";
    var backdropEl = null;
    var drawerEl = null;

    function visualTag(vtype) {
        var t = String(vtype || "").toLowerCase();
        if (t === "group") return "GRP";
        if (t.indexOf("slicer") !== -1) return "SLC";
        if (t.indexOf("card") !== -1) return "CARD";
        if (t.indexOf("kpi") !== -1) return "KPI";
        if (t.indexOf("matrix") !== -1 || t.indexOf("pivot") !== -1) return "MTX";
        if (t.indexOf("table") !== -1) return "TBL";
        if (t.indexOf("combo") !== -1) return "CMB";
        if (t.indexOf("line") !== -1 || t.indexOf("area") !== -1) return "LINE";
        if (t.indexOf("bar") !== -1 || t.indexOf("column") !== -1 || t.indexOf("waterfall") !== -1) return "BAR";
        if (t.indexOf("pie") !== -1 || t.indexOf("donut") !== -1) return "PIE";
        if (t.indexOf("map") !== -1) return "MAP";
        if (t.indexOf("gauge") !== -1) return "GAU";
        if (t.indexOf("text") !== -1) return "TXT";
        return "VIS";
    }

    function visualGlyphSvg(vtype, gx, gy, hasBroken) {
        var t = String(vtype || "").toLowerCase();
        var paths = "";
        if (t === "group") {
            paths = '<rect x="1.5" y="2" width="11" height="10" rx="1.5" stroke-dasharray="2.5,2"/>';
        } else if (t.indexOf("slicer") !== -1 || t.indexOf("filter") !== -1) {
            paths = '<path d="M2 2.5h10L8 7.2v3.8L6 12V7.2Z"/>';
        } else if (t.indexOf("card") !== -1 || t.indexOf("kpi") !== -1) {
            paths = '<rect x="1.5" y="2.5" width="11" height="9" rx="2"/><path d="M4.2 6.5h5.6M4.2 9h3.4"/>';
        } else if (t.indexOf("matrix") !== -1 || t.indexOf("pivot") !== -1 || t.indexOf("table") !== -1) {
            paths = '<rect x="1.5" y="2" width="11" height="10" rx="1.5"/><path d="M1.5 5.4h11M1.5 8.6h11M5.3 2v10"/>';
        } else if (t.indexOf("combo") !== -1) {
            paths = '<path d="M2.5 12V7.5M7 12V5M11.5 12V8.5"/><path d="M2 6.5L7 3.5L12 5.5"/>';
        } else if (t.indexOf("line") !== -1 || t.indexOf("area") !== -1) {
            paths = '<path d="M1.5 11L5 6.8L8.4 8.6L12.5 3.2"/><path d="M1.5 12.2h11"/>';
        } else if (t.indexOf("bar") !== -1) {
            paths = '<path d="M2 3.2h8.5M2 7h10.5M2 10.8h6"/>';
        } else if (t.indexOf("column") !== -1 || t.indexOf("waterfall") !== -1 || t.indexOf("ribbon") !== -1) {
            paths = '<rect x="2" y="6.5" width="2.4" height="5.5" rx="0.5"/><rect x="5.8" y="3" width="2.4" height="9" rx="0.5"/><rect x="9.6" y="5" width="2.4" height="7" rx="0.5"/>';
        } else if (t.indexOf("pie") !== -1 || t.indexOf("donut") !== -1) {
            paths = '<circle cx="7" cy="7" r="5"/><path d="M7 2v5h5"/>';
        } else if (t.indexOf("map") !== -1) {
            paths = '<path d="M7 12.5C7 12.5 11 8.8 11 5.7A4 4 0 1 0 3 5.7C3 8.8 7 12.5 7 12.5Z"/><circle cx="7" cy="5.7" r="1.3"/>';
        } else if (t.indexOf("gauge") !== -1) {
            paths = '<path d="M2 10.5A5 5 0 0 1 12 10.5"/><path d="M7 10.5L9.8 6.2"/>';
        } else if (t.indexOf("text") !== -1 || t.indexOf("button") !== -1) {
            paths = '<path d="M3 3.2h8M7 3.2v8.2"/>';
        } else {
            paths = '<rect x="2" y="2.5" width="10" height="9" rx="1.8"/><circle cx="5.2" cy="5.8" r="1"/><path d="M3.5 10l2.8-2.4 2.2 1.8 2-1.4"/>';
        }
        var pillFill = hasBroken ? "var(--bad-bg)" : "var(--accent-soft)";
        var pillStroke = hasBroken ? "var(--bad)" : "var(--accent)";
        return '<g class="xray-vis-glyph" transform="translate(' + gx + ',' + gy + ')">' +
            '<rect x="0" y="0" width="24" height="24" rx="5" fill="' + pillFill + '" stroke="' + pillStroke + '" stroke-width="1.2" opacity="0.92"/>' +
            '<g transform="translate(2.2,2.2) scale(1.4)" stroke="' + pillStroke + '" stroke-width="1.65" fill="none" stroke-linecap="round" stroke-linejoin="round">' + paths + '</g>' +
            '</g>';
    }

    function visualSchematicSvg(vtype, x, y, w, h, hasBroken) {
        var t = String(vtype || "").toLowerCase();
        if (t === "group" || w < 120 || h < 88) return "";
        var sx = x + 16;
        var sy = y + 66;
        var sw = Math.max(40, w - 32);
        var sh = Math.max(20, h - 78);
        if (sh < 22) return "";
        var col = hasBroken ? "var(--bad)" : "var(--accent)";
        var out = '<g class="xray-vis-schematic" opacity="0.28" pointer-events="none">';
        if (t.indexOf("column") !== -1 || t.indexOf("waterfall") !== -1 || t.indexOf("ribbon") !== -1 || t.indexOf("combo") !== -1) {
            var nBars = Math.min(7, Math.max(4, Math.floor(sw / 52)));
            var gap = 10;
            var bw = Math.max(10, Math.min(44, (sw - gap * (nBars - 1)) / nBars));
            var totalW = nBars * bw + (nBars - 1) * gap;
            var startX = sx + Math.max(0, (sw - totalW) / 2);
            var heights = [0.52, 0.86, 0.68, 0.95, 0.61, 0.78, 0.46];
            for (var i = 0; i < nBars; i++) {
                var bh = Math.max(8, sh * heights[i % heights.length]);
                out += '<rect x="' + (startX + i * (bw + gap)).toFixed(1) + '" y="' + (sy + sh - bh).toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + bh.toFixed(1) + '" rx="3" fill="' + col + '"/>';
            }
            out += '<line x1="' + sx + '" y1="' + (sy + sh) + '" x2="' + (sx + sw) + '" y2="' + (sy + sh) + '" stroke="' + col + '" stroke-width="2"/>';
        } else if (t.indexOf("bar") !== -1) {
            var nRows = Math.min(5, Math.max(3, Math.floor(sh / 26)));
            var rgap = 8;
            var rh = Math.max(8, Math.min(22, (sh - rgap * (nRows - 1)) / nRows));
            var widths = [0.88, 0.64, 0.94, 0.48, 0.73];
            for (var r = 0; r < nRows; r++) {
                out += '<rect x="' + sx + '" y="' + (sy + r * (rh + rgap)).toFixed(1) + '" width="' + (sw * widths[r % widths.length]).toFixed(1) + '" height="' + rh.toFixed(1) + '" rx="3" fill="' + col + '"/>';
            }
        } else if (t.indexOf("line") !== -1 || t.indexOf("area") !== -1) {
            var pts = [
                [sx, sy + sh * 0.78],
                [sx + sw * 0.25, sy + sh * 0.46],
                [sx + sw * 0.5, sy + sh * 0.60],
                [sx + sw * 0.75, sy + sh * 0.24],
                [sx + sw, sy + sh * 0.14]
            ];
            var poly = pts.map(function (p) { return p[0].toFixed(1) + "," + p[1].toFixed(1); }).join(" ");
            out += '<polyline points="' + poly + '" fill="none" stroke="' + col + '" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>';
            pts.forEach(function (p) {
                out += '<circle cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="4" fill="' + col + '"/>';
            });
            out += '<line x1="' + sx + '" y1="' + (sy + sh) + '" x2="' + (sx + sw) + '" y2="' + (sy + sh) + '" stroke="' + col + '" stroke-width="1.8"/>';
        } else if (t.indexOf("pie") !== -1 || t.indexOf("donut") !== -1) {
            var rad = Math.max(14, Math.min(sw, sh) * 0.42);
            var cx = sx + sw / 2;
            var cy = sy + sh / 2;
            out += '<circle cx="' + cx.toFixed(1) + '" cy="' + cy.toFixed(1) + '" r="' + rad.toFixed(1) + '" fill="none" stroke="' + col + '" stroke-width="' + Math.max(6, rad * 0.36).toFixed(1) + '"/>';
            out += '<line x1="' + cx.toFixed(1) + '" y1="' + (cy - rad).toFixed(1) + '" x2="' + cx.toFixed(1) + '" y2="' + cy.toFixed(1) + '" stroke="var(--surface)" stroke-width="3"/>';
        } else if (t.indexOf("matrix") !== -1 || t.indexOf("pivot") !== -1 || t.indexOf("table") !== -1) {
            var gh = Math.min(sh, 150);
            out += '<rect x="' + sx + '" y="' + sy + '" width="' + sw + '" height="' + gh + '" rx="4" fill="none" stroke="' + col + '" stroke-width="1.8"/>';
            out += '<rect x="' + sx + '" y="' + sy + '" width="' + sw + '" height="' + Math.min(22, gh * 0.26) + '" rx="3" fill="' + col + '"/>';
            for (var gr = 1; gr <= 3; gr++) {
                var gyLine = sy + (gh * gr) / 4;
                out += '<line x1="' + sx + '" y1="' + gyLine.toFixed(1) + '" x2="' + (sx + sw) + '" y2="' + gyLine.toFixed(1) + '" stroke="' + col + '" stroke-width="1.3"/>';
            }
            out += '<line x1="' + (sx + sw * 0.36).toFixed(1) + '" y1="' + sy + '" x2="' + (sx + sw * 0.36).toFixed(1) + '" y2="' + (sy + gh) + '" stroke="' + col + '" stroke-width="1.3"/>';
            out += '<line x1="' + (sx + sw * 0.68).toFixed(1) + '" y1="' + sy + '" x2="' + (sx + sw * 0.68).toFixed(1) + '" y2="' + (sy + gh) + '" stroke="' + col + '" stroke-width="1.3"/>';
        } else if (t.indexOf("card") !== -1 || t.indexOf("kpi") !== -1) {
            var kh = Math.min(20, sh * 0.42);
            out += '<rect x="' + sx + '" y="' + (sy + 4) + '" width="' + Math.min(130, sw * 0.55).toFixed(1) + '" height="' + kh.toFixed(1) + '" rx="4" fill="' + col + '"/>';
            if (sh >= 38) {
                out += '<rect x="' + sx + '" y="' + (sy + kh + 10).toFixed(1) + '" width="' + Math.min(84, sw * 0.35).toFixed(1) + '" height="8" rx="3" fill="' + col + '" opacity="0.65"/>';
            }
        } else if (t.indexOf("slicer") !== -1 || t.indexOf("filter") !== -1) {
            var dh = Math.min(26, sh * 0.65);
            out += '<rect x="' + sx + '" y="' + sy + '" width="' + sw + '" height="' + dh.toFixed(1) + '" rx="4" fill="none" stroke="' + col + '" stroke-width="1.8"/>';
            var ax = sx + sw - 16;
            var ay = sy + dh / 2 - 2;
            out += '<path d="M' + (ax - 5) + ' ' + ay + 'L' + ax + ' ' + (ay + 5) + 'L' + (ax + 5) + ' ' + ay + '" fill="none" stroke="' + col + '" stroke-width="2" stroke-linecap="round"/>';
        }
        out += '</g>';
        return out;
    }

    function getBrokenTargets(item) {
        if (!item || item.kind !== "report") return [];
        var out = [];
        (item.pages || []).forEach(function (pg, pIdx) {
            (pg.visuals || []).forEach(function (v) {
                var brCnt = (v.broken_refs || []).length;
                if (!brCnt && v.fields) {
                    brCnt = v.fields.filter(function (f) { return f.broken; }).length;
                }
                if (brCnt > 0) {
                    out.push({
                        pageIdx: pIdx,
                        visRef: v,
                        visId: v.id,
                        hidden: !!v.hidden,
                        fieldCount: brCnt,
                        pageName: pg.name || ("Page " + (pIdx + 1)),
                        visTitle: v.title || v.type_label || "Visual"
                    });
                }
            });
        });
        return out;
    }

    function jumpToBrokenIndex(idx) {
        var item = registry[activeItemId];
        var targets = getBrokenTargets(item);
        if (!targets.length) return;
        var normIdx = ((idx % targets.length) + targets.length) % targets.length;
        var t = targets[normIdx];
        activeBrokenCursor = normIdx;
        if (t.hidden) showHiddenVisuals = true;
        activePageIdx = t.pageIdx;
        var pg = (item.pages || [])[activePageIdx];
        var visList = getVisibleVisuals(pg);
        var foundVisIdx = visList.indexOf(t.visRef);
        if (foundVisIdx === -1 && t.visId) {
            foundVisIdx = visList.findIndex(function (cand) { return cand.id === t.visId; });
        }
        activeVisIdx = foundVisIdx >= 0 ? foundVisIdx : 0;
        pulseBrokenOnce = true;
        renderDrawerContent();
        setTimeout(function () {
            var activePgBtn = drawerEl && drawerEl.querySelector(".xray-page-btn.active");
            if (activePgBtn && activePgBtn.scrollIntoView) activePgBtn.scrollIntoView({ block: "nearest" });
            var brokenFld = drawerEl && drawerEl.querySelector(".xray-inspector-pane .xray-field-item.is-broken");
            if (brokenFld && brokenFld.scrollIntoView) brokenFld.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }, 35);
    }

    function ensureDrawerDom() {
        if (drawerEl) return;
        var dataTag = document.getElementById("xrayRegistryData");
        if (dataTag) {
            try {
                var parsed = JSON.parse(dataTag.textContent || "{}");
                registry = parsed.items || {};
                reportOrder = parsed.reportOrder || [];
            } catch (e) { registry = {}; }
        }
        backdropEl = document.createElement("div");
        backdropEl.className = "xray-backdrop";
        drawerEl = document.createElement("aside");
        drawerEl.className = "xray-drawer";
        drawerEl.setAttribute("role", "dialog");
        drawerEl.setAttribute("aria-modal", "true");
        document.body.appendChild(backdropEl);
        document.body.appendChild(drawerEl);

        backdropEl.addEventListener("click", closeDrawer);
        document.addEventListener("keydown", function (e) {
            if (e.key === "Escape" && drawerEl.classList.contains("is-open")) closeDrawer();
        });

        drawerEl.addEventListener("click", function (e) {
            if (e.target.closest("[data-xray-close]")) { closeDrawer(); return; }
            var brGo = e.target.closest("[data-xray-broken-go]");
            if (brGo) {
                var targetK = parseInt(brGo.getAttribute("data-xray-broken-go"), 10) || 0;
                jumpToBrokenIndex(targetK);
                return;
            }
            var brStep = e.target.closest("[data-xray-broken-step]");
            if (brStep) {
                var stepDir = parseInt(brStep.getAttribute("data-xray-broken-step"), 10) || 1;
                var nextK = activeBrokenCursor < 0 ? 0 : activeBrokenCursor + stepDir;
                jumpToBrokenIndex(nextK);
                return;
            }
            var hidBtn = e.target.closest("[data-xray-toggle-hidden]");
            if (hidBtn) {
                showHiddenVisuals = !showHiddenVisuals;
                activeVisIdx = 0;
                renderDrawerContent();
                return;
            }
            var navBtn = e.target.closest("[data-xray-step]");
            if (navBtn && reportOrder.length > 1) {
                var dir = parseInt(navBtn.getAttribute("data-xray-step"), 10);
                var idx = reportOrder.indexOf(activeItemId);
                if (idx !== -1) {
                    var nxt = (idx + dir + reportOrder.length) % reportOrder.length;
                    openDrawer(reportOrder[nxt]);
                }
                return;
            }
            var pgBtn = e.target.closest("[data-xray-page]");
            if (pgBtn) {
                activePageIdx = parseInt(pgBtn.getAttribute("data-xray-page"), 10) || 0;
                var curItem = registry[activeItemId];
                activeVisIdx = defaultVisIndex(curItem && curItem.pages ? curItem.pages[activePageIdx] : null);
                renderDrawerContent();
                return;
            }
            var visGrp = e.target.closest("[data-xray-vis]");
            if (visGrp) {
                activeVisIdx = parseInt(visGrp.getAttribute("data-xray-vis"), 10) || 0;
                renderDrawerContent();
                return;
            }
            var traceBtn = e.target.closest("[data-trace-e2e]");
            if (traceBtn) {
                var e2eId = traceBtn.getAttribute("data-trace-e2e");
                closeDrawer();
                if (window.PbiFocusLineage && e2eId) {
                    window.PbiFocusLineage(e2eId);
                }
                return;
            }
            var mJump = e.target.closest("[data-xray-jump-anchor]");
            if (mJump) {
                var href = mJump.getAttribute("data-xray-jump-anchor");
                closeDrawer();
                if (href && href.charAt(0) === "#") {
                    var cardsBtn = document.querySelector('[data-dax-view="cards"]');
                    if (cardsBtn && !cardsBtn.classList.contains("active")) cardsBtn.click();
                    var target = document.getElementById(href.slice(1));
                    if (target) {
                        var parentDet = target.closest("details.dax-folder-details");
                        if (parentDet) parentDet.open = true;
                        var hostDet = target.closest("details.dax-table-group");
                        if (hostDet) hostDet.open = true;
                        if (target.tagName === "DETAILS") target.open = true;
                        target.scrollIntoView({ behavior: "smooth", block: "center" });
                    }
                } else if (href) {
                    window.location.href = href;
                }
            }
        });

        drawerEl.addEventListener("input", function (e) {
            if (e.target.matches("[data-xray-page-search]")) {
                pageFilter = e.target.value || "";
                renderPagesListOnly();
            }
        });
    }

    function closeDrawer() {
        if (!drawerEl) return;
        backdropEl.classList.remove("is-open");
        drawerEl.classList.remove("is-open");
        document.body.classList.remove("xray-open-lock");
    }

    function defaultVisIndex(pg) {
        var list = getVisibleVisuals(pg);
        var brkIdx = list.findIndex(function (v) { return v.type !== "group" && ((v.broken_refs || []).length > 0 || (v.fields && v.fields.some(function (f) { return f.broken; }))); });
        if (brkIdx >= 0) return brkIdx;
        var idx = list.findIndex(function (v) { return v.type !== "group" && !v.decorative && v.fields && v.fields.length > 0; });
        if (idx >= 0) return idx;
        var nonGrp = list.findIndex(function (v) { return v.type !== "group"; });
        return nonGrp >= 0 ? nonGrp : 0;
    }

    function openDrawer(itemId, autoJumpBroken) {
        ensureDrawerDom();
        if (!registry[itemId]) return;
        activeItemId = itemId;
        activePageIdx = 0;
        var firstPg = (registry[itemId].pages || [])[0] || null;
        activeVisIdx = defaultVisIndex(firstPg);
        activeBrokenCursor = -1;
        pulseBrokenOnce = false;
        pageFilter = "";
        renderDrawerContent();
        backdropEl.classList.add("is-open");
        drawerEl.classList.add("is-open");
        document.body.classList.add("xray-open-lock");
        if (autoJumpBroken) {
            jumpToBrokenIndex(0);
        }
    }

    function getVisibleVisuals(pg) {
        var all = (pg && pg.visuals) ? pg.visuals.slice() : [];
        all.sort(function (a, b) {
            var ga = a.type === "group" ? 0 : 1;
            var gb = b.type === "group" ? 0 : 1;
            if (ga !== gb) return ga - gb;
            return (a.z || 0) - (b.z || 0);
        });
        if (showHiddenVisuals) return all;
        return all.filter(function (v) { return !v.hidden; });
    }

    function renderPagesListOnly() {
        var item = registry[activeItemId];
        if (!item || item.kind !== "report") return;
        var listWrap = drawerEl.querySelector(".xray-pages-list");
        if (!listWrap) return;
        var pages = item.pages || [];
        var q = pageFilter.toLowerCase().trim();
        listWrap.innerHTML = pages.map(function (pg, i) {
            if (q && pg.name.toLowerCase().indexOf(q) === -1) return "";
            var brokenCnt = (pg.visuals || []).reduce(function (acc, v) { return acc + ((v.broken_refs || []).length ? 1 : 0); }, 0);
            var cleanPgName = /^\d+[\.\)\s-]/.test(pg.name || "") ? pg.name : ((i + 1) + ". " + pg.name);
            return '<button type="button" class="xray-page-btn ' + (i === activePageIdx ? "active" : "") + '" data-xray-page="' + i + '">' +
                '<div style="display:flex;justify-content:space-between;align-items:center;gap:6px">' +
                  '<span title="' + escHtml(pg.name) + '" style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + escHtml(cleanPgName) + '</span>' +
                  (brokenCnt ? '<span class="badge badge-bad" style="font-size:10px;padding:1px 5px;flex-shrink:0">' + brokenCnt + '!</span>' : '') +
                '</div>' +
                '<span style="font-size:10.5px;color:var(--fg-muted)">' + (pg.visuals || []).length + ' visuals' + (pg.hidden ? ' &bull; Hidden' : '') + '</span>' +
            '</button>';
        }).join("");
    }

    function renderWireframeSvg(pg, visuals) {
        var pw = Math.max(320, pg.width || 1280);
        var ph = Math.max(200, pg.height || 720);
        var defs = [];
        var shapes = [];

        visuals.forEach(function (v, idx) {
            var x = Math.max(0, Math.min(pw - 24, v.x || 0));
            var y = Math.max(0, Math.min(ph - 20, v.y || 0));
            var w = Math.max(36, Math.min(pw - x, v.width || 160));
            var h = Math.max(26, Math.min(ph - y, v.height || 100));
            var clipId = "xrclip-" + activePageIdx + "-" + idx;
            defs.push('<clipPath id="' + clipId + '"><rect x="' + (x + 6) + '" y="' + (y + 4) + '" width="' + Math.max(10, w - 12) + '" height="' + Math.max(10, h - 8) + '"/></clipPath>');

            var isGroup = v.type === "group";
            var hasBroken = (v.broken_refs || []).length > 0 || !!(v.fields && v.fields.some(function (f) { return f.broken; }));
            var fill = hasBroken ? "var(--bad-bg)" : (isGroup ? "rgba(148,163,184,0.07)" : (v.decorative ? "var(--surface-alt)" : "var(--surface)"));
            var stroke = hasBroken ? "var(--bad)" : (idx === activeVisIdx ? "var(--accent)" : "var(--border)");
            var sw = (idx === activeVisIdx || hasBroken) ? "2.5" : "1.4";
            var dashAttr = (isGroup || v.hidden) ? ' stroke-dasharray="6,4"' : '';
            var opAttr = v.hidden ? ' opacity="0.68"' : '';
            var selCls = idx === activeVisIdx ? " is-selected" : "";
            if (idx === activeVisIdx && hasBroken && pulseBrokenOnce) {
                selCls += " is-broken-pulse";
            }

            if (isGroup) {
                shapes.push(
                    '<g class="xray-vis-group' + selCls + '" data-xray-vis="' + idx + '" data-vtype="group"' + opAttr + '>' +
                      '<title>' + escHtml("Visual Group: " + (v.title || "Group")) + '</title>' +
                      '<rect class="vis-box" x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="7" fill="rgba(148,163,184,0.04)" stroke="' + stroke + '" stroke-width="1.2" stroke-dasharray="6,4"/>' +
                    '</g>'
                );
                return;
            }

            var showLeadGlyph = (w >= 72 && h >= 32);
            var textX = showLeadGlyph ? (x + 38) : (x + 10);
            var rightPad = hasBroken ? 36 : 12;
            var maxChars = Math.max(5, Math.floor((w - (textX - x) - rightPad) / 6.9));
            var hdrLbl = midTrunc(v.title || v.type_label || "Visual", maxChars);
            var subLbl = midTrunc(v.type_label + (v.fields && v.fields.length ? " (" + v.fields.length + ")" : ""), maxChars + 3);
            var glyphMarkup = showLeadGlyph ? visualGlyphSvg(v.type, x + 8, y + 7, hasBroken) : "";
            var brokenBadgeSvg = (hasBroken && w >= 96 && h >= 32)
                ? ('<g transform="translate(' + (x + w - 30) + ',' + (y + 8) + ')" stroke="var(--bad)" stroke-width="2" fill="var(--bad-bg)" stroke-linecap="round" stroke-linejoin="round">' +
                   '<path d="M11 2.5L20 18.5H2Z"/><path d="M11 8.5v4.5M11 15.8h0.02"/></g>')
                : "";
            var schematicMarkup = visualSchematicSvg(v.type, x, y, w, h, hasBroken);

            var textLines = '<text x="' + textX + '" y="' + (y + 23) + '" font-size="13" font-weight="700" fill="var(--fg)">' + escHtml(hdrLbl) + '</text>';
            if (h >= 50) {
                textLines += '<text x="' + (x + 10) + '" y="' + (y + 44) + '" font-size="11.5" fill="var(--fg-muted)">' + escHtml(subLbl) + '</text>';
            }
            if (h >= 76 && v.fields && v.fields.length) {
                var f0 = v.fields[0];
                textLines += '<text x="' + (x + 10) + '" y="' + (y + 61) + '" font-size="11" font-family="Consolas,monospace" fill="var(--accent)">' + escHtml(midTrunc(f0.display || f0.property, maxChars + 4)) + '</text>';
            }

            shapes.push(
                '<g class="xray-vis-group' + selCls + '" data-xray-vis="' + idx + '" data-vtype="' + escHtml(v.type || "") + '"' + opAttr + '>' +
                  '<title>' + escHtml((v.title || v.type_label) + (v.hidden ? " [Hidden]" : "") + (hasBroken ? " [Broken Field Binding!]" : "") + " - Click to inspect bindings") + '</title>' +
                  '<rect class="vis-box" x="' + x + '" y="' + y + '" width="' + w + '" height="' + h + '" rx="6" fill="' + fill + '" stroke="' + stroke + '" stroke-width="' + sw + '"' + dashAttr + '/>' +
                  schematicMarkup +
                  glyphMarkup +
                  brokenBadgeSvg +
                  '<g clip-path="url(#' + clipId + ')">' + textLines + '</g>' +
                '</g>'
            );
        });
        pulseBrokenOnce = false;

        return '<svg viewBox="0 0 ' + pw + ' ' + ph + '" xmlns="http://www.w3.org/2000/svg">' +
            '<defs>' + defs.join("") + '</defs>' +
            '<rect width="' + pw + '" height="' + ph + '" fill="var(--surface-alt)" opacity="0.45"/>' +
            shapes.join("") +
        '</svg>';
    }

    function renderDrawerContent() {
        var item = registry[activeItemId];
        if (!item) return;

        if (item.kind === "dataflow") {
            var genLbl = String(item.generation || "Gen1").replace(/^Gen/i, "");
            var genBadgeTxt = genLbl === "2" ? "Fabric Dataflow Gen2" : "Power BI Dataflow Gen1";
            var entHtml = (item.entities || []).length
                ? (item.entities || []).map(function (ent) {
                    var rolePill = ent.role ? '<span class="badge">' + escHtml(ent.role) + '</span>' : '';
                    return '<div class="card" style="padding:14px 16px">' +
                        '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">' +
                          '<b>Query / Entity: <code>' + escHtml(ent.name) + '</code></b>' +
                          '<div class="model-meta">' + rolePill + '<span class="badge badge-dim">' + ent.columns_count + ' columns</span><span class="badge">' + ent.pq_steps + ' PQ steps</span></div>' +
                        '</div>' +
                        (ent.description ? '<div style="font-size:12px;color:var(--fg-muted);margin-top:4px">' + escHtml(ent.description) + '</div>' : '') +
                        (ent.pq_block_html || ent.pipeline_html || '') +
                        (!ent.pq_block_html ? (ent.m_html || '') : '') +
                    '</div>';
                }).join("")
                : '<div class="card"><p style="margin:0;color:var(--fg-muted)">Entity-level M definition was not returned by the workspace API (metadata-only Dataflow entry).</p></div>';

            drawerEl.innerHTML =
                '<div class="xray-header">' +
                  '<div>' +
                    '<div class="model-meta"><span class="badge badge-dim">' + escHtml(genBadgeTxt) + '</span><span class="badge">Workspace: ' + escHtml(item.workspace) + '</span></div>' +
                    '<h3>' + escHtml(item.name) + '</h3>' +
                    (item.description ? '<div style="font-size:12.5px;color:var(--fg-muted)">' + escHtml(item.description) + '</div>' : '') +
                  '</div>' +
                  '<div class="xray-header-controls">' +
                    '<button type="button" class="lin-btn" data-xray-close="1">Close (Esc)</button>' +
                  '</div>' +
                '</div>' +
                '<div class="xray-body">' + entHtml + '</div>';
            return;
        }

        // Report X-Ray Drawer
        var posIdx = reportOrder.indexOf(activeItemId);
        var navHtml = reportOrder.length > 1 && posIdx !== -1
            ? '<button type="button" class="lin-btn" data-xray-step="-1">&larr; Prev</button>' +
              '<span style="font-size:11.5px;color:var(--fg-muted);padding:0 4px">' + (posIdx + 1) + ' / ' + reportOrder.length + '</span>' +
              '<button type="button" class="lin-btn" data-xray-step="1">Next &rarr;</button>'
            : '';

        var pages = item.pages || [];
        var bodyInner = "";

        if (!pages.length) {
            bodyInner = '<div class="card"><p style="margin:0;color:var(--fg-muted)">Visual page layout is not stored yet for this report. Re-scan with Contributor+ workspace permissions or import the <code>.pbix</code> / <code>.pbip</code> file locally to inspect visual bindings.</p></div>';
        } else {
            var pg = pages[Math.min(activePageIdx, pages.length - 1)];
            var totalHidden = (pg.visuals || []).filter(function (v) { return v.hidden; }).length;
            var visuals = getVisibleVisuals(pg);
            var selVis = visuals[Math.min(activeVisIdx, Math.max(0, visuals.length - 1))] || null;

            var hidToggleHtml = totalHidden > 0
                ? '<button type="button" class="lin-btn ' + (showHiddenVisuals ? "active" : "") + '" data-xray-toggle-hidden="1">' +
                  (showHiddenVisuals ? "Hide" : "Show") + ' hidden (' + totalHidden + ')</button>'
                : '';

            var inspHtml = "";
            if (selVis) {
                var flds = selVis.fields || [];
                var fldsHtml = flds.length
                    ? flds.map(function (f) {
                        var statusPill = f.broken
                            ? '<span class="badge badge-bad">Missing in Model</span>'
                            : (f.is_report_measure ? '<span class="badge badge-warn">Report-Level DAX</span>' : '');
                        var btnRow = [];
                        if (!f.broken && f.anchor_href) {
                            btnRow.push('<button type="button" class="lin-btn" style="padding:2px 7px;font-size:10.5px" data-xray-jump-anchor="' + escHtml(f.anchor_href) + '">View in Model &rarr;</button>');
                        }
                        if (!f.broken && f.e2e_id) {
                            btnRow.push('<button type="button" class="lin-btn" style="padding:2px 7px;font-size:10.5px;border-color:var(--accent);color:var(--accent)" data-trace-e2e="' + escHtml(f.e2e_id) + '">Trace to SQL &rarr;</button>');
                        }
                        var btnsMarkup = btnRow.length ? '<div style="display:flex;gap:5px;flex-wrap:wrap;margin-top:5px">' + btnRow.join("") + '</div>' : '';
                        return '<div class="xray-field-item ' + (f.broken ? "is-broken" : "") + '">' +
                            '<div style="display:flex;justify-content:space-between;align-items:center;gap:4px">' +
                              '<span style="font-weight:650;color:var(--fg-muted);font-size:10.5px">' + escHtml(f.role) + '</span>' +
                              statusPill +
                            '</div>' +
                            '<div style="font-family:Consolas,monospace;font-weight:650;margin-top:2px">' + escHtml(f.ref) + '</div>' +
                            btnsMarkup +
                        '</div>';
                    }).join("")
                    : '<div style="color:var(--fg-muted)">Decorative / container visual (0 bound data fields).</div>';

                var selMarkup = "";
                if (selVis.selection) {
                    var selTxt = Array.isArray(selVis.selection)
                        ? selVis.selection.join(", ")
                        : (selVis.selection.condition || (Array.isArray(selVis.selection.values) ? selVis.selection.values.join(", ") : String(selVis.selection)));
                    if (selTxt) {
                        selMarkup = '<div style="margin-top:4px"><b style="font-size:11px;color:var(--fg-muted)">Slicer Selection:</b>' +
                            '<div style="margin-top:3px"><span class="dep-chip" style="border-color:var(--accent)">' + escHtml(selTxt) + '</span></div></div>';
                    }
                }
                var txtMarkup = "";
                if (selVis.text) {
                    txtMarkup = '<div style="margin-top:4px;font-size:11.5px;color:var(--fg-muted)"><b>Text:</b> ' + escHtml(midTrunc(selVis.text, 140)) + '</div>';
                }

                var seenFlt = {};
                var allFilters = [];
                (selVis.filters || []).forEach(function (x) { var lbl = "Visual: " + x; if (!seenFlt[lbl]) { seenFlt[lbl] = 1; allFilters.push(lbl); } });
                (pg.filters || []).forEach(function (x) { var lbl = "Page: " + x; if (!seenFlt[lbl]) { seenFlt[lbl] = 1; allFilters.push(lbl); } });
                (item.report_filters || []).forEach(function (x) { var lbl = "Report: " + x; if (!seenFlt[lbl]) { seenFlt[lbl] = 1; allFilters.push(lbl); } });
                var filtHtml = allFilters.length
                    ? '<div style="margin-top:6px"><b style="font-size:11px;color:var(--fg-muted)">Active Visual, Page &amp; Report Filters:</b><div class="lin-list" style="margin-top:4px">' +
                      allFilters.map(function (flt) { return '<span class="dep-chip">' + escHtml(flt) + '</span>'; }).join("") + '</div></div>'
                    : '';

                inspHtml =
                    '<div style="display:flex;gap:5px;flex-wrap:wrap">' +
                      '<span class="badge badge-accent">' + escHtml(selVis.type_label) + '</span>' +
                      (selVis.hidden ? '<span class="badge badge-warn">Hidden</span>' : '') +
                      (selVis.parent ? '<span class="badge">In group</span>' : '') +
                    '</div>' +
                    '<h4>' + escHtml(selVis.title || selVis.type_label) + '</h4>' +
                    '<div style="font-size:11px;color:var(--fg-muted)">Position: ' + selVis.x + ', ' + selVis.y + ' (' + selVis.width + '&times;' + selVis.height + 'px)</div>' +
                    txtMarkup +
                    selMarkup +
                    '<div style="font-weight:650;font-size:11.5px;margin-top:4px">Bound Fields (' + flds.length + ')</div>' +
                    fldsHtml +
                    filtHtml;
            } else {
                inspHtml = '<div style="color:var(--fg-muted)">No visible visuals on this page.</div>';
            }

            var singlePage = pages.length <= 1;
            bodyInner =
                '<div class="xray-explorer' + (singlePage ? ' single-page' : '') + '">' +
                  (singlePage ? '' : (
                    '<div class="xray-pages-pane">' +
                      '<div class="xray-pages-hdr">' +
                        '<span>Report Pages (' + pages.length + ')</span>' +
                        (pages.length > 5 ? '<input type="search" data-xray-page-search="1" value="' + escHtml(pageFilter) + '" placeholder="Filter ' + pages.length + ' pages...">' : '') +
                      '</div>' +
                      '<div class="xray-pages-list"></div>' +
                    '</div>'
                  )) +
                  '<div class="xray-canvas-pane">' +
                    '<div class="xray-canvas-caption">' +
                      '<span>Page: <b>' + escHtml(pg.name) + '</b> (' + Math.round(pg.width || 1280) + '&times;' + Math.round(pg.height || 720) + 'px)</span>' +
                      '<div style="display:flex;align-items:center;gap:8px">' +
                        '<span>Click any visual to inspect bindings</span>' +
                        hidToggleHtml +
                      '</div>' +
                    '</div>' +
                    '<div class="xray-svg-wrap">' + renderWireframeSvg(pg, visuals) + '</div>' +
                  '</div>' +
                  '<div class="xray-inspector-pane">' + inspHtml + '</div>' +
                '</div>';
        }

        if (item.report_measures_html) {
            bodyInner += item.report_measures_html;
        }

        var crossBadge = item.cross_workspace ? '<span class="badge badge-accent">Cross-Workspace Thin Report</span>' : '<span class="badge badge-ok">Same-Workspace Report</span>';
        var brokenTargets = getBrokenTargets(item);
        var brokenBadge = "";
        var brokenStripHtml = "";
        if (brokenTargets.length > 0 || item.broken_count) {
            if (brokenTargets.length > 0) {
                if (activeBrokenCursor >= 0 && activeBrokenCursor < brokenTargets.length) {
                    brokenBadge =
                        '<span class="xray-broken-stepper">' +
                        '<button type="button" data-xray-broken-step="-1" title="Previous broken visual">&larr;</button>' +
                        '<span data-xray-broken-go="' + activeBrokenCursor + '" style="cursor:pointer">! Broken visual ' + (activeBrokenCursor + 1) + ' / ' + brokenTargets.length + ' (' + (item.broken_count || brokenTargets.length) + ' fields)</span>' +
                        '<button type="button" data-xray-broken-step="1" title="Next broken visual">&rarr;</button>' +
                        '</span>';
                } else {
                    brokenBadge =
                        '<button type="button" class="badge-bad-btn" data-xray-broken-go="0" title="Click to jump straight to broken visual #1">' +
                        '! ' + (item.broken_count || brokenTargets.length) + ' broken field(s) in ' + brokenTargets.length + ' visual(s) &bull; Jump &rarr;' +
                        '</button>';
                }
                brokenStripHtml =
                    '<div style="padding:8px 14px;border-radius:9px;background:var(--bad-bg);border:1px solid rgba(185,28,28,0.28);display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12px">' +
                    '<b style="color:var(--bad)">Broken Field Bindings (' + brokenTargets.length + '):</b>' +
                    brokenTargets.slice(0, 12).map(function (bt, bi) {
                        var activeStyle = bi === activeBrokenCursor ? 'border-color:var(--bad);background:var(--surface);font-weight:700' : '';
                        return '<button type="button" class="dep-chip" style="cursor:pointer;' + activeStyle + '" data-xray-broken-go="' + bi + '">' +
                            escHtml(midTrunc(bt.pageName, 18) + ' > ' + midTrunc(bt.visTitle, 22)) + ' (' + bt.fieldCount + ')' +
                            '</button>';
                    }).join("") +
                    '</div>';
            } else {
                brokenBadge = '<span class="badge badge-bad">' + item.broken_count + ' broken field(s)</span>';
            }
        }
        var shadowBadge = item.report_measures_count ? '<span class="badge badge-warn">' + item.report_measures_count + ' report-level DAX</span>' : '';

        drawerEl.innerHTML =
            '<div class="xray-header">' +
              '<div>' +
                '<div class="model-meta">' + crossBadge + '<span class="badge">Workspace: ' + escHtml(item.workspace) + '</span>' + brokenBadge + shadowBadge + '</div>' +
                '<h3>' + escHtml(item.name) + '</h3>' +
                '<div style="font-size:12px;color:var(--fg-muted)">Bound Semantic Model: <b>' + escHtml(item.model_name) + '</b> (' + escHtml(item.model_workspace) + ')</div>' +
              '</div>' +
              '<div class="xray-header-controls">' +
                navHtml +
                '<button type="button" class="lin-btn" data-xray-close="1">Close (Esc)</button>' +
              '</div>' +
            '</div>' +
            '<div class="xray-body">' + brokenStripHtml + bodyInner + '</div>';

        renderPagesListOnly();
    }

    // Interactive Clickable Power Query M Step-Through (UTF-16 range highlighter)
    document.addEventListener("click", function (e) {
        var stepBtn = e.target.closest("button.pq-step-btn[data-pq-step]");
        if (stepBtn) {
            var wrap = stepBtn.closest(".pq-interactive-wrap");
            if (!wrap) return;
            var metaEl = wrap.querySelector("script.pq-meta-json");
            var inspEl = wrap.querySelector(".pq-step-inspector");
            var preEl = wrap.querySelector("pre.pq-m-pre");
            var detEl = wrap.querySelector("details.m-script-toggle");
            if (!metaEl || !inspEl || !preEl) return;

            var meta;
            try { meta = JSON.parse(metaEl.textContent || "{}"); } catch (err) { return; }
            var idx = parseInt(stepBtn.getAttribute("data-pq-step"), 10);
            var steps = meta.steps || [];
            var raw = String(meta.raw || "");
            if (isNaN(idx) || !steps[idx]) return;

            if (!preEl._origHtml) preEl._origHtml = preEl.innerHTML;

            var wasActive = stepBtn.classList.contains("is-active");
            wrap.querySelectorAll("button.pq-step-btn").forEach(function (b) { b.classList.remove("is-active"); });
            if (wasActive) {
                inspEl.style.display = "none";
                preEl.innerHTML = preEl._origHtml;
                return;
            }

            stepBtn.classList.add("is-active");
            var st = steps[idx];
            var detChips = (st.details || []).map(function (d) {
                return '<span class="dep-chip" style="background:var(--surface)">' + escHtml(d) + '</span>';
            }).join(" ");
            inspEl.innerHTML =
                '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">' +
                  '<span><b>Step ' + st.index + ': ' + escHtml(st.name) + '</b> <span class="badge">' + escHtml(st.op) + '</span></span>' +
                  '<span style="font-size:11px;color:var(--fg-muted)">Click step again to clear highlight</span>' +
                '</div>' +
                '<div style="margin-top:4px">' + escHtml(st.summary || st.op) + '</div>' +
                (detChips ? '<div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:6px">' + detChips + '</div>' : '');
            inspEl.style.display = "";

            if (typeof st.start === "number" && typeof st.end === "number" && st.end > st.start && st.end <= raw.length) {
                preEl.innerHTML =
                    escHtml(raw.slice(0, st.start)) +
                    '<mark class="pq-span-mark">' + escHtml(raw.slice(st.start, st.end)) + '</mark>' +
                    escHtml(raw.slice(st.end));
                if (detEl) detEl.open = true;
                var mk = preEl.querySelector("mark.pq-span-mark");
                if (mk && mk.scrollIntoView) {
                    setTimeout(function () { mk.scrollIntoView({ behavior: "smooth", block: "nearest" }); }, 30);
                }
            }
            return;
        }

        var btn = e.target.closest("[data-open-xray]");
        if (!btn) return;
        e.preventDefault();
        openDrawer(btn.getAttribute("data-open-xray"), btn.hasAttribute("data-xray-jump-broken"));
    });

    window.PbiOpenXray = openDrawer;
})();
"""


def build_star_schema_json(analysis: dict) -> tuple[dict, set[str], set[str]]:
    """Build structured Star-Schema JSON + classify Fact & Dimension tables deterministically."""
    rels = analysis["parsed"]["relationships"]
    many_side: set[str] = set()
    one_side: set[str] = set()
    for r in rels:
        if r["cardinality"].startswith("many"):
            many_side.add(r["from_table"])
        else:
            one_side.add(r["from_table"])
        if r["cardinality"].endswith("many"):
            many_side.add(r["to_table"])
        else:
            one_side.add(r["to_table"])

    facts = {t for t in many_side if t not in one_side} or set(many_side)
    dims = (many_side | one_side) - facts

    rel_degree: dict[str, int] = collections.Counter()
    for r in rels:
        rel_degree[r["from_table"]] += 1
        rel_degree[r["to_table"]] += 1

    ordered_facts = sorted(
        facts,
        key=lambda fn: (
            -rel_degree[fn],
            -next((ts["measures_count"] for ts in analysis["table_summaries"] if ts["name"] == fn), 0),
            fn.lower(),
        ),
    )

    visible_tables = [
        ts
        for ts in analysis["table_summaries"]
        if not ts["hidden"] or ts["name"] in (many_side | one_side)
    ]

    table_nodes = []
    for ts in visible_tables:
        role = "Fact" if ts["name"] in facts else ("Dimension" if ts["name"] in dims else "KPI / Table")
        table_nodes.append(
            {
                "name": ts["name"],
                "role": role,
                "mode": ts["mode"],
                "columns": ts["columns_count"],
                "measures": ts["measures_count"],
                "anchor": "t-" + slugify(ts["name"]),
            }
        )

    payload = {
        "facts": ordered_facts,
        "tables": table_nodes,
        "relationships": rels,
    }
    return payload, facts, dims


def build_report_xray_entry(
    rep: dict,
    model_name: str,
    model_slug: str,
    model_workspace: str,
    highlight_dax_fn: Callable[[str], str],
    from_index: bool = False,
    anonymous: bool = False,
    e2e_graph: dict | None = None,
    dataset_id: str = "",
) -> dict[str, Any]:
    """Build serializable Report Inspector entry for the Slide-Over X-Ray Drawer (privacy-safe in anonymous mode)."""
    from .e2e_lineage import resolve_field_node_id

    raw_layout = rep.get("layout") or {}
    layout = redact_report_layout_literals(raw_layout) if anonymous else raw_layout
    rep_id = str(rep.get("id") or "")
    ds_id = dataset_id or str(rep.get("dataset_id") or "")

    pages_out: list[dict[str, Any]] = []
    for pg in layout.get("pages") or []:
        vis_out = []
        for v in pg.get("visuals") or []:
            flds_out = []
            for f in v.get("fields") or []:
                m_key = f.get("measure_key") or ""
                anchor_href = ""
                if m_key and "[" in m_key and not f.get("is_report_measure"):
                    t_part, m_part = m_key.split("[", 1)
                    m_anchor = "#m-" + slugify(f"{t_part}-{m_part.rstrip(']')}")
                    anchor_href = f"models/{model_slug}.html{m_anchor}" if from_index and model_slug else m_anchor
                elif f.get("entity") and not f.get("broken"):
                    t_anchor = "#t-" + slugify(str(f.get("entity") or ""))
                    anchor_href = f"models/{model_slug}.html{t_anchor}" if from_index and model_slug else t_anchor

                e2e_id = ""
                if e2e_graph and ds_id and not f.get("broken"):
                    e2e_id = resolve_field_node_id(e2e_graph, ds_id, f, report_id=rep_id) or ""

                flds_out.append(
                    {
                        "role": f.get("role", "Values"),
                        "display": f.get("display", ""),
                        "property": f.get("property", ""),
                        "ref": f.get("ref", ""),
                        "broken": bool(f.get("broken")),
                        "is_report_measure": bool(f.get("is_report_measure")),
                        "anchor_href": anchor_href,
                        "e2e_id": e2e_id,
                    }
                )
            v_entry: dict[str, Any] = {
                "title": v.get("title", ""),
                "type": v.get("type", "visual"),
                "type_label": v.get("type_label", "Visual"),
                "decorative": bool(v.get("decorative")),
                "hidden": bool(v.get("hidden")),
                "parent": v.get("parent", ""),
                "z": v.get("z", 0),
                "x": v.get("x", 0),
                "y": v.get("y", 0),
                "width": v.get("width", 160),
                "height": v.get("height", 100),
                "fields": flds_out,
                "filters": v.get("filters") or [],
                "broken_refs": v.get("broken_refs") or [],
            }
            if v.get("selection"):
                v_entry["selection"] = v["selection"]
            if v.get("text"):
                v_entry["text"] = v["text"]
            vis_out.append(v_entry)
        pages_out.append(
            {
                "name": pg.get("name", "Page"),
                "hidden": bool(pg.get("hidden")),
                "width": pg.get("width", 1280),
                "height": pg.get("height", 720),
                "filters": pg.get("filters") or [],
                "visuals": vis_out,
            }
        )

    rep_measures = layout.get("report_measures") or []
    rep_m_html = ""
    if rep_measures:
        cards = []
        for rm in rep_measures:
            desc_html = f'<div class="measure-desc">{esc(rm.get("description", ""))}</div>' if rm.get("description") else ""
            fmt_b = f'<span class="badge">Format: {esc(rm["format"])}</span>' if rm.get("format") else ""
            rm_e2e_btn = ""
            if e2e_graph and ds_id:
                cand_id = f"m:{ds_id}:rpt:{rep_id}:{rm.get('table', '')}[{rm.get('name', '')}]"
                if cand_id in (e2e_graph.get("nodes") or {}):
                    rm_e2e_btn = (
                        f'<div class="measure-actions-row">'
                        f'<button type="button" class="lin-btn" data-trace-e2e="{esc(cand_id)}">Trace to SQL &rarr;</button>'
                        f'<button type="button" class="lin-btn" data-export-measure-md="{esc(cand_id)}">Measure Doc (.md)</button>'
                        f"</div>"
                    )
            cards.append(
                f'<div class="measure-card">'
                f'<div class="measure-head"><span class="measure-name">{esc(rm.get("name", ""))}</span>'
                f'<div class="model-meta"><span class="badge badge-warn">Report-Level DAX ({esc(rm.get("table", ""))})</span>{fmt_b}</div></div>'
                f"{desc_html}"
                f'<div class="code-block"><button type="button" class="copy-btn" data-copy="1">Copy DAX</button><pre>{highlight_dax_fn(rm.get("expr", ""))}</pre></div>'
                f"{rm_e2e_btn}"
                f"</div>"
            )
        rep_m_html = (
            f'<div class="card">'
            f'<h4 style="margin:0 0 6px 0;font-size:14.5px">Report-Level DAX Extensions ({len(rep_measures)})</h4>'
            f'<p style="margin:0 0 12px 0;font-size:12px;color:var(--fg-muted)">Defined locally inside this thin report rather than in the shared semantic model:</p>'
            f'<div class="measure-grid">{"".join(cards)}</div>'
            f"</div>"
        )

    cross = bool(rep.get("workspace") and model_workspace and rep.get("workspace") != model_workspace)
    broken_cnt = len(rep.get("broken_refs") or [])
    return {
        "kind": "report",
        "id": rep_id,
        "name": rep.get("name", "Report"),
        "workspace": rep.get("workspace", ""),
        "model_name": model_name,
        "model_workspace": model_workspace,
        "cross_workspace": cross,
        "broken_count": broken_cnt,
        "report_measures_count": len(rep_measures),
        "report_filters": layout.get("report_filters") or [],
        "pages": pages_out,
        "report_measures_html": rep_m_html,
    }


def build_dataflow_xray_entry(
    df: dict,
    highlight_m_fn: Callable[[str], str],
    extract_m_steps_fn: Callable[[str], list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    """Build serializable Dataflow Gen1 / Gen2 Inspector entry with Native SQL & Clickable M Step-Through."""
    raw_items = df.get("queries") or df.get("entities") or []
    ents_out = []
    for ent in raw_items:
        m_code = ent.get("m_code") or ""
        df_refs = ent.get("dataflow_refs") or []
        linked_ref = df_refs[0] if (not m_code.strip() and df_refs) else None
        pq_block_html = render_pq_partition_block(
            m_code=m_code,
            highlight_m_fn=highlight_m_fn,
            script_title=f"View Dataflow Power Query M Script - {ent.get('name', '')}",
            native_sql_items=ent.get("native_sql"),
            step_items=ent.get("step_items"),
            destination=ent.get("destination"),
            linked_df_ref=linked_ref,
        )
        cols_cnt = ent.get("columns_count") if ent.get("columns_count") is not None else len(ent.get("columns") or [])
        steps_cnt = ent.get("pq_steps") if ent.get("pq_steps") is not None else ent.get("step_count", 0)
        ents_out.append(
            {
                "name": ent.get("name", ""),
                "role": ent.get("role", ""),
                "description": ent.get("description", ""),
                "columns_count": cols_cnt,
                "pq_steps": steps_cnt,
                "pq_block_html": pq_block_html,
            }
        )
    gen_val = str(df.get("generation", 1))
    return {
        "kind": "dataflow",
        "id": df.get("id", ""),
        "name": df.get("name", "Dataflow"),
        "description": df.get("description", ""),
        "generation": gen_val,
        "workspace": df.get("workspace", ""),
        "entities": ents_out,
    }


def render_upstream_dataflows_banner(analysis: dict) -> str:
    """Render clean Upstream Dataflows section in Chapter 3 ONLY when the model consumes Dataflows."""
    dfs = analysis.get("upstream_dataflows") or []
    if not dfs:
        return ""
    cards = []
    for df in dfs:
        feeds = ", ".join(df.get("feeds_tables") or [])
        ent_cnt = len(df.get("entities") or df.get("queries") or [])
        gen_raw = str(df.get("generation", 1)).replace("Gen", "")
        gen_badge_lbl = "Fabric Dataflow Gen2" if gen_raw == "2" else "Dataflow Gen1"
        layer_num = int(df.get("layer") or 1)
        layer_badge = (
            f' <span class="badge badge-accent">Layer L{layer_num} Upstream</span>'
            if layer_num > 1
            else ' <span class="badge">Layer L1 Direct</span>'
        )
        cards.append(
            f'<div class="upstream-df-card">'
            f"<div>"
            f'<b>{esc(df.get("name", "Dataflow"))}</b> '
            f'<span class="badge badge-dim">{esc(gen_badge_lbl)}</span>{layer_badge}'
            f'<div style="font-size:11.5px;color:var(--fg-muted)">Workspace: {esc(df.get("workspace", ""))}'
            + (f" &bull; {ent_cnt} entities" if ent_cnt else "")
            + (f" &bull; Feeds: <b>{esc(feeds)}</b>" if feeds else "")
            + "</div></div>"
            f'<button type="button" class="xray-trigger-btn" data-open-xray="df:{esc(df["id"])}">Inspect Dataflow &rarr;</button>'
            f"</div>"
        )
    return (
        f'<div class="upstream-df-banner">'
        f'<div style="font-size:13px;font-weight:700">Upstream Power BI Dataflows Feeding This Model ({len(dfs)})</div>'
        f'<div class="upstream-df-list">{"".join(cards)}</div>'
        f"</div>"
    )


def render_model_reports_html(analysis: dict) -> str:
    """Render overflow-safe, searchable Bound Reports table with Slide-Over Inspector triggers."""
    reps = analysis.get("reports") or []
    if not reps:
        return '<div class="card" style="margin-top:14px"><p style="margin:0;color:var(--fg-muted)">No Power BI reports are bound to this semantic model in the scanned workspaces.</p></div>'

    sorted_reps = sorted(
        reps,
        key=lambda r: (
            -len(r.get("broken_refs") or []),
            -(r.get("report_measures_count") or 0),
            -(r.get("pages_count") or 0),
            (r.get("name") or "").lower(),
        ),
    )

    rows = []
    for r in sorted_reps:
        rid = r.get("id", "")
        cross = r.get("workspace") and r.get("workspace") != analysis["workspace"]
        cross_badge = ' <span class="badge badge-accent">Cross-Workspace</span>' if cross else ""
        pg_cnt = r.get("pages_count") or 0
        vis_cnt = r.get("visuals_count") or 0
        rm_cnt = r.get("report_measures_count") or 0
        br_cnt = len(r.get("broken_refs") or [])

        struct_txt = f"{pg_cnt} page(s) &bull; {vis_cnt} visual(s)" if pg_cnt else f"<code>{esc(r.get('report_type', 'PowerBIReport'))}</code>"
        dax_txt = f'<span class="badge badge-warn">{rm_cnt} local DAX</span>' if rm_cnt else '<span style="color:var(--fg-muted)">0 (Clean)</span>'
        status_pill = (
            f'<button type="button" class="badge-bad-btn" data-open-xray="rep:{esc(rid)}" data-xray-jump-broken="0" title="Jump directly to broken visual field">{br_cnt} broken ref(s) &rarr;</button> '
            if br_cnt
            else ""
        )
        btn = f'<button type="button" class="xray-trigger-btn" data-open-xray="rep:{esc(rid)}">Inspect Layout &rarr;</button>'
        search_txt = f"{r.get('name', '')} {r.get('workspace', '')} {'broken' if br_cnt else ''} {'local dax' if rm_cnt else ''}".lower()

        rows.append(
            f'<tr data-report-row="{esc(search_txt)}">'
            f'<td><b>{esc(middle_truncate(r.get("name", ""), 52))}</b>{cross_badge}</td>'
            f"<td>{esc(r.get('workspace', ''))}</td>"
            f"<td>{struct_txt}</td>"
            f"<td>{dax_txt}</td>"
            f'<td style="text-align:right">{status_pill}{btn}</td>'
            f"</tr>"
        )

    if len(sorted_reps) > 6:
        filter_hdr = (
            f'<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin:14px 0 8px 0;flex-wrap:wrap">'
            f'<b>Downstream Thin &amp; Bound Reports ({len(sorted_reps)})</b>'
            f'<input type="search" id="boundReportsSearch" placeholder="Filter {len(sorted_reps)} bound reports..." '
            f'style="padding:6px 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface);color:var(--fg);font-size:12px;width:240px">'
            f"</div>"
        )
    else:
        filter_hdr = f'<div style="margin:14px 0 8px 0"><b>Downstream Bound Reports ({len(sorted_reps)})</b></div>'

    wrap_cls = "sticky-table-scroll" if len(sorted_reps) > 8 else "table-scroll"
    return (
        f"{filter_hdr}"
        f'<div class="{wrap_cls}">'
        f'<table class="data-table fixed-table">'
        f'<colgroup><col style="width:32%"><col style="width:20%"><col style="width:17%"><col style="width:13%"><col style="width:18%"></colgroup>'
        f"<thead><tr><th>Downstream Report</th><th>Report Workspace</th><th>Pages &amp; Visuals</th><th>Report DAX</th><th style='text-align:right'>Inspector</th></tr></thead>"
        f'<tbody id="boundReportsBody">{"".join(rows)}</tbody></table></div>'
    )


def render_model_access_html(analysis: dict, anonymous: bool = False) -> str:
    """Render logically proportioned, collapsible, searchable Workspace & Dataset Access table."""
    if anonymous:
        return ""
    raw_users = analysis.get("permissions") or analysis.get("workspace_users") or []
    if not raw_users:
        return ""

    has_rls = bool(analysis["parsed"]["roles"])
    role_counts: dict[str, int] = collections.Counter()
    rows = []
    for u in raw_users:
        disp = u.get("displayName") or u.get("identifier") or u.get("emailAddress") or "-"
        ptype = u.get("principalType") or "User"
        right = u.get("groupUserAccessRight") or u.get("datasetUserAccessRight") or "Read"
        role_counts[right] += 1

        is_elevated = any(k in right.lower() for k in ("admin", "member", "contributor", "write"))
        if has_rls and is_elevated:
            note = '<span class="badge badge-warn">Edit role (Bypasses RLS)</span>'
        elif has_rls:
            note = '<span class="badge badge-ok">RLS Enforced</span>'
        else:
            note = '<span style="color:var(--fg-muted);font-size:11.5px">Standard access</span>'

        rows.append(
            f'<tr data-principal-row="{esc((disp + " " + ptype + " " + right).lower())}" data-principal-role="{esc(right.lower())}">'
            f'<td title="{esc(disp)}"><b>{esc(middle_truncate(disp, 46))}</b></td>'
            f"<td><code>{esc(ptype)}</code></td>"
            f"<td><span class='badge badge-accent'>{esc(right)}</span></td>"
            f"<td>{note}</td>"
            f"</tr>"
        )

    role_summary = " &bull; ".join(f"{cnt} {esc(r)}" for r, cnt in sorted(role_counts.items(), key=lambda kv: -kv[1]))
    table_markup = (
        f'<div class="{"sticky-table-scroll compact-scroll" if len(rows) > 10 else "table-scroll"}">'
        f'<table class="data-table fixed-table">'
        f'<colgroup><col style="width:42%"><col style="width:16%"><col style="width:20%"><col style="width:22%"></colgroup>'
        f"<thead><tr><th>Principal / Account</th><th>Type</th><th>Access Role</th><th>RLS &amp; Governance Note</th></tr></thead>"
        f'<tbody id="principalsTableBody">{"".join(rows)}</tbody></table></div>'
    )

    if len(rows) <= 10:
        return f'<div style="margin-top:16px"><div style="margin-bottom:8px"><b>Workspace &amp; Model Access ({len(rows)})</b> <span style="font-size:12px;color:var(--fg-muted)">({role_summary})</span></div>{table_markup}</div>'

    return (
        f'<details class="principals-details">'
        f"<summary>"
        f'<span>Workspace &amp; Model Access Principals (<b>{len(rows)}</b>)</span>'
        f'<span style="font-size:12px;color:var(--fg-muted);font-weight:500">{role_summary} &bull; <span style="color:var(--accent);font-weight:650">Click to expand &amp; search</span></span>'
        f"</summary>"
        f'<div class="principals-body">'
        f'<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap">'
        f'<input type="search" id="principalsSearchInput" placeholder="Search {len(rows)} users, groups, or roles..." '
        f'style="padding:6px 10px;border:1px solid var(--border);border-radius:8px;background:var(--surface-alt);color:var(--fg);font-size:12px;width:280px">'
        f'<span style="font-size:11.5px;color:var(--fg-muted)">Showing bounded scrollable list (max 300px)</span>'
        f"</div>"
        f"{table_markup}"
        f"</div></details>"
    )
