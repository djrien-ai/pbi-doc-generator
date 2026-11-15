"""
Unified Command-Line Interface for PBI Doc Generator v1.1.

Commands:
  pbi-doc-generator                  Launch the Localhost Web Studio (default)
  pbi-doc-generator studio           Launch the Localhost Web Studio
  pbi-doc-generator scan             Scan Power BI Service workspaces, TMDL, Reports & Dataflows
  pbi-doc-generator portal           Generate offline HTML Documentation & Lineage Portal
  pbi-doc-generator export-site      Export SharePoint Single-File (.html) or Offline Bundle (.zip)
  pbi-doc-generator measure-doc      Export audit-ready End-to-End Measure Specification (.md)
  pbi-doc-generator import-local     Import a local .pbix, .pbip, .xlsx, or .SemanticModel into catalog
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
from .e2e_lineage import build_e2e_graph, find_nodes, render_measure_doc_markdown
from .export_bundle import build_site_export
from .mcp_server import CatalogMcpEngine, run_mcp_stdio
from .portal import generate_portal
from .scanner import WorkspaceScanner
from .security import mask_secrets
from .store import CatalogStore
from .web_ui import run_web_studio

KNOWN_SUBCOMMANDS = (
    "studio",
    "ui",
    "scan",
    "portal",
    "export-site",
    "measure-doc",
    "import-local",
    "file",
    "mcp",
    "-h",
    "--help",
    "--version",
)


def _default_catalog_dir() -> Path:
    env_dir = os.environ.get("PBI_CATALOG_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return (Path.home() / ".pbi-doc-generator" / "catalog").resolve()


def main(argv: list[str] | None = None) -> int:
    try:
        return _run_cli(argv)
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        err_code = type(exc).__name__.upper()
        safe_msg = mask_secrets(str(exc) or err_code)
        print(f"Error [{err_code}]: {safe_msg}", file=sys.stderr)
        return 1


def _run_cli(argv: list[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)

    # Backwards compatibility: if first arg is an existing .pbix / .pbip / .xlsx file, run single-file doc
    if args_list and args_list[0] not in KNOWN_SUBCOMMANDS:
        candidate = Path(args_list[0])
        if candidate.exists():
            args_list = ["file", *args_list]

    parser = argparse.ArgumentParser(
        prog="pbi-doc-generator",
        description="Power BI Workspace Catalog, Semantic Model Documentation, Dataflows, Report X-Ray, Live Lineage & MCP Server (v1.1.0)",
    )
    parser.add_argument("--version", action="version", version="pbi-doc-generator 1.1.0")
    sub = parser.add_subparsers(dest="command")

    # studio / ui
    p_ui = sub.add_parser("studio", aliases=["ui"], help="Launch the Localhost Web Studio in your browser")
    p_ui.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_ui.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    p_ui.add_argument("--port", type=int, default=8765, help="Bind port (default: 8765)")
    p_ui.add_argument("--no-browser", action="store_true", help="Do not auto-open browser tab")

    # scan
    p_scan = sub.add_parser("scan", help="Scan Power BI workspaces, semantic models, TMDL, reports, and dataflows")
    p_scan.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_scan.add_argument("--auth", default="oauth", choices=["oauth", "browser", "az", "spn", "token", "clipboard", "auto"], help="Authentication mode")
    p_scan.add_argument("--workspace", default="", help="Optional case-insensitive workspace name filter")
    p_scan.add_argument("--refresh", action="store_true", help="Re-fetch definitions even for already scanned items")
    p_scan.add_argument("--no-reports", action="store_true", help="Skip report visual layout scanning")
    p_scan.add_argument("--no-dataflows", action="store_true", help="Skip Dataflow Gen1/Gen2 definition scanning")
    p_scan.add_argument("--follow-outside", action="store_true", help="Follow shared models and upstream dataflows outside filtered workspaces")
    p_scan.add_argument("--include-access", action="store_true", help="Fetch workspace and dataset user permissions")
    p_scan.add_argument("--anonymous", action="store_true", help="Redact owner, user names, and filter literals in generated portal")
    p_scan.add_argument("--limit", type=int, default=0, help="Optional max items to scan per step")

    # portal
    p_portal = sub.add_parser("portal", help="Build offline HTML Documentation & Live Lineage Portal from catalog")
    p_portal.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_portal.add_argument("--output", default="", help="Optional custom output folder")
    p_portal.add_argument("--anonymous", action="store_true", help="Redact owner, user names, and report filter literals")

    # export-site
    p_exp = sub.add_parser("export-site", help="Export SharePoint Single-File (.html) or Offline Portal Bundle (.zip)")
    p_exp.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_exp.add_argument("--format", default="single", choices=["single", "zip"], help="Export format: 'single' (.html for SharePoint) or 'zip'")
    p_exp.add_argument("-o", "--output", default="", help="Output file path")
    p_exp.add_argument("--anonymous", action="store_true", help="Redact personal names and report filter literals")
    p_exp.add_argument("--aspx", action="store_true", help="Include .aspx page copies inside zip bundle")

    # measure-doc
    p_mdoc = sub.add_parser("measure-doc", help="Generate End-to-End DAX-to-SQL Measure Specification in Markdown")
    p_mdoc.add_argument("measure", help="DAX measure name or Table[Measure] reference")
    p_mdoc.add_argument("--catalog", default=str(_default_catalog_dir()), help="Local catalog directory")
    p_mdoc.add_argument("--model", default="", help="Optional semantic model name filter")
    p_mdoc.add_argument("-o", "--output", default="", help="Optional Markdown file path (prints to stdout if omitted)")

    # import-local
    p_imp = sub.add_parser("import-local", help="Import a local .pbix, .pbip, .xlsx, or .SemanticModel into the catalog")
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
        if not ns.no_reports:
            scanner.scan_report_definitions(
                workspace_filter=ns.workspace,
                refresh=ns.refresh,
                limit=ns.limit,
                follow_shared_models=ns.follow_outside,
            )
        if not ns.no_dataflows:
            scanner.scan_dataflow_definitions(
                workspace_filter=ns.workspace,
                refresh=ns.refresh,
                limit=ns.limit,
                follow_outside=ns.follow_outside,
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

    if cmd == "export-site":
        store = CatalogStore(ns.catalog)
        is_single = ns.format == "single"
        default_name = "PBI_Documentation_Portal_SharePoint.html" if is_single else "PBI_Documentation_Portal_Bundle.zip"
        out_path = Path(ns.output) if ns.output else (Path.cwd() / default_name)
        built = build_site_export(
            store,
            out_path,
            anonymous=ns.anonymous,
            include_aspx=ns.aspx,
            single_file_only=is_single,
        )
        print(f"Exported portal package: {built}")
        return 0

    if cmd == "measure-doc":
        store = CatalogStore(ns.catalog)
        engine = CatalogMcpEngine(store)
        analyses = engine._load_analyses()
        if ns.model:
            mdl_low = ns.model.strip().lower()
            analyses = [a for a in analyses if mdl_low in a["name"].lower() or mdl_low == a["dataset_id"].lower()]
        graph = build_e2e_graph(store, analyses)
        matches = find_nodes(graph, ns.measure, kinds=["measure"])
        if not matches:
            print(f"Measure matching '{ns.measure}' not found in catalog.", file=sys.stderr)
            return 1
        md_text = mask_secrets(render_measure_doc_markdown(graph, matches[0]["id"]))
        if ns.output:
            out_f = Path(ns.output)
            out_f.parent.mkdir(parents=True, exist_ok=True)
            out_f.write_text(md_text, encoding="utf-8")
            print(f"Measure specification written: {out_f}")
        else:
            sys.stdout.write(md_text + ("\n" if not md_text.endswith("\n") else ""))
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
