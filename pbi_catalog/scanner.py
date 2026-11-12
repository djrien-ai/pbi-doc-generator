"""
Workspace, Semantic Model, Report, Dataflow, and Governance Metadata Scanner.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .analyzer import bundle_from_local_tmdl_dir
from .api import PowerBiReadOnlyClient
from .store import CatalogStore, utc_now_iso


class WorkspaceScanner:
    """Orchestrates incremental read-only scanning of Power BI workspaces and Fabric TMDL definitions."""

    def __init__(self, client: PowerBiReadOnlyClient, store: CatalogStore, log_fn: Callable[[str], None] | None = None):
        self.client = client
        self.store = store
        self.log = log_fn or (lambda msg: print(msg))

    def scan_inventory(self, workspace_filter: str = "", workspace_ids: list[str] | None = None) -> dict:
        """Step 1: List visible workspaces and collect reports, semantic models, dataflows, and data sources."""
        state = self.store.load()
        self.log("Fetching visible Power BI workspaces...")

        capacities: dict[str, str] = {}
        try:
            for cap in self.client.pbi_get_list("capacities"):
                capacities[cap["id"]] = cap.get("sku", "")
        except Exception:
            pass

        raw_groups = self.client.pbi_get_list("groups?$top=5000")
        visible_ids = set()
        for g in raw_groups:
            ws_id = g["id"]
            visible_ids.add(ws_id)
            cap_id = g.get("capacityId") or ""
            sku = capacities.get(cap_id, "Dedicated" if cap_id else "Shared (Pro)")
            prev = state["workspaces"].get(ws_id) or {}
            state["workspaces"][ws_id] = {
                "id": ws_id,
                "name": g.get("name", ""),
                "type": g.get("type", "Workspace"),
                "capacity_sku": sku,
                "is_dedicated": bool(g.get("isOnDedicatedCapacity")),
                "is_read_only": bool(g.get("isReadOnly")),
                "users": prev.get("users", []),
                "last_scanned": prev.get("last_scanned", ""),
            }

        if workspace_ids:
            chosen = [state["workspaces"][wid] for wid in workspace_ids if wid in state["workspaces"]]
        elif workspace_filter:
            needle = workspace_filter.lower()
            chosen = [w for w in state["workspaces"].values() if needle in w["name"].lower()]
        else:
            chosen = list(state["workspaces"].values())

        self.log(f"Scanning inventory for {len(chosen)} workspace(s)...")
        for idx, ws in enumerate(chosen, 1):
            ws_id = ws["id"]
            ws_name = ws["name"]
            # Clear stale reports/dataflows for this workspace before refreshing
            state["reports"] = {rid: r for rid, r in state["reports"].items() if r.get("workspace_id") != ws_id}
            state["dataflows"] = {did: d for did, d in state["dataflows"].items() if d.get("workspace_id") != ws_id}

            r_count = m_count = df_count = 0
            try:
                for r in self.client.pbi_get_list(f"groups/{ws_id}/reports"):
                    r_count += 1
                    state["reports"][r["id"]] = {
                        "id": r["id"],
                        "name": r.get("name", ""),
                        "report_type": r.get("reportType", "PowerBIReport"),
                        "dataset_id": r.get("datasetId", ""),
                        "dataset_workspace_id": r.get("datasetWorkspaceId", ws_id),
                        "workspace_id": ws_id,
                        "workspace": ws_name,
                        "web_url": r.get("webUrl", ""),
                    }
            except Exception as exc:
                state["errors"].append({"step": "reports", "workspace": ws_name, "error": str(exc)})

            try:
                ws_ds_ids = set()
                for d in self.client.pbi_get_list(f"groups/{ws_id}/datasets"):
                    m_count += 1
                    ds_id = d["id"]
                    ws_ds_ids.add(ds_id)
                    prev_m = state["models"].get(ds_id) or {}
                    sources = prev_m.get("datasources", [])
                    try:
                        sources = self.client.pbi_get_list(f"groups/{ws_id}/datasets/{ds_id}/datasources")
                    except Exception:
                        pass
                    state["models"][ds_id] = {
                        "id": ds_id,
                        "name": d.get("name", ""),
                        "workspace_id": ws_id,
                        "workspace": ws_name,
                        "configured_by": d.get("configuredBy", ""),
                        "created_date": d.get("createdDate", ""),
                        "target_storage_mode": d.get("targetStorageMode", ""),
                        "is_refreshable": bool(d.get("isRefreshable")),
                        "datasources": sources,
                        "last_refresh": prev_m.get("last_refresh", {}),
                        "permissions": prev_m.get("permissions", []),
                        "workspace_users": prev_m.get("workspace_users", []),
                        "definition_status": prev_m.get("definition_status", "pending"),
                        "definition_read_at": prev_m.get("definition_read_at", ""),
                    }
                # Prune models deleted from this workspace
                for old_id in [mid for mid, m in state["models"].items() if m.get("workspace_id") == ws_id and mid not in ws_ds_ids]:
                    state["models"].pop(old_id, None)
            except Exception as exc:
                state["errors"].append({"step": "datasets", "workspace": ws_name, "error": str(exc)})

            try:
                for df in self.client.pbi_get_list(f"groups/{ws_id}/dataflows"):
                    df_count += 1
                    df_id = df["objectId"]
                    state["dataflows"][df_id] = {
                        "id": df_id,
                        "name": df.get("name", ""),
                        "workspace_id": ws_id,
                        "workspace": ws_name,
                        "configured_by": df.get("configuredBy", ""),
                        "modified_at": df.get("modifiedDateTime", ""),
                    }
            except Exception:
                pass

            ws["last_scanned"] = utc_now_iso()
            self.store.save(state)
            self.log(f"  [{idx}/{len(chosen)}] {ws_name}: {m_count} models, {r_count} reports, {df_count} dataflows")

        return state

    def scan_model_definitions(
        self,
        workspace_filter: str = "",
        workspace_ids: list[str] | None = None,
        dataset_ids: list[str] | None = None,
        refresh: bool = False,
        include_access: bool = True,
        limit: int = 0,
    ) -> dict:
        """Step 2: Fetch full TMDL definitions, refresh history, and access lists for semantic models."""
        state = self.store.load()
        models = list(state["models"].values())
        if dataset_ids:
            target_set = set(dataset_ids)
            models = [m for m in models if m["id"] in target_set]
        elif workspace_ids:
            ws_set = set(workspace_ids)
            models = [m for m in models if m["workspace_id"] in ws_set]
        elif workspace_filter:
            needle = workspace_filter.lower()
            models = [m for m in models if needle in m["workspace"].lower()]

        if not refresh:
            models = [m for m in models if m.get("definition_status") != "ok"]
        if limit > 0:
            models = models[:limit]

        self.log(f"Reading full TMDL definitions for {len(models)} semantic model(s)...")
        ws_users_cache: dict[str, list[dict]] = {}

        for idx, m in enumerate(models, 1):
            ws_id = m["workspace_id"]
            ds_id = m["id"]
            self.log(f"  [{idx}/{len(models)}] {m['workspace']} / {m['name']}")

            try:
                files = self.client.get_model_tmdl_files(ws_id, ds_id)
                self.store.write_tmdl_bundle(m["name"], ds_id, files)
                m["definition_status"] = "ok"
                m["definition_read_at"] = utc_now_iso()
            except Exception as exc:
                m["definition_status"] = f"error: {str(exc)[:180]}"
                state["errors"].append({"step": "getDefinition", "workspace": m["workspace"], "model": m["name"], "error": str(exc)})

            if include_access:
                if ws_id not in ws_users_cache:
                    try:
                        ws_users_cache[ws_id] = self.client.pbi_get_list(f"groups/{ws_id}/users")
                        if ws_id in state["workspaces"]:
                            state["workspaces"][ws_id]["users"] = ws_users_cache[ws_id]
                    except Exception:
                        ws_users_cache[ws_id] = []
                m["workspace_users"] = ws_users_cache[ws_id]

                try:
                    refs = self.client.pbi_get_list(f"groups/{ws_id}/datasets/{ds_id}/refreshes?$top=1")
                    if refs:
                        r0 = refs[0]
                        m["last_refresh"] = {
                            "status": r0.get("status", ""),
                            "end_time": r0.get("endTime", ""),
                            "refresh_type": r0.get("refreshType", ""),
                        }
                except Exception:
                    pass

                try:
                    m["permissions"] = self.client.pbi_get_list(f"groups/{ws_id}/datasets/{ds_id}/users")
                except Exception:
                    pass

            self.store.save(state)

        return state

    @staticmethod
    def register_local_tmdl(store: CatalogStore, path: str, workspace_name: str = "Local Projects") -> dict:
        """Import a local `.pbip` or `.SemanticModel` directory directly into the catalog store."""
        p = Path(path).resolve()
        model_name, bundle = bundle_from_local_tmdl_dir(p)
        ds_id = f"local-{abs(hash(str(p).lower())) % 10**10:010d}"
        ws_id = "local-workspace"

        state = store.load()
        state["workspaces"][ws_id] = {
            "id": ws_id,
            "name": workspace_name,
            "type": "Local",
            "capacity_sku": "Local Disk",
            "is_dedicated": False,
            "is_read_only": True,
            "users": [],
            "last_scanned": utc_now_iso(),
        }
        out_tmdl = store.tmdl_path(model_name, ds_id)
        out_tmdl.write_text(bundle, encoding="utf-8")

        state["models"][ds_id] = {
            "id": ds_id,
            "name": model_name,
            "workspace_id": ws_id,
            "workspace": workspace_name,
            "configured_by": "Local Developer",
            "created_date": utc_now_iso(),
            "target_storage_mode": "TMDL (PBIP)",
            "is_refreshable": False,
            "datasources": [],
            "last_refresh": {"status": "Local", "end_time": utc_now_iso(), "refresh_type": "PBIP"},
            "permissions": [],
            "workspace_users": [],
            "definition_status": "ok",
            "definition_read_at": utc_now_iso(),
        }

        # Register sibling .Report folder if present so downstream report lineage lights up
        search_root = p.parent if (p.is_file() or p.name.endswith(".SemanticModel")) else p
        rep_dirs = list(search_root.glob("*.Report"))
        if rep_dirs:
            for rdir in rep_dirs:
                rep_name = rdir.name[: -len(".Report")]
                rep_id = f"rep-{abs(hash(str(rdir).lower())) % 10**10:010d}"
                state["reports"][rep_id] = {
                    "id": rep_id,
                    "name": rep_name,
                    "workspace_id": ws_id,
                    "workspace": workspace_name,
                    "dataset_id": ds_id,
                    "report_type": "PowerBIReport (PBIP)",
                }

        store.save(state)
        return state["models"][ds_id]

    @staticmethod
    def register_local_pbix_or_xlsx(store: CatalogStore, path: str, workspace_name: str = "Local Projects") -> dict:
        """Convert a local `.pbix` or `.xlsx` file (via PBIXRay / excel_extractor) into a catalog TMDL bundle."""
        import sys as _sys

        p = Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {p}")

        root_dir = str(Path(__file__).resolve().parent.parent)
        if root_dir not in _sys.path:
            _sys.path.insert(0, root_dir)

        is_excel = p.suffix.lower() == ".xlsx"
        from pbixray import PBIXRay  # type: ignore

        model = None
        try:
            model = PBIXRay(str(p))
        except Exception as exc:
            if not is_excel:
                raise ValueError(f"Could not read PBIX data model from '{p.name}': {exc}") from exc

        pq_override = None
        if is_excel:
            import excel_extractor  # type: ignore

            pq_override = excel_extractor.extract_excel_power_query(str(p))

        def _q(name: str) -> str:
            escaped = str(name).replace("'", "''")
            return f"'{escaped}'"

        def _fenced(code_text: str, tabs: int) -> str:
            pad = "\t" * tabs
            body_lines = [f"{pad}{ln}" for ln in str(code_text or "").splitlines()]
            return "```\n" + "\n".join(body_lines) + f"\n{pad}```"

        def _clean_str(val: object) -> str:
            if val is None:
                return ""
            s = str(val).strip()
            return "" if s.lower() == "nan" else s

        dtype_map = {
            "int64": "int64",
            "Int64": "int64",
            "float64": "double",
            "Float64": "double",
            "bool": "boolean",
            "boolean": "boolean",
            "datetime64[ns]": "dateTime",
            "decimal": "decimal",
            "string": "string",
            "object": "string",
        }

        all_tables: list[str] = []
        seen_tables: set[str] = set()

        def _add_tbl(tname: str) -> None:
            t = _clean_str(tname)
            if t and t not in seen_tables:
                seen_tables.add(t)
                all_tables.append(t)

        if model is not None and getattr(model, "tables", None) is not None:
            for t in model.tables:
                _add_tbl(str(t))

        pq_df = pq_override if pq_override is not None else (getattr(model, "power_query", None) if model is not None else None)
        dax_tables_df = getattr(model, "dax_tables", None) if model is not None else None
        schema_df = getattr(model, "schema", None) if model is not None else None
        measures_df = getattr(model, "dax_measures", None) if model is not None else None
        calc_cols_df = getattr(model, "dax_columns", None) if model is not None else None
        rels_df = getattr(model, "relationships", None) if model is not None else None
        params_df = getattr(model, "m_parameters", None) if model is not None else None

        for df in (pq_df, dax_tables_df, schema_df, measures_df, calc_cols_df):
            if df is not None and not getattr(df, "empty", True) and "TableName" in df.columns:
                for t in df["TableName"].dropna().astype(str).tolist():
                    _add_tbl(t)

        pq_by_tbl: dict[str, list[str]] = {}
        if pq_df is not None and not getattr(pq_df, "empty", True) and "TableName" in pq_df.columns:
            for _, row in pq_df.iterrows():
                t = _clean_str(row.get("TableName"))
                expr = _clean_str(row.get("Expression"))
                if t and expr:
                    pq_by_tbl.setdefault(t, []).append(expr)

        dax_tbl_by_name: dict[str, str] = {}
        if dax_tables_df is not None and not getattr(dax_tables_df, "empty", True) and "TableName" in dax_tables_df.columns:
            for _, row in dax_tables_df.iterrows():
                t = _clean_str(row.get("TableName"))
                expr = _clean_str(row.get("Expression"))
                if t and expr:
                    dax_tbl_by_name[t] = expr

        calc_col_map: dict[tuple[str, str], str] = {}
        if calc_cols_df is not None and not getattr(calc_cols_df, "empty", True):
            for _, row in calc_cols_df.iterrows():
                t = _clean_str(row.get("TableName"))
                c = _clean_str(row.get("ColumnName", row.get("Name")))
                expr = _clean_str(row.get("Expression"))
                if t and c and expr:
                    calc_col_map[(t, c)] = expr

        cols_by_tbl: dict[str, list[tuple[str, str]]] = {}
        seen_cols: set[tuple[str, str]] = set()
        if schema_df is not None and not getattr(schema_df, "empty", True):
            for _, row in schema_df.iterrows():
                t = _clean_str(row.get("TableName"))
                c = _clean_str(row.get("ColumnName"))
                dt_raw = _clean_str(row.get("PandasDataType", row.get("DataType", "string")))
                if t and c and (t, c) not in seen_cols:
                    seen_cols.add((t, c))
                    cols_by_tbl.setdefault(t, []).append((c, dtype_map.get(dt_raw, "string")))
        for (t, c) in calc_col_map:
            if (t, c) not in seen_cols:
                seen_cols.add((t, c))
                cols_by_tbl.setdefault(t, []).append((c, "string"))

        meas_by_tbl: dict[str, list[dict]] = {}
        if measures_df is not None and not getattr(measures_df, "empty", True):
            for _, row in measures_df.iterrows():
                t = _clean_str(row.get("TableName"))
                mname = _clean_str(row.get("Name"))
                if not t or not mname:
                    continue
                meas_by_tbl.setdefault(t, []).append(
                    {
                        "name": mname,
                        "expr": _clean_str(row.get("Expression")),
                        "folder": _clean_str(row.get("DisplayFolder")),
                        "format": _clean_str(row.get("FormatString")),
                        "desc": _clean_str(row.get("Description")),
                    }
                )

        files_dict: dict[str, str] = {"definition/model.tmdl": "model Model\n\tculture: en-US\n"}

        if params_df is not None and not getattr(params_df, "empty", True):
            expr_lines: list[str] = []
            for _, row in params_df.iterrows():
                pname = _clean_str(row.get("ParameterName", row.get("Name")))
                pexpr = _clean_str(row.get("Expression"))
                pdesc = _clean_str(row.get("Description"))
                if not pname or not pexpr:
                    continue
                if pdesc:
                    for dln in pdesc.splitlines():
                        expr_lines.append(f"/// {dln}")
                expr_lines.append(f"expression {_q(pname)} = {_fenced(pexpr, 2)}")
                expr_lines.append("")
            if expr_lines:
                files_dict["definition/expressions.tmdl"] = "\n".join(expr_lines)

        if rels_df is not None and not getattr(rels_df, "empty", True):
            rel_lines: list[str] = []
            for idx, (_, row) in enumerate(rels_df.iterrows(), 1):
                ft = _clean_str(row.get("FromTableName", row.get("FromTable")))
                fc = _clean_str(row.get("FromColumnName", row.get("FromColumn")))
                tt = _clean_str(row.get("ToTableName", row.get("ToTable")))
                tc = _clean_str(row.get("ToColumnName", row.get("ToColumn")))
                if not (ft and fc and tt and tc):
                    continue
                card_raw = _clean_str(row.get("Cardinality", "M:1")).upper()
                fcard = "one" if card_raw.startswith("1:") else "many"
                tcard = "many" if card_raw.endswith(":M") else "one"
                cf_raw = _clean_str(row.get("CrossFilteringBehavior", "Single")).lower()
                cf_val = "bothDirections" if cf_raw in ("2", "both", "bothdirections") else "oneDirection"
                act_raw = row.get("IsActive", True)
                is_active = str(act_raw).strip().lower() not in ("0", "false")
                rel_lines.append(f"relationship rel_{idx}")
                rel_lines.append(f"\tfromColumn: {_q(ft)}.{_q(fc)}")
                rel_lines.append(f"\ttoColumn: {_q(tt)}.{_q(tc)}")
                rel_lines.append(f"\tfromCardinality: {fcard}")
                rel_lines.append(f"\ttoCardinality: {tcard}")
                rel_lines.append(f"\tcrossFilteringBehavior: {cf_val}")
                if not is_active:
                    rel_lines.append("\tisActive: false")
                rel_lines.append("")
            if rel_lines:
                files_dict["definition/relationships.tmdl"] = "\n".join(rel_lines)

        for idx, tname in enumerate(all_tables, 1):
            safe_file = re.sub(r"[^A-Za-z0-9._-]+", "_", tname).strip("_") or f"table_{idx}"
            tlines = [f"table {_q(tname)}"]
            for m in meas_by_tbl.get(tname, []):
                if m["desc"]:
                    for dln in m["desc"].splitlines():
                        tlines.append(f"\t/// {dln}")
                tlines.append(f"\tmeasure {_q(m['name'])} = {_fenced(m['expr'], 3)}")
                if m["format"]:
                    tlines.append(f"\t\tformatString: {m['format']}")
                if m["folder"]:
                    tlines.append(f"\t\tdisplayFolder: {m['folder']}")
            for cname, cdtype in cols_by_tbl.get(tname, []):
                cexpr = calc_col_map.get((tname, cname), "")
                if cexpr:
                    tlines.append(f"\tcolumn {_q(cname)} = {_fenced(cexpr, 3)}")
                    tlines.append(f"\t\tdataType: {cdtype}")
                else:
                    tlines.append(f"\tcolumn {_q(cname)}")
                    tlines.append(f"\t\tdataType: {cdtype}")
                    tlines.append(f"\t\tsourceColumn: {cname}")
            if tname in dax_tbl_by_name:
                tlines.append(f"\tpartition {_q(tname)} = calculated")
                tlines.append("\t\tmode: import")
                tlines.append(f"\t\tsource = {_fenced(dax_tbl_by_name[tname], 3)}")
            else:
                for p_i, m_expr in enumerate(pq_by_tbl.get(tname, []), 1):
                    pname = tname if p_i == 1 else f"{tname}_{p_i}"
                    tlines.append(f"\tpartition {_q(pname)} = m")
                    tlines.append("\t\tmode: import")
                    tlines.append(f"\t\tsource = {_fenced(m_expr, 3)}")
            files_dict[f"definition/tables/{idx:03d}_{safe_file}.tmdl"] = "\n".join(tlines) + "\n"

        model_name = p.stem
        ds_id = f"local-{abs(hash(str(p).lower())) % 10**10:010d}"
        ws_id = "local-workspace"

        state = store.load()
        state["workspaces"][ws_id] = {
            "id": ws_id,
            "name": workspace_name,
            "type": "Local",
            "capacity_sku": "Local Disk",
            "is_dedicated": False,
            "is_read_only": True,
            "users": [],
            "last_scanned": utc_now_iso(),
        }
        store.write_tmdl_bundle(model_name, ds_id, files_dict)

        fmt_label = "Excel Data Model (.xlsx)" if is_excel else "PBIX Binary (.pbix)"
        state["models"][ds_id] = {
            "id": ds_id,
            "name": model_name,
            "workspace_id": ws_id,
            "workspace": workspace_name,
            "configured_by": "Local Developer",
            "created_date": utc_now_iso(),
            "target_storage_mode": fmt_label,
            "is_refreshable": False,
            "datasources": [],
            "last_refresh": {"status": "Local", "end_time": utc_now_iso(), "refresh_type": p.suffix.upper().lstrip(".")},
            "permissions": [],
            "workspace_users": [],
            "definition_status": "ok",
            "definition_read_at": utc_now_iso(),
        }

        if not is_excel:
            rep_id = f"rep-{ds_id}"
            state["reports"][rep_id] = {
                "id": rep_id,
                "name": f"{model_name} (Embedded Report)",
                "workspace_id": ws_id,
                "workspace": workspace_name,
                "dataset_id": ds_id,
                "report_type": "PowerBIReport (PBIX)",
            }

        store.save(state)
        return state["models"][ds_id]

    @classmethod
    def register_local_any(cls, store: CatalogStore, path: str, workspace_name: str = "Local Projects") -> dict:
        """Import any supported local Power BI artifact (.pbip, .SemanticModel folder, .pbix, or .xlsx) into the catalog."""
        p = Path(path).expanduser().resolve()
        if p.is_dir() or p.suffix.lower() in (".pbip", ".tmdl"):
            target = p.parent if (p.is_file() and p.suffix.lower() == ".tmdl") else p
            return cls.register_local_tmdl(store, str(target), workspace_name=workspace_name)
        if p.suffix.lower() in (".pbix", ".xlsx"):
            return cls.register_local_pbix_or_xlsx(store, str(p), workspace_name=workspace_name)
        raise ValueError(f"Unsupported path '{p}'. Provide a .pbix, .pbip, .xlsx, or .SemanticModel directory.")
