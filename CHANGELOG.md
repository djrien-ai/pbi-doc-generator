# Changelog

All notable changes to `pbi-doc-generator` are documented in this file.
This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Dataflow Gen1 scanning:** exports dataflow definitions (`model.json` + Power Query), upstream dataflow links and data sources with the existing sign-in; follows dataflow -> dataflow references across workspaces (`scan_dataflow_definitions`, `pbi_catalog/dataflows.py`).
- **End-to-End Measure Lineage explorer (`portal/e2e_lineage.html`):** layered reference map from SQL / Excel / file sources through every dataflow layer and the dataset's Power Query to the DAX measure chain, with code for every step and upstream / downstream modes (`pbi_catalog/e2e_lineage.py`, `pbi_catalog/e2e_explorer.py`).
- **Measure documentation export:** HTML, Word and Markdown, per measure or for every measure of a model; CLI `measure-doc` command; MCP tool `pbi_trace_measure_end_to_end`.
- **Native SQL & step browser:** formatted native SQL (HANA `Query=`, `Value.NativeQuery`, SQL assembled with `&` parameters or held in a step) under every query; plain-language, clickable Power Query step interpreter; both included in documentation exports.
- **Export all data:** SharePoint-ready static portal `.zip` (`.html` + `.aspx` twins, README) from the explorer or `pbi-doc-generator export-site`.
- **Diagnostics:** `--trace` recording of Power BI API calls, Studio logs and browser errors; `pbi-doc-generator diagnose` with metadata-only verification.
- Studio option *Include Dataflow Gen1 definitions* and CLI flag `scan --no-dataflows`.
- **Dataflows and thin-report measures across the portal (`pbi_catalog/portal_xref.py`):** new *Dataflows* tab (workspace / usage filters, queries, connectors, native SQL, upstream / downstream dataflows, models fed); model pages show *Dataflows Feeding This Model* (L1/L2+), per-table upstream lineage, report-level measures of thin reports and dataflow layers in the lineage widget; the report map, workspace table, KPIs, portfolio lineage and Governance tab (unreadable dataflows / report definitions) include them too.
- **Workspace selection is respected everywhere:** the scan records the selected workspaces (`scope` in `catalog_state.json`); dataflow and thin-report steps no longer read dataflows or shared models in unselected workspaces (they become "outside selected workspaces" placeholders in lineage). The portal, explorer, site export and MCP tools show only the selected workspaces (`CatalogStore.load_scoped`); *Rebuild HTML Portal* uses the workspaces ticked at that moment. Opt-in: Studio *Follow references outside the selected workspaces* / `scan --follow-outside` reads just the referenced objects.
- **End-to-End explorer as portal tab 6:** embedded in the portal home page (no page switch, deep links `index.html#e2e:<filters>`; the old `e2e_lineage.html` URL forwards there), with KPI cards instead of a text line.
- **Export buttons on every tab and model page (`pbi_catalog/portal_export.py`):** *Export all data* (Studio) plus a context-aware documentation export - semantic models, workspaces & reports, dataflows, data lineage, governance & health report, or (End-to-End tab) measures - as HTML, Word or Markdown, built offline from `assets/portal_meta.js` + the lineage graph.
- Regenerating the portal removes model pages that are no longer in scope.
- **Report Explorer (portal tab 3, `pbi_catalog/report_explorer.py`):** report pages drawn to scale from the report definition (no data): visuals with type, title, bound fields, visual filters, slicer selections and text. Click a visual, then a field / filter / slicer, for its DAX or column details, upstream lineage map and "used in" list across all reports; deep links `index.html#rpt:r=<id>&p=<page>&v=<visual>`. Layouts are parsed during the report scan (`reports.parse_report_layout`, PBIR and legacy `report.json`) and stored in `catalog/report_layouts/`; reports read before this version are re-read automatically on the next scan. New governance finding for visuals that use fields missing from their model; *Export report documentation*; End-to-End explorer lists the report visuals using a measure / table; MCP tool `pbi_report_layout`.
- **Single-file SharePoint export (`pbi_catalog/sharepoint_single.py`):** the whole portal (pages, styles, scripts, lineage graph) packed into one compressed `.html` that works inside SharePoint Online's sandboxed file viewer (relative links, lazy data loads and the embedded explorer are served by an in-file shell). Default format of *Export all data*; `export-site --single-file`. The `.zip` keeps the folder version (and contains the single file); `.aspx` copies are now opt-in (`--aspx`). Browser storage access is guarded everywhere.
- **Documentation & CI:** README (dataflows, end-to-end lineage, Report Explorer, SharePoint export, CLI options), ARCHITECTURE, CONTRIBUTING, SECURITY (structure-only guarantee, workspace scope, sensitive diagnostics trace) and ROADMAP updated; CI also runs the new pytest suites (`tests/test_dataflow_lineage.py`, `test_report_layout.py`, `test_sql_steps.py`, `test_trace_diagnostics.py`); `.gitignore` excludes catalogs, traces, exports and model files so scanned data is never committed.
- **End-to-end explorer filters:** Workspace → semantic model / thin report / dataflow → details (table, folder, role, connector, dataflow, native SQL); picking a model lists everything upstream of it, picking a dataflow also lists what depends on it; filter state is kept in the URL so portal pages deep-link into filtered views.

## [1.0.0] - 2026-11-12

### Added
- **Power BI Service Multi-Workspace Scanner (`pbi_catalog`):** Scan 1 to 50+ Power BI / Microsoft Fabric workspaces into a unified, searchable offline HTML catalog (`Semantic Models`, `Workspaces & Reports Map` including cross-workspace shared datasets & orphan models, `Live Lineage Explorer`, and `Governance & Health`).
- **Zero-Admin Browser Authentication:** Supports standard Microsoft OAuth 2.0 PKCE (`Sign in with Microsoft`), corporate Edge/Chrome Web Window fallback (`Sign in via Power BI Web Window`), Azure CLI (`az`), Service Principal (`client_credentials`), and in-memory bearer tokens.
- **Unified Localhost Web Studio (`http://127.0.0.1:8765`):** Guided 2-part web interface (`1. Scanner & Setup` and `2. Documentation Portal`) with native browser file/drag-and-drop import for `.pbix`, `.pbip` (automatic companion `.SemanticModel` resolution), and Excel PowerPivot `.xlsx` files.
- **Interactive 3-Panel Live Lineage Explorer:** End-to-end interactive SVG impact tracing from upstream data sources (28+ enterprise connectors including SAP HANA, SAP BW, Snowflake, Databricks, Fabric, SQL Server, SharePoint, BigQuery) through tables and columns to DAX measures and downstream reports.
- **Structured DAX & Visual Power Query Catalog:** Auto-pretty-prints single-line DAX formulas, groups measures by `Table -> Display Folder -> Dependency Tier`, defaults to a fast `Compact Table` view with instant toggle to `Formatted Cards`, and renders step-by-step Power Query M transformation ribbons on crisp light-themed code blocks.
- **Flexible Catalog Views:** Switch between `Grid`, sortable `List`, and `By Workspace` views with synchronized Light/Dark mode.
- **Model Context Protocol (MCP) Server (`pbi-doc-generator mcp`):** Local read-only stdio MCP server with 7 tools (`list_catalog_overview`, `search_catalog`, `get_model_blueprint`, `trace_lineage`, `find_unused_and_health_risks`, `compare_models`, `get_workspace_report_map`) and automatic secret redaction.
- **Interactive Star-Schema Mermaid Viewer:** Zoom, pan, fullscreen, hover preview, and click-to-pin relationship highlighting (contributed by `@jakubpokusa` in PR #10).
- **Automated CI/CD & Portable Packaging:** GitHub Actions workflows for multi-version test matrices and automated zero-install `Windows_Portable.zip` + Python wheel builds on release tags.

### Fixed
- **TMDL Table Documentation Comments (`///`):** Fixed table-level doc comments inadvertently overwriting the parsed table name (reported by `@nblankes` in Issue #12).
- **Legacy Compatibility `.pbix` Power Query Extraction:** Added automatic fallback extraction from `DataMashup` (`Formulas/Section1.m`) when SQLite partition metadata returns empty Power Query rows.
- **Zero Horizontal Scrollbars:** Responsive wrapping across wide relationship, column, DAX, and lineage panels.

## [0.7.0] - 2026-03-19
- Added AI Prompt-Pack extraction and Excel PowerPivot (`.xlsx`) Power Query & Data Model support.
- Bumped `pbixray` to `0.15.5` for Xpress9 DataModel decompression support (contributed by `@okiyuki99` in PR #11).

## [0.6.1] - 2026-03-01
- Standalone portable `.exe` build improvements, resilient error reporting (`ExtractionError`), and secret redaction in logs.

## [0.5.0] - 2026-02-15
- Report page & visual inventory mapping and semantic data-role extraction.

## [0.2.0] - 2026-01-20
- Native TMDL / `.pbip` SemanticModel parsing, calculation groups, and Mermaid measure lineage diagrams.

## [0.1.0-beta] - 2026-01-05
- Initial release: standalone HTML documentation generator for Power BI `.pbix` files.
