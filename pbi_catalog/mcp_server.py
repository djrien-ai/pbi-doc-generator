"""
Pure-Python Model Context Protocol (MCP) Server over stdio (JSON-RPC 2.0).
Exposes scanned Power BI workspaces, semantic models, DAX lineage, upstream source impact,
and governance health audits to AI assistants (VS Code Copilot, Claude Desktop, Cursor, Antigravity)
with automatic secret redaction.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path
from typing import Any

from .analyzer import analyze_model
from .portal import format_dax_pretty, generate_portal
from .security import mask_secrets
from .store import CatalogStore

SERVER_INFO = {"name": "pbi-doc-generator-mcp", "version": "1.0.0"}
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
        "description": "Return full architecture blueprint of a semantic model: tables, storage modes, relationships, RLS roles, DAX measures, and health findings.",
        "inputSchema": {
            "type": "object",
            "properties": {"model": {"type": "string", "description": "Model name or dataset GUID."}},
            "required": ["model"],
        },
    },
    {
        "name": "pbi_search_dax_and_m",
        "description": "Search across all DAX measures, calculated columns, and Power Query M scripts in the catalog.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Keyword, table, view, column, or function name to search for."}},
            "required": ["query"],
        },
    },
    {
        "name": "pbi_source_impact",
        "description": "Perform end-to-end impact analysis for an upstream database, server, view, SharePoint site, or table name: returns every affected Power BI table, semantic model, DAX measure, and downstream report.",
        "inputSchema": {
            "type": "object",
            "properties": {"source": {"type": "string", "description": "Database, server, schema/view, or object substring."}},
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
        "name": "pbi_health_audit",
        "description": "Return governance, refresh, performance, and architecture findings across all scanned Power BI models.",
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
            "properties": {"anonymous": {"type": "boolean", "description": "Redact owner and user permission lists."}},
        },
    },
]


class CatalogMcpEngine:
    def __init__(self, store: CatalogStore):
        self.store = store

    def _load_analyses(self) -> list[dict]:
        state = self.store.load()
        reports_by_ds: dict[str, list[dict]] = collections.defaultdict(list)
        for r in state["reports"].values():
            if r.get("dataset_id"):
                reports_by_ds[r["dataset_id"]].append(r)

        out = []
        for ds_id, m in state["models"].items():
            bundle = self.store.read_tmdl_bundle(m["name"], ds_id)
            if not bundle:
                continue
            out.append(analyze_model(m, bundle, reports=reports_by_ds.get(ds_id, [])))
        return out

    def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        state = self.store.load()
        if name == "pbi_catalog_summary":
            analyses = self._load_analyses()
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
            for a in self._load_analyses():
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
                        "refresh_status": (a.get("last_refresh") or {}).get("status", ""),
                        "findings_count": len(a["findings"]),
                    }
                )
            return items

        if name == "pbi_inspect_model":
            needle = (args.get("model") or "").strip().lower()
            for a in self._load_analyses():
                if needle in (a["dataset_id"].lower(), a["name"].lower()) or needle in a["name"].lower():
                    return {
                        "name": a["name"],
                        "workspace": a["workspace"],
                        "stats": a["stats"],
                        "source_types": a["source_types"],
                        "source_endpoints": a["source_endpoints"],
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
            for a in self._load_analyses():
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
            return hits[:50]

        if name == "pbi_source_impact":
            q = (args.get("source") or "").strip().lower()
            impacts = []
            for a in self._load_analyses():
                matched_tables = []
                for tbl in a["parsed"]["tables"]:
                    part_hit = any(q in (p.get("code") or "").lower() for p in tbl["partitions"])
                    if part_hit or q in tbl["name"].lower():
                        matched_tables.append(tbl["name"])
                if matched_tables:
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
            return {"source_query": args.get("source"), "impacted_models_count": len(impacts), "impacts": impacts}

        if name == "pbi_measure_lineage":
            m_q = (args.get("measure") or "").strip().lower()
            mdl_q = (args.get("model") or "").strip().lower()
            results = []
            for a in self._load_analyses():
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

        if name == "pbi_health_audit":
            sev = (args.get("severity") or "").strip().lower()
            findings = []
            for a in self._load_analyses():
                for f in a["findings"]:
                    if sev and f["severity"] != sev:
                        continue
                    findings.append({"model": a["name"], "workspace": a["workspace"], **f})
            return findings

        if name == "pbi_generate_portal":
            idx = generate_portal(self.store, anonymous=bool(args.get("anonymous")))
            return {"portal_index": str(idx)}

        raise ValueError(f"Unknown MCP tool: {name}")


def handle_jsonrpc_message(engine: CatalogMcpEngine, msg: dict[str, Any]) -> dict[str, Any] | None:
    method = msg.get("method", "")
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
            length = int(stripped.split(b":", 1)[1].strip())
            while True:
                hdr = stdin.readline()
                if not hdr or hdr in (b"\r\n", b"\n"):
                    break
            raw_body = stdin.read(length)
        else:
            raw_body = stripped

        try:
            msg = json.loads(raw_body.decode("utf-8"))
        except Exception:
            continue

        resp = handle_jsonrpc_message(engine, msg)
        if resp is not None:
            encoded = json.dumps(resp, ensure_ascii=False).encode("utf-8")
            if use_framing:
                stdout.write(f"Content-Length: {len(encoded)}\r\n\r\n".encode("ascii") + encoded)
            else:
                stdout.write(encoded + b"\n")
            stdout.flush()
