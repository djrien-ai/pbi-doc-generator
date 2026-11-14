"""
Cross-references between semantic models, thin reports and Gen1 dataflows for the portal pages.

Derived entirely from the end-to-end lineage graph (`e2e_lineage.build_e2e_graph`) so the model pages,
the portal home tabs and the end-to-end explorer always show the same dataflow chains and the same
report-level measures.
"""

from __future__ import annotations

import collections
import urllib.parse

E2E_PAGE = "e2e_lineage.html"


def e2e_href(prefix: str = "", **params: str) -> str:
    """Link into the end-to-end explorer, e.g. e2e_href("../", grp="model:<id>", kind="measure")."""
    q = "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in params.items() if v)
    # The explorer is tab 6 of the portal home page; "#e2e:<state>" opens that tab with the explorer state
    return f"{prefix}index.html#e2e" + (f":{q}" if q else "")


def _reach(start: str, out: dict[str, list[dict]], nodes: dict) -> tuple[list[str], list[str]]:
    """All dataflow queries and sources upstream of `start` (breadth-first, cycle safe)."""
    seen = {start}
    frontier = [start]
    dfq: list[str] = []
    srcs: list[str] = []
    while frontier:
        nxt = []
        for nid in frontier:
            for e in out.get(nid, []):
                t = e["to"]
                if t in seen or t not in nodes:
                    continue
                seen.add(t)
                kind = nodes[t]["kind"]
                if kind == "dataflow_query":
                    dfq.append(t)
                elif kind == "source":
                    srcs.append(t)
                if kind in ("dataflow_query", "expression", "table", "calc_table", "source"):
                    nxt.append(t)
        frontier = nxt
    return dfq, srcs


def build_portal_xref(graph: dict, state: dict) -> dict:
    nodes = graph["nodes"]
    out: dict[str, list[dict]] = collections.defaultdict(list)
    for e in graph["edges"]:
        out[e["from"]].append(e)

    df_summ = {d["id"].lower(): d for d in graph.get("dataflows") or []}
    df_state = {k.lower(): v for k, v in (state.get("dataflows") or {}).items()}

    def df_info(gid: str) -> dict:
        d = dataflows.get(gid)
        if d is None:
            meta = df_state.get(gid) or {}
            summ = df_summ.get(gid) or {}
            d = dataflows[gid] = {
                "id": gid,
                "name": summ.get("name") or meta.get("name") or f"Dataflow {gid[:8]}",
                "workspace": summ.get("workspace") or meta.get("workspace") or "",
                "workspace_id": meta.get("workspace_id", ""),
                "status": summ.get("status") or meta.get("definition_status") or "not scanned",
                "configured_by": meta.get("configured_by", ""),
                "modified": meta.get("modified_at") or meta.get("modifiedDateTime") or "",
                "queries": [],
                "roles": collections.Counter(),
                "connectors": collections.Counter(),
                "sql_queries": 0,
                "upstream": set(),
                "downstream": set(),
                "models": {},  # ds_id -> {"name", "workspace", "tables": set(), "direct": bool}
                "sources": set(),
                "href": e2e_href("", grp=f"df:{gid}", kind="dataflow_query"),
            }
        return d

    dataflows: dict[str, dict] = {}
    for gid in list(df_summ) + list(df_state):
        df_info(gid)

    # Dataflow queries: roles, connectors, SQL, dataflow -> dataflow links, sources
    for nid, n in nodes.items():
        if n["kind"] != "dataflow_query":
            continue
        gid = n.get("group_id") or ""
        d = df_info(gid)
        if n.get("external"):
            continue
        d["queries"].append(nid)
        d["roles"][n.get("role") or "Entity"] += 1
        for c in n.get("source_types") or []:
            d["connectors"][c] += 1
        d["sql_queries"] += 1 if n.get("sql") else 0
        for e in out.get(nid, []):
            t = nodes.get(e["to"])
            if not t:
                continue
            if t["kind"] == "dataflow_query" and t.get("group_id") != gid:
                d["upstream"].add(t.get("group_id") or "")
                df_info(t.get("group_id") or "")["downstream"].add(gid)
            elif t["kind"] == "source":
                d["sources"].add(e["to"])

    # Dataflows referenced from the selection but living in unselected workspaces: lineage placeholders only
    for gid, d in dataflows.items():
        d["outside"] = gid not in df_summ and gid not in df_state
        if d["outside"]:
            d["status"] = "outside selected workspaces"

    # Semantic models: tables -> dataflow entities (direct + every upstream layer) and sources
    models: dict[str, dict] = {}
    for m in graph.get("models") or []:
        models[m["id"]] = {"tables": {}, "dataflows": {}, "report_measures": [], "reports": {}}
    for nid, n in nodes.items():
        if n["kind"] not in ("table", "calc_table"):
            continue
        ds_id = n.get("model_id") or ""
        mx = models.setdefault(ds_id, {"tables": {}, "dataflows": {}, "report_measures": [], "reports": {}})
        direct = []
        for e in out.get(nid, []):
            t = nodes.get(e["to"])
            if t and t["kind"] == "dataflow_query":
                direct.append(e["to"])
            elif t and t["kind"] == "expression":
                # Table that reads a shared dataset query that itself loads the dataflow
                direct += [x["to"] for x in out.get(e["to"], []) if nodes.get(x["to"], {}).get("kind") == "dataflow_query"]
        dfq, srcs = _reach(nid, out, nodes)
        direct_set = set(direct)
        mx["tables"][n["name"]] = {
            "node": nid,
            "direct": sorted(direct_set),
            "dataflow_queries": dfq,
            "sources": srcs,
        }
        for q in dfq:
            gid = nodes[q].get("group_id") or ""
            is_direct = q in direct_set
            info = mx["dataflows"].setdefault(gid, {"id": gid, "direct": False, "tables": set(), "entities": set()})
            info["direct"] = info["direct"] or is_direct
            info["tables"].add(n["name"])
            if is_direct:
                info["entities"].add(nodes[q]["name"])
            dm = df_info(gid)["models"].setdefault(ds_id, {"name": n.get("model", ""), "workspace": n.get("workspace", ""), "tables": set(), "direct": False})
            dm["direct"] = dm["direct"] or is_direct
            dm["tables"].add(n["name"])

    # Report-level measures of thin reports, attached to the shared model they extend
    reports: dict[str, dict] = {}
    for nid, n in nodes.items():
        if n["kind"] != "measure" or not n.get("report_id"):
            continue
        rid = n["report_id"]
        r = reports.setdefault(rid, {"id": rid, "name": n.get("report", ""), "workspace": n.get("workspace", ""), "model_id": n.get("model_id", ""),
                                     "model": n.get("model", ""), "measures": [], "href": e2e_href("", grp=f"rpt:{rid}", kind="measure")})
        r["measures"].append(nid)
        mx = models.setdefault(n.get("model_id") or "", {"tables": {}, "dataflows": {}, "report_measures": [], "reports": {}})
        mx["report_measures"].append(nid)
        mx["reports"][rid] = r
    for r in reports.values():
        r["measures"].sort(key=lambda x: nodes[x]["name"].lower())

    # Dataflow layer numbers per model (1 = loaded by the model, 2 = feeds layer 1, ...)
    for mx in models.values():
        layer: dict[str, int] = {gid: 1 for gid, i in mx["dataflows"].items() if i["direct"]}
        for _ in range(30):
            changed = False
            for gid in list(layer):
                for up in dataflows.get(gid, {}).get("upstream", ()):
                    if up in mx["dataflows"] and layer.get(up, 0) < layer[gid] + 1 <= 30:
                        layer[up] = layer[gid] + 1
                        changed = True
            if not changed:
                break
        for gid, i in mx["dataflows"].items():
            i["layer"] = layer.get(gid, 1 if i["direct"] else 2)

    return {"models": models, "dataflows": dataflows, "reports": reports, "nodes": nodes, "out": out}
