"""
Diagnostics report: verifies a scan end to end.

1. Power BI service interaction (from the HTTP trace): every call grouped by endpoint, status codes,
   errors, retries / throttling, slowest calls, and a metadata-only check (flags anything that is not on
   the known structure/schema endpoint allowlist, e.g. executeQueries or table rows).
2. Browser events (from the trace): JS errors, failed fetches, console errors, explorer activity.
3. Catalog & lineage health: model / dataflow definition status, dataflow parsing results, unresolved
   dataflow references, tables without a resolved origin, graph statistics.
"""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

from .store import CatalogStore

# Endpoints the tool is expected to call. Anything else is reported.
METADATA_ENDPOINTS = [
    r"api\.powerbi\.com/v1\.0/myorg/capacities$",
    r"api\.powerbi\.com/v1\.0/myorg/groups$",
    r"api\.powerbi\.com/v1\.0/myorg/groups/\{id\}/(reports|datasets|dataflows|users)$",
    r"api\.powerbi\.com/v1\.0/myorg/groups/\{id\}/datasets/upstreamDataflows$",
    r"api\.powerbi\.com/v1\.0/myorg/groups/\{id\}/datasets/\{id\}/(datasources|refreshes|users)$",
    r"api\.powerbi\.com/v1\.0/myorg/groups/\{id\}/dataflows/\{id\}$",
    r"api\.powerbi\.com/v1\.0/myorg/groups/\{id\}/datasets/\{id\}$",
    r"api\.fabric\.microsoft\.com/v1/workspaces/\{id\}/reports/\{id\}/getDefinition$",
    r"api\.powerbi\.com/v1\.0/myorg/groups/\{id\}/dataflows/\{id\}/(upstreamDataflows|datasources)$",
    r"api\.fabric\.microsoft\.com/v1/workspaces/\{id\}/semanticModels/\{id\}/getDefinition$",
    r"api\.fabric\.microsoft\.com/v1/operations/\{id\}(/result)?$",
    # getDefinition long-running operation: Location header points at the tenant's cluster host
    r"^[\w.-]+\.analysis\.windows\.net/v1/operations/\{id\}(/result)?$",
]
DATA_ENDPOINT_HINTS = re.compile(r"(?i)executeQueries|/rows\b|/tables/|/exportTo|/export\b|/storage|/transactions|/files?\b")


def _read_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def http_section(trace_dir: Path) -> list[str]:
    calls = _read_jsonl(trace_dir / "http_trace.jsonl")
    out = ["## 1. Power BI service interaction", ""]
    if not calls:
        return out + ["_No HTTP trace recorded (start with `--trace` / `PBI_TRACE_DIR`)._", ""]
    allow = [re.compile(p) for p in METADATA_ENDPOINTS]
    by_ep: dict[str, list[dict]] = collections.defaultdict(list)
    for c in calls:
        by_ep[f"{c['method']} {c['endpoint']}"].append(c)
    total_bytes = sum(c.get("bytes", 0) for c in calls)
    out += [f"- **{len(calls)}** HTTP attempts, **{total_bytes / 1024:.0f} KB** received, first {calls[0]['ts']}, last {calls[-1]['ts']}", ""]
    out += ["| Endpoint | Calls | Status codes | Avg ms | KB |", "|---|---|---|---|---|"]
    for ep, cs in sorted(by_ep.items(), key=lambda kv: -len(kv[1])):
        st = collections.Counter(str(c.get("status") or "ERR") for c in cs)
        out.append(f"| `{ep}` | {len(cs)} | {', '.join(f'{k}x{v}' for k, v in sorted(st.items()))} | "
                   f"{sum(c['ms'] for c in cs) / len(cs):.0f} | {sum(c.get('bytes', 0) for c in cs) / 1024:.0f} |")

    # Metadata-only verification
    out += ["", "### Metadata-only check", ""]
    unexpected = [c for c in calls if not any(a.search(c["endpoint"]) for a in allow)]
    data_like = [c for c in calls if DATA_ENDPOINT_HINTS.search(c["endpoint"])]
    non_get = [c for c in calls if c["method"] != "GET" and "/getdefinition" not in c["url"].lower()]
    if not unexpected and not data_like and not non_get:
        out.append("PASS - every call hit a known structure/schema endpoint; no data-query, row, export or write endpoint was called.")
    for label, items in (("Calls outside the metadata allowlist", unexpected), ("Calls that look like data access", data_like), ("Non-GET calls (other than getDefinition)", non_get)):
        if items:
            out.append(f"**FAIL - {label}:**")
            out += [f"- `{c['method']} {c['url']}` -> {c.get('status')}" for c in items[:30]]

    errs = [c for c in calls if c.get("error") or (c.get("status") or 0) >= 400]
    out += ["", f"### Errors ({len(errs)})", ""]
    for c in errs[:60]:
        snippet = ""
        if c.get("body_file") and (trace_dir / c["body_file"]).exists():
            snippet = (trace_dir / c["body_file"]).read_text(encoding="utf-8", errors="replace").replace("\n", " ")[:220]
        out.append(f"- {c['ts']} `{c['method']} {c['url']}` -> **{c.get('status') or c.get('error')}** {snippet}")
    throttled = [c for c in calls if c.get("status") == 429]
    if throttled:
        out.append(f"- Throttled (429) {len(throttled)} time(s).")
    out += ["", "### Slowest calls", ""]
    for c in sorted(calls, key=lambda c: -c["ms"])[:8]:
        out.append(f"- {c['ms']:.0f} ms `{c['method']} {c['endpoint']}` ({c.get('bytes', 0) / 1024:.0f} KB)")
    return out + [""]


def browser_section(trace_dir: Path) -> list[str]:
    evs = _read_jsonl(trace_dir / "browser.jsonl")
    out = ["## 2. Browser events", ""]
    if not evs:
        return out + ["_No browser events recorded yet._", ""]
    kinds = collections.Counter(e.get("type", "?") for e in evs)
    out.append("- " + ", ".join(f"{k}: {v}" for k, v in kinds.most_common()))
    problems = [e for e in evs if e.get("type") in ("js-error", "promise-rejection", "console-error", "fetch-failed", "fetch-error", "resource-error", "explorer-missing-node")]
    out += ["", f"### Problems ({len(problems)})", ""]
    for e in problems[-40:]:
        out.append(f"- {e.get('ts')} **{e.get('type')}** on `{e.get('page', '')}`: {e.get('message') or e.get('url') or e.get('src') or e.get('id', '')}"
                   + (f" ({e.get('source')}:{e.get('line')})" if e.get("source") else ""))
    sel = [e for e in evs if e.get("type") == "explorer-select"]
    if sel:
        out += ["", "### Recent explorer selections", ""]
        for e in sel[-10:]:
            out.append(f"- `{e.get('id')}` ({e.get('dir')}): {e.get('nodes')} nodes, {e.get('edges')} edges, "
                       f"unscanned dataflow queries: {e.get('unscanned_dataflow_queries')}, render {e.get('render_ms')} ms")
    return out + [""]


def catalog_section(store: CatalogStore) -> list[str]:
    from .dataflows import DATAFLOW_CONNECTOR_RE, parse_dataflow_definition
    from .e2e_lineage import build_e2e_graph

    state = store.load()
    out = ["## 3. Catalog & lineage health", ""]
    models = state.get("models", {})
    dfs = state.get("dataflows", {})
    m_status = collections.Counter("ok" if m.get("definition_status") == "ok" else ("pending" if m.get("definition_status") == "pending" else "error") for m in models.values())
    d_status = collections.Counter("ok" if d.get("definition_status") == "ok" else ("pending" if d.get("definition_status", "pending") == "pending" else "error") for d in dfs.values())
    out += [
        f"- Workspaces: **{len(state.get('workspaces', {}))}**, reports: **{len(state.get('reports', {}))}**",
        f"- Semantic models: **{len(models)}** ({dict(m_status)})",
        f"- Dataflows: **{len(dfs)}** ({dict(d_status)}), discovered via cross-workspace reference: {sum(1 for d in dfs.values() if d.get('discovered_via') == 'reference')}",
        f"- Dataset -> dataflow REST links: {sum(len(v) for v in (state.get('dataset_dataflow_links') or {}).values())}",
        "",
    ]
    bad_models = [m for m in models.values() if m.get("definition_status") not in ("ok", "pending")]
    bad_dfs = [d for d in dfs.values() if d.get("definition_status", "pending") not in ("ok", "pending")]
    if bad_models or bad_dfs:
        out += ["### Definitions that could not be read", ""]
        out += [f"- Model `{m.get('workspace')} / {m.get('name')}`: {m.get('definition_status')}" for m in bad_models[:40]]
        out += [f"- Dataflow `{d.get('workspace')} / {d.get('name')}`: {d.get('definition_status')}" for d in bad_dfs[:40]]
        out.append("")

    out += ["### Dataflow parsing", "", "| Dataflow | Queries | Roles | Sources | Linked refs | Issues |", "|---|---|---|---|---|---|"]
    for df_id, meta in sorted(dfs.items(), key=lambda kv: kv[1].get("name", "")):
        definition = store.read_dataflow_definition(df_id)
        if not definition:
            continue
        doc = (definition.get("pbi:mashup") or {}).get("document") or ""
        try:
            pdf = parse_dataflow_definition(meta, definition)
        except Exception as exc:  # pragma: no cover - surfaced in report
            out.append(f"| {meta.get('name')} | - | - | - | - | PARSER CRASH: {exc} |")
            continue
        roles = collections.Counter(q["role"] for q in pdf["queries"])
        issues = []
        shared_cnt = len(re.findall(r"(?m)^\s*shared\s", doc))
        from_doc = sum(1 for q in pdf["queries"] if q["code"] or q["kind"] == "parameter")
        if shared_cnt and shared_cnt != from_doc:
            issues.append(f"{shared_cnt} `shared` members in document but {from_doc} parsed")
        if not doc:
            issues.append("no M document in export")
        orphans = [q["name"] for q in pdf["queries"] if q["kind"] == "query" and not q["sources"] and not q["depends_on"] and not q["dataflow_refs"] and not q["endpoints"]]
        if orphans:
            issues.append(f"no detected source/dependency: {', '.join(orphans[:5])}")
        unresolved = [r for q in pdf["queries"] for r in q["dataflow_refs"] if "{param:" in r["dataflow_id"] or not r["dataflow_id"]]
        if unresolved:
            issues.append(f"{len(unresolved)} dataflow ref(s) with unresolved id")
        out.append(
            f"| {meta.get('name')} | {len(pdf['queries'])} | {', '.join(f'{k} {v}' for k, v in roles.items())} | "
            f"{sum(len(q['sources']) for q in pdf['queries'])} | {sum(len(q['dataflow_refs']) for q in pdf['queries'])} | {'; '.join(issues) or 'OK'} |"
        )

    graph = build_e2e_graph(store)
    nodes = graph["nodes"]
    kinds = collections.Counter(n["kind"] for n in nodes.values())
    out += ["", "### Lineage graph", "", f"- Nodes: {dict(kinds)}; edges: {len(graph['edges'])}"]
    external = [n for n in nodes.values() if n.get("external")]
    if external:
        out.append(f"- **{len(external)} dataflow quer(ies) referenced but not scanned** (lineage stops there):")
        out += [f"  - `{n['group']}` / `{n['name']}`: {n.get('note', '')}" for n in external[:30]]
    has_out = {e["from"] for e in graph["edges"]}
    no_origin = [n for n in nodes.values() if n["kind"] == "table" and n["id"] not in has_out]
    if no_origin:
        out.append(f"- {len(no_origin)} model table(s) with no resolved origin (no source / dataflow / query detected):")
        for n in no_origin[:30]:
            hint = " - uses dataflow connector but entity not resolved" if DATAFLOW_CONNECTOR_RE.search(n.get("code") or "") else ""
            out.append(f"  - `{n.get('model')}` / `{n['name']}`{hint}")
    no_deps = [n for n in nodes.values() if n["kind"] == "measure" and n["id"] not in has_out]
    if no_deps:
        out.append(f"- {len(no_deps)} measure(s) with no detected dependency (constants, or a reference the DAX scanner missed): "
                   + ", ".join(f"`[{n['name']}]`" for n in no_deps[:15]))
    return out + [""]


def build_report(store: CatalogStore, trace_dir: Path | None) -> str:
    lines = ["# PBI Doc Generator - Diagnostics", "", f"- Catalog: `{store.root}`", f"- Trace: `{trace_dir or 'not enabled'}`", ""]
    if trace_dir:
        lines += http_section(trace_dir) + browser_section(trace_dir)
    lines += catalog_section(store)
    return "\n".join(lines)
