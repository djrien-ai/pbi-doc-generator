"""Entry point for both source execution and packaged Windows Portable builds."""

from __future__ import annotations

import sys
from pathlib import Path

root_dir = str(Path(__file__).resolve().parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from pbi_catalog.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
