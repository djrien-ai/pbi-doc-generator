"""
Incremental, resumable, thread-safe local catalog state store (`pbi_catalog_data/`).

Keeps clean JSON metadata + raw `.tmdl`, report layout, and dataflow definitions on local disk so
interrupted scans resume automatically, Windows file locks (`WinError 5`) retry safely, and workspace
selections scope portal views without discarding previously scanned workspaces.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .security import safe_filename

_STATE_LOCK = threading.RLock()
LOCAL_WORKSPACE_IDS = {"", "local-workspace"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def set_scan_scope(state: dict, workspace_ids: list[str], follow_outside: bool = False) -> None:
    """Remember which workspaces the user selected; the portal and lineage explorer scope to those."""
    state["scope"] = {
        "workspace_ids": sorted(set(workspace_ids)),
        "follow_outside": bool(follow_outside),
        "extra_ids": [],
        "set_at": utc_now_iso(),
    }


def add_scope_extra(state: dict, object_id: str) -> None:
    scope = state.get("scope")
    if scope is not None and object_id:
        existing = {x.lower() for x in scope.setdefault("extra_ids", [])}
        if object_id.lower() not in existing:
            scope["extra_ids"].append(object_id)


def scope_workspace_ids(state: dict) -> set[str] | None:
    ids = (state.get("scope") or {}).get("workspace_ids") or []
    return set(ids) if ids else None


def scoped_state(state: dict) -> dict:
    """Return a view of the catalog restricted to the selected workspaces (+ explicitly followed objects)."""
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
    out["fabric_items"] = {k: v for k, v in (state.get("fabric_items") or {}).items() if keep(k, v, False)}
    out["out_of_scope_models"] = {k: v for k, v in (state.get("models") or {}).items() if k not in out["models"]}
    out["out_of_scope_dataflows"] = {k: v for k, v in (state.get("dataflows") or {}).items() if k not in out["dataflows"]}
    used_ws = ws | {
        v.get("workspace_id", "")
        for part in ("models", "reports", "dataflows", "fabric_items")
        for v in out[part].values()
    }
    out["workspaces"] = {k: v for k, v in (state.get("workspaces") or {}).items() if k in used_ws}
    out["dataset_dataflow_links"] = {
        k: v for k, v in (state.get("dataset_dataflow_links") or {}).items() if k in out["models"]
    }
    return out


class CatalogStore:
    """Manages local catalog JSON state, TMDL bundles, report layouts, and dataflow definitions."""

    def __init__(self, root_dir: str | Path = "./pbi_catalog_data"):
        self.root = Path(root_dir).resolve()
        self.defs_dir = self.root / "definitions"
        self.portal_dir = self.root / "portal"
        self.state_file = self.root / "catalog_state.json"

    @property
    def dataflows_dir(self) -> Path:
        return self.root / "dataflows"

    def ensure_dirs(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.defs_dir.mkdir(parents=True, exist_ok=True)
        self.portal_dir.mkdir(parents=True, exist_ok=True)

    def clear(self) -> None:
        """Completely wipe cached models, report layouts, dataflows, and generated HTML pages for a fresh start."""
        with _STATE_LOCK:
            for sub in ("definitions", "dataflows", "portal", "report_layouts", "report_measures", "_exports", "_staged_imports"):
                shutil.rmtree(self.root / sub, ignore_errors=True)
            for f in (self.state_file, self.state_file.with_suffix(".json.tmp")):
                try:
                    f.unlink(missing_ok=True)
                except OSError:
                    pass
            self.ensure_dirs()

    def _default_state(self) -> dict:
        return {
            "schema_version": "1.1",
            "updated_at": "",
            "workspaces": {},
            "reports": {},
            "models": {},
            "dataflows": {},
            "fabric_items": {},
            "dataset_dataflow_links": {},
            "errors": [],
        }

    def load(self) -> dict:
        if not self.state_file.exists():
            return self._default_state()
        last_perm_exc: PermissionError | None = None
        for attempt in range(8):
            try:
                with _STATE_LOCK:
                    raw_txt = self.state_file.read_text(encoding="utf-8-sig")
                    data = json.loads(raw_txt) if raw_txt.strip() else {}
                if not isinstance(data, dict):
                    raise ValueError("Catalog state root must be a JSON object")
                for k, default in self._default_state().items():
                    if k not in data or not isinstance(data[k], type(default)):
                        data[k] = default
                return data
            except PermissionError as exc:
                last_perm_exc = exc
                time.sleep(0.08 * (attempt + 1))
            except (OSError, ValueError):
                if attempt < 3:
                    time.sleep(0.06 * (attempt + 1))
                    continue
                # Recover gracefully from a truncated/corrupted state file instead of crashing Studio
                with _STATE_LOCK:
                    try:
                        backup = self.state_file.with_suffix(".corrupt.json")
                        shutil.copy2(self.state_file, backup)
                    except OSError:
                        pass
                recovered = self._default_state()
                recovered["errors"] = ["Recovered from a corrupted local catalog_state.json (backed up to catalog_state.corrupt.json)."]
                return recovered
        if last_perm_exc is not None:
            return self._default_state()
        return self._default_state()

    def load_scoped(self) -> dict:
        """Catalog limited to the workspaces selected for the last scan."""
        return scoped_state(self.load())

    def save(self, state: dict) -> None:
        self.ensure_dirs()
        state["updated_at"] = utc_now_iso()
        payload = json.dumps(state, indent=2, ensure_ascii=False)
        tmp = self.state_file.with_suffix(".json.tmp")
        with _STATE_LOCK:
            tmp.write_text(payload, encoding="utf-8")
            for attempt in range(12):
                try:
                    tmp.replace(self.state_file)
                    return
                except PermissionError:
                    if attempt == 11:
                        raise
                    time.sleep(0.05 * (attempt + 1))

    # ----- Semantic model TMDL bundles -----
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

    def read_tmdl_bundle(self, model_name: str, dataset_id: str) -> str:
        p = self.tmdl_path(model_name, dataset_id)
        if p.exists():
            return p.read_text(encoding="utf-8-sig")
        matches = list(self.defs_dir.glob(f"*__{(dataset_id or '')[:8]}.tmdl"))
        return matches[0].read_text(encoding="utf-8-sig") if matches else ""

    # ----- Report layouts (includes report-level DAX measures, pages, visuals, filters) -----
    def report_layout_path(self, report_id: str) -> Path:
        self.ensure_dirs()
        clean_id = safe_filename(report_id or "report")
        return self.defs_dir / f"report__{clean_id}.json"

    def write_report_layout(self, report_id: str, layout: dict) -> Path:
        out_path = self.report_layout_path(report_id)
        out_path.write_text(json.dumps(layout, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return out_path

    def read_report_layout(self, report_id: str) -> dict | None:
        for cand in (
            self.report_layout_path(report_id),
            self.root / "report_layouts" / f"{safe_filename(report_id or 'report')}.json",
        ):
            if cand.is_file():
                try:
                    return json.loads(cand.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError):
                    continue
        return None

    def read_report_measures(self, report_id: str) -> dict:
        """Return `{measures, dataset_id, format}` from the stored report layout (or legacy report_measures file)."""
        lay = self.read_report_layout(report_id)
        if isinstance(lay, dict) and "report_measures" in lay:
            return {
                "measures": lay.get("report_measures") or [],
                "dataset_id": lay.get("dataset_id") or lay.get("dataset_ref") or "",
                "format": lay.get("format") or "",
            }
        legacy_p = self.root / "report_measures" / f"{safe_filename(report_id or 'report')}.json"
        if legacy_p.is_file():
            try:
                return json.loads(legacy_p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                pass
        return {}

    def write_report_measures(self, report_id: str, data: dict) -> Path:
        """Compatibility helper when writing standalone report-level measures."""
        lay = self.read_report_layout(report_id) or {"pages": [], "report_filters": []}
        lay["report_measures"] = data.get("measures") or []
        if data.get("dataset_id") or data.get("dataset_ref"):
            lay["dataset_id"] = data.get("dataset_id") or data.get("dataset_ref")
        if data.get("format"):
            lay["format"] = data["format"]
        return self.write_report_layout(report_id, lay)

    # ----- Dataflow Gen1 & Gen2 definitions -----
    def dataflow_path(self, dataflow_id: str) -> Path:
        return self.dataflows_dir / f"{safe_filename(dataflow_id)}.json"

    def write_dataflow_definition(self, dataflow_id: str, definition: dict) -> Path:
        self.dataflows_dir.mkdir(parents=True, exist_ok=True)
        out = self.dataflow_path(dataflow_id)
        out.write_text(json.dumps(definition, indent=2, ensure_ascii=False), encoding="utf-8")
        return out

    def read_dataflow_definition(self, dataflow_id: str) -> dict:
        p = self.dataflow_path(dataflow_id)
        if not p.is_file():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return {}
