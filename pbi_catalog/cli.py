"""
Unified Command-Line Interface for PBI Doc Generator v1.0.

Commands:
  pbi-doc-generator                  Launch the Localhost Web Studio (default)
  pbi-doc-generator studio           Launch the Localhost Web Studio
  pbi-doc-generator scan             Scan Power BI Service workspaces + TMDL definitions
  pbi-doc-generator portal           Generate offline HTML Documentation & Lineage Portal
  pbi-doc-generator import-local     Import a local .pbip / .SemanticModel directory into the catalog
  pbi-doc-generator file <path>      Generate standalone HTML for a single .pbix, .pbip, or .xlsx
  pbi-doc-generator mcp              Start the Model Context Protocol (MCP) server over stdio
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from .api import PowerBiReadOnlyClient
from .auth import TokenProvider
from .mcp_server import run_mcp_stdio
from .portal import generate_portal
from .scanner import WorkspaceScanner
from .store import CatalogStore
from .web_ui import run_web_studio


def _default_catalog_dir() -> Path:
    env_dir = os.environ.get("PBI_CATALOG_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return (Path.home() / ".pbi-doc-generator" / "catalog").resolve()


def main(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)

    # Backwards compatibility: if first arg is an existing .pbix / .pbip / .xlsx file, run single-file doc
    if args_list and args_list[0] not in ("studio", "ui", "scan", "portal", "import-local", "file", "mcp", "-h", "--help", "--version"):
        candidate = Path(args_list[0])
        if candidate.exists():
            args_list = ["file", *args_list]

    parser = argparse.ArgumentParser(
        prog="pbi-doc-generator",
        description="Power BI Workspace Catalog, Semantic Model Documentation, Live Lineage & MCP Server (v1.0.0)",
    )
    parser.add_argument("--version", action="version", version="pbi-doc-generator 1.0.0")
    sub = parser.add_subparsers(dest="command")

    # studio / ui
    p_ui = sub.add_parser("studio", aliases=["ui"], help="Launch the Localhost Web Studio in your browser")
    p_ui.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_ui.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_ui.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    p_ui.add_argument("--no-browser", action="store_true", help="Do not auto-open browser tab")

    # scan
    p_scan = sub.add_parser("scan", help="Scan Power BI workspaces, semantic models, and TMDL definitions")
    p_scan.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_scan.add_argument("--auth", default="oauth", choices=["oauth", "browser", "az", "spn", "token", "clipboard", "auto"], help="Authentication mode")
    p_scan.add_argument("--workspace", default="", help="Optional case-insensitive workspace name filter")
    p_scan.add_argument("--refresh", action="store_true", help="Re-fetch TMDL even for already scanned models")
    p_scan.add_argument("--include-access", action="store_true", help="Fetch workspace and dataset user permissions")
    p_scan.add_argument("--anonymous", action="store_true", help="Redact owner and user names in generated portal")
    p_scan.add_argument("--limit", type=int, default=0, help="Optional max models to scan")

    # portal
    p_portal = sub.add_parser("portal", help="Build offline HTML Documentation & Live Lineage Portal from catalog")
    p_portal.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_portal.add_argument("--output", default="", help="Optional custom output folder")
    p_portal.add_argument("--anonymous", action="store_true", help="Redact owner and user names")

    # import-local
    p_imp = sub.add_parser("import-local", help="Import a local .pbix, .pbip, .xlsx, or .SemanticModel into the v1.0 catalog")
    p_imp.add_argument("path", help="Path to local .pbix, .pbip, .xlsx, or .SemanticModel directory")
    p_imp.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_imp.add_argument("--workspace-name", default="Local Projects", help="Workspace label in catalog")

    # file (single-file legacy compatibility)
    p_file = sub.add_parser("file", help="Generate standalone HTML documentation for a single .pbix, .pbip, or .xlsx file")
    p_file.add_argument("path", help="Path to .pbix, .pbip, or .xlsx file")
    p_file.add_argument("-o", "--output", default=None, help="Output HTML path")

    # mcp
    p_mcp = sub.add_parser("mcp", help="Run the Model Context Protocol (MCP) server over stdio")
    p_mcp.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")

    ns = parser.parse_args(args_list)
    cmd = ns.command or "studio"

    if cmd in ("studio", "ui") or ns.command is None:
        cat = getattr(ns, "catalog", str(_default_catalog_dir()))
        port = getattr(ns, "port", 8765)
        host = getattr(ns, "host", "127.0.0.1")
        no_br = getattr(ns, "no_browser", False)
        run_web_studio(cat, host=host, port=port, open_browser=not no_br)
        return 0

    if cmd == "scan":
        store = CatalogStore(ns.catalog)
        auth = TokenProvider(mode=ns.auth)
        client = PowerBiReadOnlyClient(auth)
        scanner = WorkspaceScanner(client, store)
        scanner.scan_inventory(workspace_filter=ns.workspace)
        scanner.scan_model_definitions(
            workspace_filter=ns.workspace,
            refresh=ns.refresh,
            include_access=ns.include_access,
            limit=ns.limit,
        )
        idx = generate_portal(store, anonymous=ns.anonymous)
        print(f"Portal generated: {idx}")
        return 0

    if cmd == "portal":
        store = CatalogStore(ns.catalog)
        out = ns.output or None
        idx = generate_portal(store, output_dir=out, anonymous=ns.anonymous)
        print(f"Portal generated: {idx}")
        return 0

    if cmd == "import-local":
        store = CatalogStore(ns.catalog)
        WorkspaceScanner.register_local_any(store, ns.path, workspace_name=ns.workspace_name)
        idx = generate_portal(store)
        print(f"Imported local project and updated portal: {idx}")
        return 0

    if cmd == "file":
        root_dir = str(Path(__file__).resolve().parent.parent)
        if root_dir not in sys.path:
            sys.path.insert(0, root_dir)
        from extract import ExtractionError, extract_documentation  # type: ignore

        res = extract_documentation(ns.path, ns.output)
        if isinstance(res, ExtractionError):
            print(f"Extraction error ({res.code}):\n{res.report}", file=sys.stderr)
            return 1
        out_path = res[0] if isinstance(res, tuple) else res
        print(f"Generated standalone documentation: {out_path}")
        return 0

    if cmd == "mcp":
        run_mcp_stdio(ns.catalog)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
