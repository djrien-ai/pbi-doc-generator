"""
Incremental, resumable local catalog state store (`pbi_catalog_data/`).

Keeps clean JSON metadata + raw `.tmdl` files on local disk so interrupted scans resume
automatically and re-scanning a single workspace or model replaces only its own state.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .security import safe_filename

# Serialises catalog_state.json reads/writes across Studio threads (scan worker vs. status polling)
_STATE_LOCK = threading.RLock()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


LOCAL_WORKSPACE_IDS = {"", "local-workspace"}


def set_scan_scope(state: dict, workspace_ids: list[str], follow_outside: bool = False) -> None:
    """Remember which workspaces the user selected; the portal and explorer only show those."""
    state["scope"] = {
        "workspace_ids": sorted(set(workspace_ids)),
        "follow_outside": bool(follow_outside),
        "extra_ids": [],  # objects outside the selection pulled in on purpose (follow_outside)
        "set_at": utc_now_iso(),
    }


def add_scope_extra(state: dict, object_id: str) -> None:
    scope = state.get("scope")
    if scope is not None and object_id and object_id.lower() not in {x.lower() for x in scope.setdefault("extra_ids", [])}:
        scope["extra_ids"].append(object_id)


def scope_workspace_ids(state: dict) -> set[str] | None:
    ids = (state.get("scope") or {}).get("workspace_ids") or []
    return set(ids) if ids else None


def scoped_state(state: dict) -> dict:
    """View of the catalog restricted to the selected workspaces (+ objects explicitly followed outside them).

    Objects from earlier scans of other workspaces stay on disk (so re-selecting them is incremental) but are
    moved to `out_of_scope_*` so lineage can name them as "outside the selected workspaces" placeholders.
    """
    ws = scope_workspace_ids(state)
    if not ws:
        return state
    extra = {x.lower() for x in (state.get("scope") or {}).get("extra_ids") or []}

    def keep(obj_id: str, meta: dict, allow_local: bool) -> bool:
        wid = meta.get("workspace_id") or ""
        return wid in ws or obj_id.lower() in extra or (allow_local and wid in LOCAL_WORKSPACE_IDS)

    out = dict(state)
    out["models"] = {k: v for k, v in (state.get("models") or {}).items() if keep(k, v, True)}
    out["reports"] = {k: v for k, v in (state.get("reports") or {}).items() if keep(k, v, True)}
    out["dataflows"] = {k: v for k, v in (state.get("dataflows") or {}).items() if keep(k, v, False)}
    out["out_of_scope_models"] = {k: v for k, v in (state.get("models") or {}).items() if k not in out["models"]}
    out["out_of_scope_dataflows"] = {k: v for k, v in (state.get("dataflows") or {}).items() if k not in out["dataflows"]}
    used_ws = ws | {v.get("workspace_id", "") for part in ("models", "reports", "dataflows") for v in out[part].values()}
    out["workspaces"] = {k: v for k, v in (state.get("workspaces") or {}).items() if k in used_ws}
    out["dataset_dataflow_links"] = {k: v for k, v in (state.get("dataset_dataflow_links") or {}).items() if k in out["models"]}
    return out


class CatalogStore:
    """Manages local catalog JSON state and raw TMDL definition files."""

    def __init__(self, root_dir: str | Path = "./pbi_catalog_data"):
        self.root = Path(root_dir).resolve()
        self.defs_dir = self.root / "definitions"
        self.portal_dir = self.root / "portal"
        self.state_file = self.root / "catalog_state.json"

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.defs_dir.mkdir(parents=True, exist_ok=True)
        self.portal_dir.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict:
        if not self.state_file.exists():
            return {
                "schema_version": "1.0",
                "updated_at": "",
                "workspaces": {},
                "reports": {},
                "models": {},
                "dataflows": {},
                "errors": [],
            }
        last_exc: Exception | None = None
        for attempt in range(8):
            try:
                with _STATE_LOCK:
                    return json.loads(self.state_file.read_text(encoding="utf-8"))
            except (PermissionError, ValueError) as exc:
                # Windows: file briefly locked by antivirus / indexer, or caught mid-replace
                last_exc = exc
                time.sleep(0.1 * (attempt + 1))
        raise last_exc  # type: ignore[misc]

    def load_scoped(self) -> dict:
        """Catalog limited to the workspaces selected for the last scan (see `scoped_state`)."""
        return scoped_state(self.load())

    def save(self, state: dict) -> None:
        self.ensure_dirs()
        state["updated_at"] = utc_now_iso()
        payload = json.dumps(state, indent=2, ensure_ascii=False)
        tmp = self.state_file.with_suffix(".json.tmp")
        with _STATE_LOCK:
            tmp.write_text(payload, encoding="utf-8")
            # On Windows, replace() fails with WinError 5 while another handle (status poll in another
            # thread, Defender, Search indexer, OneDrive) has the target open. Retry with back-off.
            for attempt in range(12):
                try:
                    tmp.replace(self.state_file)
                    return
                except PermissionError:
                    if attempt == 11:
                        raise
                    time.sleep(0.05 * (attempt + 1))

    def tmdl_path(self, model_name: str, dataset_id: str) -> Path:
        self.ensure_dirs()
        short_id = (dataset_id or "local")[:8]
        return self.defs_dir / f"{safe_filename(model_name)}__{short_id}.tmdl"

    def write_tmdl_bundle(self, model_name: str, dataset_id: str, files: dict[str, str]) -> Path:
        """Persist multi-file TMDL parts into a single lossless `.tmdl` bundle."""
        blocks = []
        for path, content in sorted(files.items()):
            if path.endswith(".tmdl"):
                blocks.append(f"// ===== {path}\n{content}")
        out_path = self.tmdl_path(model_name, dataset_id)
        out_path.write_text("\n\n".join(blocks), encoding="utf-8")
        return out_path

    # ----- Report-level measures of thin reports (only measures are stored, never visuals) -----
    def report_measures_path(self, report_id: str) -> Path:
        return self.root / "report_measures" / f"{safe_filename(report_id)}.json"

    def write_report_measures(self, report_id: str, data: dict) -> Path:
        p = self.report_measures_path(report_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return p

    def read_report_measures(self, report_id: str) -> dict:
        p = self.report_measures_path(report_id)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}

    # ----- Report layouts: pages, visuals, bound fields, filters (definition metadata, no data) -----
    def report_layout_path(self, report_id: str) -> Path:
        return self.root / "report_layouts" / f"{safe_filename(report_id)}.json"

    def write_report_layout(self, report_id: str, data: dict) -> Path:
        p = self.report_layout_path(report_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return p

    def read_report_layout(self, report_id: str) -> dict:
        p = self.report_layout_path(report_id)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}

    # ----- Dataflow Gen1 definitions (model.json exports) -----
    @property
    def dataflows_dir(self) -> Path:
        return self.root / "dataflows"

    def dataflow_path(self, dataflow_id: str) -> Path:
        return self.dataflows_dir / f"{safe_filename(dataflow_id)}.json"

    def write_dataflow_definition(self, dataflow_id: str, definition: dict) -> Path:
        self.dataflows_dir.mkdir(parents=True, exist_ok=True)
        out = self.dataflow_path(dataflow_id)
        out.write_text(json.dumps(definition, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    def read_dataflow_definition(self, dataflow_id: str) -> dict:
        p = self.dataflow_path(dataflow_id)
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}

    def read_tmdl_bundle(self, model_name: str, dataset_id: str) -> str:
        p = self.tmdl_path(model_name, dataset_id)
        if p.exists():
            return p.read_text(encoding="utf-8-sig")
        matches = list(self.defs_dir.glob(f"*__{(dataset_id or '')[:8]}.tmdl"))
        return matches[0].read_text(encoding="utf-8-sig") if matches else ""
