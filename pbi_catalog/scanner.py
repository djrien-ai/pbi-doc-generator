"""
Workspace, Semantic Model, Report, Dataflow, and Governance Metadata Scanner.
"""

from __future__ import annotations

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
        model_name, bundle = bundle_from_local_tmdl_dir(path)
        ds_id = f"local-{ abs(hash(str(path))) % 10**10:010d}"
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
            "target_storage_mode": "TMDL",
            "is_refreshable": False,
            "datasources": [],
            "last_refresh": {"status": "Local", "end_time": utc_now_iso(), "refresh_type": "File"},
            "permissions": [],
            "workspace_users": [],
            "definition_status": "ok",
            "definition_read_at": utc_now_iso(),
        }
        store.save(state)
        return state["models"][ds_id]
