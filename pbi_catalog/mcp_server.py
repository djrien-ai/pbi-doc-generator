"""
Pure-Python Model Context Protocol (MCP) Server over stdio (JSON-RPC 2.0).
Exposes scanned Power BI workspaces, semantic models, Dataflows (Gen1 & Gen2), report layouts,
end-to-end DAX-to-SQL lineage, upstream source impact, and governance health audits to AI assistants
(VS Code Copilot, Claude Desktop, Cursor, Antigravity) with automatic secret redaction.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path
from typing import Any

from .analyzer import analyze_model
from .dataflows import parse_dataflow_definition
from .e2e_lineage import (
    build_e2e_graph,
    find_nodes,
    render_measure_doc_markdown,
    resolve_field_node_id,
    trace_upstream,
)
from .portal import format_dax_pretty, generate_portal
from .report_parser import redact_report_layout_literals
from .security import mask_secrets
from .store import CatalogStore

SERVER_INFO = {"name": "pbi-doc-generator-mcp", "version": "1.1.0"}
PROTOCOL_VERSION = "2024-11-05"

TOOLS_SPEC: list[dict[str, Any]] = [
    {
        "name": "pbi_catalog_summary",
        "description": "Return high-level counts of scanned Power BI workspaces, semantic models, reports, dataflows, and source connectors.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pbi_list_models",
        "description": "List documented Power BI semantic models with workspace, refresh status, source connectors, table/measure counts, and health warnings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Optional case-insensitive workspace name filter."},
                "search": {"type": "string", "description": "Optional substring filter on model name or source type."},
            },
        },
    },
    {
        "name": "pbi_inspect_model",
        "description": "Return full architecture blueprint of a semantic model: tables, storage modes, upstream dataflows, relationships, RLS roles, DAX measures, and health findings.",
        "inputSchema": {
            "type": "object",
            "properties": {"model": {"type": "string", "description": "Model name or dataset GUID."}},
            "required": ["model"],
        },
    },
    {
        "name": "pbi_search_dax_and_m",
        "description": "Search across all DAX measures, calculated columns, model Power Query M partitions, Dataflow Gen1/Gen2 M queries, and Native SQL in the catalog.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keyword, table, view, column, or function name to search for."}},
            "required": ["query"],
        },
    },
    {
        "name": "pbi_source_impact",
        "description": "Perform end-to-end impact analysis for an upstream database, server, view, SharePoint site, dataflow, or table name: returns every affected dataflow, Power BI table, semantic model, DAX measure, and downstream report.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": {"type": "string", "description": "Database, server, schema/view, dataflow, or object substring."}},
            "required": ["source"],
        },
    },
    {
        "name": "pbi_measure_lineage",
        "description": "Return full upstream (referenced columns and base measures) and downstream (dependent KPIs and reports) lineage for a DAX measure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "measure": {"type": "string", "description": "DAX measure name."},
                "model": {"type": "string", "description": "Optional semantic model name filter."},
            },
            "required": ["measure"],
        },
    },
    {
        "name": "pbi_trace_measure_end_to_end",
        "description": "Trace a DAX measure end-to-end across Dependent Measures -> Model Columns & Tables -> Power Query M Steps -> Upstream Dataflows (Gen1/Gen2) -> Native SQL & Physical Sources, returning Markdown documentation or structured JSON.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "measure": {"type": "string", "description": "DAX measure name or Table[Measure] reference."},
                "model": {"type": "string", "description": "Optional semantic model name or dataset GUID filter."},
                "format": {
                    "type": "string",
                    "enum": ["markdown", "json"],
                    "description": "Output format: 'markdown' (default, audit-ready KPI spec) or 'json' (nodes + edges).",
                },
            },
            "required": ["measure"],
        },
    },
    {
        "name": "pbi_report_layout",
        "description": "Inspect Power BI report visual layouts, pages, visual groups, slicer selections, report-level thin DAX measures, and broken visual bindings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "report": {"type": "string", "description": "Optional report name or report GUID filter (omit to list all scanned reports)."},
                "include_visuals": {"type": "boolean", "description": "Include per-page visual items and field bindings (default: true)."},
                "redact_literals": {"type": "boolean", "description": "Scrub filter literals, slicer selections, and free-text boxes (default: false)."},
            },
        },
    },
    {
        "name": "pbi_health_audit",
        "description": "Return governance, refresh, performance, deleted-dataflow, and architecture findings across all scanned Power BI models.",
        "inputSchema": {
            "type": "object",
            "properties": {"severity": {"type": "string", "description": "Optional filter: 'bad' or 'warn'."}},
        },
    },
    {
        "name": "pbi_generate_portal",
        "description": "Regenerate the offline HTML Documentation & Live Lineage Portal from the local catalog store.",
        "inputSchema": {
            "type": "object",
            "properties": {"anonymous": {"type": "boolean", "description": "Redact owner, user permission lists, and report filter literals."}},
        },
    },
]


class CatalogMcpEngine:
    def __init__(self, store: CatalogStore):
        self.store = store

    def _load_enriched_dataflows(self, state: dict[str, Any]) -> dict[str, dict[str, Any]]:
        enriched: dict[str, dict[str, Any]] = {}
        for df_id, df_meta in (state.get("dataflows") or {}).items():
            df_copy = dict(df_meta)
            raw_def = self.store.read_dataflow_definition(df_id)
            if raw_def:
                parsed_df = parse_dataflow_definition(df_copy, raw_def)
                for k in ("queries", "entities", "description", "generation", "source_types"):
                    if parsed_df.get(k) or k not in df_copy:
                        df_copy[k] = parsed_df.get(k)
            enriched[df_id] = df_copy
        return enriched

    def _load_analyses(self, state: dict[str, Any] | None = None) -> list[dict]:
        st = state if state is not None else self.store.load_scoped()
        enriched_dfs = self._load_enriched_dataflows(st)
        reports_by_ds: dict[str, list[dict]] = collections.defaultdict(list)
        for r in st["reports"].values():
            if r.get("dataset_id"):
                rc = dict(r)
                lay = self.store.read_report_layout(rc["id"])
                if lay:
                    rc["layout"] = lay
                reports_by_ds[rc["dataset_id"]].append(rc)

        out = []
        for ds_id, m in st["models"].items():
            bundle = self.store.read_tmdl_bundle(m["name"], ds_id)
            if not bundle:
                continue
            out.append(
                analyze_model(
                    m,
                    bundle,
                    reports=reports_by_ds.get(ds_id, []),
                    dataflows=enriched_dfs,
                    fabric_items=st.get("fabric_items"),
                    dataset_dataflow_links=(st.get("dataset_dataflow_links") or {}).get(ds_id, []),
                )
            )
        return out

    def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        state = self.store.load_scoped()
        if name == "pbi_catalog_summary":
            analyses = self._load_analyses(state)
            return {
                "catalog_dir": str(self.store.root),
                "workspaces": len(state["workspaces"]),
                "models_inventory": len(state["models"]),
                "models_with_tmdl": len(analyses),
                "reports": len(state["reports"]),
                "dataflows": len(state["dataflows"]),
                "source_connectors": sorted({s for a in analyses for s in a["source_types"]}),
                "total_measures": sum(a["stats"]["measures"] for a in analyses),
                "total_tables": sum(a["stats"]["tables"] for a in analyses),
            }

        if name == "pbi_list_models":
            ws_q = (args.get("workspace") or "").lower()
            s_q = (args.get("search") or "").lower()
            items = []
            for a in self._load_analyses(state):
                if ws_q and ws_q not in a["workspace"].lower():
                    continue
                blob = f"{a['name']} {' '.join(a['source_types'])}".lower()
                if s_q and s_q not in blob:
                    continue
                items.append(
                    {
                        "dataset_id": a["dataset_id"],
                        "name": a["name"],
                        "workspace": a["workspace"],
                        "source_types": a["source_types"],
                        "tables": a["stats"]["tables"],
                        "measures": a["stats"]["measures"],
                        "relationships": a["stats"]["relationships"],
                        "reports": len(a["reports"]),
                        "upstream_dataflows": len(a.get("upstream_dataflows") or []),
                        "refresh_status": (a.get("last_refresh") or {}).get("status", ""),
                        "findings_count": len(a["findings"]),
                    }
                )
            return items

        if name == "pbi_inspect_model":
            needle = (args.get("model") or "").strip().lower()
            for a in self._load_analyses(state):
                if needle in (a["dataset_id"].lower(), a["name"].lower()) or needle in a["name"].lower():
                    return {
                        "name": a["name"],
                        "workspace": a["workspace"],
                        "stats": a["stats"],
                        "source_types": a["source_types"],
                        "source_endpoints": a["source_endpoints"],
                        "upstream_dataflows": [
                            {
                                "id": df.get("id"),
                                "name": df.get("name"),
                                "workspace": df.get("workspace"),
                                "generation": df.get("generation", 1),
                                "layer": df.get("layer", 1),
                            }
                            for df in (a.get("upstream_dataflows") or [])
                        ],
                        "tables": a["table_summaries"],
                        "relationships": a["parsed"]["relationships"],
                        "rls_roles": a["parsed"]["roles"],
                        "reports": [r["name"] for r in a["reports"]],
                        "findings": a["findings"],
                    }
            return {"error": f"Model matching '{needle}' not found in catalog."}

        if name == "pbi_search_dax_and_m":
            q = (args.get("query") or "").strip().lower()
            hits = []
            for a in self._load_analyses(state):
                for tbl in a["parsed"]["tables"]:
                    for m in tbl["measures"]:
                        if q in m["name"].lower() or q in m["expr"].lower() or q in m.get("description", "").lower():
                            hits.append(
                                {
                                    "kind": "DAX Measure",
                                    "model": a["name"],
                                    "workspace": a["workspace"],
                                    "table": tbl["name"],
                                    "name": m["name"],
                                    "expression": mask_secrets(format_dax_pretty(m["expr"])),
                                }
                            )
                    for c in tbl["columns"]:
                        if c.get("expr") and (q in c["name"].lower() or q in c["expr"].lower()):
                            hits.append(
                                {
                                    "kind": "Calculated Column",
                                    "model": a["name"],
                                    "workspace": a["workspace"],
                                    "table": tbl["name"],
                                    "name": c["name"],
                                    "expression": mask_secrets(format_dax_pretty(c["expr"])),
                                }
                            )
                    for p in tbl["partitions"]:
                        if p["code"] and q in p["code"].lower():
                            hits.append(
                                {
                                    "kind": f"Partition ({p['kind']})",
                                    "model": a["name"],
                                    "workspace": a["workspace"],
                                    "table": tbl["name"],
                                    "name": p["name"],
                                    "expression": mask_secrets(p["code"][:1200]),
                                }
                            )
            enriched_dfs = self._load_enriched_dataflows(state)
            for df in enriched_dfs.values():
                for qry in df.get("queries") or df.get("entities") or []:
                    m_txt = qry.get("m_code") or qry.get("expression") or ""
                    sql_blobs = " ".join((sq.get("formatted") or sq.get("sql") or "") for sq in (qry.get("native_sql") or []))
                    if q in (qry.get("name") or "").lower() or q in m_txt.lower() or q in sql_blobs.lower():
                        hits.append(
                            {
                                "kind": f"Dataflow Gen{df.get('generation', 1)} Query",
                                "dataflow": df.get("name", ""),
                                "workspace": df.get("workspace", ""),
                                "name": qry.get("name", ""),
                                "expression": mask_secrets((m_txt or sql_blobs)[:1200]),
                            }
                        )
            return hits[:50]

        if name == "pbi_source_impact":
            q = (args.get("source") or "").strip().lower()
            enriched_dfs = self._load_enriched_dataflows(state)
            matched_df_ids: set[str] = set()
            matched_dataflows: list[dict[str, Any]] = []
            for df_id, df in enriched_dfs.items():
                df_hit = q in (df.get("name") or "").lower()
                for qry in df.get("queries") or df.get("entities") or []:
                    m_txt = qry.get("m_code") or qry.get("expression") or ""
                    sql_txt = " ".join((sq.get("sql") or "") for sq in (qry.get("native_sql") or []))
                    src_txt = " ".join(
                        f"{s.get('kind', '')} {s.get('server', '')} {s.get('database', '')}" for s in (qry.get("sources") or [])
                    )
                    if q in (qry.get("name") or "").lower() or q in m_txt.lower() or q in sql_txt.lower() or q in src_txt.lower():
                        df_hit = True
                if df_hit:
                    matched_df_ids.add(df_id)
                    matched_dataflows.append(
                        {"id": df_id, "name": df.get("name", ""), "workspace": df.get("workspace", ""), "generation": df.get("generation", 1)}
                    )

            impacts = []
            for a in self._load_analyses(state):
                matched_tables = []
                up_df_ids = {df.get("id") for df in (a.get("upstream_dataflows") or []) if df.get("id")}
                df_linked = bool(matched_df_ids & up_df_ids)
                for tbl in a["parsed"]["tables"]:
                    part_hit = any(
                        q in (p.get("code") or "").lower() or any(did.lower() in (p.get("code") or "").lower() for did in matched_df_ids)
                        for p in tbl["partitions"]
                    )
                    if part_hit or q in tbl["name"].lower():
                        matched_tables.append(tbl["name"])
                if not matched_tables and df_linked:
                    matched_tables = [t["name"] for t in a["table_summaries"] if "Power BI Dataflow" in (t.get("source_types") or [])]
                if matched_tables or df_linked:
                    t_set = set(matched_tables)
                    impacted_measures = [
                        mi["name"]
                        for mi in (a["lineage"] or {}).values()
                        if mi["table"] in t_set or any(c.split("[", 1)[0] in t_set for c in mi.get("upstream_columns", []))
                    ]
                    impacts.append(
                        {
                            "model": a["name"],
                            "workspace": a["workspace"],
                            "impacted_tables": matched_tables,
                            "impacted_measures": impacted_measures[:40],
                            "downstream_reports": [{"name": r["name"], "workspace": r.get("workspace", "")} for r in a["reports"]],
                        }
                    )
            return {
                "source_query": args.get("source"),
                "impacted_dataflows": matched_dataflows,
                "impacted_models_count": len(impacts),
                "impacts": impacts,
            }

        if name == "pbi_measure_lineage":
            m_q = (args.get("measure") or "").strip().lower()
            mdl_q = (args.get("model") or "").strip().lower()
            results = []
            for a in self._load_analyses(state):
                if mdl_q and mdl_q not in a["name"].lower():
                    continue
                for m_key, mi in (a["lineage"] or {}).items():
                    if m_q == mi["name"].lower() or m_q in m_key.lower():
                        results.append(
                            {
                                "model": a["name"],
                                "workspace": a["workspace"],
                                "measure": mi["name"],
                                "table": mi["table"],
                                "expression": mask_secrets(format_dax_pretty(mi.get("expr", ""))),
                                "uses_columns": mi.get("upstream_columns", []),
                                "uses_measures": mi.get("upstream_measures", []),
                                "used_by_measures": mi.get("downstream_measures", []),
                                "downstream_reports": [r["name"] for r in a["reports"]],
                            }
                        )
            return results[:25]

        if name == "pbi_trace_measure_end_to_end":
            m_q = (args.get("measure") or "").strip()
            mdl_q = (args.get("model") or "").strip().lower()
            out_fmt = (args.get("format") or "markdown").strip().lower()
            analyses = self._load_analyses(state)
            if mdl_q:
                analyses = [a for a in analyses if mdl_q in a["name"].lower() or mdl_q == a["dataset_id"].lower()]
            graph = build_e2e_graph(self.store, analyses)
            matches = find_nodes(graph, m_q, kinds=["measure"])
            if not matches:
                return {"error": f"No DAX measure matching '{m_q}' found in catalog."}
            primary = matches[0]
            if out_fmt == "json":
                sub = trace_upstream(graph, primary["id"])
                return {
                    "matched_measure": primary,
                    "other_candidates": [m["id"] for m in matches[1:10]],
                    "upstream_trace": sub,
                }
            md_doc = render_measure_doc_markdown(graph, primary["id"])
            return {
                "measure_id": primary["id"],
                "label": primary.get("label"),
                "model": primary.get("model"),
                "markdown": mask_secrets(md_doc),
            }

        if name == "pbi_report_layout":
            rep_q = (args.get("report") or "").strip().lower()
            include_vis = bool(args.get("include_visuals", True))
            redact_lit = bool(args.get("redact_literals", False))
            analyses = self._load_analyses(state)
            graph = build_e2e_graph(self.store, analyses)
            enriched_rep_by_id: dict[str, dict] = {}
            for a in analyses:
                for r in a.get("reports") or []:
                    enriched_rep_by_id[r["id"]] = r

            reports_out = []
            for rep_id, rep_meta in sorted(state["reports"].items(), key=lambda kv: (kv[1].get("workspace", "").lower(), kv[1].get("name", "").lower())):
                if rep_q and rep_q not in rep_id.lower() and rep_q not in (rep_meta.get("name") or "").lower():
                    continue
                enr = enriched_rep_by_id.get(rep_id) or rep_meta
                lay = enr.get("layout") or self.store.read_report_layout(rep_id)
                if lay and redact_lit:
                    lay = redact_report_layout_literals(lay)
                ds_id = rep_meta.get("dataset_id") or ""
                ds_name = (state["models"].get(ds_id) or {}).get("name", "")
                entry: dict[str, Any] = {
                    "id": rep_id,
                    "name": rep_meta.get("name", ""),
                    "workspace": rep_meta.get("workspace", ""),
                    "dataset_id": ds_id,
                    "model": ds_name,
                    "has_layout": bool(lay),
                }
                if lay:
                    pages_raw = lay.get("pages") or []
                    entry["format"] = lay.get("format", "")
                    entry["pages_count"] = len(pages_raw)
                    entry["visuals_count"] = sum(len(p.get("visuals") or []) for p in pages_raw)
                    entry["report_measures"] = [
                        {
                            "table": rm.get("table", ""),
                            "name": rm.get("name", ""),
                            "expression": mask_secrets(format_dax_pretty(rm.get("expr", ""))),
                        }
                        for rm in (lay.get("report_measures") or [])
                    ]
                    entry["broken_refs"] = enr.get("broken_refs") or []
                    if include_vis:
                        pages_out = []
                        for p in pages_raw:
                            vis_list = []
                            for v in p.get("visuals") or []:
                                fields_out = []
                                for fld in v.get("fields") or []:
                                    f_tbl = fld.get("entity") or fld.get("table") or ""
                                    f_nm = fld.get("property") or fld.get("name") or ""
                                    nid = resolve_field_node_id(graph, ds_id, f_tbl, f_nm, fld.get("kind")) if ds_id else None
                                    fields_out.append({**fld, "e2e_node_id": nid})
                                vis_list.append(
                                    {
                                        "id": v.get("id", ""),
                                        "type": v.get("type", ""),
                                        "title": v.get("title", ""),
                                        "hidden": bool(v.get("hidden")),
                                        "parent": v.get("parent", ""),
                                        "rect": {
                                            "x": v.get("x", 0),
                                            "y": v.get("y", 0),
                                            "w": v.get("width", v.get("w", 0)),
                                            "h": v.get("height", v.get("h", 0)),
                                            "z": v.get("z", 0),
                                        },
                                        "fields": fields_out,
                                        "filters": v.get("filters") or [],
                                        "selection": v.get("selection") if v.get("selection") is not None else [],
                                    }
                                )
                            pages_out.append(
                                {
                                    "name": p.get("name", ""),
                                    "hidden": bool(p.get("hidden")),
                                    "width": p.get("width", 1280),
                                    "height": p.get("height", 720),
                                    "filters": p.get("filters") or [],
                                    "visuals": vis_list,
                                }
                            )
                        entry["pages"] = pages_out
                reports_out.append(entry)
            return reports_out[:30]

        if name == "pbi_health_audit":
            sev = (args.get("severity") or "").strip().lower()
            findings = []
            for a in self._load_analyses(state):
                for f in a["findings"]:
                    if sev and f["severity"] != sev:
                        continue
                    findings.append({"model": a["name"], "workspace": a["workspace"], **f})
            return findings

        if name == "pbi_generate_portal":
            idx = generate_portal(self.store, anonymous=bool(args.get("anonymous")))
            return {"portal_index": str(idx)}

        raise ValueError(f"Unknown MCP tool: {name}")


def handle_jsonrpc_message(engine: CatalogMcpEngine, msg: Any) -> dict[str, Any] | None:
    if not isinstance(msg, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid JSON-RPC request object"}}
    method = str(msg.get("method") or "")
    req_id = msg.get("id")

    if method.startswith("notifications/"):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS_SPEC}}

    if method == "tools/call":
        params = msg.get("params") or {}
        t_name = params.get("name", "")
        t_args = params.get("arguments") or {}
        try:
            payload = engine.call_tool(t_name, t_args)
            safe_text = mask_secrets(json.dumps(payload, indent=2, ensure_ascii=False))
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": safe_text}], "isError": False},
            }
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": mask_secrets(str(exc))}], "isError": True},
            }

    if req_id is not None:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return None


def run_mcp_stdio(catalog_dir: str | Path) -> None:
    """Serve MCP over stdin/stdout supporting both newline-delimited JSON and Content-Length framing."""
    store = CatalogStore(catalog_dir)
    engine = CatalogMcpEngine(store)
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer

    while True:
        first_line = stdin.readline()
        if not first_line:
            break
        stripped = first_line.strip()
        if not stripped:
            continue

        use_framing = False
        if stripped.lower().startswith(b"content-length:"):
            use_framing = True
            try:
                length = int(stripped.split(b":", 1)[1].strip())
            except ValueError:
                continue
            while True:
                hdr = stdin.readline()
                if not hdr or hdr in (b"\r\n", b"\n"):
                    break
            raw_body = stdin.read(max(0, length))
        else:
            raw_body = stripped

        try:
            msg = json.loads(raw_body.decode("utf-8", errors="replace"))
        except Exception:
            continue

        try:
            resp = handle_jsonrpc_message(engine, msg)
        except Exception as exc:
            req_id = msg.get("id") if isinstance(msg, dict) else None
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32603, "message": mask_secrets(f"Internal MCP server error: {exc}")},
            }
        if resp is not None:
            encoded = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            try:
                if use_framing:
                    stdout.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii") + encoded)
                else:
                    stdout.write(encoded + b"\n")
                stdout.flush()
            except BrokenPipeError:
                break
