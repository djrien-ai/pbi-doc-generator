"""
End-to-End Cross-Workspace Lineage Graph & Measure Documentation Generator.

Traces complete calculation and ETL chains from consumer to physical source:
Report Visual / Thin-Report DAX -> Model DAX Measures -> Calculated Columns / Tables ->
Dataset Power Query / Direct Lake -> Fabric Lakehouse / Dataflow Gen2 / Dataflow Gen1 (multi-layer L1..Ln) ->
Physical Source Systems & Native SQL Scripts.

Edges point from consumer to provider ("X depends on Y").
"""

from __future__ import annotations

import collections
import hashlib
import re
from typing import Any

from .analyzer import analyze_full_model, analyze_m_partition
from .dataflows import DATAFLOW_CONNECTOR_RE, find_dataflow_refs, parse_dataflow_definition
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
    """Remove DAX strings and comments so references inside literals/comments are ignored."""
    s = re.sub(r"//[^\n]*|--[^\n]*", " ", expr or "")
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r'"(?:[^"]|"")*"', '""', s)


_TBL_COL_RE = re.compile(r"('(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_]*)\s*\[([^\]]+)\]")
_BARE_RE = re.compile(r"(?<![A-Za-z0-9_'\]])\[([^\]]+)\]")
_QUOTED_TBL_RE = re.compile(r"'((?:[^']|'')+)'(?!\s*\[)")
_IDENT_RE = re.compile(r"(?<![\w.'\[])([A-Za-z_][A-Za-z0-9_]*)(?![\w'\[(])(?!\s*\()")


def dax_references(
    expr: str,
    host_table: str,
    tables: dict[str, dict],
    measure_by_bare: dict[str, str],
    measure_by_qual: dict[tuple[str, str], str] | None = None,
    row_context: bool = False,
) -> dict:
    """Find measures, columns `(table, column)`, and whole tables referenced by a DAX expression."""
    s = _strip_dax_noise(expr)
    measures: set[str] = set()
    columns: set[tuple[str, str]] = set()
    whole_tables: set[str] = set()
    lower_tables = {t.lower(): t for t in tables}
    qual = measure_by_qual or {}
    host_low = (host_table or "").lower()
    spans_blank: list[tuple[int, int]] = []

    for m in _TBL_COL_RE.finditer(s):
        raw_t = m.group(1)
        tname = raw_t[1:-1].replace("''", "'") if raw_t.startswith("'") else raw_t
        real_t = lower_tables.get(tname.lower())
        if not raw_t.startswith("'") and not real_t:
            continue
        spans_blank.append(m.span())
        if not real_t:
            continue
        col = m.group(2).strip()
        mkey = qual.get((real_t.lower(), col.lower()))
        if not mkey:
            cand = measure_by_bare.get(col.lower())
            if cand and re.sub(r"^rpt:[^:]+:", "", cand).lower().startswith(f"{real_t.lower()}["):
                mkey = cand
        if mkey:
            measures.add(mkey)
        else:
            columns.add((real_t, col))

    if spans_blank:
        ch_arr = list(s)
        for s_i, e_i in spans_blank:
            for k_i in range(s_i, e_i):
                ch_arr[k_i] = " "
        rest = "".join(ch_arr)
    else:
        rest = s

    for m in _BARE_RE.finditer(rest):
        ref = m.group(1).strip()
        if row_context and host_table in tables and any(c["name"].lower() == ref.lower() for c in tables[host_table]["columns"]):
            columns.add((host_table, ref))
            continue
        mkey = qual.get((host_low, ref.lower())) or measure_by_bare.get(ref.lower())
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
        if real_t and m.group(1).upper() not in ("VAR", "RETURN", "TRUE", "FALSE", "BLANK"):
            whole_tables.add(real_t)
    return {"measures": measures, "columns": columns, "tables": whole_tables}


class _GraphBuilder:
    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: dict[tuple[str, str], dict] = {}

    def node(self, nid: str, **fields: Any) -> dict:
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

    def source_node(
        self,
        kind_label: str,
        endpoint: str,
        database: str = "",
        obj: str = "",
        sql: str = "",
        files: list[str] | None = None,
    ) -> str:
        sig = "|".join([kind_label, endpoint, database, obj, sql.strip()]).lower()
        nid = "s:" + hashlib.sha1(sig.encode("utf-8")).hexdigest()[:14]
        sql_from = re.search(
            r'(?is)\bfrom\s+((?:"[^"]+"|\[[^\]]+\]|`[^`]+`|[\w$#]+)(?:\s*\.\s*(?:"[^"]+"|\[[^\]]+\]|`[^`]+`|[\w$#]+))*)',
            sql or "",
        )
        sql_title = f"SQL: {sql_from.group(1)}" if sql_from else ("Native SQL query" if sql else "")
        title = (
            obj
            or sql_title
            or (files[0].replace("\\", "/").rsplit("/", 1)[-1] if files else "")
            or database
            or endpoint
            or kind_label
        )
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

    def add_m_sources(self, consumer: str, info: dict) -> list[str]:
        """Turn analyzed M sources + native SQL into source nodes linked from `consumer`."""
        endpoints = info.get("endpoints") or []
        objects = info.get("objects") or []
        obj = ", ".join(objects)
        db_labels = {e.get("label") for e in endpoints}
        sql_eps = set()
        sql_ids: list[str] = []
        for q in info.get("native_sql") or []:
            nid = self.source_node(
                q.get("connector") or "Native SQL",
                q.get("server", ""),
                q.get("database", ""),
                "",
                q["sql"],
            )
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
                continue
            if s["type"] == "Entered Data (Manual Table)":
                nid = self.source_node("Entered Data (Manual Table)", "", "", "Rows typed into Power Query (Enter data)", "")
                self.edge(consumer, nid, "entered data", "source")
                continue
            if s["type"] == "Web API" and any(
                t in (info.get("source_types") or []) for t in ("Excel", "CSV", "JSON", "Parquet", "XML")
            ):
                continue
            files = (
                [f for f in info.get("files") or []]
                if s["type"] in ("Excel", "CSV", "File", "SharePoint", "JSON", "Parquet", "XML", "Folder")
                else []
            )
            sheet = ", ".join(info.get("sheets") or [])
            detail = s["detail"]
            if detail in ("Web.Contents", "File.Contents") and files:
                detail = files[0]
            nid = self.source_node(s["type"], detail, "", sheet or ("" if files else obj), "", files)
            self.edge(consumer, nid, sheet or obj or "reads", "source")
        return sql_ids


def _sql_entries(native: list[dict] | None, source_ids: list[str]) -> list[dict]:
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
        st.pop("code", None)
    return steps


def _wire_dax(
    g: _GraphBuilder,
    ds_id: str,
    tables: dict,
    measure_by_bare: dict,
    measure_by_qual: dict,
    nid: str,
    expr: str,
    host: str,
    row_context: bool = False,
) -> None:
    refs = dax_references(expr, host, tables, measure_by_bare, measure_by_qual, row_context=row_context)
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


def _add_report_measures(
    g: _GraphBuilder,
    store: CatalogStore,
    state: dict,
    model_ctx: dict,
    report_summaries: list,
) -> None:
    """Wire thin-report DAX measures into the shared semantic model they connect to (collision-safe)."""
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
        bare_idx = dict((ctx or {}).get("measure_by_bare") or {})
        qual_idx = dict((ctx or {}).get("measure_by_qual") or {})

        keys_by_pair: dict[tuple[str, str], str] = {}
        for m in measures:
            t_nm = m.get("table") or "Report Measures"
            m_nm = m["name"]
            key = f"rpt:{rid}:{t_nm}[{m_nm}]"
            keys_by_pair[(t_nm.lower(), m_nm.lower())] = key
            qual_idx[(t_nm.lower(), m_nm.lower())] = key
            bare_idx.setdefault(m_nm.lower(), key)

        report_summaries.append(
            {
                "id": rid,
                "name": rep.get("name", ""),
                "workspace": rep.get("workspace", ""),
                "model": model_name,
                "measures": len(measures),
                "model_scanned": bool(ctx),
            }
        )
        cross = (rep.get("workspace_id") or "") != (
            ds_meta.get("workspace_id") or rep.get("dataset_workspace_id") or rep.get("workspace_id") or ""
        )
        for m in measures:
            t_nm = m.get("table") or "Report Measures"
            m_nm = m["name"]
            m_key = keys_by_pair[(t_nm.lower(), m_nm.lower())]
            mid = f"m:{ds_id}:{m_key}"
            g.node(
                mid,
                kind="measure",
                name=m_nm,
                group=rep.get("name", "Report"),
                table=t_nm,
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
            _wire_dax(g, ds_id, tables, bare_idx, qual_idx, mid, m.get("expr", ""), t_nm if t_nm in tables else "")


def build_e2e_graph(store: CatalogStore, analyses: list[dict] | None = None) -> dict:
    """Build the full cross-model, cross-dataflow (Gen1 & Gen2), Direct Lake lineage graph from the local catalog."""
    state = store.load_scoped()
    g = _GraphBuilder()
    dataflow_summaries: list[dict] = []
    model_summaries: list[dict] = []

    # ---------------- Dataflows (Gen1 & Gen2) ----------------
    parsed_dfs: dict[str, dict] = {}
    gen2_dest_by_table: dict[str, list[str]] = collections.defaultdict(list)

    for df_id, df_meta in state.get("dataflows", {}).items():
        definition = store.read_dataflow_definition(df_id)
        if not definition:
            # Support catalog entries populated directly with pre-parsed entities (e.g. demo or lightweight state)
            if df_meta.get("entities"):
                synth_queries = []
                for ent in df_meta["entities"]:
                    minfo = analyze_m_partition(ent.get("m_code", ""), {}, [])
                    synth_queries.append(
                        {
                            "name": ent.get("name", ""),
                            "kind": "query",
                            "role": ent.get("role", "Entity"),
                            "load_enabled": True,
                            "description": ent.get("description", ""),
                            "code": ent.get("m_code", ""),
                            "depends_on": minfo["depends_on"],
                            "parameters": [],
                            "dataflow_refs": ent.get("dataflow_refs") or minfo["dataflow_refs"],
                            "source_types": ent.get("source_types") or minfo["source_types"],
                            "sources": minfo["sources"],
                            "endpoints": minfo["endpoints"],
                            "files": minfo["files"],
                            "sheets": minfo["sheets"],
                            "objects": minfo["objects"],
                            "native_queries": minfo["native_queries"],
                            "native_sql": ent.get("native_sql") or minfo["native_sql"],
                            "step_count": ent.get("pq_steps") or minfo["step_count"],
                            "columns": ent.get("columns", []),
                            "destination": ent.get("destination"),
                        }
                    )
                pdf = {
                    "id": df_id,
                    "name": df_meta.get("name", df_id),
                    "workspace": df_meta.get("workspace", ""),
                    "generation": str(df_meta.get("generation") or "Gen1"),
                    "parameters": {},
                    "queries": synth_queries,
                }
                parsed_dfs[df_id.lower()] = pdf
                dataflow_summaries.append(
                    {
                        "id": df_id,
                        "name": pdf["name"],
                        "workspace": pdf["workspace"],
                        "generation": pdf["generation"],
                        "status": "ok",
                        "queries": len(synth_queries),
                    }
                )
            else:
                dataflow_summaries.append(
                    {
                        "id": df_id,
                        "name": df_meta.get("name", df_id),
                        "workspace": df_meta.get("workspace", ""),
                        "generation": str(df_meta.get("generation") or "Gen1"),
                        "status": df_meta.get("definition_status", "pending"),
                        "queries": 0,
                    }
                )
            continue

        pdf = parse_dataflow_definition(df_meta, definition)
        parsed_dfs[df_id.lower()] = pdf
        dataflow_summaries.append(
            {
                "id": df_id,
                "name": pdf["name"],
                "workspace": pdf["workspace"],
                "generation": pdf.get("generation", "Gen1"),
                "status": "ok",
                "queries": len(pdf["queries"]),
            }
        )

    def df_query_id(df_id: str, qname: str) -> str:
        return f"q:{df_id.lower()}:{qname}"

    def resolve_df_ref(ref: dict) -> str:
        df_id = (ref.get("dataflow_id") or "").lower()
        ent = ref.get("entity") or ""
        pdf = parsed_dfs.get(df_id)
        if not pdf and ent and not df_id:
            for cand_id, cand_pdf in parsed_dfs.items():
                if any(x["name"].lower() == ent.lower() for x in cand_pdf["queries"]):
                    df_id, pdf = cand_id, cand_pdf
                    break
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
                generation=pdf.get("generation", "Gen1"),
                role=q["role"],
                description=q["description"],
                code=q["code"],
                lang="m",
                columns=q["columns"],
                parameters={p: pdf["parameters"].get(p, "") for p in q.get("parameters", [])},
                step_count=q["step_count"],
                source_types=q["source_types"],
                destination=q.get("destination"),
                steps=_steps_with_ids(q["code"], list(q_by_name), lambda n, d=df_id: df_query_id(d, n)) if q["code"] else [],
            )
            if q.get("destination") and isinstance(q["destination"], dict) and q["destination"].get("table"):
                gen2_dest_by_table[q["destination"]["table"].lower()].append(nid)
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
            rep_with_lay = dict(rep)
            if "layout" not in rep_with_lay:
                lay = store.read_report_layout(rep["id"])
                if lay:
                    rep_with_lay["layout"] = lay
            reports_by_ds[rep["dataset_id"]].append(rep_with_lay)

    links = state.get("dataset_dataflow_links") or {}
    if analyses is None:
        analyses = []
        for ds_id, m_meta in state.get("models", {}).items():
            bundle = store.read_tmdl_bundle(m_meta.get("name", ""), ds_id)
            if bundle:
                analyses.append(
                    analyze_full_model(
                        m_meta,
                        bundle,
                        reports=reports_by_ds.get(ds_id, []),
                        dataflows=state.get("dataflows", {}),
                        fabric_items=state.get("fabric_items", {}),
                        dataset_dataflow_links=links.get(ds_id, []),
                    )
                )

    model_ctx: dict[str, dict] = {}
    for a in analyses:
        ds_id = a["dataset_id"]
        parsed = a["parsed"]
        tables = {t["name"]: t for t in parsed["tables"] if not t["auto_date"]}
        params = {x["name"]: x["default_value"] for x in parsed["expressions"] if x["kind"] == "parameter"}
        expr_names = [x["name"] for x in parsed["expressions"] if x["kind"] != "parameter"]
        measure_by_bare: dict[str, str] = {}
        measure_by_qual: dict[tuple[str, str], str] = {}
        for t in tables.values():
            for m in t["measures"]:
                mk = f"{t['name']}[{m['name']}]"
                measure_by_bare[m["name"].lower()] = mk
                measure_by_qual[(t["name"].lower(), m["name"].lower())] = mk

        linked_dfs = [ln.get("dataflow_id", "").lower() for ln in links.get(ds_id, []) if ln.get("dataflow_id")]
        model_summaries.append(
            {
                "id": ds_id,
                "name": a["name"],
                "workspace": a["workspace"],
                "measures": a["stats"]["measures"],
                "tables": a["stats"]["tables"],
            }
        )
        common = {"model": a["name"], "model_id": ds_id, "workspace": a["workspace"]}

        def tid(tname: str, _ds: str = ds_id) -> str:
            return f"t:{_ds}:{tname}"

        model_ctx[ds_id] = {
            "name": a["name"],
            "tables": tables,
            "measure_by_bare": dict(measure_by_bare),
            "measure_by_qual": dict(measure_by_qual),
        }

        def wire_dax(
            nid: str,
            expr: str,
            host: str,
            row_context: bool = False,
            _ds: str = ds_id,
            _t: dict = tables,
            _mb: dict = measure_by_bare,
            _mq: dict = measure_by_qual,
        ) -> None:
            _wire_dax(g, _ds, _t, _mb, _mq, nid, expr, host, row_context=row_context)

        m_table_names = [t["name"] for t in tables.values() if any(p["kind"] == "m" for p in t["partitions"])]

        def wire_m(
            nid: str,
            code: str,
            own_name: str,
            _ds: str = ds_id,
            _params: dict = params,
            _exprs: list = expr_names,
            _mtbls: list = m_table_names,
            _ldfs: list = linked_dfs,
        ) -> dict:
            info = analyze_m_partition(code, _params, [n for n in _exprs if n != own_name])
            for dep in info["depends_on"]:
                if dep in _exprs:
                    g.edge(nid, f"e:{_ds}:{dep}", "references query", "query")
            for other in _mtbls:
                if other != own_name and re.search(
                    r'(?<![\w."#])(?:#"' + re.escape(other) + r'"|' + re.escape(other) + r')(?![\w".(])',
                    code or "",
                ):
                    g.edge(nid, tid(other, _ds), "references table query", "query")
            refs = find_dataflow_refs(code, _params)
            for ref in refs:
                if ref["dataflow_id"].startswith("{param:") and len(_ldfs) == 1:
                    ref = {**ref, "dataflow_id": _ldfs[0]}
                g.edge(nid, resolve_df_ref(ref), "loads dataflow entity", "dataflow")
            if not refs and DATAFLOW_CONNECTOR_RE.search(code or "") and _ldfs:
                for df_id in _ldfs:
                    g.edge(nid, resolve_df_ref({"dataflow_id": df_id, "entity": own_name}), "loads dataflow (REST link)", "dataflow")
            sql_ids = g.add_m_sources(nid, info)
            node = g.nodes[nid]
            node["sql"] = (node.get("sql") or []) + _sql_entries(info.get("native_sql"), sql_ids)
            if not node.get("steps") and (node.get("code") or "").startswith(code or "\0"):
                node["steps"] = _steps_with_ids(
                    code,
                    _exprs + [t for t in _mtbls if t != own_name],
                    lambda n, __ds=_ds, __ex=_exprs: f"e:{__ds}:{n}" if n in __ex else tid(n, __ds),
                )
            return info

        for x in parsed["expressions"]:
            if x["kind"] == "parameter":
                continue
            nid = f"e:{ds_id}:{x['name']}"
            g.node(
                nid,
                kind="expression",
                name=x["name"],
                group=a["name"],
                role=x["kind"].title(),
                description=x["description"],
                code=x["code"],
                lang="m",
                **common,
            )
            wire_m(nid, x["code"], x["name"])

        for t in tables.values():
            nid = tid(t["name"], ds_id)
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
                hierarchies=[h["name"] for h in t.get("hierarchies", [])],
                columns=[
                    {
                        "name": c["name"],
                        "type": c["type"],
                        "source": c["source"],
                        "format": c.get("format", ""),
                        "expr": c.get("expr", ""),
                        "calculated": bool(c["expr"]),
                        "usage": (c.get("usage") or {}).get("summary", "-"),
                    }
                    for c in t["columns"]
                ],
                **common,
            )
            for p in m_parts:
                wire_m(nid, p["code"], t["name"])
            for p in calc_parts:
                wire_dax(nid, p["code"], t["name"])
            for p in parts:
                if p["kind"] == "entity":
                    ent_target = p.get("entity_name") or p["name"] or t["name"]
                    dl_obj = f"{p.get('schema_name')}.{ent_target}" if p.get("schema_name") else ent_target
                    matched_gen2 = gen2_dest_by_table.get(ent_target.lower()) or gen2_dest_by_table.get(t["name"].lower())
                    if matched_gen2:
                        for q_nid in matched_gen2:
                            g.edge(nid, q_nid, f"Direct Lake ({dl_obj})", "dataflow")
                    else:
                        src = g.source_node("Direct Lake / OneLake", p.get("expression_source") or "", "", dl_obj, "")
                        g.edge(nid, src, "Direct Lake entity", "source")

            for c in t["columns"]:
                if c.get("expr"):
                    cid = f"c:{ds_id}:{t['name']}[{c['name']}]"
                    g.node(
                        cid,
                        kind="calc_column",
                        name=f"{t['name']}[{c['name']}]",
                        group=a["name"],
                        table=t["name"],
                        description=c["description"],
                        code=c["expr"],
                        lang="dax",
                        data_type=c["type"],
                        **common,
                    )
                    g.edge(cid, nid, "column of", "dax")
                    wire_dax(cid, c["expr"], t["name"], row_context=True)

            for m in t["measures"]:
                mid = f"m:{ds_id}:{t['name']}[{m['name']}]"
                usage = (a["lineage"].get(f"{t['name']}[{m['name']}]") or {}).get("used_in_reports", [])
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
                    used_in_reports=usage,
                    **common,
                )
                wire_dax(mid, m["expr"], t["name"])

    report_summaries: list[dict] = []
    _add_report_measures(g, store, state, model_ctx, report_summaries)

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


_RESOLVE_INDEX_CACHE: dict[tuple[int, int], tuple[dict, dict]] = {}


def _get_resolve_index(nodes: dict) -> dict:
    cache_key = (id(nodes), len(nodes))
    hit = _RESOLVE_INDEX_CACHE.get(cache_key)
    if hit is not None and hit[0] is nodes:
        return hit[1]

    rpt_measures: dict[tuple[str, str], str] = {}
    ds_measures_tbl: dict[tuple[str, str, str], str] = {}
    ds_measures_model: dict[tuple[str, str], str] = {}
    ds_measures_any: dict[tuple[str, str], str] = {}
    ds_tables: dict[str, list[tuple[str, dict]]] = collections.defaultdict(list)

    for nid, n in nodes.items():
        k = n.get("kind")
        mid = n.get("model_id") or ""
        if k == "measure":
            nm_low = (n.get("name") or "").lower()
            rid = n.get("report_id") or ""
            if rid:
                rpt_measures.setdefault((rid, nm_low), nid)
                if mid:
                    ds_measures_any.setdefault((mid, nm_low), nid)
            elif mid:
                tbl_low = (n.get("table") or "").lower()
                ds_measures_tbl.setdefault((mid, tbl_low, nm_low), nid)
                ds_measures_model.setdefault((mid, nm_low), nid)
                ds_measures_any[(mid, nm_low)] = nid
        elif k in ("table", "calc_table") and mid:
            ds_tables[mid].append((nid, n))

    idx = {
        "rpt_measures": rpt_measures,
        "ds_measures_tbl": ds_measures_tbl,
        "ds_measures_model": ds_measures_model,
        "ds_measures_any": ds_measures_any,
        "ds_tables": ds_tables,
    }
    if len(_RESOLVE_INDEX_CACHE) >= 4:
        _RESOLVE_INDEX_CACHE.clear()
    _RESOLVE_INDEX_CACHE[cache_key] = (nodes, idx)
    return idx


def resolve_field_node_id(
    graph: dict,
    arg1: dict | str,
    arg2: str | dict = "",
    arg3: str = "",
    arg4: str = "column",
    report_id: str = "",
) -> str | None:
    """Resolve a report visual field to its exact E2E lineage node ID (verifying column existence).

    Supports flexible call signatures:
      - resolve_field_node_id(graph, field_dict, dataset_id, report_id="")
      - resolve_field_node_id(graph, dataset_id, field_dict, report_id="")
      - resolve_field_node_id(graph, dataset_id, entity_str, property_str, kind="column", report_id="")
    """
    if isinstance(arg1, dict):
        field = arg1
        dataset_id = str(arg2 or "")
    elif isinstance(arg2, dict):
        dataset_id = str(arg1 or "")
        field = arg2
    else:
        dataset_id = str(arg1 or "")
        field = {"entity": str(arg2 or ""), "property": str(arg3 or ""), "kind": str(arg4 or "column")}

    nodes = graph.get("nodes") or {}
    tname = (field.get("entity") or field.get("table") or "").strip()
    prop = (field.get("property") or field.get("name") or "").strip()
    kind = (field.get("kind") or "column").lower()
    if not prop or not dataset_id:
        return None

    prop_low = prop.lower()
    tname_low = tname.lower()
    idx = _get_resolve_index(nodes)

    # 1. Thin-report measure check first (O(1))
    if report_id:
        rpt_cand = f"m:{dataset_id}:rpt:{report_id}:{tname}[{prop}]"
        if rpt_cand in nodes:
            return rpt_cand
        rpt_hit = idx["rpt_measures"].get((report_id, prop_low))
        if rpt_hit:
            return rpt_hit

    # 2. Model measure check (O(1) exact table first, then bare measure name in same dataset)
    if tname:
        m_exact = f"m:{dataset_id}:{tname}[{prop}]"
        if m_exact in nodes:
            return m_exact
        tbl_hit = idx["ds_measures_tbl"].get((dataset_id, tname_low, prop_low))
        if tbl_hit:
            return tbl_hit
    else:
        mdl_hit = idx["ds_measures_model"].get((dataset_id, prop_low))
        if mdl_hit:
            return mdl_hit

    if kind == "measure":
        return idx["ds_measures_any"].get((dataset_id, prop_low))

    # 3. Calculated column or verified physical column / hierarchy on model table (scoped to dataset_id tables only)
    for nid, n in idx["ds_tables"].get(dataset_id, ()):
        if tname and (n.get("name") or "").lower() != tname_low:
            continue
        real_t = n.get("name") or ""
        cc_id = f"c:{dataset_id}:{real_t}[{prop}]"
        if cc_id in nodes:
            return cc_id
        for c in n.get("columns") or []:
            if (c.get("name") or "").lower() == prop_low:
                c_exact = f"c:{dataset_id}:{real_t}[{c['name']}]"
                return c_exact if c_exact in nodes else nid
        if kind == "hierarchy" or prop_low in {"year", "quarter", "month", "day", "date"}:
            if any(h.lower() == prop_low for h in (n.get("hierarchies") or [])) or prop_low in {
                "year",
                "quarter",
                "month",
                "day",
                "date",
            }:
                return nid
    return None


# ---------------------------------------------------------------------------
# Tracing & Markdown Documentation Export
# ---------------------------------------------------------------------------
def trace_upstream(graph: dict, root_id: str) -> dict:
    """Return every upstream node and edge `root_id` depends on, with distance levels and dataflow layers."""
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
        out.append(
            f"- **{i}. {st['name']}** [{st['category_label']}] - {st['summary']}"
            + (" _(final output)_" if st.get("is_output") else "")
        )
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
    return (f"{name}<br/>{KIND_LABEL.get(n['kind'], n['kind'])} - {sub}").replace('"', "'")


def render_measure_doc_markdown(graph: dict, root_id: str) -> str:
    """Produce bottom-up end-to-end documentation: Sources/SQL -> Dataflows -> Dataset Power Query -> Tables -> DAX."""
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
        "Data flows: **Sources** -> " + ("**Dataflows** -> " if n_df else "") + "**Dataset Power Query / Direct Lake** -> **Model tables** -> **DAX**",
    ]

    if root.get("used_in_reports"):
        out += ["", "**Referenced in scanned reports:**"]
        for u in root["used_in_reports"]:
            pgs = ", ".join(u.get("pages") or [])
            out.append(f"- **{u.get('report_name', 'Report')}** ({u.get('visual_count', 0)} visual(s): {pgs})")

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

    out += ["", "## 1. Source Systems & SQL Scripts", ""]
    if not by_kind["source"]:
        out.append("_No physical source detected (data may be entered manually or come from an unscanned dataflow)._")
    sec_of: dict[str, str] = {}
    for i, n in enumerate(sorted(by_kind["source"], key=lambda x: (x.get("source_type", ""), x["name"])), 1):
        sec_of[n["id"]] = f"1.{i}"
        out += [f"### 1.{i} {n.get('source_type', 'Source')}: {n['name']}", ""]
        for k, v in (
            ("Server / endpoint", n.get("server")),
            ("Database", n.get("database")),
            ("Object / sheet", n.get("object")),
        ):
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
            + " / ".join(v for v in (x.get("connector"), x.get("database")) if v)
            + (f", via {x['via']}" if x.get("via") else "")
            + ")"
            for x in q.get("sql") or []
            if x.get("source_id") in sec_of
        ]

    out += ["## 2. Dataflow Transformations (Gen1 & Gen2)", ""]
    if not by_kind["dataflow_query"]:
        out.append("_This measure does not depend on any dataflow._")
        out.append("")
    by_df: dict[str, list[dict]] = collections.defaultdict(list)
    for n in by_kind["dataflow_query"]:
        by_df[n.get("group_id", "")].append(n)
    for i, (gid, qs) in enumerate(
        sorted(by_df.items(), key=lambda kv: (-layers.get(kv[0], 1), kv[1][0].get("group", ""))),
        1,
    ):
        layer = layers.get(gid, 1)
        gen = qs[0].get("generation", "Gen1")
        out += [
            f"### 2.{i} Dataflow {gen} (layer {layer}): {qs[0].get('group', '')}",
            "",
            f"- **Workspace:** {qs[0].get('workspace', '')}",
            f"- **Dataflow id:** `{gid}`",
            "",
        ]
        for q in sorted(qs, key=lambda x: -lvl.get(x["id"], 0)):
            out += [f"#### {q['name']} ({q.get('role', 'Query')})", ""]
            if q.get("external"):
                out += [f"_Definition not available: {q.get('note', '')}_", ""]
                continue
            if q.get("description"):
                out += [f"> {q['description']}", ""]
            out += dep_list(q)
            if q.get("destination") and isinstance(q["destination"], dict):
                out.append(
                    f"- Output destination: **{q['destination'].get('kind', 'Lakehouse')}** table `{q['destination'].get('table', '')}`"
                )
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

    out += ["## 3. Semantic Model Power Query & Direct Lake Tables", ""]
    pq_nodes = sorted(by_kind["expression"], key=lambda x: -lvl.get(x["id"], 0)) + sorted(
        list(by_kind["table"]), key=lambda x: -lvl.get(x["id"], 0)
    )
    if not pq_nodes:
        out.append("_No Power Query or Direct Lake tables involved._")
        out.append("")
    for i, n in enumerate(pq_nodes, 1):
        label = "Shared query" if n["kind"] == "expression" else f"Table ({n.get('storage_mode', 'import')} mode)"
        out += [f"### 3.{i} {n['name']} - {label}", "", f"- **Model:** {n.get('model', '')}"]
        out += dep_list(n)
        out += sql_refs(n) + _step_lines(n)
        if n.get("code"):
            out += ["", "**Power Query (M):**", "", _fence(n["code"], "powerquery")]
        out.append("")

    out += ["## 4. Model Tables & Columns Used", "", "| Table | Columns referenced by DAX | Storage |", "|---|---|---|"]
    for n in sorted(by_kind["table"] + by_kind["calc_table"], key=lambda x: x["name"].lower()):
        cols = sorted({lbl for e in tr["edges"] if e["to"] == n["id"] for lbl in e["labels"] if "[" in lbl})
        out.append(
            f"| {_md_escape(n['name'])} | {_md_escape(', '.join(cols) or '-')} | "
            f"{n.get('storage_mode', 'calculated' if n['kind'] == 'calc_table' else '')} |"
        )
    for n in by_kind["calc_table"]:
        out += ["", f"**Calculated table {n['name']}:**", "", _fence(n.get("code", ""), "dax")]
    for n in by_kind["calc_column"]:
        out += ["", f"**Calculated column {n['name']}:**", "", _fence(n.get("code", ""), "dax")]

    if by_kind["measure"]:
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


def find_nodes(
    graph: dict,
    query: str,
    kind: str = "",
    model: str = "",
    kinds: list[str] | tuple[str, ...] | set[str] | None = None,
) -> list[dict]:
    """Case-insensitive lookup by name, Table[Measure], or node id (exact matches first)."""
    raw_q = (query or "").strip()
    q = raw_q.lower().strip("[]")
    if not q:
        return []
    allowed_kinds = set(kinds) if kinds else ({kind} if kind else set())
    hits = []
    for n in graph["nodes"].values():
        if allowed_kinds and n["kind"] not in allowed_kinds:
            continue
        if model and model.lower() not in (n.get("model") or n.get("group") or "").lower():
            continue
        nm = (n.get("name") or "").lower()
        tbl_qual = f"{(n.get('table') or '').lower()}[{nm}]" if n.get("table") else ""
        if raw_q.lower() == n["id"].lower() or (tbl_qual and raw_q.lower() == tbl_qual):
            hits.append((0, nm, n))
        elif nm == q:
            hits.append((1, nm, n))
        elif q in nm or (tbl_qual and q in tbl_qual):
            hits.append((2, nm, n))
    return [h[2] for h in sorted(hits, key=lambda h: (h[0], h[1]))]
