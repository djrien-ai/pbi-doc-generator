"""Allow launching via `python -m pbi_catalog` or `py -m pbi_catalog` when Scripts is not on PATH."""

from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
