"""
Power BI Dataflow Gen1 parser.

A Gen1 dataflow export (`GET groups/{ws}/dataflows/{id}`) is a CDM `model.json` whose
`pbi:mashup.document` holds every Power Query of the dataflow as one M *section document*:

    section Section1;
    shared Customers = let Source = Sql.Database("srv", "db", [Query="select ..."]) in Source;
    shared #"Sales Linked" = let Source = PowerPlatform.Dataflows(null), ... {[entity="Sales"]}[Data] in ...;

This module splits that document into individual queries, classifies them (entity, computed
entity, linked entity, staging query, function, parameter), finds the queries / dataflows they
depend on, and extracts their physical sources (SQL server/database/native SQL, Excel files, ...).
The same dataflow-reference resolver is used for semantic model partitions so dataset tables can
be tied to the exact dataflow entity they load.
"""

from __future__ import annotations

import re

from .analyzer import analyze_m_partition
from .security import mask_secrets

DATAFLOW_CONNECTOR_RE = re.compile(r"\b(?:PowerPlatform|PowerBI)\.Dataflows\s*\(", re.I)
_DF_KEY_RE = re.compile(
    r'\b(workspaceId|dataflowId|entity)\s*=\s*(?:"((?:[^"]|"")*)"|#"((?:[^"]|"")*)"|([A-Za-z_][\w.]*))',
    re.I,
)
_GUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


# ---------------------------------------------------------------------------
# M section document splitting
# ---------------------------------------------------------------------------
def split_m_section(document: str) -> list[dict]:
    """Split an M section document into `{name, code, description}` members (string/comment aware)."""
    text = (document or "").replace("\r\n", "\n")
    # Drop the `section X;` header
    text = re.sub(r"^\s*section\s+[^;]+;", "", text, count=1)
    members: list[str] = []
    buf: list[str] = []
    depth = 0
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == '"':
            j = i + 1
            while j < n:
                if text[j] == '"':
                    if j + 1 < n and text[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            buf.append(text[i : j + 1])
            i = j + 1
            continue
        if ch == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            buf.append(text[i:j])
            i = j
            continue
        if ch == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            buf.append(text[i:j])
            i = j
            continue
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth = max(0, depth - 1)
        elif ch == ";" and depth == 0:
            members.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if "".join(buf).strip():
        members.append("".join(buf))

    out: list[dict] = []
    head_re = re.compile(r'^\s*(?:\[(?P<attrs>(?:[^\[\]"]|"(?:[^"]|"")*")*)\]\s*)?(?:shared\s+)?(?P<name>#"(?:[^"]|"")+"|[A-Za-z_][\w.]*)\s*=\s*', re.S)
    for raw in members:
        body = raw.strip()
        if not body:
            continue
        # Strip leading line comments so the header regex sees `shared X =`
        lead_comments = []
        while body.startswith("//") or body.startswith("/*"):
            if body.startswith("//"):
                line, _, body = body.partition("\n")
                lead_comments.append(line[2:].strip())
            else:
                cm, _, body = body.partition("*/")
                lead_comments.append(cm[2:].strip())
            body = body.lstrip()
        m = head_re.match(body)
        if not m:
            continue
        name = m.group("name")
        if name.startswith('#"'):
            name = name[2:-1].replace('""', '"')
        desc = ""
        attrs = m.group("attrs") or ""
        dm = re.search(r'Description\s*=\s*"((?:[^"]|"")*)"', attrs)
        if dm:
            desc = dm.group(1).replace('""', '"')
        elif lead_comments:
            desc = " ".join(c for c in lead_comments if c)
        out.append({"name": name, "code": body[m.end() :].strip(), "description": desc})
    return out


# ---------------------------------------------------------------------------
# Reference / source resolution (shared by dataflows and semantic models)
# ---------------------------------------------------------------------------
def _resolve_value(match: re.Match, params: dict[str, str]) -> str:
    lit = match.group(2)
    if lit is not None:
        return lit.replace('""', '"')
    ident = (match.group(3) or match.group(4) or "").replace('""', '"')
    if ident in params:
        return str(params[ident]).strip().strip('"')
    return f"{{param:{ident}}}"


def find_dataflow_refs(code: str, params: dict[str, str] | None = None) -> list[dict]:
    """Return `[{workspace_id, dataflow_id, entity}]` for every dataflow entity navigated in an M script."""
    src = code or ""
    if not DATAFLOW_CONNECTOR_RE.search(src) and "dataflowId" not in src:
        return []
    params = params or {}
    refs: list[dict] = []
    seen = set()
    ws_id = df_id = ""
    for m in _DF_KEY_RE.finditer(src):
        key = m.group(1).lower()
        val = _resolve_value(m, params)
        if key == "workspaceid":
            ws_id = val
        elif key == "dataflowid":
            df_id = val
        elif key == "entity":
            sig = (ws_id.lower(), df_id.lower(), val.lower())
            if sig not in seen:
                seen.add(sig)
                refs.append({"workspace_id": ws_id, "dataflow_id": df_id, "entity": val})
    if not refs and df_id:
        refs.append({"workspace_id": ws_id, "dataflow_id": df_id, "entity": ""})
    return refs


_SQL_ARGS_RE = re.compile(
    r'\b(Sql\.Databases?|AzureSql\.Database|PostgreSQL\.Database|MySQL\.Database|Oracle\.Database|Teradata\.Database|'
    r'Snowflake\.Databases|AmazonRedshift\.Database|Sql\.Endpoint|Fabric\.Warehouse|SapHana\.Database|'
    r'Databricks\.Catalogs|GoogleBigQuery\.Database|Odbc\.DataSource|Odbc\.Query|OleDb\.DataSource)\(\s*'
    r'(?:"((?:[^"]|"")*)"|([#\w".]+))\s*(?:,\s*(?:"((?:[^"]|"")*)"|([#\w".]+)))?',
)
DB_CONNECTOR_LABELS = {
    "Sql.Database": "SQL Server / Azure SQL", "Sql.Databases": "SQL Server / Azure SQL", "AzureSql.Database": "SQL Server / Azure SQL",
    "PostgreSQL.Database": "PostgreSQL", "MySQL.Database": "MySQL", "Oracle.Database": "Oracle", "Teradata.Database": "Teradata",
    "Snowflake.Databases": "Snowflake", "AmazonRedshift.Database": "Amazon Redshift", "Sql.Endpoint": "Microsoft Fabric",
    "Fabric.Warehouse": "Microsoft Fabric", "SapHana.Database": "SAP HANA", "Databricks.Catalogs": "Databricks",
    "GoogleBigQuery.Database": "BigQuery", "Odbc.DataSource": "ODBC", "Odbc.Query": "ODBC", "OleDb.DataSource": "OLE DB",
}
_FILE_URL_RE = re.compile(r'(?:File\.Contents|Web\.Contents|SharePoint\.(?:Files|Contents|Tables))\(\s*"((?:[^"]|"")*)"')


def _param_or_literal(lit: str | None, ident: str | None, params: dict[str, str]) -> str:
    if lit is not None:
        return lit.replace('""', '"')
    name = (ident or "").strip("#").strip('"')
    if not name:
        return ""
    return str(params.get(name, f"{{param:{name}}}"))


def describe_sources(code: str, params: dict[str, str], shared_names: list[str]) -> dict:
    """Run the core M analyzer and enrich it with server/database pairs, file paths, and native SQL."""
    info = analyze_m_partition(code, params, shared_names)
    src = code or ""
    from .mparse import extract_native_sql
    from .sql_format import format_sql

    endpoints: list[dict] = []
    for m in _SQL_ARGS_RE.finditer(src):
        server = mask_secrets(_param_or_literal(m.group(2), m.group(3), params))
        database = mask_secrets(_param_or_literal(m.group(4), m.group(5), params)) if (m.group(4) is not None or m.group(5)) else ""
        warehouse = ""
        if m.group(1) == "Snowflake.Databases":
            # Snowflake.Databases(account, warehouse){[Name="DB"]}[Data]
            warehouse, database = database, ""
            nav = re.search(r'\{\[\s*Name\s*=\s*"((?:[^"]|"")*)"', src[m.end() : m.end() + 400])
            if nav:
                database = nav.group(1)
        endpoints.append({"connector": m.group(1), "label": DB_CONNECTOR_LABELS.get(m.group(1), m.group(1)), "server": server,
                          "database": database, "warehouse": warehouse, "pos": m.start()})
    files = [mask_secrets(m.group(1).replace('""', '"')) for m in _FILE_URL_RE.finditer(src)]
    native = []
    for q in extract_native_sql(src):
        raw = mask_secrets(q["sql"])
        ep = max((e for e in endpoints if e["pos"] <= q["pos"]), key=lambda e: e["pos"], default=endpoints[0] if endpoints else None)
        native.append({"sql": format_sql(raw), "raw": raw, "via": q["via"], "parameters": q["parameters"], "pos": q["pos"],
                       "connector": (ep or {}).get("label", ""), "server": (ep or {}).get("server", ""), "database": (ep or {}).get("database", "")})
    info["native_sql"] = native
    info["native_queries"] = [n["sql"] for n in native]
    info["endpoints"] = endpoints
    info["files"] = list(dict.fromkeys(files))
    # Full navigation records, e.g. Source{[Schema="dbo",Item="DimProduct"]}[Data] -> "dbo/DimProduct"
    schema_objs: list[str] = []
    for rec in re.finditer(r'\{\[((?:[^\]"]|"(?:[^"]|"")*")*)\]\}', src):
        kv = {k.lower(): v.replace('""', '"') for k, v in re.findall(r'(\w+)\s*=\s*"((?:[^"]|"")*)"', rec.group(1))}
        if "schema" in kv and ("item" in kv or "name" in kv):
            schema_objs.append(f"{kv['schema']}/{kv.get('item') or kv.get('name')}")
    if schema_objs:
        info["objects"] = list(dict.fromkeys(schema_objs))
    # Excel / CSV sheet or item navigation (e.g. Source{[Item="Sheet1",Kind="Sheet"]}[Data])
    info["sheets"] = list(
        dict.fromkeys(m.group(1) for m in re.finditer(r'\{\[\s*Item\s*=\s*"((?:[^"]|"")*)"\s*,\s*Kind\s*=\s*"(?:Sheet|Table|DefinedName)"', src))
    )
    return info


def decode_m_escapes(text: str) -> str:
    """Turn M string escapes such as `#(lf)`, `#(cr,lf)`, `#(tab)` into real characters (readable SQL)."""
    names = {"cr": "\r", "lf": "\n", "tab": "\t"}

    def _one(m: re.Match) -> str:
        out = []
        for part in m.group(1).split(","):
            p = part.strip().lower()
            if p in names:
                out.append(names[p])
            elif re.fullmatch(r"[0-9a-f]{4}|[0-9a-f]{8}", p):
                out.append(chr(int(p, 16)))
            else:
                return m.group(0)
        return "".join(out)

    return re.sub(r"#\(([^)]{1,40})\)", _one, text or "").replace("\r\n", "\n")


def _query_kind(code: str) -> str:
    compact = (code or "").replace(" ", "")
    if "IsParameterQuery=true" in compact:
        return "parameter"
    if re.search(r"^\s*(let\s+)?\w+\s*=\s*\([^)]*\)\s*=>|^\s*\([^)]*\)\s*(as\s+\w+\s*)?=>", code or "", re.M):
        return "function"
    return "query"


def _param_value(code: str) -> str:
    pm = re.search(r'^\s*"((?:[^"]|"")*)"\s+meta\s*\[', code or "")
    if pm:
        return pm.group(1).replace('""', '"')
    pm = re.search(r"^\s*([\w.\-]+)\s+meta\s*\[", code or "")
    return pm.group(1) if pm else ""


# ---------------------------------------------------------------------------
# Dataflow definition parsing
# ---------------------------------------------------------------------------
def parse_dataflow_definition(meta: dict, definition: dict) -> dict:
    """Turn a Gen1 `model.json` export + catalog metadata into structured, classified queries."""
    mashup = definition.get("pbi:mashup") or {}
    document = mashup.get("document") or ""
    q_meta = mashup.get("queriesMetadata") or {}
    members = split_m_section(document)

    entities_by_name: dict[str, dict] = {}
    for ent in definition.get("entities") or []:
        if ent.get("name"):
            entities_by_name[ent["name"]] = ent

    # Linked entities: real Gen1 exports list them only as `ReferenceEntity` (no M in the document).
    # `modelId` is "<workspaceId>/<dataflowId>" and `source` is the entity name in the upstream dataflow.
    member_names = {m["name"] for m in members}
    reference_refs: dict[str, dict] = {}
    for ent in definition.get("entities") or []:
        if ent.get("$type") != "ReferenceEntity" or not ent.get("name"):
            continue
        reference_refs[ent["name"]] = reference_entity_ref(ent, definition)
        if ent["name"] not in member_names:
            members.append({"name": ent["name"], "code": "", "description": ent.get("description", ""), "linked_only": True})
            member_names.add(ent["name"])

    params: dict[str, str] = {}
    for mem in members:
        if _query_kind(mem["code"]) == "parameter":
            params[mem["name"]] = _param_value(mem["code"])
    shared_names = [mem["name"] for mem in members]
    loaded_names = {
        mem["name"]
        for mem in members
        if (q_meta.get(mem["name"]) or {}).get("loadEnabled", mem["name"] in entities_by_name)
    }

    queries: list[dict] = []
    for mem in members:
        name = mem["name"]
        code = mem["code"]
        kind = _query_kind(code)
        qm = q_meta.get(name) or {}
        ent = entities_by_name.get(name) or {}
        load_enabled = name in loaded_names
        info = describe_sources(code, params, [s for s in shared_names if s != name])
        refs = find_dataflow_refs(code, params)
        if not refs and name in reference_refs:
            refs = [reference_refs[name]]

        intra = [d for d in info["depends_on"] if d in shared_names]
        param_deps = [d for d in intra if d in params]
        query_deps = [d for d in intra if d not in params]

        if mem.get("linked_only"):
            role = "Linked entity"
        elif kind == "parameter":
            role = "Parameter"
        elif kind == "function":
            role = "Function"
        elif refs:
            role = "Linked entity" if load_enabled else "Linked query (staging)"
        elif load_enabled and any(d in loaded_names for d in query_deps):
            role = "Computed entity"
        elif load_enabled:
            role = "Entity"
        else:
            role = "Staging / helper query"

        columns = [
            {"name": a.get("name", ""), "type": a.get("dataType", "")}
            for a in (ent.get("attributes") or [])
            if a.get("name")
        ]
        queries.append(
            {
                "name": name,
                "kind": kind,
                "role": role,
                "load_enabled": load_enabled,
                "description": mem["description"] or ent.get("description", ""),
                "code": mask_secrets(code),
                "depends_on": query_deps,
                "parameters": param_deps,
                "dataflow_refs": refs,
                "source_types": [t for t in info["source_types"] if t != "Power BI Dataflow"],
                "sources": [s for s in info["sources"] if s["type"] != "Power BI Dataflow"],
                "endpoints": info["endpoints"],
                "files": info["files"],
                "sheets": info["sheets"],
                "objects": info["objects"],
                "native_queries": info["native_queries"],
                "native_sql": info["native_sql"],
                "step_count": info["step_count"],
                "columns": columns,
                "query_id": qm.get("queryId", ""),
                "default_value": mask_secrets(params.get(name, "")) if kind == "parameter" else "",
            }
        )

    return {
        "id": meta.get("id", ""),
        "name": meta.get("name") or definition.get("name", "Dataflow"),
        "description": meta.get("description") or definition.get("description", ""),
        "workspace_id": meta.get("workspace_id", ""),
        "workspace": meta.get("workspace", ""),
        "configured_by": meta.get("configured_by", ""),
        "modified_at": meta.get("modified_at") or definition.get("modifiedTime", ""),
        "allow_native_queries": bool(mashup.get("allowNativeQueries")),
        "parameters": {k: mask_secrets(v) for k, v in params.items()},
        "queries": queries,
        "upstream_dataflows": [
            {"dataflow_id": u.get("targetDataflowId") or u.get("dataflowObjectId", ""), "workspace_id": u.get("groupId") or u.get("workspaceObjectId", "")}
            for u in meta.get("upstream") or []
        ],
        "datasources": meta.get("datasources") or [],
    }


def reference_entity_ref(ent: dict, definition: dict) -> dict:
    """Resolve a model.json `ReferenceEntity` to `{workspace_id, dataflow_id, entity}`."""
    model_id = ent.get("modelId") or ""
    ws_id, _, df_id = model_id.rpartition("/")
    if not ws_id:
        ref_model = next((r for r in definition.get("referenceModels") or [] if (r.get("id") or "").endswith(model_id)), {})
        ws_id = (ref_model.get("id") or "").rpartition("/")[0]
    return {"workspace_id": ws_id, "dataflow_id": df_id or model_id, "entity": ent.get("source") or ent.get("name", "")}


def definition_dataflow_refs(definition: dict) -> list[tuple[str, str]]:
    """All upstream `(workspace_id, dataflow_id)` pairs of a dataflow export (M navigation + reference entities)."""
    pairs = referenced_dataflow_ids([(definition.get("pbi:mashup") or {}).get("document") or ""])
    seen = {d.lower() for _, d in pairs}
    for ent in definition.get("entities") or []:
        if ent.get("$type") == "ReferenceEntity":
            r = reference_entity_ref(ent, definition)
            if _GUID_RE.match(r["dataflow_id"]) and r["dataflow_id"].lower() not in seen:
                seen.add(r["dataflow_id"].lower())
                pairs.append((r["workspace_id"] if _GUID_RE.match(r["workspace_id"]) else "", r["dataflow_id"]))
    return pairs


def strip_data_locations(definition: dict) -> dict:
    """Remove links to stored dataflow output (CSV snapshots / blob URLs) before persisting a definition.

    The tool never reads them; dropping them keeps the local catalog free of pointers to actual table data.
    """
    for ent in definition.get("entities") or []:
        for part in ent.get("partitions") or []:
            if "location" in part:
                part["location"] = "(removed - data file location not stored)"
    for ref in definition.get("referenceModels") or []:
        if "location" in ref:
            ref["location"] = "(removed)"
    return definition


def referenced_dataflow_ids(parsed_or_codes: list[str], params: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """Collect `(workspace_id, dataflow_id)` pairs (GUIDs only) referenced across M scripts."""
    out: list[tuple[str, str]] = []
    seen = set()
    for code in parsed_or_codes:
        for r in find_dataflow_refs(code, params):
            if _GUID_RE.match(r["dataflow_id"] or "") and r["dataflow_id"].lower() not in seen:
                seen.add(r["dataflow_id"].lower())
                out.append((r["workspace_id"] if _GUID_RE.match(r["workspace_id"] or "") else "", r["dataflow_id"]))
    return out
