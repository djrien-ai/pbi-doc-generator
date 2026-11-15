"""
Workspace, Semantic Model, Report, Dataflow (Gen1 & Gen2), and Governance Metadata Scanner.
"""

from __future__ import annotations

import hashlib
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from .analyzer import bundle_from_local_tmdl_dir
from .api import PowerBiReadOnlyClient
from .dataflows import (
    definition_dataflow_refs,
    parse_dataflow_definition,
    referenced_dataflow_ids,
    strip_data_locations,
)
from .report_parser import (
    LAYOUT_VERSION,
    parse_pbip_report_dir,
    parse_pbix_report,
    parse_report_definition_files,
)
from .store import (
    CatalogStore,
    add_scope_extra,
    scope_workspace_ids,
    set_scan_scope,
    utc_now_iso,
)


class WorkspaceScanner:
    """Orchestrates incremental read-only scanning of Power BI workspaces, models, reports, and dataflows."""

    def __init__(
        self,
        client: PowerBiReadOnlyClient,
        store: CatalogStore,
        log_fn: Callable[[str], None] | None = None,
        progress_fn: Callable[[dict], None] | None = None,
    ):
        self.client = client
        self.store = store
        self.inventory_workers = 8
        self.definition_workers = 6
        self.report_workers = 8
        self.follow_outside = False
        self.log = log_fn or (lambda msg: print(msg))
        self.progress = progress_fn

    def _emit(self, **payload) -> None:
        if self.progress is not None:
            try:
                self.progress(payload)
            except Exception:
                pass

    def scan_inventory(self, workspace_filter: str = "", workspace_ids: list[str] | None = None) -> dict:
        """Step 1: List visible workspaces and collect reports, semantic models, dataflows (Gen1/Gen2), and links."""
        state = self.store.load()
        self.log("Fetching visible Power BI workspaces...")
        self._emit(phase="inventory", done=0, total=1, item="Listing Power BI workspaces...")

        capacities: dict[str, str] = {}
        try:
            for cap in self.client.pbi_get_list("capacities"):
                capacities[cap["id"]] = cap.get("sku", "")
        except Exception:
            pass

        raw_groups = self.client.pbi_get_list("groups?$top=5000")
        for g in raw_groups:
            ws_id = g["id"]
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

        set_scan_scope(state, [w["id"] for w in chosen], follow_outside=bool(self.follow_outside))
        self.log(f"Scanning inventory for {len(chosen)} workspace(s)...")

        datasource_jobs: list[tuple[str, str, str, str]] = []
        total_m_discovered = 0
        total_r_discovered = 0
        total_df_discovered = 0

        for idx, ws in enumerate(chosen, 1):
            ws_id = ws["id"]
            ws_name = ws["name"]
            self._emit(phase="inventory", done=idx - 1, total=max(1, len(chosen)), item=f"Listing items in {ws_name}...")
            prev_reports = {rid: r for rid, r in state["reports"].items() if r.get("workspace_id") == ws_id}
            prev_dfs = {did: d for did, d in state["dataflows"].items() if d.get("workspace_id") == ws_id}
            state["reports"] = {rid: r for rid, r in state["reports"].items() if r.get("workspace_id") != ws_id}
            state["dataflows"] = {did: d for did, d in state["dataflows"].items() if d.get("workspace_id") != ws_id}
            state["fabric_items"] = {
                iid: it for iid, it in state.get("fabric_items", {}).items() if it.get("workspace_id") != ws_id
            }

            r_count = m_count = df_count = 0
            try:
                for r in self.client.pbi_get_list(f"groups/{ws_id}/reports"):
                    r_count += 1
                    rid = r["id"]
                    prev_r = prev_reports.get(rid) or {}
                    same_ds = prev_r.get("dataset_id") == r.get("datasetId", "")
                    rep_obj = {
                        "id": rid,
                        "name": r.get("name") or "",
                        "report_type": r.get("reportType") or "PowerBIReport",
                        "dataset_id": r.get("datasetId") or "",
                        "dataset_workspace_id": r.get("datasetWorkspaceId") or ws_id,
                        "workspace_id": ws_id,
                        "workspace": ws_name,
                        "web_url": r.get("webUrl") or "",
                        "layout_status": prev_r.get("layout_status", "pending") if same_ds else "pending",
                        "measures_status": prev_r.get("measures_status", "pending") if same_ds else "pending",
                        "layout_version": prev_r.get("layout_version", 0) if same_ds else 0,
                        "pages_count": prev_r.get("pages_count", 0) if same_ds else 0,
                        "page_count": prev_r.get("pages_count", 0) if same_ds else 0,
                        "visuals_count": prev_r.get("visuals_count", 0) if same_ds else 0,
                        "visual_count": prev_r.get("visuals_count", 0) if same_ds else 0,
                        "report_measures_count": prev_r.get("report_measures_count", 0) if same_ds else 0,
                        "report_measure_count": prev_r.get("report_measures_count", 0) if same_ds else 0,
                    }
                    state["reports"][rid] = rep_obj
            except Exception as exc:
                state["errors"].append({"step": "reports", "workspace": ws_name, "error": str(exc)})

            ws_ds_ids: set[str] = set()
            try:
                for d in self.client.pbi_get_list(f"groups/{ws_id}/datasets"):
                    m_count += 1
                    ds_id = d["id"]
                    ds_name = d.get("name") or ""
                    ws_ds_ids.add(ds_id)
                    prev_m = state["models"].get(ds_id) or {}
                    state["models"][ds_id] = {
                        "id": ds_id,
                        "name": ds_name,
                        "workspace_id": ws_id,
                        "workspace": ws_name,
                        "configured_by": d.get("configuredBy") or "",
                        "created_date": d.get("createdDate") or "",
                        "target_storage_mode": d.get("targetStorageMode") or "",
                        "is_refreshable": bool(d.get("isRefreshable")),
                        "datasources": prev_m.get("datasources", []),
                        "last_refresh": prev_m.get("last_refresh", {}),
                        "permissions": prev_m.get("permissions", []),
                        "workspace_users": prev_m.get("workspace_users", []),
                        "definition_status": prev_m.get("definition_status", "pending"),
                        "definition_read_at": prev_m.get("definition_read_at", ""),
                    }
                    datasource_jobs.append((ws_id, ws_name, ds_id, ds_name))
                for old_id in [
                    mid for mid, m in state["models"].items() if m.get("workspace_id") == ws_id and mid not in ws_ds_ids
                ]:
                    state["models"].pop(old_id, None)
            except Exception as exc:
                state["errors"].append({"step": "datasets", "workspace": ws_name, "error": str(exc)})

            try:
                for df in self.client.pbi_get_list(f"groups/{ws_id}/dataflows"):
                    df_count += 1
                    df_id = df["objectId"]
                    prev_df = prev_dfs.get(df_id) or {}
                    modified = df.get("modifiedDateTime") or ""
                    unchanged = bool(prev_df) and prev_df.get("modified_at", "") == modified
                    gen_val = df.get("generation", 1)
                    gen_label = "Gen2" if str(gen_val) in ("2", "Gen2") else "Gen1"
                    state["dataflows"][df_id] = {
                        "id": df_id,
                        "name": df.get("name") or "",
                        "description": df.get("description") or "",
                        "generation": gen_label,
                        "workspace_id": ws_id,
                        "workspace": ws_name,
                        "configured_by": df.get("configuredBy") or "",
                        "modified_at": modified,
                        "upstream": prev_df.get("upstream", []),
                        "datasources": prev_df.get("datasources", []),
                        "entities": prev_df.get("entities", []) if unchanged else [],
                        "source_types": prev_df.get("source_types", []) if unchanged else [],
                        "definition_status": prev_df.get("definition_status", "pending") if unchanged else "pending",
                        "definition_read_at": prev_df.get("definition_read_at", "") if unchanged else "",
                    }
                if ws_id in state["workspaces"]:
                    state["workspaces"][ws_id]["dataflows_listed"] = True
            except Exception as exc:
                if ws_id in state["workspaces"]:
                    state["workspaces"][ws_id]["dataflows_listed"] = False
                state["errors"].append({"step": "dataflows", "workspace": ws_name, "error": str(exc)})

            try:
                links = self.client.get_dataset_dataflow_links(ws_id)
                state.setdefault("dataset_dataflow_links", {})
                for ds_id in ws_ds_ids:
                    state["dataset_dataflow_links"].pop(ds_id, None)
                for ln in links:
                    ds_id = ln.get("datasetObjectId") or ""
                    if ds_id:
                        state["dataset_dataflow_links"].setdefault(ds_id, []).append(
                            {
                                "dataflow_id": ln.get("dataflowObjectId", ""),
                                "workspace_id": ln.get("workspaceObjectId", ""),
                            }
                        )
            except Exception:
                pass

            try:
                fabric_keep = {"Lakehouse", "Warehouse", "SQLEndpoint", "Dataflow", "Notebook", "DataPipeline"}
                for fitem in self.client.get_fabric_workspace_items(ws_id):
                    ftype = fitem.get("type", "")
                    fid = fitem.get("id", "")
                    if not fid or ftype not in fabric_keep:
                        continue
                    fname = fitem.get("displayName") or fitem.get("name") or ""
                    fdesc = fitem.get("description", "")
                    if ftype == "Dataflow" and fid not in state["dataflows"]:
                        df_count += 1
                        prev_df = prev_dfs.get(fid) or {}
                        state["dataflows"][fid] = {
                            "id": fid,
                            "name": fname,
                            "description": fdesc,
                            "generation": "Gen2",
                            "workspace_id": ws_id,
                            "workspace": ws_name,
                            "configured_by": prev_df.get("configured_by", ""),
                            "modified_at": prev_df.get("modified_at", ""),
                            "upstream": prev_df.get("upstream", []),
                            "datasources": prev_df.get("datasources", []),
                            "entities": prev_df.get("entities", []),
                            "source_types": prev_df.get("source_types", []),
                            "definition_status": prev_df.get("definition_status", "pending"),
                            "definition_read_at": prev_df.get("definition_read_at", ""),
                        }
                    if fid not in state["dataflows"]:
                        state["fabric_items"][fid] = {
                            "id": fid,
                            "name": fname,
                            "type": ftype,
                            "description": fdesc,
                            "workspace_id": ws_id,
                            "workspace": ws_name,
                        }
            except Exception:
                pass

            ws["last_scanned"] = utc_now_iso()
            total_m_discovered += m_count
            total_r_discovered += r_count
            total_df_discovered += df_count
            self.log(f"  [{idx}/{len(chosen)}] {ws_name}: {m_count} models, {r_count} reports, {df_count} dataflows")

        self._emit(
            phase="inventory",
            event="counts",
            workspaces_total=len(chosen),
            models_total=total_m_discovered,
            reports_total=total_r_discovered,
            dataflows_total=total_df_discovered,
            done=0,
            total=max(1, len(datasource_jobs)),
            item="Reading gateway & datasource bindings...",
        )

        if datasource_jobs:
            total_ds = len(datasource_jobs)
            if total_ds > 10:
                self.log(f"Reading gateway & datasource bindings for {total_ds} semantic model(s) in parallel...")

            def _fetch_ds_sources(job: tuple[str, str, str, str]) -> tuple[str, str, str, list[dict] | None]:
                w_id, w_nm, d_id, d_nm = job
                try:
                    return d_id, w_nm, d_nm, self.client.pbi_get_list(f"groups/{w_id}/datasets/{d_id}/datasources")
                except Exception:
                    return d_id, w_nm, d_nm, None

            pool = ThreadPoolExecutor(max_workers=max(1, self.inventory_workers))
            try:
                futs = [pool.submit(_fetch_ds_sources, j) for j in datasource_jobs]
                for done_i, fut in enumerate(as_completed(futs), 1):
                    d_id, w_nm, d_nm, srcs = fut.result()
                    if srcs is not None and d_id in state["models"]:
                        state["models"][d_id]["datasources"] = srcs
                    self._emit(phase="inventory", done=done_i, total=total_ds, item=d_nm)
                    if total_ds > 10 and (done_i % 40 == 0 or done_i == total_ds):
                        self.log(f"  Datasource bindings: [{done_i}/{total_ds}] ({w_nm} / {d_nm})")
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

        self.store.save(state)
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
        """Step 2: Fetch full TMDL definitions in parallel, plus refresh history and access lists."""
        state = self.store.load()
        models = [m for m in state["models"].values() if m.get("workspace_id") != "local-workspace"]
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
        if not models:
            self._emit(phase="models", done=0, total=0, item="All semantic models up to date")
            return state

        total_models = len(models)
        self.log(f"Reading full TMDL definitions for {total_models} semantic model(s) ({self.definition_workers} parallel workers)...")
        self._emit(phase="models", done=0, total=total_models, item=models[0].get("name", ""))

        ws_users_cache: dict[str, list[dict]] = {}
        if include_access:
            for ws_id in {m["workspace_id"] for m in models}:
                try:
                    ws_users_cache[ws_id] = self.client.pbi_get_list(f"groups/{ws_id}/users")
                    if ws_id in state["workspaces"]:
                        state["workspaces"][ws_id]["users"] = ws_users_cache[ws_id]
                except Exception:
                    ws_users_cache[ws_id] = []

        def _fetch_one_model(m_item: dict) -> tuple[dict, str | None, dict | None, list[dict] | None]:
            w_id = m_item["workspace_id"]
            d_id = m_item["id"]
            err_msg: str | None = None
            try:
                files = self.client.get_model_tmdl_files(w_id, d_id)
                self.store.write_tmdl_bundle(m_item["name"], d_id, files)
            except Exception as exc:
                err_msg = str(exc)

            last_ref: dict | None = None
            perms: list[dict] | None = None
            if include_access:
                try:
                    refs = self.client.pbi_get_list(f"groups/{w_id}/datasets/{d_id}/refreshes?$top=1")
                    if refs:
                        r0 = refs[0]
                        last_ref = {
                            "status": r0.get("status", ""),
                            "end_time": r0.get("endTime", ""),
                            "refresh_type": r0.get("refreshType", ""),
                        }
                except Exception:
                    pass
                try:
                    perms = self.client.pbi_get_list(f"groups/{w_id}/datasets/{d_id}/users")
                except Exception:
                    pass
            return m_item, err_msg, last_ref, perms

        pool = ThreadPoolExecutor(max_workers=max(1, self.definition_workers))
        last_save = time.monotonic()
        try:
            futs = [pool.submit(_fetch_one_model, m) for m in models]
            for done_idx, fut in enumerate(as_completed(futs), 1):
                m, err_txt, last_ref, perms = fut.result()
                ws_id = m["workspace_id"]
                self.log(f"  [{done_idx}/{total_models}] {m['workspace']} / {m['name']}")
                if err_txt is None:
                    m["definition_status"] = "ok"
                    m["definition_read_at"] = utc_now_iso()
                else:
                    low_err = err_txt.lower()
                    if any(tok in low_err for tok in ("403", "401", "forbidden", "insufficientprivileges", "unauthorized")):
                        hint = "Requires at least Contributor workspace role (Viewer role cannot extract TMDL definitions)"
                        err_txt = f"{hint} - {err_txt}"
                        self.log(f"    Skipped TMDL for '{m['name']}': {hint}")
                    m["definition_status"] = f"error: {err_txt[:180]}"
                    state["errors"].append({"step": "getDefinition", "workspace": m["workspace"], "model": m["name"], "error": err_txt})

                if include_access:
                    m["workspace_users"] = ws_users_cache.get(ws_id, [])
                    if last_ref is not None:
                        m["last_refresh"] = last_ref
                    if perms is not None:
                        m["permissions"] = perms

                self._emit(phase="models", done=done_idx, total=total_models, item=m["name"])
                if time.monotonic() - last_save > 3.5:
                    self.store.save(state)
                    last_save = time.monotonic()
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        self.store.save(state)
        return state

    def scan_report_definitions(
        self,
        workspace_filter: str = "",
        workspace_ids: list[str] | None = None,
        refresh: bool = False,
        limit: int = 0,
        follow_shared_models: bool | None = None,
    ) -> dict:
        """Step 3: Fetch PBIR / layout definitions and thin-report DAX measures in parallel."""
        if follow_shared_models is None:
            follow_shared_models = bool(self.follow_outside)

        state = self.store.load()
        reps = [
            r
            for r in state.get("reports", {}).values()
            if r.get("workspace_id") != "local-workspace" and (r.get("report_type") or "PowerBIReport") == "PowerBIReport"
        ]
        if workspace_ids:
            ws_set = set(workspace_ids)
            reps = [r for r in reps if r.get("workspace_id") in ws_set]
        elif workspace_filter:
            needle = workspace_filter.lower()
            reps = [r for r in reps if needle in (r.get("workspace") or "").lower()]

        todo = [
            r
            for r in reps
            if refresh or r.get("layout_status") != "ok" or r.get("layout_version") != LAYOUT_VERSION
        ]
        if limit > 0:
            todo = todo[:limit]

        if todo:
            total_reps = len(todo)
            self.log(f"Reading visual layouts & thin-report DAX for {total_reps} Power BI report(s) ({self.report_workers} parallel workers)...")
            self._emit(phase="reports", done=0, total=total_reps, item=todo[0].get("name", ""))

            def _fetch_one_report(r_item: dict) -> tuple[dict, dict | None, str | None]:
                r_id = r_item["id"]
                try:
                    parts = self.client.get_report_definition_files(r_item["workspace_id"], r_id)
                    layout = parse_report_definition_files(parts)
                    ds_id = r_item.get("dataset_id") or layout.get("dataset_ref") or ""
                    layout["report_id"] = r_id
                    layout["dataset_id"] = ds_id
                    self.store.write_report_layout(r_id, layout)
                    return r_item, layout, None
                except Exception as exc:
                    return r_item, None, str(exc)

            pool = ThreadPoolExecutor(max_workers=max(1, self.report_workers))
            found_measures = 0
            last_save = time.monotonic()
            try:
                futs = [pool.submit(_fetch_one_report, r) for r in todo]
                for done_idx, fut in enumerate(as_completed(futs), 1):
                    rep, layout, err_raw = fut.result()
                    if err_raw is None and layout is not None:
                        ds_id = rep.get("dataset_id") or layout.get("dataset_ref") or ""
                        if ds_id and not rep.get("dataset_id"):
                            rep["dataset_id"] = ds_id
                        p_cnt = len(layout.get("pages", []))
                        v_cnt = sum(len(p.get("visuals", [])) for p in layout.get("pages", []))
                        rm_cnt = len(layout.get("report_measures", []))
                        rep["layout_status"] = "ok" if (p_cnt or rm_cnt) else "empty"
                        rep["measures_status"] = "ok"
                        rep["layout_version"] = LAYOUT_VERSION
                        rep["definition_format"] = layout.get("format", "")
                        rep["pages_count"] = rep["page_count"] = p_cnt
                        rep["visuals_count"] = rep["visual_count"] = v_cnt
                        rep["report_measures_count"] = rep["report_measure_count"] = rm_cnt
                        found_measures += rm_cnt
                        extra_m = f", {rm_cnt} report-level measure(s)" if rm_cnt else ""
                        self.log(
                            f"  [{done_idx}/{total_reps}] {rep.get('workspace')} / {rep.get('name')}: "
                            f"{p_cnt} page(s), {v_cnt} visual(s){extra_m}"
                        )
                    else:
                        err = err_raw or "Unknown report definition error"
                        if any(t in err.lower() for t in ("403", "401", "forbidden", "unauthorized")):
                            err = f"No access to report definition (requires Contributor role or higher) - {err}"
                        rep["layout_status"] = "unavailable"
                        rep["measures_status"] = f"error: {err[:180]}"
                        state["errors"].append(
                            {"step": "reportDefinition", "workspace": rep.get("workspace", ""), "report": rep.get("name", ""), "error": err}
                        )
                        self.log(f"  [{done_idx}/{total_reps}] {rep.get('workspace')} / {rep.get('name')} (layout unavailable)")

                    self._emit(phase="reports", done=done_idx, total=total_reps, item=rep.get("name", ""))
                    if time.monotonic() - last_save > 4.0:
                        self.store.save(state)
                        last_save = time.monotonic()
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

            self.store.save(state)
            self.log(
                f"Report definitions read: {sum(r.get('pages_count', 0) for r in todo)} page(s), "
                f"{sum(r.get('visuals_count', 0) for r in todo)} visual(s), {found_measures} report-level measure(s)."
            )
        else:
            self._emit(phase="reports", done=0, total=0, item="All report layouts up to date")

        if follow_shared_models:
            self.follow_shared_models(reps)
        return self.store.load()

    def follow_shared_models(self, reports: list[dict]) -> list[str]:
        """Register and read shared models used by thin reports when they reside outside selected workspaces."""
        state = self.store.load()
        in_scope = scope_workspace_ids(state)
        missing: dict[str, str] = {}
        for r in reports:
            ds = r.get("dataset_id") or ""
            if ds and ds not in state["models"]:
                missing[ds] = r.get("dataset_workspace_id") or r.get("workspace_id") or ""
            elif ds and in_scope and state["models"][ds].get("workspace_id") not in in_scope:
                add_scope_extra(state, ds)
        for ds in missing:
            add_scope_extra(state, ds)

        added: list[str] = []
        for ds, ws in missing.items():
            if not ws:
                continue
            ws_name = (state["workspaces"].get(ws) or {}).get("name") or f"Workspace {ws[:8]}"
            try:
                d = self.client.pbi_get_json(f"groups/{ws}/datasets/{ds}")
            except Exception as exc:
                self.log(f"  Shared model {ds[:8]} in '{ws_name}' not readable: {str(exc)[:140]}")
                continue
            state["models"][ds] = {
                "id": ds,
                "name": d.get("name", f"Model {ds[:8]}"),
                "workspace_id": ws,
                "workspace": ws_name,
                "configured_by": d.get("configuredBy", ""),
                "created_date": d.get("createdDate", ""),
                "target_storage_mode": d.get("targetStorageMode", ""),
                "is_refreshable": bool(d.get("isRefreshable")),
                "datasources": [],
                "last_refresh": {},
                "permissions": [],
                "workspace_users": [],
                "definition_status": "pending",
                "definition_read_at": "",
                "discovered_via": "thin report",
            }
            added.append(ds)
            self.log(f"  Followed shared model in external workspace: {ws_name} / {state['models'][ds]['name']}")
        self.store.save(state)
        if added:
            self.scan_model_definitions(dataset_ids=added, include_access=False)
        return added

    def scan_dataflow_definitions(
        self,
        workspace_filter: str = "",
        workspace_ids: list[str] | None = None,
        refresh: bool = False,
        follow_upstream: bool = True,
        max_follow_depth: int = 6,
        follow_outside: bool | None = None,
        limit: int = 0,
    ) -> dict:
        """Step 4: Export Dataflow Gen1 (`model.json`) & Fabric Gen2 (`mashup.pq`) definitions and follow multi-hop chains."""
        if follow_outside is None:
            follow_outside = bool(self.follow_outside)
        state = self.store.load()
        state.setdefault("dataflows", {})
        dfs = list(state["dataflows"].values())
        ws_set: set[str] | None = None
        if workspace_ids:
            ws_set = set(workspace_ids)
        elif workspace_filter:
            needle = workspace_filter.lower()
            ws_set = {wid for wid, w in state.get("workspaces", {}).items() if needle in (w.get("name") or "").lower()}
        if ws_set is not None:
            dfs = [d for d in dfs if d.get("workspace_id") in ws_set]

        queue: list[tuple[str, str, int]] = [(d.get("workspace_id", ""), d["id"], 0) for d in dfs]

        if follow_upstream:
            extra = {x.lower() for x in (state.get("scope") or {}).get("extra_ids") or []}
            for ds_id, m_meta in state.get("models", {}).items():
                if ws_set is not None and m_meta.get("workspace_id") not in ws_set and ds_id.lower() not in extra:
                    continue
                for ln in (state.get("dataset_dataflow_links") or {}).get(ds_id, []):
                    if ln.get("dataflow_id"):
                        queue.append((ln.get("workspace_id", ""), ln["dataflow_id"], 1))
                bundle = self.store.read_tmdl_bundle(m_meta.get("name", ""), ds_id)
                if bundle and ("dataflowid" in bundle.lower() or "dataflows" in bundle.lower()):
                    for ws_ref, df_ref in referenced_dataflow_ids([bundle]):
                        queue.append((ws_ref or m_meta.get("workspace_id", ""), df_ref, 1))

        done: set[str] = set()
        fetched = 0
        outside = 0
        missing = 0
        scope_ws = scope_workspace_ids(state)
        last_save = time.monotonic()

        if queue:
            self.log(
                f"Reading Dataflow Gen1/Gen2 definitions ({len(dfs)} in selected workspaces, following upstream chains"
                + (" across workspaces)..." if follow_outside else " within selection)...")
            )
            self._emit(phase="dataflows", done=0, total=max(1, len(dfs)), item="Reading Dataflow definitions...")
        else:
            self._emit(phase="dataflows", done=0, total=0, item="No dataflows in selection")

        while queue:
            ws_id, df_id, depth = queue.pop(0)
            key = (df_id or "").lower()
            if not df_id or key in done:
                continue
            done.add(key)

            meta = state["dataflows"].get(df_id)
            if meta is None:
                exist_id = next((k for k in state["dataflows"] if k.lower() == key), None)
                if exist_id:
                    df_id = exist_id
                    meta = state["dataflows"][df_id]
                else:
                    ws_meta = state["workspaces"].get(ws_id) or {}
                    meta = {
                        "id": df_id,
                        "name": f"Dataflow {df_id[:8]}",
                        "description": "",
                        "workspace_id": ws_id,
                        "workspace": ws_meta.get("name") or (f"Workspace {ws_id[:8]}" if ws_id else "Unknown workspace"),
                        "configured_by": "",
                        "modified_at": "",
                        "generation": "Gen1",
                        "discovered_via": "reference",
                        "upstream": [],
                        "datasources": [],
                        "entities": [],
                        "source_types": [],
                        "definition_status": "pending",
                    }
                    state["dataflows"][df_id] = meta

            ws_id = ws_id or meta.get("workspace_id", "")
            if not ws_id:
                meta["definition_status"] = "error: unknown workspace for referenced dataflow"
                continue

            if ws_set is not None and ws_id not in ws_set:
                if not follow_outside:
                    outside += 1
                    if meta.get("discovered_via") == "reference" and meta.get("definition_status") != "ok":
                        meta["definition_status"] = "outside selected workspaces"
                    continue
                add_scope_extra(state, df_id)

            listed_ws = {wid for wid, w in state.get("workspaces", {}).items() if w.get("dataflows_listed")}
            if meta.get("discovered_via") == "reference" and ws_id in listed_ws:
                users = sorted(
                    state["models"].get(ds, {}).get("name", ds[:8])
                    for ds, links in (state.get("dataset_dataflow_links") or {}).items()
                    if any((ln.get("dataflow_id") or "").lower() == key for ln in links)
                )
                meta["definition_status"] = (
                    f"missing: not in the dataflow list of workspace '{meta.get('workspace', '')}' (deleted or re-created under a new id)"
                    + (f" - referenced by {', '.join(users)}" if users else "")
                )
                missing += 1
                self.log(
                    f"    Dataflow {df_id} referenced by {', '.join(users) or 'upstream chain'} no longer exists in '{meta.get('workspace', '')}' - recorded as broken reference."
                )
                continue

            definition = self.store.read_dataflow_definition(df_id)
            is_gen2 = str(meta.get("generation", "")).upper().endswith("2")
            if refresh or meta.get("definition_status") != "ok" or not definition:
                try:
                    if is_gen2:
                        definition = self.client.get_fabric_dataflow_definition(ws_id, df_id)
                    else:
                        definition = strip_data_locations(self.client.get_dataflow_definition(ws_id, df_id))
                    self.store.write_dataflow_definition(df_id, definition)
                    meta["workspace_id"] = ws_id
                    if definition.get("name") and meta.get("discovered_via") == "reference":
                        meta["name"] = definition["name"]
                    meta["definition_status"] = "ok"
                    meta["definition_read_at"] = utc_now_iso()
                    fetched += 1
                    self.log(f"  Dataflow ({meta.get('generation', 'Gen1')}): {meta.get('workspace', '')} / {meta.get('name', df_id)}")
                except Exception as exc:
                    err_txt = str(exc)
                    if any(tok in err_txt.lower() for tok in ("403", "401", "forbidden", "unauthorized")):
                        err_txt = f"No access to export dataflow (requires Contributor+ or dataflow owner) - {err_txt}"
                    meta["definition_status"] = f"error: {err_txt[:180]}"
                    state["errors"].append(
                        {"step": "dataflowDefinition", "workspace": meta.get("workspace", ""), "dataflow": meta.get("name", df_id), "error": err_txt}
                    )
                    self.log(f"    Skipped dataflow '{meta.get('name', df_id)}': {err_txt[:140]}")
                    definition = {}

                if not is_gen2:
                    for attr, fn in (("upstream", self.client.get_dataflow_upstream), ("datasources", self.client.get_dataflow_datasources)):
                        try:
                            meta[attr] = fn(ws_id, df_id)
                        except Exception:
                            pass

            if definition:
                parsed_df = parse_dataflow_definition(meta, definition)
                meta["entities"] = parsed_df.get("entities", [])
                meta["source_types"] = parsed_df.get("source_types", [])
                if parsed_df.get("description") and not meta.get("description"):
                    meta["description"] = parsed_df["description"]

            if follow_upstream and definition and depth < max_follow_depth:
                for ws_ref, df_ref in definition_dataflow_refs(definition):
                    queue.append((ws_ref, df_ref, depth + 1))
                for up in meta.get("upstream") or []:
                    if not isinstance(up, dict):
                        continue
                    up_id = up.get("targetDataflowId") or up.get("dataflowObjectId") or ""
                    if up_id:
                        queue.append((up.get("groupId") or up.get("workspaceObjectId") or "", up_id, depth + 1))

            if time.monotonic() - last_save > 5:
                self.store.save(state)
                last_save = time.monotonic()
            self._emit(
                phase="dataflows",
                done=len(done),
                total=max(len(done), len(done) + len({(q[1] or '').lower() for q in queue if q[1]} - done)),
                item=meta.get("name", df_id),
            )

        if done:
            self.log(
                f"Dataflow definitions read: {fetched} exported, {len(done) - outside} in lineage scope"
                + (f", {outside} external skipped" if outside else "")
                + (f", {missing} broken reference(s) to deleted dataflows." if missing else ".")
            )
        self.store.save(state)
        return state

    @staticmethod
    def register_local_tmdl(store: CatalogStore, path: str, workspace_name: str = "Local Projects") -> dict:
        """Import a local `.pbip` or `.SemanticModel` directory directly into the catalog store."""
        p = Path(path).resolve()
        model_name, bundle = bundle_from_local_tmdl_dir(p)
        h12 = hashlib.sha1(f"{str(p.parent).lower()}::{model_name.lower()}".encode("utf-8")).hexdigest()[:12]
        ds_id = f"{h12}-local"
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

        # Register matching sibling .Report folder if present so downstream report lineage lights up
        search_root = p.parent if (p.is_file() or p.name.endswith(".SemanticModel")) else p
        exact_rep = search_root / f"{model_name}.Report"
        if exact_rep.is_dir():
            rep_dirs = [exact_rep]
        elif len(list(search_root.glob("*.SemanticModel"))) <= 1:
            rep_dirs = sorted(search_root.glob("*.Report"))
        else:
            rep_dirs = []
        for rdir in rep_dirs:
            rep_name = rdir.name[: -len(".Report")]
            rh12 = hashlib.sha1(str(rdir).lower().encode("utf-8")).hexdigest()[:12]
            rep_id = f"rep-{rh12}"
            layout = parse_pbip_report_dir(rdir)
            if layout.get("pages"):
                store.write_report_layout(rep_id, layout)
            state["reports"][rep_id] = {
                "id": rep_id,
                "name": rep_name,
                "workspace_id": ws_id,
                "workspace": workspace_name,
                "dataset_id": ds_id,
                "report_type": "PowerBIReport (PBIP)",
                "layout_status": "ok" if layout.get("pages") else "unavailable",
                "pages_count": len(layout.get("pages", [])),
                "visuals_count": sum(len(pg.get("visuals", [])) for pg in layout.get("pages", [])),
                "report_measures_count": len(layout.get("report_measures", [])),
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
        mashup_fallback_df = None
        if is_excel:
            import excel_extractor  # type: ignore

            pq_override = excel_extractor.extract_excel_power_query(str(p))
        elif model is not None:
            raw_pq = getattr(model, "power_query", None)
            if raw_pq is None or getattr(raw_pq, "empty", True):
                import excel_extractor  # type: ignore

                mashup_fallback_df = excel_extractor.extract_pbix_datamashup_power_query(str(p))

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
        extra_expressions: list[tuple[str, str]] = []
        if pq_df is not None and not getattr(pq_df, "empty", True) and "TableName" in pq_df.columns:
            for _, row in pq_df.iterrows():
                t = _clean_str(row.get("TableName"))
                expr = _clean_str(row.get("Expression"))
                if t and expr:
                    pq_by_tbl.setdefault(t, []).append(expr)
        elif mashup_fallback_df is not None and not getattr(mashup_fallback_df, "empty", True):
            lower_to_tbl = {t.lower(): t for t in all_tables}
            for _, row in mashup_fallback_df.iterrows():
                qname = _clean_str(row.get("TableName"))
                expr = _clean_str(row.get("Expression"))
                if not qname or not expr:
                    continue
                matched_tbl = lower_to_tbl.get(qname.lower())
                if matched_tbl:
                    pq_by_tbl.setdefault(matched_tbl, []).append(expr)
                else:
                    extra_expressions.append((qname, expr))

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

        expr_lines: list[str] = []
        seen_expr_names: set[str] = set()
        if params_df is not None and not getattr(params_df, "empty", True):
            for _, row in params_df.iterrows():
                pname = _clean_str(row.get("ParameterName", row.get("Name")))
                pexpr = _clean_str(row.get("Expression"))
                pdesc = _clean_str(row.get("Description"))
                if not pname or not pexpr or pname.lower() in seen_expr_names:
                    continue
                seen_expr_names.add(pname.lower())
                if pdesc:
                    for dln in pdesc.splitlines():
                        expr_lines.append(f"/// {dln}")
                expr_lines.append(f"expression {_q(pname)} = {_fenced(pexpr, 2)}")
                expr_lines.append("")
        for qname, qexpr in extra_expressions:
            if qname.lower() in seen_expr_names:
                continue
            seen_expr_names.add(qname.lower())
            expr_lines.append(f"expression {_q(qname)} = {_fenced(qexpr, 2)}")
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
        h12 = hashlib.sha1(str(p).lower().encode("utf-8")).hexdigest()[:12]
        ds_id = f"{h12}-local"
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
            layout = parse_pbix_report(p)
            if layout.get("pages"):
                store.write_report_layout(rep_id, layout)
            state["reports"][rep_id] = {
                "id": rep_id,
                "name": f"{model_name} (Embedded Report)",
                "workspace_id": ws_id,
                "workspace": workspace_name,
                "dataset_id": ds_id,
                "report_type": "PowerBIReport (PBIX)",
                "layout_status": "ok" if layout.get("pages") else "unavailable",
                "pages_count": len(layout.get("pages", [])),
                "visuals_count": sum(len(pg.get("visuals", [])) for pg in layout.get("pages", [])),
                "report_measures_count": len(layout.get("report_measures", [])),
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
