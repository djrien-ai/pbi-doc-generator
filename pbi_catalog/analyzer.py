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


def parse_tmdl_bundle(tmdl: str) -> dict:
    """Losslessly parse a bundled TMDL definition into structured tables, expressions, relationships, and RLS roles."""
    tables: list[dict] = []
    expressions: list[dict] = []
    relationships: list[dict] = []
    roles: list[dict] = []

    for block in re.split(r"(?m)^// ===== ", tmdl or ""):
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
                "columns": [],
                "measures": [],
                "partitions": [],
                "hierarchies": [],
                "calculation_items": [],
            }
            for hdr, body, desc in _objects(head[0][1], 1):
                if hdr == "calculationGroup":
                    for chdr, cbody, cdesc in _objects(body, 2):
                        cm = re.match(r"^calculationItem\s+('(?:[^']|'')+'|[^=]+?)\s*=\s*(.*)$", chdr)
                        if cm:
                            tbl["calculation_items"].append(
                                {"name": _unquote(cm.group(1)), "expr": _expression(cm.group(2), cbody, 2), "description": cdesc}
                            )
                    continue
                kind, _, rest = hdr.partition(" ")
                hm = re.match(r"^('(?:[^']|'')+'|[^=]+?)\s*(?:(=)\s*(.*))?$", rest) if rest else None
                nm, eq, expr = hm.groups() if hm else (rest.partition("=")[0], "=" if "=" in rest else "", rest.partition("=")[2])
                eq, expr = eq or "", expr or ""
                pr = _props(body, 1)
                if kind == "column":
                    tbl["columns"].append(
                        {
                            "name": _unquote(nm),
                            "type": pr.get("dataType", ""),
                            "source": pr.get("sourceColumn", ""),
                            "format": pr.get("formatString", ""),
                            "folder": pr.get("displayFolder", ""),
                            "hidden": bool(pr.get("isHidden")),
                            "description": desc,
                            "expr": mask_secrets(_expression(expr, body, 1)) if eq else "",
                        }
                    )
                elif kind == "measure":
                    tbl["measures"].append(
                        {
                            "name": _unquote(nm),
                            "expr": mask_secrets(_expression(expr, body, 1)),
                            "format": pr.get("formatString", ""),
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
                    tbl["partitions"].append(
                        {
                            "name": _unquote(nm),
                            "kind": expr.strip(),
                            "mode": pr.get("mode", ""),
                            "code": mask_secrets(code),
                        }
                    )
                elif kind == "hierarchy":
                    levels = [
                        _props(lb, 2).get("column", _unquote(lh.partition(" ")[2]))
                        for lh, lb, _ in _objects(body, 2)
                        if lh.startswith("level ")
                    ]
                    tbl["hierarchies"].append({"name": _unquote(rest), "levels": levels})
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
            for hdr, body, _ in _objects(head[0][1], 1):
                m = re.match(r"^tablePermission\s+('(?:[^']|'')+'|[^=]+?)\s*=\s*(.*)$", hdr)
                if m:
                    filters.append({"table": _unquote(m.group(1)), "filter_dax": mask_secrets(_expression(m.group(2), body, 1))})
            roles.append(
                {
                    "name": _unquote(re.sub(r"^role\s+", "", head[0][0])),
                    "permission": pr.get("modelPermission", "read"),
                    "filters": filters,
                }
            )

    tables.sort(key=lambda t: (t["auto_date"], t["name"].lower()))
    return {
        "tables": tables,
        "expressions": expressions,
        "relationships": relationships,
        "roles": roles,
    }


def analyze_m_partition(code: str, params: dict[str, str], shared_names: list[str]) -> dict:
    """Inspect a Power Query M script to detect connectors, objects/views, native SQL, and transformation counts."""
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

    # Extract navigated object/view/table names (e.g. Schema/Table or HANA Package/View)
    nav_objects: list[str] = []
    nav_names = [
        m.group(1).replace('""', '"')
        for m in re.finditer(r'\{\[\s*(?:Name|Item|Schema)\s*=\s*"((?:[^"]|"")*)"', src)
        if m.group(1) not in ("Contents",)
    ]
    if len(nav_names) >= 2:
        nav_objects.append("/".join(nav_names[-2:]))
    elif len(nav_names) == 1:
        nav_objects.append(nav_names[0])

    native_queries = [
        mask_secrets(m.group(1).replace('""', '"'))
        for m in re.finditer(r'(?:Query\s*=|Value\.NativeQuery\([^,]+,)\s*"((?:[^"]|"")*)"', src)
    ]

    deps = []
    for sname in shared_names:
        pat = r'(?<![\w."])(?:#"' + re.escape(sname) + r'"|' + re.escape(sname) + r')(?![\w"])'
        if re.search(pat, src):
            deps.append(sname)

    steps = {label: len(re.findall(pat, src)) for label, pat in STEP_PATTERNS}
    step_count = len(re.findall(r'(?m)^\s*(?:#"(?:[^"]|"")+"|[A-Za-z_][\w.]*)\s*=(?!=)', src))

    src_types = sorted({s["type"] for s in sources})
    if "Entered Data (Manual Table)" in src_types and "JSON" in src_types:
        src_types.remove("JSON")

    return {
        "source_types": src_types,
        "sources": sources,
        "objects": nav_objects,
        "native_queries": native_queries,
        "depends_on": deps,
        "step_count": step_count,
        "steps": steps,
    }


def build_dax_lineage(parsed_model: dict) -> dict[str, dict]:
    """Build upstream and downstream DAX measure & column dependency map."""
    measure_Index: dict[str, str] = {}
    items: dict[str, dict] = {}

    for tbl in parsed_model.get("tables", []):
        if tbl["auto_date"]:
            continue
        tname = tbl["name"]
        for m in tbl["measures"]:
            key = f"{tname}[{m['name']}]"
            measure_Index[m["name"].lower()] = key
            items[key] = {
                "key": key,
                "kind": "measure",
                "table": tname,
                "name": m["name"],
                "expr": m["expr"],
                "upstream_measures": [],
                "upstream_columns": [],
                "downstream_measures": [],
            }

    table_col_re = re.compile(r"('(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_ ]*)\[([^\]]+)\]")
    bare_ref_re = re.compile(r"(?<![A-Za-z0-9_'])\[([^\]]+)\]")

    for key, info in items.items():
        expr = info["expr"] or ""
        up_m = set()
        up_c = set()

        for tm in table_col_re.finditer(expr):
            rt = _unquote(tm.group(1))
            rc = tm.group(2).strip()
            cand = measure_Index.get(rc.lower())
            if cand and cand != key and cand.startswith(f"{rt}["):
                up_m.add(cand)
            else:
                up_c.add(f"{rt}[{rc}]")

        stripped_expr = table_col_re.sub(" ", expr)
        for bm in bare_ref_re.finditer(stripped_expr):
            ref_name = bm.group(1).strip()
            cand = measure_Index.get(ref_name.lower())
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


def analyze_full_model(model_meta: dict, tmdl_bundle: str, reports: list[dict] | None = None) -> dict:
    """Combine live Power BI metadata + parsed TMDL into a complete governance & documentation profile."""
    parsed = parse_tmdl_bundle(tmdl_bundle)
    params = {x["name"]: x["default_value"] for x in parsed["expressions"] if x["kind"] == "parameter" and x.get("default_value")}
    shared_names = [x["name"] for x in parsed["expressions"] if x["kind"] != "parameter"]

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

    code_by_table = {
        t["name"]: "\n".join(p["code"] for p in t["partitions"] if p["kind"] == "m")
        for t in data_tables
    }

    for tbl in data_tables:
        t_types: list[str] = []
        t_details: list[str] = []
        t_objects: list[str] = []
        t_steps = 0
        t_merges = 0
        t_appends = 0
        t_native: list[str] = []
        mode = ""

        for part in tbl["partitions"]:
            mode = mode or part.get("mode", "")
            if part["kind"] == "m":
                minfo = analyze_m_partition(part["code"], params, shared_names)
                for st in minfo["source_types"]:
                    if st not in t_types:
                        t_types.append(st)
                    all_source_types.add(st)
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
            elif part["kind"] == "calculated":
                if "DAX Calculated Table" not in t_types:
                    t_types.append("DAX Calculated Table")
            elif part["kind"] == "entity":
                if "Direct Lake" not in t_types:
                    t_types.append("Direct Lake")
                    all_source_types.add("Direct Lake")

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
                "merges": t_merges,
                "native_queries": t_native,
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
        "reports": reports or [],
        "workspace_users": model_meta.get("workspace_users") or [],
        "permissions": perms,
        "stats": {
            "tables": len(data_tables),
            "auto_date_tables": len(auto_dates),
            "import_tables": import_count,
            "directquery_tables": dq_count,
            "columns": columns_total,
            "measures": measures_total,
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

