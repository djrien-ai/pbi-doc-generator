# Power BI Documentation & Live Lineage Studio (`pbi-doc-generator` v1.0)

[![CI](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml)
[![Live Demo Portal](https://img.shields.io/badge/Live_Demo-Explore_v1.0_Portal-0b63ce?logo=github)](https://djrien-ai.github.io/pbi-doc-generator/)
[![Download Windows ZIP](https://img.shields.io/badge/Windows_Download-Portable_.zip_(No_Python)-15803d?logo=windows)](https://github.com/djrien-ai/pbi-doc-generator/releases/latest/download/PBI_Doc_Generator_Windows_Portable.zip)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![100% Local & Read-Only](https://img.shields.io/badge/Privacy-100%25_Local_%26_Read--Only-0f766e.svg)](SECURITY.md)

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
```

---

## Security & Privacy by Design

- **100% Local Execution:** Metadata, TMDL definitions, and generated HTML files stay on your machine (`127.0.0.1`). Zero telemetry or external CDN calls.
- **Enforced Read-Only API Guard:** `PowerBiReadOnlyClient` blocks `DELETE`, `PATCH`, `PUT`, and mutating `POST` requests in code, allowing only `GET` metadata calls and the read-only Fabric `getDefinition` endpoint.
- **In-Memory Tokens Only:** OAuth access tokens live strictly in Python RAM for the active session and are never written to disk.
- **Automatic Secret Redaction:** Connection passwords, SAS tokens, API keys, and bearer tokens are automatically masked in both HTML pages and MCP responses. See [SECURITY.md](SECURITY.md) for details.

---

## Enterprise Integrations & Architecture Audits

The core of `pbi-doc-generator` is and remains 100% free and open-source under the MIT License. Organizations looking for custom enterprise integrations (automated CI/CD lineage publishing to SharePoint, Confluence, or Microsoft Purview, historical semantic-model drift monitoring, or white-label governance portals) or an independent **Power BI Estate & Semantic Model Architecture Audit** can inquire via **Bohan VOF** ([connect with Rien Scheerlinck on LinkedIn](https://www.linkedin.com/in/rien-scheerlinck/)).

---

## Community & Support

Special thanks to community contributors `@jakubpokusa` (interactive Mermaid relationship viewer), `@okiyuki99` (Xpress9 `pbixray` support), and `@nblankes` (TMDL table doc-comment bug report).

If `pbi-doc-generator` saves your BI team hours of manual documentation or impact analysis, consider starring the repository or supporting ongoing open-source development via **GitHub Sponsors** on this repository.

## License

MIT License - Copyright (c) 2024-2026 Rien Scheerlinck. See [LICENSE](LICENSE) for full text.
