"""
End-to-End Lineage Graph: DAX measure -> measures -> tables/columns -> dataset Power Query ->
Dataflow Gen1 queries (any number of dataflow layers) -> physical sources (SQL, Excel, files, APIs).

The graph is a plain JSON-serialisable dict so it can be embedded in the offline explorer page,
served to MCP clients, and turned into measure documentation (`render_measure_doc_markdown`).

Edges always point from the *consumer* to the *provider* ("X depends on Y").
"""

from __future__ import annotations

import collections
import hashlib
import re

from .analyzer import analyze_model
from .dataflows import DATAFLOW_CONNECTOR_RE, describe_sources, find_dataflow_refs, parse_dataflow_definition
from .pq_steps import interpret_query
from .store import CatalogStore, utc_now_iso

KIND_ORDER = {
    "measure": 0,
    "calc_column": 1,
    "calc_table": 2,
    "table": 2,
    "expression": 3,
    "dataflow_query": 4,
    "source": 6,
}
KIND_LABEL = {
    "measure": "DAX measure",
    "calc_column": "Calculated column",
    "calc_table": "Calculated table",
    "table": "Model table",
    "expression": "Dataset query (Power Query)",
    "dataflow_query": "Dataflow query",
    "source": "Data source",
}


def _strip_dax_noise(expr: str) -> str:
    """Remove DAX strings and comments so references inside them are ignored."""
    s = re.sub(r"//[^\n]*|--[^\n]*", " ", expr or "")
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r'"(?:[^"]|"")*"', '""', s)


_TBL_COL_RE = re.compile(r"('(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_]*)\s*\[([^\]]+)\]")
_BARE_RE = re.compile(r"(?<![A-Za-z0-9_'\]])\[([^\]]+)\]")
_QUOTED_TBL_RE = re.compile(r"'((?:[^']|'')+)'(?!\s*\[)")
_IDENT_RE = re.compile(r"(?<![\w.'\[])([A-Za-z_][A-Za-z0-9_]*)(?![\w'\[(])(?!\s*\()")


def dax_references(expr: str, host_table: str, tables: dict[str, dict], measure_index: dict[str, str]) -> dict:
    """Find measures, columns `(table, column)` and whole tables referenced by a DAX expression."""
    s = _strip_dax_noise(expr)
    measures: set[str] = set()
    columns: set[tuple[str, str]] = set()
    whole_tables: set[str] = set()
    lower_tables = {t.lower(): t for t in tables}

    for m in _TBL_COL_RE.finditer(s):
        raw_t = m.group(1)
        tname = raw_t[1:-1].replace("''", "'") if raw_t.startswith("'") else raw_t
        col = m.group(2).strip()
        real_t = lower_tables.get(tname.lower())
        if not real_t:
            continue
        mkey = measure_index.get(col.lower())
        if mkey and re.sub(r"^rpt:[^:]+:", "", mkey).startswith(f"{real_t}["):
            measures.add(mkey)
        else:
            columns.add((real_t, col))
    rest = _TBL_COL_RE.sub(" ", s)
    for m in _BARE_RE.finditer(rest):
        ref = m.group(1).strip()
        mkey = measure_index.get(ref.lower())
        if mkey:
            measures.add(mkey)
        elif host_table in tables and any(c["name"].lower() == ref.lower() for c in tables[host_table]["columns"]):
            columns.add((host_table, ref))
    rest = _BARE_RE.sub(" ", rest)
    for m in _QUOTED_TBL_RE.finditer(rest):
        real_t = lower_tables.get(m.group(1).replace("''", "'").lower())
        if real_t:
            whole_tables.add(real_t)
    for m in _IDENT_RE.finditer(rest):
        real_t = lower_tables.get(m.group(1).lower())
        if real_t and m.group(1) not in ("VAR", "RETURN", "TRUE", "FALSE"):
            whole_tables.add(real_t)
    return {"measures": measures, "columns": columns, "tables": whole_tables}


class _GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str], dict] = {}

    def node(self, nid: str, **fields) -> dict:
        n = self.nodes.get(nid)
        if n is None:
            n = {"id": nid}
            self.nodes[nid] = n
        for k, v in fields.items():
            if v not in (None, "", [], {}) or k not in n:
                n[k] = v
        return n

    def edge(self, src: str, dst: str, label: str = "", kind: str = "") -> None:
        if src == dst:
            return
        e = self.edges.get((src, dst))
        if e is None:
            e = {"from": src, "to": dst, "labels": [], "kind": kind}
            self.edges[(src, dst)] = e
        if label and label not in e["labels"]:
            e["labels"].append(label)

    def source_node(self, kind_label: str, endpoint: str, database: str = "", obj: str = "", sql: str = "", files: list[str] | None = None) -> str:
        sig = "|".join([kind_label, endpoint, database, obj, sql.strip()]).lower()
        nid = "s:" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:14]
        sql_from = re.search(r'(?is)\bfrom\s+((?:"[^"]+"|\[[^\]]+\]|`[^`]+`|[\w$#]+)(?:\s*\.\s*(?:"[^"]+"|\[[^\]]+\]|`[^`]+`|[\w$#]+))*)', sql or "")
        sql_title = f"SQL: {sql_from.group(1)}" if sql_from else ("Native SQL query" if sql else "")
        title = obj or sql_title or (files[0].replace("\\", "/").rsplit("/", 1)[-1] if files else "") or database or endpoint or kind_label
        sub = " / ".join(x for x in (endpoint, database) if x)
        self.node(
            nid,
            kind="source",
            name=title,
            source_type=kind_label,
            server=endpoint,
            database=database,
            object=obj,
            files=files or [],
            code=sql,
            lang="sql" if sql else "",
            group=kind_label,
            subtitle=sub,
        )
        return nid

    def add_m_sources(self, consumer: str, info: dict) -> None:
        """Turn analysed M sources (+ native SQL) into source nodes linked from `consumer`."""
        endpoints = info.get("endpoints") or []
        objects = info.get("objects") or []
        obj = ", ".join(objects)
        db_labels = {e.get("label") for e in endpoints}
        sql_eps = set()
        sql_ids: list[str] = []
        for q in info.get("native_sql") or []:
            nid = self.source_node(q.get("connector") or "Native SQL", q.get("server", ""), q.get("database", ""), "", q["sql"])
            self.nodes[nid]["sql_parameters"] = q.get("parameters") or []
            self.edge(consumer, nid, "native SQL", "source")
            sql_eps.add((q.get("server"), q.get("database")))
            sql_ids.append(nid)
        for ep in endpoints:
            if (ep["server"], ep["database"]) in sql_eps:
                continue
            nid = self.source_node(ep.get("label") or ep["connector"], ep["server"], ep["database"], obj, "")
            self.edge(consumer, nid, obj or "reads", "source")
        entered = any(x["type"] == "Entered Data (Manual Table)" for x in info.get("sources") or [])
        for s in info.get("sources") or []:
            if s["type"] == "Power BI Dataflow" or (endpoints and s["type"] in db_labels):
                continue
            if entered and s["type"] == "JSON" and "Binary.Decompress" in (s.get("detail") or ""):
                continue  # part of the "Enter data" encoding, not a separate source
            if s["type"] == "Entered Data (Manual Table)":
                nid = self.source_node("Entered Data (Manual Table)", "", "", "Rows typed into Power Query (Enter data)", "")
                self.edge(consumer, nid, "entered data", "source")
                continue
            if s["type"] == "Web API" and any(t in (info.get("source_types") or []) for t in ("Excel", "CSV", "JSON", "Parquet", "XML")):
                continue  # Web.Contents is only the transport for a file source already listed
            files = [f for f in info.get("files") or []] if s["type"] in ("Excel", "CSV", "File", "SharePoint", "JSON", "Parquet", "XML", "Folder") else []
            sheet = ", ".join(info.get("sheets") or [])
            detail = s["detail"]
            if detail in ("Web.Contents", "File.Contents") and files:
                detail = files[0]
            nid = self.source_node(s["type"], detail, "", sheet or ("" if files else obj), "", files)
            self.edge(consumer, nid, sheet or obj or "reads", "source")
        return sql_ids


def _sql_entries(native: list[dict], source_ids: list[str]) -> list[dict]:
    """Per-query SQL entries; the formatted SQL text lives once, on the source node (`source_id`)."""
    out = []
    for q, sid in zip(native or [], source_ids):
        e = {k: q.get(k, "") for k in ("via", "connector", "server", "database", "parameters")}
        e["source_id"] = sid
        out.append(e)
    return out


def _steps_with_ids(code: str, names: list[str], id_for) -> list[dict]:
    steps = interpret_query(code, names)
    for st in steps:
        st["query_ids"] = [id_for(q) for q in st.get("queries", [])]
        st.pop("fn", None)
        st.pop("code", None)  # the UI slices node.code[start:end]; avoids duplicating the M text
    return steps


def _wire_dax(g: "_GraphBuilder", ds_id: str, tables: dict, measure_index: dict, nid: str, expr: str, host: str) -> None:
    refs = dax_references(expr, host, tables, measure_index)
    for mk in refs["measures"]:
        g.edge(nid, f"m:{ds_id}:{mk}", "uses measure", "dax")
    for t_name, col in refs["columns"]:
        col_def = next((c for c in tables[t_name]["columns"] if c["name"].lower() == col.lower()), None)
        if col_def and col_def.get("expr"):
            g.edge(nid, f"c:{ds_id}:{t_name}[{col_def['name']}]", "uses calculated column", "dax")
        else:
            g.edge(nid, f"t:{ds_id}:{t_name}", f"{t_name}[{col}]", "dax")
    for t_name in refs["tables"]:
        g.edge(nid, f"t:{ds_id}:{t_name}", f"table '{t_name}'", "dax")


def _add_report_measures(g: "_GraphBuilder", store: CatalogStore, state: dict, model_ctx: dict, report_summaries: list) -> None:
    """Report-level measures of thin reports, wired into the shared model they connect to."""
    for rid, rep in state.get("reports", {}).items():
        data = store.read_report_measures(rid)
        measures = data.get("measures") or []
        if not measures:
            continue
        ds_id = rep.get("dataset_id") or data.get("dataset_id") or ""
        ctx = model_ctx.get(ds_id)
        ds_meta = state.get("models", {}).get(ds_id) or (state.get("out_of_scope_models") or {}).get(ds_id) or {}
        model_name = (ctx or {}).get("name") or ds_meta.get("name") or f"Model {ds_id[:8]}"
        tables = (ctx or {}).get("tables") or {}
        index = dict((ctx or {}).get("measure_index") or {})
        keys = {}
        for m in measures:
            key = f"rpt:{rid}:{m['table']}[{m['name']}]"
            keys[m["name"]] = key
            index[m["name"].lower()] = key
        report_summaries.append({"id": rid, "name": rep.get("name", ""), "workspace": rep.get("workspace", ""), "model": model_name,
                                 "measures": len(measures), "model_scanned": bool(ctx)})
        cross = (rep.get("workspace_id") or "") != (ds_meta.get("workspace_id") or rep.get("dataset_workspace_id") or rep.get("workspace_id") or "")
        for m in measures:
            mid = f"m:{ds_id}:{keys[m['name']]}"
            g.node(
                mid,
                kind="measure",
                name=m["name"],
                group=rep.get("name", "Report"),
                table=m["table"],
                description=m.get("description", ""),
                code=m.get("expr", ""),
                lang="dax",
                format=m.get("format", ""),
                folder=m.get("folder", ""),
                hidden=m.get("hidden", False),
                model=model_name,
                model_id=ds_id,
                workspace=rep.get("workspace", ""),
                report=rep.get("name", ""),
                report_id=rid,
                model_workspace=ds_meta.get("workspace", ""),
                role="Report-level measure (thin report" + (", shared model in another workspace)" if cross else ")"),
                note=""
                if ctx
                else (
                    "Shared model is in a workspace outside the selection - select its workspace (or enable following references outside the selection) and rescan."
                    if ds_id in (state.get("out_of_scope_models") or {}) or (state.get("scope") and not ds_meta)
                    else "Shared model definition not in catalog - DAX references to the model cannot be resolved."
                ),
            )
            _wire_dax(g, ds_id, tables, index, mid, m.get("expr", ""), m["table"] if m["table"] in tables else "")


def build_e2e_graph(store: CatalogStore, analyses: list[dict] | None = None) -> dict:
    """Build the full cross-model, cross-dataflow lineage graph from the local catalog."""
    state = store.load_scoped()
    g = _GraphBuilder()
    dataflow_summaries: list[dict] = []
    model_summaries: list[dict] = []

    # ---------------- Dataflows ----------------
    parsed_dfs: dict[str, dict] = {}
    for df_id, df_meta in state.get("dataflows", {}).items():
        definition = store.read_dataflow_definition(df_id)
        if not definition:
            dataflow_summaries.append(
                {"id": df_id, "name": df_meta.get("name", df_id), "workspace": df_meta.get("workspace", ""), "status": df_meta.get("definition_status", "pending"), "queries": 0}
            )
            continue
        pdf = parse_dataflow_definition(df_meta, definition)
        parsed_dfs[df_id.lower()] = pdf
        dataflow_summaries.append(
            {"id": df_id, "name": pdf["name"], "workspace": pdf["workspace"], "status": "ok", "queries": len(pdf["queries"])}
        )

    def df_query_id(df_id: str, qname: str) -> str:
        return f"q:{df_id.lower()}:{qname}"

    def resolve_df_ref(ref: dict) -> str:
        """Return the node id for a dataflow entity reference, creating a placeholder when not scanned."""
        df_id = (ref.get("dataflow_id") or "").lower()
        ent = ref.get("entity") or ""
        pdf = parsed_dfs.get(df_id)
        if pdf:
            q = next((x for x in pdf["queries"] if x["name"].lower() == ent.lower()), None)
            if q:
                return df_query_id(df_id, q["name"])
        meta = state.get("dataflows", {}).get(ref.get("dataflow_id", "")) or {}
        oos = {k.lower(): v for k, v in (state.get("out_of_scope_dataflows") or {}).items()}.get(df_id)
        meta = meta or oos or {}
        df_name = (pdf or {}).get("name") or meta.get("name") or (f"Dataflow {df_id[:8]}" if df_id else "Unknown dataflow")
        nid = df_query_id(df_id or "unknown", ent or "(entity)")
        g.node(
            nid,
            kind="dataflow_query",
            name=ent or "(entity not resolved)",
            group=df_name,
            group_id=df_id,
            workspace=meta.get("workspace", ""),
            role="Entity (outside selected workspaces)" if oos else "Entity (definition not scanned)",
            external=True,
            outside=bool(oos),
            note="Dataflow is in a workspace outside the selection - select its workspace (or enable following references outside the selection) and rescan."
            if oos
            else (meta.get("definition_status") or "Dataflow not in catalog - scan its workspace to resolve its queries."),
            code="",
            lang="m",
        )
        return nid

    for df_id, pdf in parsed_dfs.items():
        q_by_name = {q["name"]: q for q in pdf["queries"]}
        for q in pdf["queries"]:
            if q["kind"] == "parameter":
                continue
            nid = df_query_id(df_id, q["name"])
            g.node(
                nid,
                kind="dataflow_query",
                name=q["name"],
                group=pdf["name"],
                group_id=df_id,
                workspace=pdf["workspace"],
                role=q["role"],
                description=q["description"],
                code=q["code"],
                lang="m",
                columns=q["columns"],
                parameters={p: pdf["parameters"].get(p, "") for p in q["parameters"]},
                step_count=q["step_count"],
                source_types=q["source_types"],
                steps=_steps_with_ids(q["code"], list(q_by_name), lambda n, d=df_id: df_query_id(d, n)) if q["code"] else [],
            )
            for dep in q["depends_on"]:
                dq = q_by_name.get(dep)
                if dq and dq["kind"] != "parameter":
                    g.edge(nid, df_query_id(df_id, dep), "references query", "query")
            for ref in q["dataflow_refs"]:
                g.edge(nid, resolve_df_ref(ref), "linked entity", "dataflow")
            g.nodes[nid]["sql"] = _sql_entries(q.get("native_sql"), g.add_m_sources(nid, q))

    # ---------------- Semantic models ----------------
    reports_by_ds: dict[str, list[dict]] = collections.defaultdict(list)
    for rep in state.get("reports", {}).values():
        if rep.get("dataset_id"):
            reports_by_ds[rep["dataset_id"]].append(rep)

    if analyses is None:
        analyses = []
        for ds_id, m_meta in state.get("models", {}).items():
            bundle = store.read_tmdl_bundle(m_meta.get("name", ""), ds_id)
            if bundle:
                analyses.append(analyze_model(m_meta, bundle, reports=reports_by_ds.get(ds_id, [])))

    links = state.get("dataset_dataflow_links") or {}
    model_ctx: dict[str, dict] = {}
    for a in analyses:
        ds_id = a["dataset_id"]
        parsed = a["parsed"]
        tables = {t["name"]: t for t in parsed["tables"] if not t["auto_date"]}
        params = {x["name"]: x["default_value"] for x in parsed["expressions"] if x["kind"] == "parameter"}
        expr_names = [x["name"] for x in parsed["expressions"] if x["kind"] != "parameter"]
        measure_index: dict[str, str] = {}
        for t in tables.values():
            for m in t["measures"]:
                measure_index[m["name"].lower()] = f"{t['name']}[{m['name']}]"
        linked_dfs = [ln.get("dataflow_id", "").lower() for ln in links.get(ds_id, []) if ln.get("dataflow_id")]
        model_summaries.append(
            {"id": ds_id, "name": a["name"], "workspace": a["workspace"], "measures": a["stats"]["measures"], "tables": a["stats"]["tables"]}
        )
        common = {"model": a["name"], "model_id": ds_id, "workspace": a["workspace"]}

        def tid(tname: str) -> str:
            return f"t:{ds_id}:{tname}"

        model_ctx[ds_id] = {"name": a["name"], "tables": tables, "measure_index": dict(measure_index)}

        def wire_dax(nid: str, expr: str, host: str, _ds=ds_id, _t=tables, _mi=measure_index) -> None:
            _wire_dax(g, _ds, _t, _mi, nid, expr, host)

        m_table_names = [t["name"] for t in tables.values() if any(p["kind"] == "m" for p in t["partitions"])]

        def wire_m(nid: str, code: str, own_name: str) -> None:
            info = describe_sources(code, params, [n for n in expr_names if n != own_name])
            for dep in info["depends_on"]:
                if dep in expr_names:
                    g.edge(nid, f"e:{ds_id}:{dep}", "references query", "query")
            # Power Query references to other tables' queries (e.g. `Source = Sales`), never `Date.Year(...)`
            for other in m_table_names:
                if other != own_name and re.search(r'(?<![\w."#])(?:#"' + re.escape(other) + r'"|' + re.escape(other) + r')(?![\w".(])', code or ""):
                    g.edge(nid, tid(other), "references table query", "query")
            refs = find_dataflow_refs(code, params)
            for ref in refs:
                if ref["dataflow_id"].startswith("{param:") and len(linked_dfs) == 1:
                    ref = {**ref, "dataflow_id": linked_dfs[0]}
                g.edge(nid, resolve_df_ref(ref), "loads dataflow entity", "dataflow")
            if not refs and DATAFLOW_CONNECTOR_RE.search(code or "") and linked_dfs:
                # Dataflow connector with unresolvable navigation: fall back to REST dataset -> dataflow links
                for df_id in linked_dfs:
                    g.edge(nid, resolve_df_ref({"dataflow_id": df_id, "entity": own_name}), "loads dataflow (REST link)", "dataflow")
            sql_ids = g.add_m_sources(nid, info)
            node = g.nodes[nid]
            node["sql"] = (node.get("sql") or []) + _sql_entries(info.get("native_sql"), sql_ids)
            if not node.get("steps") and (node.get("code") or "").startswith(code or "\0"):
                node["steps"] = _steps_with_ids(
                    code, expr_names + [t for t in m_table_names if t != own_name],
                    lambda n: f"e:{ds_id}:{n}" if n in expr_names else tid(n),
                )
            return info

        for x in parsed["expressions"]:
            if x["kind"] == "parameter":
                continue
            nid = f"e:{ds_id}:{x['name']}"
            g.node(nid, kind="expression", name=x["name"], group=a["name"], role=x["kind"].title(), description=x["description"], code=x["code"], lang="m", **common)
            wire_m(nid, x["code"], x["name"])

        for t in tables.values():
            nid = tid(t["name"])
            parts = t["partitions"]
            m_parts = [p for p in parts if p["kind"] == "m"]
            calc_parts = [p for p in parts if p["kind"] == "calculated"]
            kind = "calc_table" if calc_parts and not m_parts else "table"
            mode = next((p["mode"] for p in parts if p.get("mode")), "")
            code = "\n\n".join(p["code"] for p in (m_parts or calc_parts or parts) if p.get("code"))
            g.node(
                nid,
                kind=kind,
                name=t["name"],
                group=a["name"],
                description=t["description"],
                code=code,
                lang="dax" if kind == "calc_table" else "m",
                storage_mode=mode or "import",
                columns=[{"name": c["name"], "type": c["type"], "source": c["source"], "calculated": bool(c["expr"])} for c in t["columns"]],
                **common,
            )
            for p in m_parts:
                wire_m(nid, p["code"], t["name"])
            for p in calc_parts:
                wire_dax(nid, p["code"], t["name"])
            for p in parts:
                if p["kind"] == "entity":
                    src = g.source_node("Direct Lake / OneLake", "", "", p["name"] or t["name"], "")
                    g.edge(nid, src, "Direct Lake entity", "source")
            for c in t["columns"]:
                if c.get("expr"):
                    cid = f"c:{ds_id}:{t['name']}[{c['name']}]"
                    g.node(cid, kind="calc_column", name=f"{t['name']}[{c['name']}]", group=a["name"], table=t["name"], description=c["description"], code=c["expr"], lang="dax", data_type=c["type"], **common)
                    g.edge(cid, nid, "column of", "dax")
                    wire_dax(cid, c["expr"], t["name"])
            for m in t["measures"]:
                mid = f"m:{ds_id}:{t['name']}[{m['name']}]"
                g.node(
                    mid,
                    kind="measure",
                    name=m["name"],
                    group=a["name"],
                    table=t["name"],
                    description=m["description"],
                    code=m["expr"],
                    lang="dax",
                    format=m["format"],
                    folder=m["folder"],
                    hidden=m["hidden"],
                    **common,
                )
                wire_dax(mid, m["expr"], t["name"])

    report_summaries: list[dict] = []
    _add_report_measures(g, store, state, model_ctx, report_summaries)

    # Drop edges to nodes that were never materialised (e.g. measure in an auto-date table)
    edges = [e for e in g.edges.values() if e["from"] in g.nodes and e["to"] in g.nodes]
    return {
        "schema": "pbi-e2e-lineage/1",
        "generated_at": utc_now_iso(),
        "models": sorted(model_summaries, key=lambda m: (m["workspace"].lower(), m["name"].lower())),
        "dataflows": sorted(dataflow_summaries, key=lambda d: (d["workspace"].lower(), d["name"].lower())),
        "reports": sorted(report_summaries, key=lambda r: (r["workspace"].lower(), r["name"].lower())),
        "nodes": g.nodes,
        "edges": edges,
    }


# ---------------------------------------------------------------------------
# Tracing & documentation
# ---------------------------------------------------------------------------
def trace_upstream(graph: dict, root_id: str) -> dict:
    """Return every node/edge the root depends on, with level (distance) and dataflow layer numbers."""
    adj: dict[str, list[dict]] = collections.defaultdict(list)
    for e in graph["edges"]:
        adj[e["from"]].append(e)
    nodes = graph["nodes"]
    if root_id not in nodes:
        raise KeyError(root_id)

    level = {root_id: 0}
    order = [root_id]
    frontier = [root_id]
    edges: list[dict] = []
    seen_edges = set()
    # Longest-path levels with a relaxation bound to stay safe on cyclic graphs
    for _ in range(len(nodes) + 1):
        nxt = []
        for nid in frontier:
            for e in adj.get(nid, []):
                if (e["from"], e["to"]) not in seen_edges:
                    seen_edges.add((e["from"], e["to"]))
                    edges.append(e)
                cand = level[nid] + 1
                if e["to"] not in level:
                    order.append(e["to"])
                if cand > level.get(e["to"], -1) and cand <= len(nodes):
                    level[e["to"]] = cand
                    nxt.append(e["to"])
        if not nxt:
            break
        frontier = list(dict.fromkeys(nxt))

    # Dataflow layers: 1 = consumed directly by the semantic model, 2 = feeds layer 1, ...
    df_layer: dict[str, int] = {}
    changed = True
    guard = 0
    while changed and guard < 50:
        changed = False
        guard += 1
        for e in edges:
            a, b = nodes[e["from"]], nodes[e["to"]]
            if b["kind"] != "dataflow_query":
                continue
            if a["kind"] != "dataflow_query":
                want = 1
            else:
                base = df_layer.get(a.get("group_id", ""), 1)
                want = base if a.get("group_id") == b.get("group_id") else base + 1
            gid = b.get("group_id", "")
            if want > df_layer.get(gid, 0):
                df_layer[gid] = want
                changed = True
    return {"root": root_id, "order": order, "level": level, "edges": edges, "dataflow_layer": df_layer}


def _fence(code: str, lang: str) -> str:
    body = (code or "").rstrip()
    ticks = "````" if "```" in body else "```"
    return f"{ticks}{lang}\n{body}\n{ticks}"


def _md_val(v: str) -> str:
    t = str(v or "")
    if re.match(r"(?i)^https?://", t):
        return f"[{t.replace('[', '').replace(']', '')}]({t.replace(' ', '%20').replace(')', '%29')})"
    return f"`{t}`"


def _step_lines(q: dict) -> list[str]:
    steps = q.get("steps") or []
    if not steps:
        return []
    out = ["", f"**Transformation steps ({len(steps)}):**", ""]
    for i, st in enumerate(steps, 1):
        out.append(f"- **{i}. {st['name']}** [{st['category_label']}] - {st['summary']}" + (" _(final output)_" if st.get("is_output") else ""))
        details = st.get("details") or []
        out += [f"  - {d}" for d in details[:15]]
        if len(details) > 15:
            out.append(f"  - ... {len(details) - 15} more")
    return out


def _md_escape(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def _mermaid_id(nid: str) -> str:
    return "n" + hashlib.sha1(nid.encode("utf-8")).hexdigest()[:10]


def _mermaid_label(n: dict) -> str:
    name = n.get("name", "")
    if n["kind"] == "measure":
        name = f"[{name}]"
    sub = n.get("group", "")
    return (f"{name}<br/><small>{KIND_LABEL.get(n['kind'], n['kind'])} - {sub}</small>").replace('"', "'")


def render_measure_doc_markdown(graph: dict, root_id: str) -> str:
    """Produce bottom-up measure documentation: sources/SQL -> dataflows -> dataset Power Query -> DAX."""
    tr = trace_upstream(graph, root_id)
    nodes = graph["nodes"]
    root = nodes[root_id]
    in_trace = [nodes[i] for i in tr["order"]]
    by_kind: dict[str, list[dict]] = collections.defaultdict(list)
    for n in in_trace:
        by_kind[n["kind"]].append(n)
    deps_of: dict[str, list[dict]] = collections.defaultdict(list)
    for e in tr["edges"]:
        deps_of[e["from"]].append(e)
    lvl = tr["level"]
    layers = tr["dataflow_layer"]

    title = f"[{root['name']}]" if root["kind"] == "measure" else root["name"]
    out: list[str] = [f"# Measure Documentation: {title}", ""]
    meta_rows = [
        ("Object type", KIND_LABEL.get(root["kind"], root["kind"])),
        ("Report (report-level measure)", root.get("report", "")),
        ("Semantic model", root.get("model", root.get("group", ""))),
        ("Workspace", root.get("workspace", "")),
        ("Home table", root.get("table", "")),
        ("Display folder", root.get("folder", "")),
        ("Format string", root.get("format", "")),
        ("Generated", graph.get("generated_at", "")),
    ]
    out += ["| Property | Value |", "|---|---|"] + [f"| {k} | {_md_escape(str(v))} |" for k, v in meta_rows if v]
    if root.get("description"):
        out += ["", f"> {root['description']}"]

    # Summary chain
    n_df = len({n.get("group_id") for n in by_kind["dataflow_query"]})
    out += [
        "",
        "## Summary",
        "",
        f"- **{len(by_kind['source'])}** data source object(s) / SQL script(s)",
        f"- **{len(by_kind['dataflow_query'])}** dataflow quer(ies) across **{n_df}** dataflow(s)"
        + (f" in **{max(layers.values())}** dataflow layer(s)" if layers else ""),
        f"- **{len(by_kind['expression'])}** dataset Power Query helper quer(ies)",
        f"- **{len(by_kind['table']) + len(by_kind['calc_table'])}** model table(s), **{len(by_kind['calc_column'])}** calculated column(s)",
        f"- **{len(by_kind['measure'])}** DAX measure(s) in the calculation chain (including this one)",
        "",
        "Data flows: **Sources** -> " + ("**Dataflows** -> " if n_df else "") + "**Dataset Power Query** -> **Model tables** -> **DAX**",
    ]

    # Reference map (Mermaid)
    out += ["", "## Reference Map", "", "```mermaid", "flowchart LR"]
    for n in in_trace:
        out.append(f'  {_mermaid_id(n["id"])}["{_mermaid_label(n)}"]')
    for e in tr["edges"]:
        out.append(f"  {_mermaid_id(e['to'])} --> {_mermaid_id(e['from'])}")
    out += ["```"]

    def dep_list(n: dict) -> list[str]:
        items = []
        for e in deps_of.get(n["id"], []):
            d = nodes[e["to"]]
            lbl = f" ({', '.join(e['labels'])})" if e["labels"] else ""
            items.append(f"  - {KIND_LABEL.get(d['kind'], d['kind'])}: **{d['name']}** - {d.get('group', '')}{lbl}")
        return ["- Depends on:", *items] if items else []

    # 1. Sources
    out += ["", "## 1. Source Systems & SQL Scripts", ""]
    if not by_kind["source"]:
        out.append("_No physical source detected (data may be entered manually or come from an unscanned dataflow)._")
    sec_of: dict[str, str] = {}
    for i, n in enumerate(sorted(by_kind["source"], key=lambda x: (x.get("source_type", ""), x["name"])), 1):
        sec_of[n["id"]] = f"1.{i}"
        out += [f"### 1.{i} {n.get('source_type', 'Source')}: {n['name']}", ""]
        for k, v in (("Server / endpoint", n.get("server")), ("Database", n.get("database")), ("Object / sheet", n.get("object"))):
            if v:
                out.append(f"- **{k}:** {_md_val(v)}")
        for f in n.get("files") or []:
            out.append(f"- **File:** {_md_val(f)}")
        consumers = sorted({nodes[e["from"]]["name"] for e in tr["edges"] if e["to"] == n["id"]})
        if consumers:
            out.append(f"- **Read by:** {', '.join(consumers)}")
        if n.get("sql_parameters"):
            out.append("- **Parameters inserted by Power Query:** " + ", ".join(f"`{{{{{x}}}}}`" for x in n["sql_parameters"]))
        if n.get("code"):
            out += ["", "**Native SQL:**", "", _fence(n["code"], "sql")]
        out.append("")

    def sql_refs(q: dict) -> list[str]:
        return [
            f"- **Native SQL:** see section {sec_of[x['source_id']]} ("
            + " \u00b7 ".join(v for v in (x.get("connector"), x.get("database")) if v)
            + (f", via {x['via']}" if x.get("via") else "") + ")"
            for x in q.get("sql") or [] if x.get("source_id") in sec_of
        ]

    # 2. Dataflows (deepest layer first)
    out += ["## 2. Dataflow Transformations (Power Query in Dataflows Gen1)", ""]
    if not by_kind["dataflow_query"]:
        out.append("_This measure does not depend on any dataflow._")
    by_df: dict[str, list[dict]] = collections.defaultdict(list)
    for n in by_kind["dataflow_query"]:
        by_df[n.get("group_id", "")].append(n)
    for i, (gid, qs) in enumerate(sorted(by_df.items(), key=lambda kv: (-layers.get(kv[0], 1), kv[1][0].get("group", ""))), 1):
        layer = layers.get(gid, 1)
        out += [f"### 2.{i} Dataflow (layer {layer}): {qs[0].get('group', '')}", "", f"- **Workspace:** {qs[0].get('workspace', '')}", f"- **Dataflow id:** `{gid}`", ""]
        for q in sorted(qs, key=lambda x: -lvl.get(x["id"], 0)):
            out += [f"#### {q['name']} ({q.get('role', 'Query')})", ""]
            if q.get("external"):
                out += [f"_Definition not available: {q.get('note', '')}_", ""]
                continue
            if q.get("description"):
                out += [f"> {q['description']}", ""]
            out += dep_list(q)
            if q.get("parameters"):
                out.append("- Parameters: " + ", ".join(f"`{k}` = `{v}`" for k, v in q["parameters"].items()))
            if q.get("columns"):
                out.append("- Output columns: " + ", ".join(f"`{c['name']}` ({c['type']})" for c in q["columns"]))
            out += sql_refs(q) + _step_lines(q)
            if q.get("code"):
                out += ["", "**Power Query (M):**", "", _fence(q["code"], "powerquery")]
            elif q.get("role") == "Linked entity":
                out += ["", "_Linked entity: reads the upstream dataflow entity listed above (no Power Query of its own)._"]
            out.append("")

    # 3. Dataset Power Query
    out += ["## 3. Semantic Model Power Query (Dataset Tables & Queries)", ""]
    pq_nodes = sorted(by_kind["expression"], key=lambda x: -lvl.get(x["id"], 0)) + sorted(
        [n for n in by_kind["table"]], key=lambda x: -lvl.get(x["id"], 0)
    )
    if not pq_nodes:
        out.append("_No Power Query tables involved._")
    for i, n in enumerate(pq_nodes, 1):
        label = "Shared query" if n["kind"] == "expression" else f"Table ({n.get('storage_mode', 'import')} mode)"
        out += [f"### 3.{i} {n['name']} - {label}", "", f"- **Model:** {n.get('model', '')}"]
        out += dep_list(n)
        out += sql_refs(n) + _step_lines(n)
        if n.get("code"):
            out += ["", "**Power Query (M):**", "", _fence(n["code"], "powerquery")]
        out.append("")

    # 4. Tables & columns used
    out += ["## 4. Model Tables & Columns Used", "", "| Table | Columns referenced by DAX | Storage |", "|---|---|---|"]
    for n in sorted(by_kind["table"] + by_kind["calc_table"], key=lambda x: x["name"].lower()):
        cols = sorted({lbl for e in tr["edges"] if e["to"] == n["id"] for lbl in e["labels"] if "[" in lbl})
        out.append(f"| {_md_escape(n['name'])} | {_md_escape(', '.join(cols) or '-')} | {n.get('storage_mode', 'calculated' if n['kind'] == 'calc_table' else '')} |")
    for n in by_kind["calc_table"]:
        out += ["", f"**Calculated table {n['name']}:**", "", _fence(n.get("code", ""), "dax")]
    for n in by_kind["calc_column"]:
        out += ["", f"**Calculated column {n['name']}:**", "", _fence(n.get("code", ""), "dax")]

    # 5. DAX chain (leaves first, root last)
    out += ["", "## 5. DAX Calculation Chain", "", "Measures are listed from base calculations to the final measure.", ""]
    for i, n in enumerate(sorted(by_kind["measure"], key=lambda x: (-lvl.get(x["id"], 0), x["name"].lower())), 1):
        is_root = n["id"] == root_id
        out += [f"### 5.{i} [{n['name']}]" + (" (documented measure)" if is_root else ""), ""]
        bits = [f"Table: `{n.get('table', '')}`"]
        if n.get("format"):
            bits.append(f"Format: `{n['format']}`")
        if n.get("folder"):
            bits.append(f"Folder: `{n['folder']}`")
        out.append(" | ".join(bits))
        if n.get("description"):
            out += ["", f"> {n['description']}"]
        out += [""] + dep_list(n) + ["", _fence(n.get("code", ""), "dax"), ""]
    return "\n".join(out).rstrip() + "\n"


def find_nodes(graph: dict, query: str, kind: str = "", model: str = "") -> list[dict]:
    """Case-insensitive lookup by name (exact matches first)."""
    q = (query or "").strip().lower().strip("[]")
    hits = []
    for n in graph["nodes"].values():
        if kind and n["kind"] != kind:
            continue
        if model and model.lower() not in (n.get("model") or n.get("group") or "").lower():
            continue
        nm = (n.get("name") or "").lower()
        if q in nm or q == n["id"].lower():
            hits.append((0 if nm == q else 1, nm, n))
    return [h[2] for h in sorted(hits, key=lambda h: (h[0], h[1]))]
