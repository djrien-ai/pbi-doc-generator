"""
Workspace, Semantic Model, Report, Dataflow, and Governance Metadata Scanner.
"""

from __future__ import annotations

import hashlib
import re
import time
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
        self.definition_workers = 4
        self.report_workers = 8
        # Read dataflows / shared models referenced from workspaces outside the selection (off = respect the selection)
        self.follow_outside = False
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

        from .store import set_scan_scope

        set_scan_scope(state, [w["id"] for w in chosen], follow_outside=getattr(self, "follow_outside", False))
        self.log(f"Scanning inventory for {len(chosen)} workspace(s)...")
        for idx, ws in enumerate(chosen, 1):
            ws_id = ws["id"]
            ws_name = ws["name"]
            # Clear stale reports/dataflows for this workspace before refreshing (keep dataflow definition state)
            prev_reports = {rid: r for rid, r in state["reports"].items() if r.get("workspace_id") == ws_id}
            state["reports"] = {rid: r for rid, r in state["reports"].items() if r.get("workspace_id") != ws_id}
            prev_dfs = {did: d for did, d in state["dataflows"].items() if d.get("workspace_id") == ws_id}
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
                    prev_r = prev_reports.get(r["id"]) or {}
                    if prev_r.get("dataset_id") == r.get("datasetId", ""):
                        for k in ("measures_status", "report_measure_count", "definition_format", "layout_version", "page_count", "visual_count"):
                            if k in prev_r:
                                state["reports"][r["id"]][k] = prev_r[k]
            except Exception as exc:
                state["errors"].append({"step": "reports", "workspace": ws_name, "error": str(exc)})

            ws_ds_ids: set[str] = set()
            try:
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
                    prev_df = prev_dfs.get(df_id) or {}
                    modified = df.get("modifiedDateTime", "")
                    state["dataflows"][df_id] = {
                        "id": df_id,
                        "name": df.get("name", ""),
                        "description": df.get("description", ""),
                        "workspace_id": ws_id,
                        "workspace": ws_name,
                        "configured_by": df.get("configuredBy", ""),
                        "modified_at": modified,
                        "generation": "Gen1",
                        "upstream": prev_df.get("upstream", []),
                        "datasources": prev_df.get("datasources", []),
                        # Force a re-export when the dataflow changed since the last definition read
                        "definition_status": prev_df.get("definition_status", "pending")
                        if prev_df.get("modified_at", "") == modified
                        else "pending",
                        "definition_read_at": prev_df.get("definition_read_at", ""),
                    }
            except Exception as exc:
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
                            {"dataflow_id": ln.get("dataflowObjectId", ""), "workspace_id": ln.get("workspaceObjectId", "")}
                        )
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

        # getDefinition is a long-running operation: Power BI answers 202 + Retry-After (about 20 s) even
        # though the export is usually ready in under a second. Run a few in parallel so those waits overlap.
        from concurrent.futures import ThreadPoolExecutor

        pool = ThreadPoolExecutor(max_workers=max(1, self.definition_workers))
        futures = {m["id"]: pool.submit(self.client.get_model_tmdl_files, m["workspace_id"], m["id"]) for m in models}

        for idx, m in enumerate(models, 1):
            ws_id = m["workspace_id"]
            ds_id = m["id"]
            self.log(f"  [{idx}/{len(models)}] {m['workspace']} / {m['name']}")

            try:
                files = futures[ds_id].result()
                self.store.write_tmdl_bundle(m["name"], ds_id, files)
                m["definition_status"] = "ok"
                m["definition_read_at"] = utc_now_iso()
            except Exception as exc:
                err_txt = str(exc)
                low_err = err_txt.lower()
                if any(tok in low_err for tok in ("403", "401", "forbidden", "insufficientprivileges", "unauthorized")):
                    hint = "Requires at least Contributor workspace role (Viewer role cannot extract TMDL definitions)"
                    err_txt = f"{hint} - {err_txt}"
                    self.log(f"    Skipped TMDL for '{m['name']}': {hint}")
                m["definition_status"] = f"error: {err_txt[:180]}"
                state["errors"].append({"step": "getDefinition", "workspace": m["workspace"], "model": m["name"], "error": err_txt})

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

        pool.shutdown(wait=False, cancel_futures=True)
        return state

    def scan_report_definitions(
        self,
        workspace_filter: str = "",
        workspace_ids: list[str] | None = None,
        refresh: bool = False,
        follow_shared_models: bool | None = None,
    ) -> dict:
        """Step 2b: Read report-level measures of (thin) reports.

        Report definitions are read with the Fabric `reports/{id}/getDefinition` metadata call; only the
        report-level measures are kept. Shared models in workspaces outside the selection are only read when
        `follow_shared_models` (default: the scanner's `follow_outside` setting) is on; otherwise the workspace
        selection is respected and those measures show the shared model as "outside the selected workspaces".
        """
        if follow_shared_models is None:
            follow_shared_models = getattr(self, "follow_outside", False)
        from concurrent.futures import ThreadPoolExecutor

        from .reports import LAYOUT_VERSION, parse_report_layout, parse_report_measures

        state = self.store.load()
        reps = [r for r in state.get("reports", {}).values() if r.get("workspace_id") != "local-workspace"]
        reps = [r for r in reps if (r.get("report_type") or "PowerBIReport") == "PowerBIReport"]
        if workspace_ids:
            ws_set = set(workspace_ids)
            reps = [r for r in reps if r.get("workspace_id") in ws_set]
        elif workspace_filter:
            needle = workspace_filter.lower()
            reps = [r for r in reps if needle in (r.get("workspace") or "").lower()]
        # Re-read when not read yet, or read before page / visual layouts were collected
        todo = [r for r in reps if refresh or r.get("measures_status") != "ok" or r.get("layout_version") != LAYOUT_VERSION]

        self.log(f"Reading report definitions for {len(todo)} report(s): report-level measures, pages and visuals...")
        pool = ThreadPoolExecutor(max_workers=max(1, self.report_workers))
        futures = {r["id"]: pool.submit(self.client.get_report_definition_parts, r["workspace_id"], r["id"]) for r in todo}
        found = 0
        last_save = time.monotonic()
        for idx, r in enumerate(todo, 1):
            try:
                parts = futures[r["id"]].result()
                parsed = parse_report_measures(parts)
                layout = parse_report_layout(parts)
                layout["report_id"] = r["id"]
                layout["dataset_id"] = r.get("dataset_id") or parsed.get("dataset_ref", "")
                self.store.write_report_layout(r["id"], layout)
                r["layout_version"] = LAYOUT_VERSION
                r["page_count"] = len(layout["pages"])
                r["visual_count"] = layout["visual_count"]
                parsed["report_id"] = r["id"]
                parsed["dataset_id"] = r.get("dataset_id") or parsed.get("dataset_ref", "")
                self.store.write_report_measures(r["id"], parsed)
                r["measures_status"] = "ok"
                r["report_measure_count"] = len(parsed["measures"])
                r["definition_format"] = parsed.get("format", "")
                if parsed["measures"]:
                    found += len(parsed["measures"])
                    self.log(f"  [{idx}/{len(todo)}] {r.get('workspace')} / {r.get('name')}: {len(parsed['measures'])} report-level measure(s)")
            except Exception as exc:
                err = str(exc)
                if any(t in err.lower() for t in ("403", "401", "forbidden", "unauthorized")):
                    err = f"No access to report definition (requires workspace Contributor or higher) - {err}"
                r["measures_status"] = f"error: {err[:180]}"
                state["errors"].append({"step": "reportDefinition", "workspace": r.get("workspace", ""), "report": r.get("name", ""), "error": err})
            if time.monotonic() - last_save > 5:
                self.store.save(state)
                last_save = time.monotonic()
        pool.shutdown(wait=False, cancel_futures=True)
        self.store.save(state)
        self.log(f"Report definitions read: {found} report-level measure(s), {sum(r.get('page_count', 0) for r in todo)} page(s), "
                 f"{sum(r.get('visual_count', 0) for r in todo)} visual(s).")

        if follow_shared_models:
            self.follow_shared_models(reps)
        return self.store.load()

    def follow_shared_models(self, reports: list[dict]) -> list[str]:
        """Register + read shared models used by reports when they live outside the scanned workspaces."""
        from .store import add_scope_extra, scope_workspace_ids

        state = self.store.load()
        in_scope = scope_workspace_ids(state)
        missing: dict[str, str] = {}
        for r in reports:
            ds = r.get("dataset_id") or ""
            if ds and ds not in state["models"]:
                missing[ds] = r.get("dataset_workspace_id") or r.get("workspace_id") or ""
            elif ds and in_scope and state["models"][ds].get("workspace_id") not in in_scope:
                add_scope_extra(state, ds)  # already in the catalog from an earlier scan: just include it
        for ds in missing:
            add_scope_extra(state, ds)
        added = []
        for ds, ws in missing.items():
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
            self.log(f"  Shared model used by thin report(s): {ws_name} / {state['models'][ds]['name']}")
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
    ) -> dict:
        """Step 3: Export Gen1 dataflow definitions (model.json + M) and follow dataflow -> dataflow references.

        References are followed inside the selected workspaces. Dataflows in other workspaces are only exported
        when `follow_outside` (default: the scanner's `follow_outside` setting) is on; otherwise they are recorded
        as "outside the selected workspaces" so the lineage shows where it leaves the selection.
        """
        from .store import add_scope_extra

        if follow_outside is None:
            follow_outside = getattr(self, "follow_outside", False)
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

        # Seed with dataflows that scanned semantic models load from (M partitions + REST links)
        if follow_upstream:
            from .dataflows import referenced_dataflow_ids

            extra = {x.lower() for x in (state.get("scope") or {}).get("extra_ids") or []}
            for ds_id, m_meta in state.get("models", {}).items():
                if ws_set is not None and m_meta.get("workspace_id") not in ws_set and ds_id.lower() not in extra:
                    continue
                for ln in (state.get("dataset_dataflow_links") or {}).get(ds_id, []):
                    if ln.get("dataflow_id"):
                        queue.append((ln.get("workspace_id", ""), ln["dataflow_id"], 1))
                bundle = self.store.read_tmdl_bundle(m_meta.get("name", ""), ds_id)
                if bundle and "dataflowid" in bundle.lower():
                    for ws_ref, df_ref in referenced_dataflow_ids([bundle]):
                        queue.append((ws_ref or m_meta.get("workspace_id", ""), df_ref, 1))

        done: set[str] = set()
        fetched = 0
        self.log(
            f"Reading Dataflow Gen1 definitions ({len(dfs)} in the selected workspaces, following upstream references"
            + (" into other workspaces)..." if follow_outside else " inside the selection)...")
        )
        outside = 0
        missing = 0
        from .store import scope_workspace_ids

        scope_ws = scope_workspace_ids(state)
        last_save = time.monotonic()
        while queue:
            ws_id, df_id, depth = queue.pop(0)
            key = df_id.lower()
            if not df_id or key in done:
                continue
            done.add(key)
            meta = state["dataflows"].get(df_id)
            if meta is None:
                # Referenced dataflow outside the scanned workspaces: register a stub and try to read it
                ws_meta = state["workspaces"].get(ws_id) or {}
                meta = {
                    "id": df_id,
                    "name": f"Dataflow {df_id[:8]}",
                    "workspace_id": ws_id,
                    "workspace": ws_meta.get("name") or (f"Workspace {ws_id[:8]}" if ws_id else "Unknown workspace"),
                    "configured_by": "",
                    "modified_at": "",
                    "generation": "Gen1",
                    "discovered_via": "reference",
                    "upstream": [],
                    "datasources": [],
                    "definition_status": "pending",
                }
                state["dataflows"][df_id] = meta
            ws_id = ws_id or meta.get("workspace_id", "")
            if not ws_id:
                meta["definition_status"] = "error: unknown workspace for referenced dataflow"
                continue
            if ws_set is not None and ws_id not in ws_set:
                if not follow_outside:
                    # Respect the workspace selection: record where the lineage leaves it, do not export
                    outside += 1
                    if meta.get("discovered_via") == "reference" and meta.get("definition_status") != "ok":
                        meta["definition_status"] = "outside selected workspaces"
                    continue
                add_scope_extra(state, df_id)
            listed_ws = ws_set if ws_set is not None else scope_ws
            if meta.get("discovered_via") == "reference" and listed_ws and ws_id in listed_ws:
                # The workspace's dataflow list was just read and does not contain this id: it was deleted or
                # re-created under a new id. Exporting it only returns HTTP 400 "Unexpected dataflow error".
                users = sorted(
                    state["models"].get(ds, {}).get("name", ds[:8])
                    for ds, links in (state.get("dataset_dataflow_links") or {}).items()
                    if any((ln.get("dataflow_id") or "").lower() == key for ln in links)
                )
                meta["definition_status"] = (
                    f"missing: not in the dataflow list of workspace '{meta.get('workspace', '')}' (deleted or re-created under a new id?)"
                    + (f" - still referenced by {', '.join(users)}" if users else "")
                )
                missing += 1
                self.log(f"    Dataflow {df_id} referenced by {', '.join(users) or 'another dataflow'} no longer exists in '{meta.get('workspace', '')}' - broken reference, skipped.")
                continue

            definition = self.store.read_dataflow_definition(df_id)
            if refresh or meta.get("definition_status") != "ok" or not definition:
                try:
                    from .dataflows import strip_data_locations

                    definition = strip_data_locations(self.client.get_dataflow_definition(ws_id, df_id))
                    self.store.write_dataflow_definition(df_id, definition)
                    meta["workspace_id"] = ws_id
                    if definition.get("name") and meta.get("discovered_via") == "reference":
                        meta["name"] = definition["name"]
                    meta["definition_status"] = "ok"
                    meta["definition_read_at"] = utc_now_iso()
                    fetched += 1
                    self.log(f"  Dataflow: {meta.get('workspace', '')} / {meta.get('name', df_id)}")
                except Exception as exc:
                    err_txt = str(exc)
                    if any(tok in err_txt.lower() for tok in ("403", "401", "forbidden", "unauthorized")):
                        err_txt = f"No access to export dataflow (requires workspace Contributor+ or dataflow owner) - {err_txt}"
                    meta["definition_status"] = f"error: {err_txt[:180]}"
                    state["errors"].append({"step": "dataflowDefinition", "workspace": meta.get("workspace", ""), "dataflow": meta.get("name", df_id), "error": err_txt})
                    self.log(f"    Skipped dataflow '{meta.get('name', df_id)}': {err_txt[:140]}")
                    definition = {}
                for attr, fn in (("upstream", self.client.get_dataflow_upstream), ("datasources", self.client.get_dataflow_datasources)):
                    try:
                        meta[attr] = fn(ws_id, df_id)
                    except Exception:
                        pass

            if follow_upstream and definition and depth < max_follow_depth:
                from .dataflows import definition_dataflow_refs

                for ws_ref, df_ref in definition_dataflow_refs(definition):
                    queue.append((ws_ref, df_ref, depth + 1))
                for up in meta.get("upstream") or []:
                    up_id = up.get("targetDataflowId") or ""
                    if up_id:
                        queue.append((up.get("groupId") or "", up_id, depth + 1))
            # Checkpoint every few seconds (resumable) instead of after every dataflow
            if time.monotonic() - last_save > 5:
                self.store.save(state)
                last_save = time.monotonic()

        self.log(
            f"Dataflow definitions read: {fetched} exported, {len(done) - outside} dataflow(s) in lineage scope"
            + (f", {outside} referenced dataflow(s) in unselected workspaces skipped" if outside else "")
            + (f", {missing} broken reference(s) to deleted dataflows (see Governance & Health)." if missing else ".")
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
