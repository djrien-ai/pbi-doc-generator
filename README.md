# Power BI Documentation & Live Lineage Studio (`pbi-doc-generator` v1.0)

[![CI](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml)
[![Live Demo Portal](https://img.shields.io/badge/Live_Demo-Explore_v1.0_Portal-0b63ce?logo=github)](https://djrien-ai.github.io/pbi-doc-generator/)
[![Download Windows ZIP](https://img.shields.io/badge/Windows_Download-Portable_.zip_(No_Python)-15803d?logo=windows)](https://github.com/djrien-ai/pbi-doc-generator/releases/latest/download/PBI_Doc_Generator_Windows_Portable.zip)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![100% Local & Read-Only](https://img.shields.io/badge/Privacy-100%25_Local_%26_Read--Only-0f766e.svg)](SECURITY.md)
[![Support on Ko-fi](https://img.shields.io/badge/Support_on_Ko--fi-Buy_me_a_coffee-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/rienscheerlinck)

Turn **Power BI Service Workspaces** and local **`.pbix` / `.pbip` / `.xlsx`** files into clean, searchable HTML documentation with **interactive Star-Schema diagrams**, **auto-formatted DAX catalogs**, **visual Power Query pipelines**, **3-panel end-to-end Live Lineage**, and a **built-in local Model Context Protocol (MCP) server** for AI assistants.

👉 [**Explore the Live Interactive v1.0 Demo Portal in your browser**](https://djrien-ai.github.io/pbi-doc-generator/) *(no installation required)*

---

## Quick Start

### Option 1: Portable Windows Download (No Python Required - Recommended for Business Users)

1. [**Click here to download `PBI_Doc_Generator_Windows_Portable.zip` directly**](https://github.com/djrien-ai/pbi-doc-generator/releases/latest/download/PBI_Doc_Generator_Windows_Portable.zip) *(or view the [Release page](https://github.com/djrien-ai/pbi-doc-generator/releases/latest))*.
2. Right-click the downloaded ZIP file and choose **Extract All...**
3. Open the extracted folder and double-click **`PBI_Doc_Generator.exe`** -> your browser opens **`http://127.0.0.1:8765`** automatically.
   *(If Windows SmartScreen asks for confirmation on first launch: click **More info** -> **Run anyway**.)*

### Option 2: Install via `pip` (Python 3.10+ on Windows, macOS & Linux)

```bash
pip install "git+https://github.com/djrien-ai/pbi-doc-generator.git"
```

Launch the local Web Studio from anywhere:

```bash
pbi-doc-generator
```

*(Or clone/download the source repository on Windows and double-click **`Start_Studio.cmd`** - it automatically installs `requirements.txt` on first launch.)*

> [!IMPORTANT]
> **Power BI Service Workspace Role Prerequisite (`Contributor` or higher)**
> To extract full semantic model definitions (tables, relationships, DAX measures, and Power Query M) from Power BI Service workspaces, your Microsoft account must have at least the **Contributor** role (**Contributor**, **Member**, or **Admin**) in each workspace you want to document.
> - Workspaces where you only have the **Viewer** role will list basic workspace and report inventory, because Microsoft's Fabric `getDefinition` (TMDL) API blocks `Viewer`-only accounts (`HTTP 403`).
> - Documenting local `.pbix`, `.pbip`, and `.xlsx` files works 100% offline and requires no Power BI Service permissions.

---

## What Is Inside v1.0

1. **Power BI Service Multi-Workspace Scanner (Zero Azure Admin Setup Required)**
   - Sign in with your normal Microsoft account (`Sign in with Microsoft` OAuth 2.0 PKCE in your default browser, plus a fallback `Power BI Web Window` mode for locked-down corporate tenants, Azure CLI, and Service Principal support for CI/CD).
   - Document 1 or 50+ workspaces into one searchable, 100% offline HTML portal with **Grid**, **List**, and **By Workspace** views, **Workspaces & Reports Mapping** (highlighting **Cross-Workspace Shared Datasets / Thin Reports** and **Orphan Models**), **Interactive Live Lineage**, and **Governance & Health Checks**.
2. **Unified Local File Support (`.pbix`, `.pbip`, `.xlsx`)**
   - Drop or select any local `.pbix` file, `.pbip` project (automatically resolves its companion `.SemanticModel` folder), or Excel PowerPivot `.xlsx` workbook directly in the browser.
3. **Effortless-to-Read Model Documentation**
   - **Interactive Star-Schema Diagram:** Automatically classifies **Fact** vs. **Dimension** tables with zoom, pan, fullscreen, and click-to-pin relationship highlighting (contributed by `@jakubpokusa`).
   - **Visual Power Query Pipelines:** Displays an easy-to-scan transformation step ribbon (`1. Source -> 2. Filtered Rows -> 3. Typed Columns`) above collapsible syntax-highlighted M code, recognizing 28+ enterprise connectors (SAP HANA, SAP BW, Snowflake, Databricks, Microsoft Fabric, SQL Server, SharePoint, Excel, BigQuery, and more).
   - **Auto-Formatted & Structured DAX Catalog:** Defaults to a fast **Compact Table** overview with a 1-click toggle to **Formatted Cards** organized by `Table -> Display Folder -> Dependency Tier`, pretty-printing single-line DAX formulas and linking `Reads:` / `Used by:` dependencies.
4. **Interactive 3-Panel Live Lineage Explorer**
   - Click any upstream database/view, Power Query table, column, DAX measure, or Power BI report to trace live upstream origins and downstream impact with smooth SVG connectors.
5. **Built-In Local Model Context Protocol (MCP) Server for AI Assistants**
   - Tab 3 of the Web Studio (`pbi-doc-generator mcp`) exposes 8 read-only MCP tools to **VS Code GitHub Copilot**, **Claude Desktop**, **Cursor**, or **Antigravity** across all your scanned workspaces and imported local `.pbix` / `.pbip` / `.xlsx` models, with automatic secret masking.

---

## Dataflow Gen1 & End-to-End Measure Lineage

Scans now also export every **Power BI Dataflow (Gen1)** in the selected workspaces, using the same sign-in (all calls are read-only `GET`s):

- **Dataflow definitions:** each dataflow's `model.json` is exported (`GET groups/{ws}/dataflows/{id}`) and its Power Query section document is split into individual queries, classified as *Entity*, *Computed entity*, *Linked entity*, *Staging / helper query*, *Function*, or *Parameter*.
- **Dataflow -> dataflow chains:** linked entities (`PowerPlatform.Dataflows` / `PowerBI.Dataflows` navigation by `workspaceId` / `dataflowId` / `entity`) and the `upstreamDataflows` API are followed automatically inside the selected workspaces. References into other workspaces appear as *outside selected workspaces*; tick *Follow references outside the selected workspaces* (`scan --follow-outside`) to read just those dataflows too.
- **Dataset table -> dataflow entity:** every semantic-model table partition (and shared query it references) is resolved to the exact dataflow entity it loads. Parameterised dataflow ids are resolved via model parameters, with the REST `datasets/upstreamDataflows` links as a fallback.
- **Physical sources:** SQL server / database / schema.table, **native SQL scripts** (with `#(lf)` escapes decoded), Excel workbooks and sheets, SharePoint / file paths, and the other 28+ connectors.

Open **7. End-to-End Lineage** in the portal (or click *Trace end-to-end* on any measure card) to:

1. **Click a measure** and see a layered **reference map**: Sources -> Dataflow layer N ... -> Dataflow layer 1 -> Dataset Power Query -> Model tables / calculated columns -> referenced measures -> the measure. Click any box for its DAX, M or SQL code, dependencies and consumers; switch to *Downstream* to see what uses an object.
2. **Export measure documentation** (HTML for print/PDF, Word `.doc`, or Markdown with a Mermaid map) that explains the measure bottom-up: *1. Source systems & SQL scripts -> 2. Dataflow transformations (deepest layer first) -> 3. Dataset Power Query -> 4. Tables & columns used -> 5. DAX calculation chain (base measures first)*. *Export model documentation* writes one document for every measure of a model.

```bash
# Same documentation from the CLI (Markdown)
pbi-doc-generator measure-doc "Margin %" --model "Sales Model" -o margin.md
pbi-doc-generator measure-doc --all --model "Sales Model" -o sales_model_measures.md

# Skip dataflows during a scan
pbi-doc-generator scan --workspace "Finance" --no-dataflows
```

**Export all data** (portal header, when running in the Studio) produces either a **single `.html` file for SharePoint Online** - upload it to a document library and click it; the whole portal runs inside SharePoint's file viewer - or a `.zip` with the static site for a synced folder, file share or web server (also `pbi-doc-generator export-site [--single-file]`). Every tab also has a context-aware *Export ... documentation* button (models, workspaces & reports, report pages & visuals, dataflows, lineage, governance, measures).

## Report Explorer (pages & visuals, no data)

The report scan step (`reports/{id}/getDefinition`, the same read-only call used for report-level measures) also stores each report's **layout**: pages, every visual's position, size, type and title, the columns / measures bound to each visual role, report / page / visual filters with their selected values, slicer selections and text box text. No query is ever run against the model, so no report data is loaded.

Open **3. Report Explorer**:

1. Filter by **workspace** and **semantic model**, pick a **report**, then a **page** - the page is drawn to scale as a wireframe (neutral placeholder per visual type, slicers with their selected values, text boxes with their text).
2. Click a **visual** to list its fields by role (rows, columns, values, legend ...), its visual filters and slicer selection.
3. Click any **field, filter or slicer** to see its DAX / column details, the full **upstream lineage map** (measures -> tables -> Power Query -> dataflow layers -> SQL sources) and every other visual in any report that uses it. *Open in End-to-End explorer* continues there; the End-to-End explorer in turn lists the report visuals that use a measure or table.

Fields that no longer exist in the semantic model are flagged red and listed under *Governance & Health*. Everything is computed during the scan / portal build - no manual steps. AI assistants get the same data through the MCP tool `pbi_report_layout` (reports, pages, visuals with their fields' lineage ids) next to `pbi_trace_measure_end_to_end`.

> [!NOTE]
> Exporting a Gen1 dataflow definition requires the same access as editing it (workspace **Contributor** or higher, or dataflow owner). Dataflows you cannot export, or that live in workspaces you cannot see, appear as dashed *Not scanned* boxes in the map and the lineage stops there.

---

## Command-Line Usage (CLI & CI/CD)

```bash
# Launch the interactive Web Studio (default)
pbi-doc-generator

# Scan specific workspaces incrementally and generate the offline HTML portal
pbi-doc-generator scan --workspace "Supply Chain"

# Generate an anonymized portal safe for external sharing (hides personal/owner names)
pbi-doc-generator portal --anonymous

# Import a local .pbip, .SemanticModel, .pbix, or .xlsx into the multi-model catalog
pbi-doc-generator import-local ./SalesModel.pbip

# Generate a single standalone HTML file for one .pbix / .pbip / .xlsx
pbi-doc-generator file ./Report.pbix

# Start the stdio MCP server for AI assistants
pbi-doc-generator mcp

# Scan options: skip dataflows / report definitions, follow references into unselected workspaces
pbi-doc-generator scan --workspace "Finance" --no-dataflows --no-reports
pbi-doc-generator scan --workspace "Finance" --follow-outside

# Measure documentation (SQL -> Power Query -> DAX) as Markdown
pbi-doc-generator measure-doc "Margin %" --model "Sales Model" -o margin.md

# Export the portal: single file for SharePoint Online, or a folder .zip (optionally with .aspx copies)
pbi-doc-generator export-site --single-file
pbi-doc-generator export-site --aspx

# Record a diagnostics trace while using the Studio, then verify it (metadata-only check, errors, lineage health)
pbi-doc-generator studio --trace ./trace
pbi-doc-generator diagnose --trace ./trace
```

---

## Security & Privacy by Design

- **100% Local Execution:** Metadata, TMDL definitions, and generated HTML files stay on your machine (`127.0.0.1`). Zero telemetry or external CDN calls.
- **Enforced Read-Only API Guard:** `PowerBiReadOnlyClient` blocks `DELETE`, `PATCH`, `PUT`, and mutating `POST` requests in code, allowing only `GET` metadata calls and the read-only Fabric `getDefinition` endpoint.
- **In-Memory Tokens Only:** OAuth access tokens live strictly in Python RAM for the active session and are never written to disk.
- **Automatic Secret Redaction:** Connection passwords, SAS tokens, API keys, and bearer tokens are automatically masked in both HTML pages and MCP responses. See [SECURITY.md](SECURITY.md) for details.

---

## Enterprise Integrations & Architecture Audits

The core of `pbi-doc-generator` is and remains 100% free and open-source under the MIT License. Organizations looking for custom enterprise integrations (automated CI/CD lineage publishing to SharePoint, Confluence, or Microsoft Purview, historical semantic-model drift monitoring, or white-label governance portals) or an independent **Power BI Estate & Semantic Model Architecture Audit** can inquire via **Bohan VOF** ([Rien Scheerlinck](https://github.com/djrien-ai)):

[![Inquire via Email - Bohan VOF](https://img.shields.io/badge/Enterprise_&_Advisory_Inquiries-Email_Bohan_VOF-0b63ce?logo=gmail&logoColor=white)](mailto:dj.rien@gmail.com?subject=Power%20BI%20Enterprise%20%26%20Architecture%20Inquiry)

---

## Community & Support

Special thanks to community contributors `@jakubpokusa` (interactive Mermaid relationship viewer), `@okiyuki99` (Xpress9 `pbixray` support), and `@nblankes` (TMDL table doc-comment bug report).

If `pbi-doc-generator` saves your BI team hours of manual documentation or impact analysis, consider starring the repository or [**supporting ongoing open-source development on Ko-fi**](https://ko-fi.com/rienscheerlinck).

## License

MIT License - Copyright (c) 2024-2026 Rien Scheerlinck. See [LICENSE](LICENSE) for full text.
