# Changelog

All notable changes to `pbi-doc-generator` are documented in this file.
This project follows [Semantic Versioning](https://semver.org/).

## [1.1.0] - 2026-11-15

### Added
- **Slide-Over Report & Dataflow X-Ray Inspector (#14, #17):**
  - Calm 4-tab portal architecture (`Semantic Models`, `Workspaces & Reports`, `Live Lineage`, `Governance & Health`) paired with a slide-over X-Ray drawer for cloud thin reports (`PBIR` and legacy `report.json`) and Dataflows.
  - Interactive **16:9 SVG page wireframes** with chart-type schematics, visual group containers, field/filter/slicer bindings, thin-report local DAX measures (`reportExtensions.json`), and a **1-click Broken Visual Binding Stepper**.
- **Dataflow Gen1, Fabric Dataflow Gen2 & Direct Lake Lineage (#13, #18):**
  - Multi-layer **Dataflow Gen1** (`model.json`, `L1` / `L2+` chained dataflows and `ReferenceEntity` linked entities across workspaces) and **Fabric Dataflow Gen2** (`mashup.pq` + OneLake Lakehouse / Warehouse table destinations) connected to Direct Lake and Import semantic models.
  - Embedded **Native SQL formatter** and clickable **Power Query M step interpreter**.
- **High-Speed Parallel Enterprise Scanner & 5-Stage Live Progress Bar:**
  - Progressive `1s` Fabric `getDefinition` LRO polling (cutting boilerplate `20s` `Retry-After` idle waits on fast models/reports down to `~1.1s`), per-thread persistent HTTP/1.1 TLS keep-alive connection pooling, 8-worker parallel datasource inventory, `as_completed()` streaming across 6 model and 8 report workers, and `O(1)` indexed end-to-end field resolution.
  - Real-time 5-stage visual progress bar (`Inventory -> Semantic Models -> Report Layouts -> Dataflows -> Build Portal`) with live object counters, percentage, elapsed clock, and adaptive ETA.
- **Zero-Dependency Star-Schema Explorer, Stacked PDF Export & End-to-End Measure Lineage (#15):**
  - Native HTML+SVG Star-Schema Explorer with Focused Star tabs per Fact table, SQLBI-formatted DAX measures with `Used in Reports` / `Unused` filters, `measure-doc` CLI export, and **10 read-only MCP tools** (adding `pbi_trace_measure_end_to_end` and `pbi_report_layout`).
  - Isolated A4 portrait PDF print engine rendering full-width vector Star-Schema diagrams stacked cleanly across pages alongside KPIs, tables, relationships, DAX, and Power Query M.
- **Scoped Export & 1-Click SharePoint Online Publishing:**
  - Unified `Export / Publish` dialog scoped to either **This Semantic Model** or the **Entire Catalog**: A4 Print / PDF, standalone HTML, `.zip` archive, Data Dictionary (`Word` / `Markdown` / `CSV`), direct **1-click upload to a SharePoint Online Document Library URL**, and compressed `srcdoc`-safe single-file SharePoint HTML (`export-site`).
- **Guided 3-Step Web Studio, Hardened OAuth PKCE & Automatic `v1.0 -> v1.1` Upgrade Detection:**
  - Progressive `1. Connect -> 2. Choose Workspaces -> 3. Scan & Build` workflow, instant browser sign-in popup with multi-threaded localhost OAuth callback handling, `Switch Account` isolation, and automatic `HTTP 401` token refresh during long multi-workspace scans.
  - Automatic detection of pre-`v1.1` local catalog artifacts with a 1-click **Start Clean for v1.1** workflow and automatic `catalog_state.v1_0.bak.json` backup.
  - Includes PR #19 contributions by `@andreasfelder` toward #13 and #14.

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
