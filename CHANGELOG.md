# Changelog

All notable changes to `pbi-doc-generator` are documented in this file.
This project follows [Semantic Versioning](https://semver.org/).

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
