"""
Universal TMDL, Power Query (M), DAX Lineage, and Governance Health Analyzer.
100% Pure Python, vendor-neutral, and tested against complex real-world enterprise models.
"""

from __future__ import annotations

import collections
import datetime
import re
from pathlib import Path

from .security import mask_secrets

AUTO_DATE_RE = re.compile(r"^'?(LocalDateTable|DateTableTemplate)_[0-9a-fA-F-]{36}'?$")
NON_PROD_ENV_RE = re.compile(r"(?i)(?:^|[-_./\s])(dev|tst|test|uat|acc|qa|sandbox|staging)(?:$|[-_./\s0-9])")

SOURCE_PATTERNS: list[tuple[str, str]] = [
    (r"SapHana\.Database", "SAP HANA"),
    (r"SapBusinessWarehouse\.\w+", "SAP BW"),
    (r"Sql\.Databases?|AzureSql\.Database", "SQL Server / Azure SQL"),
    (r"Snowflake\.Databases", "Snowflake"),
    (r"Databricks\.(?:Catalogs|Contents)", "Databricks"),
    (r"GoogleBigQuery\.Database", "BigQuery"),
    (r"AmazonRedshift\.Database", "Amazon Redshift"),
    (r"Lakehouse\.Contents|Fabric\.Warehouse|Sql\.Endpoint", "Microsoft Fabric"),
    (r"PostgreSQL\.Database", "PostgreSQL"),
    (r"Oracle\.Database", "Oracle"),
    (r"MySQL\.Database", "MySQL"),
    (r"Teradata\.Database", "Teradata"),
    (r"AnalysisServices\.Databases?", "Analysis Services / Semantic Model"),
    (r"PowerPlatform\.Dataflows|PowerBI\.Dataflows", "Power BI Dataflow"),
    (r"CommonDataService\.Database|Dataverse\.Contents|Cds\.Entities", "Dataverse / Dynamics 365"),
    (r"SharePoint\.(?:Tables|Files|Contents)", "SharePoint"),
    (r"Excel\.Workbook", "Excel"),
    (r"Csv\.Document", "CSV"),
    (r"Json\.Document", "JSON"),
    (r"Xml\.(?:Tables|Document)", "XML"),
    (r"Parquet\.Document", "Parquet"),
    (r"Folder\.(?:Files|Contents)", "Folder"),
    (r"File\.Contents", "File"),
    (r"AzureStorage\.\w+|AzureDataExplorer\.Contents", "Azure Storage / ADX"),
    (r"OData\.Feed", "OData"),
    (r"Web\.(?:Contents|Page|BrowserContents)", "Web API"),
    (r"Odbc\.(?:DataSource|Query)", "ODBC"),
    (r"OleDb\.(?:DataSource|Query)", "OLE DB"),
    (r"Salesforce\.\w+", "Salesforce"),
    (r"ActiveDirectory\.Domains", "Active Directory"),
    (r"Exchange\.Contents", "Exchange"),
    (r"Table\.FromRows\(\s*Json\.Document\(\s*Binary\.Decompress", "Entered Data (Manual Table)"),
]

STEP_PATTERNS: list[tuple[str, str]] = [
    ("Merges", r"Table\.(?:NestedJoin|Join|FuzzyNestedJoin)\("),
    ("Appends", r"Table\.Combine\("),
    ("GroupBy", r"Table\.Group\("),
    ("PivotUnpivot", r"Table\.(?:Pivot|Unpivot|UnpivotOtherColumns)\("),
    ("CustomColumns", r"Table\.AddColumn\("),
    ("Filters", r"Table\.SelectRows\("),
    ("TypeChanges", r"Table\.TransformColumnTypes\("),
    ("Buffers", r"(?:Table|List|Binary)\.Buffer\("),
]


def _unquote(name: str) -> str:
    return (name or "").strip().strip("'").replace("''", "'")


def _dedent(lines: list[str]) -> str:
    items = list(lines)
    while items and not items[-1].strip():
        items.pop()
    while items and not items[0].strip():
        items.pop(0)
    tabs = min((len(line) - len(line.lstrip("\t")) for line in items if line.strip()), default=0)
    return "\n".join(line[tabs:].replace("\t", "    ") if line.strip() else "" for line in items)


def _objects(lines: list[str], level: int) -> list[list]:
    """Extract TMDL objects at a given tab-indentation level, preserving /// doc comments."""
    out: list[list] = []
    cur: list | None = None
    desc: list[str] = []
    prefix = "\t" * level
    for line in lines:
        if line.startswith(prefix) and not line.startswith(prefix + "\t") and line.strip():
            stripped = line.strip()
            if stripped.startswith("///"):
                desc.append(stripped[3:].strip())
                continue
            cur = [stripped, [], " ".join(d for d in desc if d)]
            desc = []
            out.append(cur)
        elif cur is not None:
            cur[1].append(line)
    return out


def _expression(rest: str, body: list[str], level: int) -> str:
    rest = rest.strip()
    if rest.startswith("```"):
        code = []
        for line in body:
            if line.strip().startswith("```"):
                break
            code.append(line)
        return _dedent(code)
    code = [rest] if rest else []
    for line in body:
        if line.strip() and (len(line) - len(line.lstrip("\t"))) <= level + 1:
            break
        code.append(line)
    return _dedent(code) if len(code) > 1 or not rest else rest


def _props(body: list[str], level: int) -> dict:
    props: dict = {}
    for line in body:
        if (len(line) - len(line.lstrip("\t"))) != level + 1 or not line.strip():
            continue
        m = re.match(r"^\s*(\w+)\s*:\s*(.*)$", line)
        if m:
            props[m.group(1)] = m.group(2).strip()
        elif re.match(r"^\s*\w+\s*$", line):
            props[line.strip()] = True
    return props


def bundle_from_local_tmdl_dir(folder: str | Path) -> tuple[str, str]:
    """Read a local `.pbip`, `.SemanticModel`, or project directory and pack its `.tmdl` files into a bundle string."""
    p = Path(folder).resolve()
    if p.is_file() and p.suffix.lower() == ".pbip":
        exact_sm = p.parent / f"{p.stem}.SemanticModel"
        if exact_sm.is_dir():
            p = exact_sm
        else:
            candidates = sorted(p.parent.glob("*.SemanticModel"))
            if not candidates:
                raise FileNotFoundError(f"No .SemanticModel folder found next to {p}")
            p = candidates[0]
    elif p.is_dir() and not (p / "definition").is_dir() and not p.name.endswith(".SemanticModel"):
        sm_dirs = sorted(p.glob("*.SemanticModel"))
        if sm_dirs:
            p = sm_dirs[0]

    def_dir = p / "definition" if (p / "definition").is_dir() else p
    tmdl_files = sorted(def_dir.rglob("*.tmdl"))
    if not tmdl_files:
        raise FileNotFoundError(f"No .tmdl files found inside {p}")

    model_name = p.name.replace(".SemanticModel", "")
    blocks = []
    for tf in tmdl_files:
        rel = tf.relative_to(def_dir.parent if def_dir.name == "definition" else def_dir).as_posix()
        if not rel.startswith("definition/"):
            rel = "definition/" + rel
        blocks.append(f"// ===== {rel}\n{tf.read_text(encoding='utf-8-sig', errors='replace')}")
    return model_name, "\n\n".join(blocks)


def parse_tmdl_bundle(tmdl: str | dict[str, str]) -> dict:
    """Losslessly parse a bundled TMDL definition into structured tables, expressions, relationships, and RLS roles."""
    tables: list[dict] = []
    expressions: list[dict] = []
    relationships: list[dict] = []
    roles: list[dict] = []

    if isinstance(tmdl, dict):
        tmdl_str = "\n".join(f"// ===== {k}\n{v}" for k, v in tmdl.items())
    else:
        tmdl_str = tmdl or ""

    for block in re.split(r"(?m)^// ===== ", tmdl_str):
        if not block.strip():
            continue
        path, _, text = block.partition("\n")
        path = path.strip()
        lines = text.splitlines()

        if path.startswith("definition/tables/"):
            head = _objects(lines, 0)
            if not head:
                continue
            tname = _unquote(re.sub(r"^table\s+", "", head[0][0]))
            t_props = _props(head[0][1], 0)
            tbl = {
                "name": tname,
                "description": head[0][2],
                "hidden": bool(t_props.get("isHidden")),
                "auto_date": bool(AUTO_DATE_RE.fullmatch(tname)),
                "refresh_policy_code": "",
                "columns": [],
                "measures": [],
                "partitions": [],
                "hierarchies": [],
                "calculation_items": [],
            }
            for hdr, body, desc in _objects(head[0][1], 1):
                if hdr == "refreshPolicy" or hdr.startswith("refreshPolicy "):
                    tbl["refresh_policy_code"] = mask_secrets(_dedent(body))
                    continue
                if hdr == "calculationGroup":
                    for chdr, cbody, cdesc in _objects(body, 2):
                        cm = re.match(r"^calculationItem\s+('(?:[^']|'')+'|[^=]+?)\s*=\s*(.*)$", chdr)
                        if cm:
                            ci_fmt_expr = ""
                            for fhdr, fbody, _ in _objects(cbody, 3):
                                fm = re.match(r"^formatStringDefinition\s*=\s*(.*)$", fhdr)
                                if fm:
                                    ci_fmt_expr = mask_secrets(_expression(fm.group(1), fbody, 3))
                            tbl["calculation_items"].append(
                                {
                                    "name": _unquote(cm.group(1)),
                                    "expr": mask_secrets(_expression(cm.group(2), cbody, 2)),
                                    "format_expr": ci_fmt_expr,
                                    "description": cdesc,
                                }
                            )
                    continue
                kind, _, rest = hdr.partition(" ")
                hm = re.match(r"^('(?:[^']|'')+'|[^=]+?)\s*(?:(=)\s*(.*))?$", rest) if rest else None
                nm, eq, expr = hm.groups() if hm else (rest.partition("=")[0], "=" if "=" in rest else "", rest.partition("=")[2])
                eq, expr = eq or "", expr or ""
                pr = _props(body, 1)
                if kind == "column":
                    group_by_cols = [
                        _unquote(m_gb.group(1))
                        for ln in body
                        if (m_gb := re.match(r"^\s*groupByColumn\s*:\s*(.+)$", ln))
                    ]
                    tbl["columns"].append(
                        {
                            "name": _unquote(nm),
                            "type": pr.get("dataType", ""),
                            "source": _unquote(pr.get("sourceColumn", "")),
                            "format": pr.get("formatString", ""),
                            "folder": pr.get("displayFolder", ""),
                            "sort_by": _unquote(pr.get("sortByColumn", "")),
                            "is_key": bool(pr.get("isKey")),
                            "group_by_columns": group_by_cols,
                            "hidden": bool(pr.get("isHidden")),
                            "description": desc,
                            "expr": mask_secrets(_expression(expr, body, 1)) if eq else "",
                        }
                    )
                elif kind == "measure":
                    m_fmt_expr = ""
                    for fhdr, fbody, _ in _objects(body, 2):
                        fm = re.match(r"^formatStringDefinition\s*=\s*(.*)$", fhdr)
                        if fm:
                            m_fmt_expr = mask_secrets(_expression(fm.group(1), fbody, 2))
                    tbl["measures"].append(
                        {
                            "name": _unquote(nm),
                            "expr": mask_secrets(_expression(expr, body, 1)),
                            "format": pr.get("formatString", ""),
                            "format_expr": m_fmt_expr,
                            "folder": pr.get("displayFolder", ""),
                            "hidden": bool(pr.get("isHidden")),
                            "description": desc,
                        }
                    )
                elif kind == "partition":
                    src_idx = next((i for i, l in enumerate(body) if re.match(r"^\t\tsource\s*(=|$)", l)), None)
                    if src_idx is None:
                        code = ""
                    elif "=" in body[src_idx]:
                        code = _expression(body[src_idx].split("=", 1)[1], body[src_idx + 1 :], 1)
                    else:
                        blk = []
                        for l in body[src_idx + 1 :]:
                            if l.strip() and (len(l) - len(l.lstrip("\t"))) <= 2:
                                break
                            blk.append(l)
                        code = _dedent(blk)
                    code = "\n".join(l for l in code.splitlines() if l.strip() != "```")
                    p_kind = expr.strip()
                    ent_name = ""
                    ent_schema = ""
                    ent_source = ""
                    if p_kind == "entity":
                        m_en = re.search(r"(?m)^\s*entityName\s*:\s*(.+)$", code)
                        m_sc = re.search(r"(?m)^\s*schemaName\s*:\s*(.+)$", code)
                        m_es = re.search(r"(?m)^\s*expressionSource\s*:\s*(.+)$", code)
                        ent_name = _unquote(m_en.group(1)) if m_en else ""
                        ent_schema = _unquote(m_sc.group(1)) if m_sc else ""
                        ent_source = _unquote(m_es.group(1)) if m_es else ""
                    tbl["partitions"].append(
                        {
                            "name": _unquote(nm),
                            "kind": p_kind,
                            "mode": pr.get("mode", ""),
                            "code": mask_secrets(code),
                            "entity_name": ent_name,
                            "schema_name": ent_schema,
                            "expression_source": ent_source,
                        }
                    )
                elif kind == "hierarchy":
                    levels: list[str] = []
                    level_aliases: list[str] = []
                    for lh, lb, _ in _objects(body, 2):
                        if lh.startswith("level "):
                            lvl_nm = _unquote(lh.partition(" ")[2])
                            col_nm = _unquote(_props(lb, 2).get("column") or lvl_nm)
                            levels.append(col_nm)
                            if lvl_nm and lvl_nm.lower() != col_nm.lower():
                                level_aliases.append(lvl_nm)
                    tbl["hierarchies"].append({"name": _unquote(rest), "levels": levels, "level_aliases": level_aliases})
            tables.append(tbl)

        elif path.startswith("definition/expressions.tmdl"):
            for hdr, body, desc in _objects(lines, 0):
                m = re.match(r"^expression\s+('(?:[^']|'')+'|[^=]+?)\s*=\s*(.*)$", hdr)
                if not m:
                    continue
                raw_code = _expression(m.group(2), body, 0)
                pr = _props(body, 0)
                compact = raw_code.replace(" ", "")
                if "IsParameterQuery=true" in compact:
                    kind = "parameter"
                elif re.search(r"^\s*(let\s+)?\w+\s*=\s*\([^)]*\)\s*=>|^\s*\([^)]*\)\s*=>", raw_code, re.M):
                    kind = "function"
                else:
                    kind = "query"
                pm = re.search(r'=\s*"((?:[^"]|"")*)"\s+meta\s*\[[^\]]*IsParameterQuery\s*=\s*true', raw_code)
                param_val = pm.group(1).replace('""', '"') if pm else ""
                expressions.append(
                    {
                        "name": _unquote(m.group(1)),
                        "kind": kind,
                        "group": pr.get("queryGroup", ""),
                        "description": desc,
                        "default_value": mask_secrets(param_val),
                        "code": mask_secrets(raw_code),
                    }
                )

        elif path.startswith("definition/relationships.tmdl"):
            for hdr, body, _ in _objects(lines, 0):
                if not hdr.startswith("relationship "):
                    continue
                pr = _props(body, 0)
                fc = pr.get("fromColumn", "")
                tc = pr.get("toColumn", "")
                if not fc or not tc:
                    continue

                def _split_col(ref: str) -> tuple[str, str]:
                    mm = re.match(r"^('(?:[^']|'')+'|[^.]+)\.(.+)$", ref.strip())
                    return (_unquote(mm.group(1)), _unquote(mm.group(2))) if mm else (ref, "")

                ft, fcol = _split_col(fc)
                tt, tcol = _split_col(tc)
                if AUTO_DATE_RE.fullmatch(ft) or AUTO_DATE_RE.fullmatch(tt):
                    continue
                fcard = pr.get("fromCardinality", "many")
                tcard = pr.get("toCardinality", "one")
                card_map = {
                    ("many", "one"): "many-to-one",
                    ("one", "one"): "one-to-one",
                    ("many", "many"): "many-to-many",
                    ("one", "many"): "one-to-many",
                }
                relationships.append(
                    {
                        "name": _unquote(hdr.partition(" ")[2]),
                        "from_table": ft,
                        "from_column": fcol,
                        "to_table": tt,
                        "to_column": tcol,
                        "cardinality": card_map.get((fcard, tcard), f"{fcard}-to-{tcard}"),
                        "bidirectional": pr.get("crossFilteringBehavior", "").lower() == "bothdirections",
                        "active": pr.get("isActive", "true").lower() != "false",
                    }
                )

        elif path.startswith("definition/roles/"):
            head = _objects(lines, 0)
            if not head:
                continue
            pr = _props(head[0][1], 0)
            filters = []
            ols_columns = []
            for hdr, body, _ in _objects(head[0][1], 1):
                m = re.match(r"^tablePermission\s+('(?:[^']|'')+'|[^=]+?)(?:\s*=\s*(.*))?$", hdr)
                if m:
                    tp_tbl = _unquote(m.group(1))
                    if m.group(2) is not None:
                        filters.append({"table": tp_tbl, "filter_dax": mask_secrets(_expression(m.group(2), body, 1))})
                    for chdr, _, _ in _objects(body, 2):
                        cm = re.match(r"^columnPermission\s+('(?:[^']|'')+'|[^=]+?)\s*=\s*(.*)$", chdr)
                        if cm:
                            ols_columns.append({"table": tp_tbl, "column": _unquote(cm.group(1)), "permission": cm.group(2).strip()})
            roles.append(
                {
                    "name": _unquote(re.sub(r"^role\s+", "", head[0][0])),
                    "permission": pr.get("modelPermission", "read"),
                    "filters": filters,
                    "ols_columns": ols_columns,
                }
            )

    tables.sort(key=lambda t: (t["auto_date"], t["name"].lower()))
    return {
        "tables": tables,
        "expressions": expressions,
        "relationships": relationships,
        "roles": roles,
    }


_SQL_ARGS_RE = re.compile(
    r"\b(Sql\.Databases?|AzureSql\.Database|PostgreSQL\.Database|MySQL\.Database|Oracle\.Database|Teradata\.Database|"
    r"Snowflake\.Databases|AmazonRedshift\.Database|Sql\.Endpoint|Fabric\.Warehouse|SapHana\.Database|"
    r"Databricks\.Catalogs|GoogleBigQuery\.Database|Odbc\.DataSource|Odbc\.Query|OleDb\.DataSource)\(\s*"
    r'(?:"((?:[^"]|"")*)"|([#\w".]+))\s*(?:,\s*(?:"((?:[^"]|"")*)"|([#\w".]+)))?',
)
DB_CONNECTOR_LABELS = {
    "Sql.Database": "SQL Server / Azure SQL",
    "Sql.Databases": "SQL Server / Azure SQL",
    "AzureSql.Database": "SQL Server / Azure SQL",
    "PostgreSQL.Database": "PostgreSQL",
    "MySQL.Database": "MySQL",
    "Oracle.Database": "Oracle",
    "Teradata.Database": "Teradata",
    "Snowflake.Databases": "Snowflake",
    "AmazonRedshift.Database": "Amazon Redshift",
    "Sql.Endpoint": "Microsoft Fabric",
    "Fabric.Warehouse": "Microsoft Fabric",
    "SapHana.Database": "SAP HANA",
    "Databricks.Catalogs": "Databricks",
    "GoogleBigQuery.Database": "BigQuery",
    "Odbc.DataSource": "ODBC",
    "Odbc.Query": "ODBC",
    "OleDb.DataSource": "OLE DB",
}
_FILE_URL_RE = re.compile(r'(?:File\.Contents|Web\.Contents|SharePoint\.(?:Files|Contents|Tables))\(\s*"((?:[^"]|"")*)"')


def _param_or_literal(lit: str | None, ident: str | None, params: dict[str, str]) -> str:
    if lit is not None:
        return lit.replace('""', '"')
    name = (ident or "").strip("#").strip('"')
    if not name:
        return ""
    return str(params.get(name, f"{{param:{name}}}"))


def analyze_m_partition(code: str, params: dict[str, str], shared_names: list[str]) -> dict:
    """Inspect a Power Query M script to detect connectors, endpoints, formatted native SQL, and step-by-step lineage."""
    from .mparse import extract_native_sql, find_dataflow_refs, parse_let_steps
    from .pq_steps import interpret_query
    from .sql_format import format_sql

    src = code or ""
    sources: list[dict] = []
    seen = set()

    for pattern, label in SOURCE_PATTERNS:
        for m in re.finditer(rf"({pattern})\(\s*(?:\"((?:[^\"]|\"\")*)\"|([#\w\"\.]+))?", src):
            arg = ""
            if m.group(2) is not None:
                arg = m.group(2).replace('""', '"')
            elif m.group(3):
                pname = m.group(3).strip("#").strip('"')
                if pname in params:
                    arg = f"{params[pname]} (param {pname})"
                else:
                    arg = pname
            arg = mask_secrets(arg)
            key = (label, arg)
            if key not in seen:
                seen.add(key)
                sources.append({"type": label, "detail": arg})

    endpoints: list[dict] = []
    for m in _SQL_ARGS_RE.finditer(src):
        server = mask_secrets(_param_or_literal(m.group(2), m.group(3), params))
        database = (
            mask_secrets(_param_or_literal(m.group(4), m.group(5), params))
            if (m.group(4) is not None or m.group(5))
            else ""
        )
        warehouse = ""
        if m.group(1) == "Snowflake.Databases":
            warehouse, database = database, ""
            nav = re.search(r'\{\[\s*Name\s*=\s*"((?:[^"]|"")*)"', src[m.end() : m.end() + 400])
            if nav:
                database = nav.group(1)
        endpoints.append(
            {
                "connector": m.group(1),
                "label": DB_CONNECTOR_LABELS.get(m.group(1), m.group(1)),
                "server": server,
                "database": database,
                "warehouse": warehouse,
                "pos": m.start(),
            }
        )

    files = list(dict.fromkeys(mask_secrets(m.group(1).replace('""', '"')) for m in _FILE_URL_RE.finditer(src)))

    # Extract navigated object/view/table names (Schema/Item records + HANA Package/View navigation)
    nav_objects: list[str] = []
    for rec in re.finditer(r'\{\[((?:[^\]"]|"(?:[^"]|"")*")*)\]\}', src):
        kv = {k.lower(): v.replace('""', '"') for k, v in re.findall(r'(\w+)\s*=\s*"((?:[^"]|"")*)"', rec.group(1))}
        if "schema" in kv and ("item" in kv or "name" in kv):
            nav_objects.append(f"{kv['schema']}/{kv.get('item') or kv.get('name')}")
    if not nav_objects:
        nav_names = [
            m.group(1).replace('""', '"')
            for m in re.finditer(r'\{\[\s*(?:Name|Item|Schema)\s*=\s*"((?:[^"]|"")*)"', src)
            if m.group(1) not in ("Contents",)
        ]
        if len(nav_names) >= 2:
            nav_objects.append("/".join(nav_names[-2:]))
        elif len(nav_names) == 1:
            nav_objects.append(nav_names[0])
    nav_objects = list(dict.fromkeys(nav_objects))

    sheets = list(
        dict.fromkeys(
            m.group(1).replace('""', '"')
            for m in re.finditer(
                r'\{\[\s*Item\s*=\s*"((?:[^"]|"")*)"\s*,\s*Kind\s*=\s*"(?:Sheet|Table|DefinedName)"', src
            )
        )
    )

    native_sql: list[dict] = []
    for q in extract_native_sql(src):
        raw = mask_secrets(q["sql"])
        ep = max(
            (e for e in endpoints if e["pos"] <= q["pos"]),
            key=lambda e: e["pos"],
            default=endpoints[0] if endpoints else None,
        )
        native_sql.append(
            {
                "sql": format_sql(raw),
                "raw": raw,
                "via": q["via"],
                "parameters": q["parameters"],
                "pos": q["pos"],
                "connector": (ep or {}).get("label", ""),
                "server": (ep or {}).get("server", ""),
                "database": (ep or {}).get("database", ""),
            }
        )
    native_queries = [n["sql"] for n in native_sql]

    deps = []
    for sname in shared_names:
        pat = r'(?<![\w."])(?:#"' + re.escape(sname) + r'"|' + re.escape(sname) + r')(?![\w"])'
        if re.search(pat, src):
            deps.append(sname)

    steps = {label: len(re.findall(pat, src)) for label, pat in STEP_PATTERNS}
    parsed_steps, _ = parse_let_steps(src)
    step_items = interpret_query(src, shared_names) if parsed_steps else []
    step_count = len(parsed_steps) if parsed_steps else len(re.findall(r'(?m)^\s*(?:#"(?:[^"]|"")+"|[A-Za-z_][\w.]*)\s*=(?!=)', src))

    src_types = sorted({s["type"] for s in sources})
    if "Entered Data (Manual Table)" in src_types and "JSON" in src_types:
        src_types.remove("JSON")

    df_refs = find_dataflow_refs(src, params)
    if not df_refs and ("Power BI Dataflow" in src_types or "Dataflows" in src):
        ent_m = re.search(r'(?i)(?:entity|Item)\s*=\s*"((?:[^"]|"")*)"', src)
        if ent_m or nav_objects:
            df_refs.append(
                {
                    "workspace_id": "",
                    "dataflow_id": "",
                    "entity": ent_m.group(1).replace('""', '"') if ent_m else nav_objects[-1],
                }
            )

    return {
        "source_types": src_types,
        "sources": sources,
        "endpoints": endpoints,
        "files": files,
        "sheets": sheets,
        "objects": nav_objects,
        "native_sql": native_sql,
        "native_queries": native_queries,
        "depends_on": deps,
        "step_count": step_count,
        "steps": steps,
        "step_items": step_items,
        "dataflow_refs": df_refs,
    }


def _strip_dax_comments_and_strings(expr: str) -> str:
    """Strip DAX string literals and single/multi-line comments so references inside them are ignored."""
    s = re.sub(r"//[^\n]*|--[^\n]*", " ", expr or "")
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    return re.sub(r'"(?:[^"]|"")*"', '""', s)


def build_dax_lineage(parsed_model: dict) -> dict[str, dict]:
    """Build upstream and downstream DAX measure & column dependency map (table-qualified aware)."""
    measure_by_bare: dict[str, str] = {}
    measure_by_qual: dict[tuple[str, str], str] = {}
    known_tables_low: dict[str, str] = {}
    items: dict[str, dict] = {}

    for tbl in parsed_model.get("tables", []):
        if tbl["auto_date"]:
            continue
        tname = tbl["name"]
        known_tables_low[tname.lower()] = tname
        for m in tbl["measures"]:
            key = f"{tname}[{m['name']}]"
            measure_by_bare[m["name"].lower()] = key
            measure_by_qual[(tname.lower(), m["name"].lower())] = key
            items[key] = {
                "key": key,
                "kind": "measure",
                "table": tname,
                "name": m["name"],
                "expr": m["expr"],
                "format_expr": m.get("format_expr", ""),
                "upstream_measures": [],
                "upstream_columns": [],
                "downstream_measures": [],
            }

    table_col_re = re.compile(r"('(?:[^']|'')+'|[^\W\d]\w*)\s*\[((?:[^\]]|\]\])+)\]")
    bare_ref_re = re.compile(r"(?<![\w'\]])\[((?:[^\]]|\]\])+)\]")

    for key, info in items.items():
        combined_expr = (info["expr"] or "") + ("\n" + info["format_expr"] if info.get("format_expr") else "")
        expr = _strip_dax_comments_and_strings(combined_expr)
        host_low = info["table"].lower()
        up_m = set()
        up_c = set()
        spans_to_blank: list[tuple[int, int]] = []

        for tm in table_col_re.finditer(expr):
            raw_t = tm.group(1)
            rt = _unquote(raw_t)
            rt_low = rt.lower()
            if not raw_t.startswith("'") and rt_low not in known_tables_low:
                continue
            spans_to_blank.append(tm.span())
            rc = tm.group(2).replace("]]", "]").strip()
            cand = measure_by_qual.get((rt_low, rc.lower()))
            if cand and cand != key:
                up_m.add(cand)
            else:
                canon_t = known_tables_low.get(rt_low, rt)
                up_c.add(f"{canon_t}[{rc}]")

        if spans_to_blank:
            chars = list(expr)
            for s_idx, e_idx in spans_to_blank:
                for i in range(s_idx, e_idx):
                    chars[i] = " "
            stripped_expr = "".join(chars)
        else:
            stripped_expr = expr

        for bm in bare_ref_re.finditer(stripped_expr):
            ref_name = bm.group(1).replace("]]", "]").strip()
            cand = measure_by_qual.get((host_low, ref_name.lower())) or measure_by_bare.get(ref_name.lower())
            if cand and cand != key:
                up_m.add(cand)

        info["upstream_measures"] = sorted(up_m)
        info["upstream_columns"] = sorted(up_c)

    for key, info in items.items():
        for up in info["upstream_measures"]:
            if up in items:
                items[up]["downstream_measures"].append(key)

    for info in items.values():
        info["downstream_measures"].sort()

    return items


def _parse_iso_date(val: str) -> datetime.datetime | None:
    if not val:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.datetime.strptime(val, fmt)
        except ValueError:
            continue
    return None


def analyze_full_model(
    model_meta: dict,
    tmdl_bundle: str,
    reports: list[dict] | None = None,
    dataflows: dict[str, dict] | None = None,
    fabric_items: dict[str, dict] | None = None,
    dataset_dataflow_links: list[dict] | None = None,
) -> dict:
    """Combine live Power BI metadata + parsed TMDL into a complete governance & documentation profile."""
    parsed = parse_tmdl_bundle(tmdl_bundle)
    params = {x["name"]: x["default_value"] for x in parsed["expressions"] if x["kind"] == "parameter" and x.get("default_value")}
    shared_names = [x["name"] for x in parsed["expressions"] if x["kind"] != "parameter"]
    expr_by_name = {x["name"]: x["code"] for x in parsed["expressions"]}

    data_tables = [t for t in parsed["tables"] if not t["auto_date"]]
    auto_dates = [t for t in parsed["tables"] if t["auto_date"]]

    table_summaries = []
    all_source_types: set[str] = set()
    source_endpoints: list[dict] = []
    seen_endpoints = set()

    total_pq_steps = 0
    total_merges = 0
    total_appends = 0
    native_query_count = 0
    import_count = 0
    dq_count = 0
    local_drive_tables = []
    manual_tables = []
    non_prod_targets: set[str] = set()
    table_df_links: list[dict] = []

    code_by_table = {
        t["name"]: "\n".join(p["code"] for p in t["partitions"] if p["kind"] == "m")
        for t in data_tables
    }
    m_table_names = [t["name"] for t in data_tables if any(p["kind"] == "m" for p in t["partitions"])]

    for tbl in data_tables:
        t_types: list[str] = []
        t_details: list[str] = []
        t_objects: list[str] = []
        t_steps = 0
        t_merges = 0
        t_appends = 0
        t_native: list[str] = []
        t_native_sql: list[dict] = []
        t_step_items: list[dict] = []
        mode = ""

        for part in tbl["partitions"]:
            mode = mode or part.get("mode", "")
            if part["kind"] == "m":
                peer_queries = shared_names + [n for n in m_table_names if n != tbl["name"]]
                minfo = analyze_m_partition(part["code"], params, peer_queries)
                for st in minfo["source_types"]:
                    if st not in t_types:
                        t_types.append(st)
                    all_source_types.add(st)
                for df_ref in minfo.get("dataflow_refs", []):
                    table_df_links.append({"table": tbl["name"], **df_ref})
                for s in minfo["sources"]:
                    det = f"{s['type']}: {s['detail']}" if s["detail"] else s["type"]
                    if det not in t_details:
                        t_details.append(det)
                    if s["detail"] and NON_PROD_ENV_RE.search(s["detail"]):
                        non_prod_targets.add(s["detail"])
                    if re.search(r"^[A-Za-z]:\\|^\\\\", s["detail"] or ""):
                        local_drive_tables.append(tbl["name"])
                    ep_key = (s["type"], s["detail"], ", ".join(minfo["objects"]))
                    if ep_key not in seen_endpoints:
                        seen_endpoints.add(ep_key)
                        source_endpoints.append(
                            {"type": s["type"], "endpoint": s["detail"], "object": ", ".join(minfo["objects"]), "table": tbl["name"]}
                        )
                for obj in minfo["objects"]:
                    if obj not in t_objects:
                        t_objects.append(obj)
                t_steps += minfo["step_count"]
                t_merges += minfo["steps"].get("Merges", 0)
                t_appends += minfo["steps"].get("Appends", 0)
                t_native.extend(minfo["native_queries"])
                t_native_sql.extend(minfo["native_sql"])
                if not t_step_items and minfo["step_items"]:
                    t_step_items = minfo["step_items"]
            elif part["kind"] == "calculated":
                if "DAX Calculated Table" not in t_types:
                    t_types.append("DAX Calculated Table")
            elif part["kind"] == "entity":
                if "Direct Lake" not in t_types:
                    t_types.append("Direct Lake")
                    all_source_types.add("Direct Lake")
                dl_obj = f"{part.get('schema_name')}.{part.get('entity_name')}" if part.get("schema_name") and part.get("entity_name") else (part.get("entity_name") or tbl["name"])
                if dl_obj and dl_obj not in t_objects:
                    t_objects.append(dl_obj)
                es_name = part.get("expression_source") or "OneLake / SQL Endpoint"
                es_code = expr_by_name.get(es_name, "")
                m_lh = re.search(r'(?:Sql\.Database|Lakehouse\.Contents|Fabric\.Warehouse)\(\s*"([^"]+)"(?:\s*,\s*"([^"]+)")?', es_code)
                dl_ep = (m_lh.group(2) or m_lh.group(1)) if m_lh else es_name
                det = f"Direct Lake: {dl_ep} ({dl_obj})"
                if det not in t_details:
                    t_details.append(det)
                ep_key = ("Direct Lake", dl_ep, dl_obj)
                if ep_key not in seen_endpoints:
                    seen_endpoints.add(ep_key)
                    source_endpoints.append({"type": "Direct Lake", "endpoint": dl_ep, "object": dl_obj, "table": tbl["name"]})

        if mode.lower() == "import":
            import_count += 1
        elif mode.lower() == "directquery":
            dq_count += 1

        if "Entered Data (Manual Table)" in t_types:
            manual_tables.append(tbl["name"])

        parent_ref = ""
        if not t_types and tbl["partitions"]:
            code = code_by_table.get(tbl["name"], "")
            refs = [
                other
                for other in code_by_table
                if other != tbl["name"]
                and re.search(r'(?<![\w."])(?:#"' + re.escape(other) + r'"|' + re.escape(other) + r')(?![\w"])', code)
            ]
            t_types = ["Derived Query"]
            if refs:
                parent_ref = refs[0] if len(refs) == 1 else ", ".join(refs)
                t_details = [f"Derived from {parent_ref}"]

        total_pq_steps += t_steps
        total_merges += t_merges
        total_appends += t_appends
        native_query_count += len(t_native)

        calc_cols = sum(1 for c in tbl["columns"] if c["expr"])
        table_summaries.append(
            {
                "name": tbl["name"],
                "description": tbl["description"],
                "hidden": tbl["hidden"],
                "mode": mode or "import",
                "source_types": t_types,
                "details": t_details,
                "objects": t_objects,
                "pq_steps": t_steps,
                "step_items": t_step_items,
                "m_code": code_by_table.get(tbl["name"], ""),
                "merges": t_merges,
                "native_queries": t_native,
                "native_sql": t_native_sql,
                "columns_count": len(tbl["columns"]),
                "calc_columns_count": calc_cols,
                "measures_count": len(tbl["measures"]),
                "parent": parent_ref,
            }
        )

    # Derived query fan-out check
    by_parent = collections.defaultdict(list)
    for ts in table_summaries:
        if ts["parent"] and "," not in ts["parent"]:
            by_parent[ts["parent"]].append(ts["name"])

    lineage = build_dax_lineage(parsed)

    # Governance & Architecture Health Checks
    findings: list[dict] = []
    refresh_info = model_meta.get("last_refresh") or {}
    ref_status = refresh_info.get("status") or ""
    ref_time = _parse_iso_date(refresh_info.get("end_time") or "")
    age_days = (datetime.datetime.now() - ref_time).days if ref_time else None

    if ref_status == "Failed":
        findings.append(
            {
                "severity": "bad",
                "title": "Last scheduled refresh failed",
                "detail": f"Last attempt ended {refresh_info.get('end_time', 'recently')}. Downstream reports may show stale figures.",
            }
        )
    if age_days is not None and age_days > 90:
        findings.append(
            {
                "severity": "bad",
                "title": f"Stale model (not refreshed for {age_days} days)",
                "detail": "Strong candidate for decommissioning or schedule review.",
            }
        )
    elif ref_status == "Disabled":
        findings.append(
            {"severity": "warn", "title": "Scheduled refresh is disabled", "detail": "Model is not refreshed automatically."}
        )

    if non_prod_targets:
        findings.append(
            {
                "severity": "bad",
                "title": "Connected to non-production source endpoint",
                "detail": f"Detected non-prod identifier in: {', '.join(sorted(non_prod_targets))}.",
            }
        )
    if local_drive_tables:
        findings.append(
            {
                "severity": "bad",
                "title": "Reads from local or mapped network drive",
                "detail": f"Tables ({', '.join(sorted(set(local_drive_tables)))}) reference a file path that breaks cloud refresh without a personal gateway.",
            }
        )
    for parent_q, children in by_parent.items():
        if len(children) >= 3:
            findings.append(
                {
                    "severity": "warn",
                    "title": f"{len(children)} tables split off from query '{parent_q}'",
                    "detail": "Duplicating and filtering one base query into multiple Power BI tables reloads the source repeatedly.",
                }
            )
    if total_merges >= 10:
        findings.append(
            {
                "severity": "warn",
                "title": f"Heavy Power Query ETL ({total_merges} merges)",
                "detail": "Complex joins inside Power Query slow down refreshes and belong upstream in SQL / Warehouse / Lakehouse views.",
            }
        )
    if manual_tables:
        findings.append(
            {
                "severity": "warn",
                "title": f"{len(manual_tables)} manually entered static table(s)",
                "detail": f"Hardcoded data inside Power BI ({', '.join(manual_tables)}) bypasses source governance.",
            }
        )
    if native_query_count > 0:
        findings.append(
            {
                "severity": "warn",
                "title": f"{native_query_count} embedded native SQL quer{'ies' if native_query_count > 1 else 'y'}",
                "detail": "Embedded SQL breaks query folding diagnostics and requires attention during database schema changes.",
            }
        )
    bi_rels = [r for r in parsed["relationships"] if r["bidirectional"]]
    if bi_rels:
        findings.append(
            {
                "severity": "warn",
                "title": f"{len(bi_rels)} bidirectional relationship(s)",
                "detail": "Both-direction cross-filtering can introduce ambiguous filter paths and degrade DAX performance.",
            }
        )
    if len(auto_dates) > 1:
        findings.append(
            {
                "severity": "warn",
                "title": f"{len(auto_dates)} hidden Auto Date/Time tables",
                "detail": "Switching off 'Auto date/time' and using one shared Calendar dimension reduces memory footprint.",
            }
        )
    perms = model_meta.get("permissions") or []
    if not parsed["roles"] and len(perms) > 10:
        findings.append(
            {
                "severity": "warn",
                "title": "Broad model access without Row-Level Security (RLS)",
                "detail": f"{len(perms)} principals hold direct permissions while 0 RLS roles are defined.",
            }
        )

    measures_total = sum(len(t["measures"]) for t in data_tables)
    calc_cols_total = sum(sum(1 for c in t["columns"] if c["expr"]) for t in data_tables)
    columns_total = sum(len(t["columns"]) for t in data_tables)

    # Build lookup sets for Column Usage Tracking, Report Visual Binding & Broken Reference Audit
    valid_cols: set[tuple[str, str]] = set()
    valid_col_names: set[str] = set()
    table_name_by_low: dict[str, str] = {}
    col_canon_by_low: dict[tuple[str, str], tuple[str, str]] = {}
    measure_key_by_low: dict[str, str] = {}
    measure_by_qual_low: dict[tuple[str, str], str] = {}
    hierarchy_levels_by_low: dict[tuple[str, str], list[str]] = {}
    level_alias_to_col_low: dict[tuple[str, str], str] = {}

    for tbl in parsed["tables"]:
        tl = tbl["name"].lower()
        if not tbl["auto_date"]:
            table_name_by_low[tl] = tbl["name"]
        for c in tbl["columns"]:
            cl = c["name"].lower()
            valid_cols.add((tl, cl))
            valid_col_names.add(cl)
            if not tbl["auto_date"]:
                col_canon_by_low[(tl, cl)] = (tbl["name"], c["name"])
        for h in tbl["hierarchies"]:
            hl = h["name"].lower()
            valid_cols.add((tl, hl))
            lvl_cols_low: list[str] = []
            for lv in h["levels"]:
                lvl_l = lv.lower()
                valid_cols.add((tl, lvl_l))
                lvl_cols_low.append(lvl_l)
            for al in h.get("level_aliases", []):
                al_l = al.lower()
                valid_cols.add((tl, al_l))
                if lvl_cols_low:
                    level_alias_to_col_low[(tl, al_l)] = lvl_cols_low[0]
            if not tbl["auto_date"]:
                hierarchy_levels_by_low[(tl, hl)] = lvl_cols_low
        for m in tbl["measures"]:
            ml = m["name"].lower()
            m_key = f"{tbl['name']}[{m['name']}]"
            measure_key_by_low[ml] = m_key
            measure_by_qual_low[(tl, ml)] = m_key
            valid_cols.add((tl, ml))

    dax_tbl_col_re = re.compile(r"('(?:[^']|'')+'|[^\W\d]\w*)\s*\[((?:[^\]]|\]\])+)\]")
    dax_bare_re = re.compile(r"(?<![\w'\]])\[((?:[^\]]|\]\])+)\]")
    dax_set_fn_re = re.compile(
        r"\b(?:UNION|EXCEPT|INTERSECT|NATURALINNERJOIN|NATURALLEFTOUTERJOIN)\s*\(([^()]*)\)",
        re.I,
    )

    def _scan_dax_usage(
        dax_code: str,
        row_context_table_low: str = "",
        local_measure_names: set[str] | None = None,
        collect_broken: bool = False,
    ) -> tuple[set[tuple[str, str]], set[str], set[str], list[str]]:
        """Extract `(col_pairs_low, measure_keys, set_locked_tables_low, broken_refs)` from a DAX expression."""
        cleaned = _strip_dax_comments_and_strings(dax_code or "")
        cols_found: set[tuple[str, str]] = set()
        meas_found: set[str] = set()
        set_tbls: set[str] = set()
        broken_found: list[str] = []
        seen_broken: set[str] = set()
        spans_blank: list[tuple[int, int]] = []
        local_m = local_measure_names or set()

        for sm in dax_set_fn_re.finditer(cleaned):
            args_txt = sm.group(1)
            for qm in re.finditer(r"'((?:[^']|'')+)'", args_txt):
                cand_tl = qm.group(1).replace("''", "'").lower()
                if cand_tl in table_name_by_low:
                    set_tbls.add(cand_tl)
            for um in re.finditer(r"\b([^\W\d]\w*)\b", args_txt):
                cand_tl = um.group(1).lower()
                if cand_tl in table_name_by_low:
                    set_tbls.add(cand_tl)

        for tm in dax_tbl_col_re.finditer(cleaned):
            raw_t = tm.group(1)
            rt = _unquote(raw_t)
            rt_low = rt.lower()
            is_quoted = raw_t.startswith("'")
            if not is_quoted and rt_low not in table_name_by_low:
                continue
            spans_blank.append(tm.span())
            rc = tm.group(2).replace("]]", "]").strip()
            rc_low = rc.lower()
            m_cand = measure_by_qual_low.get((rt_low, rc_low))
            if m_cand:
                meas_found.add(m_cand)
            elif (rt_low, rc_low) in col_canon_by_low:
                cols_found.add((rt_low, rc_low))
            elif rc_low in local_m:
                continue
            elif collect_broken and not rt_low.startswith(("localdatetable_", "datetabletemplate_")):
                b_str = f"{table_name_by_low.get(rt_low, rt)}[{rc}]"
                if b_str not in seen_broken:
                    seen_broken.add(b_str)
                    broken_found.append(b_str)

        if spans_blank:
            ch_arr = list(cleaned)
            for s_i, e_i in spans_blank:
                for idx_c in range(s_i, e_i):
                    ch_arr[idx_c] = " "
            rem = "".join(ch_arr)
        else:
            rem = cleaned

        for bm in dax_bare_re.finditer(rem):
            r_nm = bm.group(1).replace("]]", "]").strip()
            r_low = r_nm.lower()
            if row_context_table_low and (row_context_table_low, r_low) in col_canon_by_low:
                cols_found.add((row_context_table_low, r_low))
                continue
            m_cand = (
                (measure_by_qual_low.get((row_context_table_low, r_low)) if row_context_table_low else None)
                or measure_key_by_low.get(r_low)
            )
            if m_cand:
                meas_found.add(m_cand)
            elif r_low in local_m:
                continue
            elif collect_broken and not row_context_table_low:
                b_str = f"[{r_nm}]"
                if b_str not in seen_broken:
                    seen_broken.add(b_str)
                    broken_found.append(b_str)

        return cols_found, meas_found, set_tbls, broken_found

    # Intra-model column usage sets (case-insensitive `(table_low, col_low)`)
    key_cols_low: set[tuple[str, str]] = set()
    sort_by_cols_low: set[tuple[str, str]] = set()
    field_param_cols_low: set[tuple[str, str]] = set()
    hierarchy_cols_low: set[tuple[str, str]] = set()
    rls_cols_low: set[tuple[str, str]] = set()
    refresh_cols_low: set[tuple[str, str]] = set()
    dax_ref_counts: dict[tuple[str, str], int] = collections.Counter()

    for rel in parsed["relationships"]:
        ftl, fcl = rel["from_table"].lower(), rel["from_column"].lower()
        ttl, tcl = rel["to_table"].lower(), rel["to_column"].lower()
        if (ftl, fcl) in col_canon_by_low:
            key_cols_low.add((ftl, fcl))
        if (ttl, tcl) in col_canon_by_low:
            key_cols_low.add((ttl, tcl))

    intra_model_used_measures: set[str] = set()
    for tbl in data_tables:
        tl = tbl["name"].lower()
        is_calc_grp = bool(tbl.get("calculation_items"))
        rp_code = tbl.get("refresh_policy_code") or ""
        downstream_m_codes = [code_by_table.get(ch_name, "") for ch_name in by_parent.get(tbl["name"], [])]

        for h in tbl["hierarchies"]:
            for lv in h["levels"]:
                if (tl, lv.lower()) in col_canon_by_low:
                    hierarchy_cols_low.add((tl, lv.lower()))

        for c in tbl["columns"]:
            cl = c["name"].lower()
            if c.get("is_key") or is_calc_grp:
                key_cols_low.add((tl, cl))
            sb = (c.get("sort_by") or "").strip()
            if sb:
                if "." in sb:
                    sb_t, _, sb_c = sb.partition(".")
                    sb_pair = (_unquote(sb_t).lower(), _unquote(sb_c).lower())
                else:
                    sb_pair = (tl, _unquote(sb).lower())
                if sb_pair in col_canon_by_low:
                    sort_by_cols_low.add(sb_pair)
            for gb in c.get("group_by_columns") or []:
                if "." in gb:
                    gb_t, _, gb_c = gb.partition(".")
                    gb_pair = (_unquote(gb_t).lower(), _unquote(gb_c).lower())
                else:
                    gb_pair = (tl, _unquote(gb).lower())
                if gb_pair in col_canon_by_low:
                    field_param_cols_low.add(gb_pair)
            if rp_code and re.search(r'(?:\[\s*' + re.escape(c["name"]) + r'\s*\]|"' + re.escape(c["name"]) + r'")', rp_code, re.I):
                refresh_cols_low.add((tl, cl))
            for dm_code in downstream_m_codes:
                if dm_code and re.search(r'(?:\[\s*' + re.escape(c["name"]) + r'\s*\]|"' + re.escape(c["name"]) + r'")', dm_code, re.I):
                    refresh_cols_low.add((tl, cl))
            if c.get("expr"):
                c_cols, c_meas, c_sets, _ = _scan_dax_usage(c["expr"], row_context_table_low=tl)
                intra_model_used_measures.update(c_meas)
                for cp in c_cols:
                    if cp != (tl, cl):
                        dax_ref_counts[cp] += 1
                for st_l in c_sets:
                    for col_pair in col_canon_by_low:
                        if col_pair[0] == st_l:
                            dax_ref_counts[col_pair] += 1

        for part in tbl["partitions"]:
            if part["kind"] == "calculated" and part.get("code"):
                p_cols, p_meas, p_sets, _ = _scan_dax_usage(part["code"])
                intra_model_used_measures.update(p_meas)
                for cp in p_cols:
                    dax_ref_counts[cp] += 1
                for st_l in p_sets:
                    for col_pair in col_canon_by_low:
                        if col_pair[0] == st_l:
                            dax_ref_counts[col_pair] += 1

        for ci in tbl.get("calculation_items") or []:
            ci_code = (ci.get("expr") or "") + ("\n" + ci["format_expr"] if ci.get("format_expr") else "")
            if ci_code.strip():
                ci_cols, ci_meas, ci_sets, _ = _scan_dax_usage(ci_code)
                intra_model_used_measures.update(ci_meas)
                for cp in ci_cols:
                    dax_ref_counts[cp] += 1
                for st_l in ci_sets:
                    for col_pair in col_canon_by_low:
                        if col_pair[0] == st_l:
                            dax_ref_counts[col_pair] += 1

    # Model DAX measures -> column counts (plus UNION/EXCEPT set-locked tables)
    for m_key, m_info in lineage.items():
        for uc in m_info.get("upstream_columns", []):
            if "[" in uc and uc.endswith("]"):
                ut, ucol = uc.split("[", 1)
                upair = (ut.lower(), ucol[:-1].lower())
                if upair in col_canon_by_low:
                    dax_ref_counts[upair] += 1
        m_full_code = (m_info.get("expr") or "") + ("\n" + m_info["format_expr"] if m_info.get("format_expr") else "")
        _, _, m_sets, _ = _scan_dax_usage(m_full_code)
        for st_l in m_sets:
            for col_pair in col_canon_by_low:
                if col_pair[0] == st_l:
                    dax_ref_counts[col_pair] += 1

    # RLS tablePermission DAX + OLS columnPermission
    for role in parsed["roles"]:
        for tp in role.get("filters") or []:
            tp_tl = (tp.get("table") or "").lower()
            r_cols, r_meas, _, _ = _scan_dax_usage(tp.get("filter_dax") or "", row_context_table_low=tp_tl)
            rls_cols_low.update(r_cols)
            intra_model_used_measures.update(r_meas)
        for ols in role.get("ols_columns") or []:
            opair = ((ols.get("table") or "").lower(), (ols.get("column") or "").lower())
            if opair in col_canon_by_low:
                rls_cols_low.add(opair)

    auto_date_levels = {"year", "quarter", "month", "day", "date"}
    measure_report_usage: dict[str, list[dict]] = collections.defaultdict(list)
    visual_ref_counts: dict[tuple[str, str], int] = collections.Counter()
    filter_ref_counts: dict[tuple[str, str], int] = collections.Counter()
    col_report_names: dict[tuple[str, str], set[str]] = collections.defaultdict(set)
    enriched_reports: list[dict] = []
    has_parsed_layouts = False
    total_broken_refs = 0
    broken_report_names: list[str] = []
    total_report_measures = 0
    shadow_report_names: list[str] = []

    filter_str_re = re.compile(r"('(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_ .&-]*?)\[([^\]]+)\]")

    def _extract_filter_candidates(
        structured_fields: list[dict] | None,
        raw_strings: list[str] | None,
    ) -> list[dict[str, str]]:
        out_f: list[dict[str, str]] = []
        seen_f: set[tuple[str, str, str]] = set()
        for sf in structured_fields or []:
            if not isinstance(sf, dict) or not sf.get("property"):
                continue
            sig = ((sf.get("kind") or "column").lower(), (sf.get("entity") or "").lower(), sf["property"].lower())
            if sig not in seen_f:
                seen_f.add(sig)
                out_f.append(sf)
        for rs in raw_strings or []:
            for fm in filter_str_re.finditer(str(rs or "")):
                raw_ent = fm.group(1).strip()
                # Strip leading logical keywords like 'and ', 'or ', 'not ' if unquoted
                if not raw_ent.startswith("'"):
                    raw_ent = re.sub(r"^(?:and|or|not)\s+", "", raw_ent, flags=re.I).strip()
                ent_nm = _unquote(raw_ent)
                prop_nm = fm.group(2).strip()
                if not ent_nm or not prop_nm:
                    continue
                ent_l = ent_nm.lower()
                prop_l = prop_nm.lower()
                kind_guess = "measure" if (ent_l, prop_l) in measure_by_qual_low else "column"
                sig = (kind_guess, ent_l, prop_l)
                if sig not in seen_f:
                    seen_f.add(sig)
                    out_f.append({"entity": ent_nm, "property": prop_nm, "kind": kind_guess, "ref": f"{ent_nm}[{prop_nm}]"})
        return out_f

    for rep in reports or []:
        rep_copy = dict(rep)
        rep_label = rep_copy.get("name", "Report")
        layout = rep_copy.get("layout")
        if isinstance(layout, dict) and layout.get("pages"):
            has_parsed_layouts = True
            rep_meas = layout.get("report_measures") or []
            rep_meas_names = {m.get("name", "").lower() for m in rep_meas if m.get("name")}
            if rep_meas:
                total_report_measures += len(rep_meas)
                shadow_report_names.append(rep_label)

            rep_broken: list[dict] = []
            rep_used_m_pages: dict[str, set[str]] = collections.defaultdict(set)
            rep_used_m_vis_cnt: dict[str, int] = collections.defaultdict(int)
            broken_rep_meas_map: dict[str, list[str]] = {}
            projected_rep_meas: set[str] = set()

            # Report-level measures can reference both model measures and model columns
            for rm in rep_meas:
                rm_name = rm.get("name") or "Measure"
                rm_cols, rm_meas, rm_sets, rm_broken = _scan_dax_usage(
                    rm.get("expr") or "",
                    local_measure_names=rep_meas_names,
                    collect_broken=True,
                )
                rm["broken_refs"] = rm_broken
                if rm_broken:
                    broken_rep_meas_map[rm_name.lower()] = rm_broken
                for cand_m in rm_meas:
                    rep_used_m_pages[cand_m].add("Report Measure")
                    rep_used_m_vis_cnt[cand_m] += 1
                for cp in rm_cols:
                    dax_ref_counts[cp] += 1
                    col_report_names[cp].add(rep_label)
                for st_l in rm_sets:
                    for col_pair in col_canon_by_low:
                        if col_pair[0] == st_l:
                            dax_ref_counts[col_pair] += 1
                            col_report_names[col_pair].add(rep_label)

            def _validate_and_record_filter(
                fcand: dict[str, str],
                scope_page: str,
                scope_vis_label: str,
                vis_broken_out: list[str] | None = None,
            ) -> None:
                ent = (fcand.get("entity") or "").strip()
                prop = (fcand.get("property") or "").strip()
                kind = (fcand.get("kind") or "column").lower()
                if not prop:
                    return
                ent_l = ent.lower()
                prop_l = prop.lower()
                if kind == "measure" or (not ent_l and prop_l in measure_key_by_low):
                    m_key = measure_by_qual_low.get((ent_l, prop_l)) or measure_key_by_low.get(prop_l)
                    if m_key:
                        rep_used_m_pages[m_key].add(scope_page)
                        rep_used_m_vis_cnt[m_key] += 1
                        return
                    if prop_l in rep_meas_names:
                        return
                    b_ref = fcand.get("ref") or f"{ent}[{prop}]"
                    if vis_broken_out is not None:
                        if b_ref not in vis_broken_out:
                            vis_broken_out.append(b_ref)
                    else:
                        rep_broken.append({"page": scope_page, "visual": scope_vis_label, "ref": b_ref})
                    return

                if (ent_l, prop_l) in col_canon_by_low:
                    filter_ref_counts[(ent_l, prop_l)] += 1
                    col_report_names[(ent_l, prop_l)].add(rep_label)
                    return
                if (ent_l, prop_l) in hierarchy_levels_by_low:
                    for h_col_l in hierarchy_levels_by_low[(ent_l, prop_l)]:
                        if (ent_l, h_col_l) in col_canon_by_low:
                            filter_ref_counts[(ent_l, h_col_l)] += 1
                            col_report_names[(ent_l, h_col_l)].add(rep_label)
                    return
                if (ent_l, prop_l) in measure_by_qual_low:
                    m_key = measure_by_qual_low[(ent_l, prop_l)]
                    rep_used_m_pages[m_key].add(scope_page)
                    rep_used_m_vis_cnt[m_key] += 1
                    return
                if (
                    (ent_l, prop_l) in valid_cols
                    or ent_l.startswith(("localdatetable_", "datetabletemplate_"))
                    or (fcand.get("level") and (ent_l, prop_l) in valid_cols)
                ):
                    return
                # Flag broken filter reference when table or structured AST filter came from report metadata
                if ent_l in table_name_by_low or fcand in (layout.get("report_filter_fields") or []) or vis_broken_out is not None or scope_vis_label in ("Page Filter", "Report Filter"):
                    b_ref = fcand.get("ref") or (f"{ent}[{prop}]" if ent else prop)
                    if vis_broken_out is not None:
                        if b_ref not in vis_broken_out:
                            vis_broken_out.append(b_ref)
                    else:
                        rep_broken.append({"page": scope_page, "visual": scope_vis_label, "ref": b_ref})

            for rf in _extract_filter_candidates(layout.get("report_filter_fields"), layout.get("report_filters")):
                _validate_and_record_filter(rf, "Report Filters", "Report Filter")

            for pg in layout.get("pages", []):
                pg_name = pg.get("name", "Page")
                for pf in _extract_filter_candidates(pg.get("filter_fields"), pg.get("filters")):
                    _validate_and_record_filter(pf, pg_name, "Page Filter")

                for vis in pg.get("visuals", []):
                    vis_broken: list[str] = []
                    for fld in vis.get("fields", []):
                        ent = (fld.get("entity") or "").strip()
                        prop = (fld.get("property") or "").strip()
                        kind = (fld.get("kind") or "column").lower()
                        if not prop:
                            continue
                        ent_l = ent.lower()
                        prop_l = prop.lower()

                        if kind == "measure" or (not ent_l and kind != "column" and (prop_l in measure_key_by_low or prop_l in rep_meas_names)):
                            m_key = (measure_by_qual_low.get((ent_l, prop_l)) if ent_l else None) or measure_key_by_low.get(prop_l)
                            if m_key:
                                rep_used_m_pages[m_key].add(pg_name)
                                rep_used_m_vis_cnt[m_key] += 1
                                fld["broken"] = False
                                fld["measure_key"] = m_key
                                continue
                            if prop_l in rep_meas_names:
                                projected_rep_meas.add(prop_l)
                                fld["is_report_measure"] = True
                                rm_errs = broken_rep_meas_map.get(prop_l)
                                if rm_errs:
                                    fld["broken"] = True
                                    for r_err in rm_errs:
                                        msg = f"[{prop}] -> {r_err}"
                                        if msg not in vis_broken:
                                            vis_broken.append(msg)
                                else:
                                    fld["broken"] = False
                                continue
                            fld["broken"] = True
                            vis_broken.append(fld.get("ref") or prop)
                            continue

                        # Also support legacy/demo bindings where kind defaulted to 'column' on a measure or report measure ONLY if no column exists with that (ent_l, prop_l)
                        if (ent_l, prop_l) not in col_canon_by_low:
                            m_qual = measure_by_qual_low.get((ent_l, prop_l)) if ent_l else measure_key_by_low.get(prop_l)
                            if m_qual:
                                rep_used_m_pages[m_qual].add(pg_name)
                                rep_used_m_vis_cnt[m_qual] += 1
                                fld["broken"] = False
                                fld["measure_key"] = m_qual
                                continue
                            if prop_l in rep_meas_names and (not ent_l or ent_l in table_name_by_low or ent_l == "report measures"):
                                projected_rep_meas.add(prop_l)
                                fld["is_report_measure"] = True
                                rm_errs = broken_rep_meas_map.get(prop_l)
                                if rm_errs:
                                    fld["broken"] = True
                                    for r_err in rm_errs:
                                        msg = f"[{prop}] -> {r_err}"
                                        if msg not in vis_broken:
                                            vis_broken.append(msg)
                                else:
                                    fld["broken"] = False
                                continue

                        if (ent_l, prop_l) in col_canon_by_low:
                            visual_ref_counts[(ent_l, prop_l)] += 1
                            col_report_names[(ent_l, prop_l)].add(rep_label)
                            fld["broken"] = False
                            continue

                        if (ent_l, prop_l) in hierarchy_levels_by_low:
                            for h_col_l in hierarchy_levels_by_low[(ent_l, prop_l)]:
                                if (ent_l, h_col_l) in col_canon_by_low:
                                    visual_ref_counts[(ent_l, h_col_l)] += 1
                                    col_report_names[(ent_l, h_col_l)].add(rep_label)
                            fld["broken"] = False
                            continue

                        if (ent_l, prop_l) in level_alias_to_col_low:
                            real_cl = level_alias_to_col_low[(ent_l, prop_l)]
                            if (ent_l, real_cl) in col_canon_by_low:
                                visual_ref_counts[(ent_l, real_cl)] += 1
                                col_report_names[(ent_l, real_cl)].add(rep_label)
                            fld["broken"] = False
                            continue

                        is_valid_col = (
                            (ent_l, prop_l) in valid_cols
                            or (not ent_l and prop_l in valid_col_names)
                            or ent_l.startswith("localdatetable_")
                            or ent_l.startswith("datetabletemplate_")
                            or (kind == "hierarchy" and bool(fld.get("level")) and prop_l in auto_date_levels and not ent_l)
                        )
                        fld["broken"] = not is_valid_col
                        if not is_valid_col:
                            b_txt = fld.get("ref") or prop
                            if b_txt not in vis_broken:
                                vis_broken.append(b_txt)

                    for vf in _extract_filter_candidates(vis.get("filter_fields"), vis.get("filters")):
                        _validate_and_record_filter(vf, pg_name, vis.get("title") or vis.get("type_label") or "Visual", vis_broken_out=vis_broken)

                    vis["broken_refs"] = vis_broken
                    for br in vis_broken:
                        rep_broken.append({"page": pg_name, "visual": vis.get("title") or vis.get("type_label") or "Visual", "ref": br})

            # Surface broken unprojected report-level DAX measures too
            for rm_low, rm_errs in broken_rep_meas_map.items():
                if rm_low not in projected_rep_meas:
                    for r_err in rm_errs:
                        rep_broken.append({"page": "Report Measures", "visual": f"Report DAX [{rm_low}]", "ref": r_err})

            for m_key, pg_set in rep_used_m_pages.items():
                measure_report_usage[m_key].append(
                    {
                        "report_id": rep_copy.get("id", ""),
                        "report_name": rep_label,
                        "workspace": rep_copy.get("workspace", ""),
                        "pages": sorted(pg_set),
                        "visual_count": rep_used_m_vis_cnt[m_key],
                    }
                )
            rep_copy["broken_refs"] = rep_broken
            rep_copy["pages_count"] = len(layout.get("pages", []))
            rep_copy["visuals_count"] = sum(len(pg.get("visuals", [])) for pg in layout.get("pages", []))
            rep_copy["report_measures_count"] = len(rep_meas)
            if rep_broken:
                total_broken_refs += len(rep_broken)
                broken_report_names.append(rep_label)
        else:
            rep_copy.setdefault("broken_refs", [])
        enriched_reports.append(rep_copy)

    # Propagate transitive usage upstream so base measures feeding report KPIs or Field Parameters are recognized as used
    directly_used_measures = set(measure_report_usage.keys()) | intra_model_used_measures
    transitively_used_measures = set(directly_used_measures)
    queue = list(directly_used_measures)
    while queue:
        cur_m = queue.pop()
        for up_m in (lineage.get(cur_m) or {}).get("upstream_measures", []):
            if up_m not in transitively_used_measures:
                transitively_used_measures.add(up_m)
                queue.append(up_m)

    for m_key, m_info in lineage.items():
        m_info["used_in_reports"] = measure_report_usage.get(m_key, [])
        m_info["is_used_direct"] = m_key in directly_used_measures
        m_info["is_used_any"] = m_key in transitively_used_measures

    unused_measures_count = (measures_total - len(transitively_used_measures)) if has_parsed_layouts else 0

    # Finalize Column Usage Profiles on all non-auto-date tables & table_summaries
    unused_columns_count = 0
    ts_by_name = {ts["name"]: ts for ts in table_summaries}
    for tbl in data_tables:
        tl = tbl["name"].lower()
        tbl_unreferenced: list[str] = []
        for c in tbl["columns"]:
            cl = c["name"].lower()
            pair = (tl, cl)
            is_key = pair in key_cols_low
            is_sort_by = pair in sort_by_cols_low
            is_fp = pair in field_param_cols_low
            is_hier = pair in hierarchy_cols_low
            is_rls = pair in rls_cols_low
            is_ref_m = pair in refresh_cols_low
            dax_cnt = dax_ref_counts.get(pair, 0)
            vis_cnt = visual_ref_counts.get(pair, 0)
            flt_cnt = filter_ref_counts.get(pair, 0)

            badges: list[dict[str, str]] = []
            if is_key:
                badges.append({"label": "Key", "tone": "accent"})
            if is_sort_by:
                badges.append({"label": "SortBy", "tone": "dim"})
            if is_fp:
                badges.append({"label": "Field Param", "tone": "accent"})
            if is_hier:
                badges.append({"label": "Hierarchy", "tone": "dim"})
            if is_rls:
                badges.append({"label": "RLS", "tone": "warn"})
            if is_ref_m:
                badges.append({"label": "Refresh", "tone": "dim"})
            if dax_cnt > 0:
                badges.append({"label": f"DAX ({dax_cnt})", "tone": "accent"})
            if vis_cnt > 0:
                badges.append({"label": f"Visuals ({vis_cnt})", "tone": "ok"})
            if flt_cnt > 0:
                badges.append({"label": f"Filter ({flt_cnt})", "tone": "dim"})

            model_used = bool(is_key or is_sort_by or is_fp or is_hier or is_rls or is_ref_m or dax_cnt > 0)
            report_used = bool(vis_cnt > 0 or flt_cnt > 0)
            is_ref_any = model_used or report_used

            if has_parsed_layouts:
                status_val = "used" if is_ref_any else "unused"
                if not is_ref_any:
                    unused_columns_count += 1
                    tbl_unreferenced.append(c["name"])
                summary_str = ", ".join(b["label"] for b in badges) if badges else "Unused"
            else:
                status_val = "used" if model_used else "unknown"
                summary_str = ", ".join(b["label"] for b in badges) if badges else "-"

            c["usage"] = {
                "status": status_val,
                "is_referenced": is_ref_any,
                "model_used": model_used,
                "report_used": report_used,
                "key": is_key,
                "sort_by": is_sort_by,
                "field_param": is_fp,
                "hierarchy": is_hier,
                "rls": is_rls,
                "refresh": is_ref_m,
                "dax_count": dax_cnt,
                "visual_count": vis_cnt,
                "filter_count": flt_cnt,
                "reports": sorted(col_report_names.get(pair, set())),
                "badges": badges,
                "summary": summary_str,
            }

        ts_entry = ts_by_name.get(tbl["name"])
        if ts_entry is not None:
            ts_entry["unused_columns_count"] = len(tbl_unreferenced)
            ts_entry["unreferenced_columns"] = tbl_unreferenced

    used_columns_count = (columns_total - unused_columns_count) if has_parsed_layouts else columns_total

    if total_broken_refs > 0:
        findings.append(
            {
                "severity": "bad",
                "title": f"{total_broken_refs} broken visual field reference(s) in {len(broken_report_names)} bound report(s)",
                "detail": f"Reports ({', '.join(broken_report_names[:4])}) reference deleted or renamed model fields. Open the Report Inspector to locate exact pages and visuals.",
            }
        )
    if total_report_measures > 0:
        findings.append(
            {
                "severity": "warn",
                "title": f"{total_report_measures} report-level DAX measure(s) defined outside the semantic model",
                "detail": f"Thin report(s) ({', '.join(shadow_report_names[:4])}) contain local DAX extensions that cannot be shared across other reports.",
            }
        )
    if has_parsed_layouts and measures_total >= 6 and unused_measures_count > 0:
        findings.append(
            {
                "severity": "warn",
                "title": f"{unused_measures_count} of {measures_total} DAX measure(s) unused in model & scanned reports",
                "detail": "Review the 'Unused' filter in Section 4 before removing measures (verify unscanned workspaces, Analyze in Excel, or Paginated Reports first).",
            }
        )
    if has_parsed_layouts and columns_total >= 8 and unused_columns_count > 0:
        findings.append(
            {
                "severity": "warn",
                "title": f"{unused_columns_count} of {columns_total} column(s) unused in model & scanned reports",
                "detail": "Review the 'Unused' filter in Section 3 before removing columns to reduce VertiPaq memory (verify unscanned workspaces, Analyze in Excel, or Paginated Reports first).",
            }
        )

    # Match upstream Dataflows linked via M-partitions, REST links, or entity names (including multi-hop L2+ chains)
    upstream_dataflows: list[dict] = []
    if dataflows:
        df_by_id = {k.lower(): v for k, v in dataflows.items()}
        seen_df_ids: dict[str, int] = {}
        tables_by_df: dict[str, list[str]] = collections.defaultdict(list)
        raw_links = dataset_dataflow_links or []
        if isinstance(raw_links, dict):
            raw_links = raw_links.get(model_meta.get("id", ""), []) or []
        for ln in raw_links:
            if not isinstance(ln, dict):
                continue
            did = (ln.get("dataflow_id") or "").lower()
            if did in df_by_id:
                real_id = df_by_id[did]["id"]
                seen_df_ids.setdefault(real_id, 1)
        for lnk in table_df_links:
            did = (lnk.get("dataflow_id") or "").lower()
            ent_low = (lnk.get("entity") or "").lower()
            matched_df = df_by_id.get(did)
            if not matched_df and ent_low:
                for cand_df in dataflows.values():
                    if any(e.get("name", "").lower() == ent_low for e in cand_df.get("entities", [])):
                        matched_df = cand_df
                        break
            if matched_df:
                real_id = matched_df["id"]
                if lnk["table"] not in tables_by_df[real_id]:
                    tables_by_df[real_id].append(lnk["table"])
                seen_df_ids[real_id] = 1

        # Traverse multi-hop upstream dataflows (L1 -> L2 -> L3...)
        bfs_q = [(did, 1) for did in list(seen_df_ids)]
        while bfs_q:
            cur_id, cur_layer = bfs_q.pop(0)
            if cur_layer >= 8:
                continue
            cur_df = dataflows.get(cur_id) or {}
            up_ids: set[str] = set()
            for up in cur_df.get("upstream") or cur_df.get("upstream_dataflows") or []:
                if isinstance(up, dict):
                    uid = (up.get("targetDataflowId") or up.get("dataflow_id") or up.get("dataflowObjectId") or "").lower()
                    if uid in df_by_id:
                        up_ids.add(df_by_id[uid]["id"])
            for ent in cur_df.get("entities") or []:
                for r in ent.get("dataflow_refs") or []:
                    uid = (r.get("dataflow_id") or "").lower()
                    if uid in df_by_id:
                        up_ids.add(df_by_id[uid]["id"])
            for uid in up_ids:
                nxt_layer = cur_layer + 1
                if uid not in seen_df_ids or nxt_layer > seen_df_ids[uid]:
                    seen_df_ids[uid] = nxt_layer
                    for tname in tables_by_df.get(cur_id, []):
                        if tname not in tables_by_df[uid]:
                            tables_by_df[uid].append(tname)
                    bfs_q.append((uid, nxt_layer))

        missing_df_names: list[str] = []
        for did, layer in sorted(seen_df_ids.items(), key=lambda kv: (kv[1], (dataflows[kv[0]].get("name") or "").lower())):
            df_obj = dict(dataflows[did])
            df_obj["layer"] = layer
            df_obj["feeds_tables"] = tables_by_df[did]
            upstream_dataflows.append(df_obj)
            if str(df_obj.get("definition_status") or "").startswith("missing:"):
                missing_df_names.append(df_obj.get("name") or did)

        if missing_df_names:
            findings.append(
                {
                    "severity": "bad",
                    "title": f"{len(missing_df_names)} broken reference(s) to deleted or missing upstream Dataflow(s)",
                    "detail": f"Upstream dataflow(s) ({', '.join(missing_df_names)}) no longer exist in their workspace and will fail scheduled refresh.",
                }
            )

    return {
        "dataset_id": model_meta.get("id", ""),
        "name": model_meta.get("name", "Model"),
        "workspace_id": model_meta.get("workspace_id", ""),
        "workspace": model_meta.get("workspace", "Local"),
        "owner": model_meta.get("configured_by", ""),
        "storage_mode": model_meta.get("target_storage_mode", "") or "Power BI Service",
        "created_date": model_meta.get("created_date", ""),
        "last_refresh": refresh_info,
        "age_days": age_days,
        "reports": enriched_reports,
        "upstream_dataflows": upstream_dataflows,
        "fabric_items": list((fabric_items or {}).values()),
        "has_parsed_layouts": has_parsed_layouts,
        "workspace_users": model_meta.get("workspace_users") or [],
        "permissions": perms,
        "stats": {
            "tables": len(data_tables),
            "auto_date_tables": len(auto_dates),
            "import_tables": import_count,
            "directquery_tables": dq_count,
            "columns": columns_total,
            "used_columns": used_columns_count,
            "unused_columns": unused_columns_count,
            "measures": measures_total,
            "used_measures": len(transitively_used_measures) if has_parsed_layouts else measures_total,
            "unused_measures": unused_measures_count,
            "report_measures": total_report_measures,
            "broken_report_refs": total_broken_refs,
            "calc_columns": calc_cols_total,
            "relationships": len(parsed["relationships"]),
            "bidirectional_relationships": len(bi_rels),
            "rls_roles": len(parsed["roles"]),
            "pq_steps": total_pq_steps,
            "merges": total_merges,
            "appends": total_appends,
            "native_queries": native_query_count,
        },
        "source_types": sorted(all_source_types),
        "source_endpoints": source_endpoints,
        "table_summaries": table_summaries,
        "parsed": parsed,
        "lineage": lineage,
        "findings": findings,
    }


analyze_model = analyze_full_model

