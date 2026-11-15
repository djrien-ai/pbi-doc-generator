# Changelog

All notable changes to `pbi-doc-generator` are documented in this file.
This project follows [Semantic Versioning](https://semver.org/).

## [1.1.0] - Unreleased (Public Preview on branch `v1.1`)

### Added
- **Multi-Layer Dataflow Gen1 & Fabric Dataflow Gen2 Lineage:**
  - Full **Dataflow Gen1** (`model.json`) extraction with `L1` / `L2+` chained dataflow and `ReferenceEntity` linked-entity resolution across workspaces, query role classification, and automatic privacy scrubbing of internal storage locations (contributed by `@andreasfelder` in PR #19).
  - Native **Fabric Dataflow Gen2** (`mashup.pq` + `queryMetadata.json`) extraction with OneLake **Lakehouse** and **Warehouse** destination mapping, plus **Direct Lake** semantic model entity binding.
- **Native SQL Formatter & Clickable Power Query Step Interpreter:** Pretty-prints embedded SQL queries (`Value.NativeQuery`, `Sql.Database`, `Snowflake`, `SapHana`, etc.) and explains M transformation steps in plain English with expandable raw M expressions (contributed by `@andreasfelder` in PR #19).
- **Cloud Thin-Report Definitions & Slide-Over Report X-Ray Inspector:**
  - Extracts cloud report definitions (`PBIR` and legacy `report.json`), report-local DAX measures bound to shared semantic models, page/visual filters, slicer selections, and broken visual field bindings (contributed by `@andreasfelder` in PR #19).
  - New **Slide-Over Report & Dataflow X-Ray Drawer** keeping a calm 4-tab portal architecture (`Semantic Models`, `Workspaces & Reports`, `Live Lineage`, `Governance & Health`) with interactive **16:9 SVG page wireframes**, chart type glyphs, visual-group containers, and a 1-click broken-binding stepper.
- **End-to-End Measure Lineage (`Visual -> DAX -> Power Query -> Dataflow -> SQL`):**
  - Deep multi-hop lineage engine (`e2e_lineage.py`) and `pbi-doc-generator measure-doc` CLI export (contributed by `@andreasfelder` in PR #19).
  - Expanded MCP server from 8 to **10 read-only tools**, adding `pbi_trace_measure_end_to_end` and `pbi_report_layout`.
- **Unified `Export / Publish` Modal & SharePoint Online Publishing:**
  - Scope exports to either **This Semantic Model** or the **Entire Catalog**: A4 Print / PDF, self-contained HTML, offline `.zip` archive, Data Dictionary (`Word` / `Markdown` / `CSV`), compressed `srcdoc`-safe single-file SharePoint HTML (`export-site`, contributed by `@andreasfelder`), and **direct 1-click upload to a SharePoint Online Document Library URL**.
- **Enterprise Scale & Studio UX Overhaul:**
  - Parallel workspace scanning (4 concurrent models, 8 concurrent reports), `--follow-outside` workspace boundary control, and thread-safe `catalog_state.json` persistence fixing Windows `WinError 5` file-locking collisions (contributed by `@andreasfelder` in PR #19).
  - Progressive 3-step Web Studio workflow (`1. Connect -> 2. Choose Workspaces -> 3. Scan & Build`), deliberate workspace selection on tenants with `> 5` workspaces, `Sign Out / Switch Account`, and zero-dependency native HTML+SVG Star-Schema Explorer.

## [1.0.0] - 2026-11-12

### Added
- **Power BI Service Multi-Workspace Scanner (`pbi_catalog`):** Scan 1 to 50+ Power BI / Microsoft Fabric workspaces into a unified, searchable offline HTML catalog (`Semantic Models`, `Workspaces & Reports Map` including cross-workspace shared datasets & orphan models, `Live Lineage Explorer`, and `Governance & Health`).
- **Zero-Admin Browser Authentication:** Supports standard Microsoft OAuth 2.0 PKCE (`Sign in with Microsoft`), corporate Edge/Chrome Web Window fallback (`Sign in via Power BI Web Window`), Azure CLI (`az`), Service Principal (`client_credentials`), and in-memory bearer tokens.
- **Unified Localhost Web Studio (`http://127.0.0.1:8765`):** Guided 2-part web interface (`1. Scanner & Setup` and `2. Documentation Portal`) with native browser file/drag-and-drop import for `.pbix`, `.pbip` (automatic companion `.SemanticModel` resolution), and Excel PowerPivot `.xlsx` files.
- **Interactive 3-Panel Live Lineage Explorer:** End-to-end interactive SVG impact tracing from upstream data sources (28+ enterprise connectors including SAP HANA, SAP BW, Snowflake, Databricks, Fabric, SQL Server, SharePoint, BigQuery) through tables and columns to DAX measures and downstream reports.
- **Structured DAX & Visual Power Query Catalog:** Auto-pretty-prints single-line DAX formulas, groups measures by `Table -> Display Folder -> Dependency Tier`, defaults to a fast `Compact Table` view with instant toggle to `Formatted Cards`, and renders step-by-step Power Query M transformation ribbons on crisp light-themed code blocks.
- **Flexible Catalog Views:** Switch between `Grid`, sortable `List`, and `By Workspace` views with synchronized Light/Dark mode.
- **Model Context Protocol (MCP) Server (`pbi-doc-generator mcp`):** Local read-only stdio MCP server with automatic secret redaction.
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
