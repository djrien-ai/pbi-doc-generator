"""
Incremental, resumable local catalog state store (`pbi_catalog_data/`).

Keeps clean JSON metadata + raw `.tmdl` files on local disk so interrupted scans resume
automatically and re-scanning a single workspace or model replaces only its own state.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .security import safe_filename


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def save(self, state: dict) -> None:
        self.ensure_dirs()
        state["updated_at"] = utc_now_iso()
        tmp = self.state_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_file)

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
