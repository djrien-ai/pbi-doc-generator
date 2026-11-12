# Power BI Documentation & Live Lineage Studio (`pbi-doc-generator` v1.0)

[![CI](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml/badge.svg)](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![100% Local & Read-Only](https://img.shields.io/badge/Privacy-100%25%20Local%20%26%20Read--Only-15803d.svg)](SECURITY.md)

Generate clean, executive-ready HTML documentation, **Star-Schema relationship diagrams**, **auto-formatted DAX catalogs**, **visual Power Query pipelines**, **interactive end-to-end Live Lineage**, and a **local AI Model Context Protocol (MCP) server** from both **Power BI Service Workspaces** and **local `.pbix` / `.pbip` / `.xlsx` files**.

---

## Quick Start

### Option 1: Portable Windows Download (No Python Required - Recommended for Business Users)

1. Download **`PBI_Doc_Generator_v1.0.0_Windows_Portable.zip`** from [**GitHub Releases**](https://github.com/djrien-ai/pbi-doc-generator/releases/latest).
2. Extract the ZIP folder anywhere on your PC.
3. Double-click **`PBI_Doc_Generator.exe`** -> your browser opens **`http://127.0.0.1:8765`** immediately.

### Option 2: Install via `pip` (Python 3.10+ on Windows, macOS & Linux)

```bash
pip install "git+https://github.com/djrien-ai/pbi-doc-generator.git"
```

Launch the local Web Studio from anywhere:

```bash
pbi-doc-generator
```

*(Or clone/download the source repository and double-click **`Start_Studio.cmd`** on Windows - it automatically installs `requirements.txt` on first launch.)*

---

## What Is Inside v1.0

1. **Power BI Service Multi-Workspace Scanner (Zero Azure Admin Setup Required)**
   - Sign in with your normal Microsoft account (`Sign in with Microsoft` OAuth 2.0 PKCE in your default browser, plus a fallback `Power BI Web Window` mode for locked-down corporate tenants, Azure CLI, and Service Principal support for CI/CD).
   - Document 1 or 50+ workspaces into one searchable, 100% offline HTML portal with **Grid**, **List**, and **By Workspace** views, **Workspaces & Reports Mapping** (highlighting **Cross-Workspace Shared Datasets / Thin Reports** and **Orphan Models**), **Interactive Live Lineage**, and **Governance & Health Checks**.
2. **Unified Local File Support (`.pbix`, `.pbip`, `.xlsx`)**
   - Drop or select any local `.pbix` file, `.pbip` project (automatically resolves its companion `.SemanticModel` and `.Report` folders), or Excel PowerPivot `.xlsx` workbook directly in the browser.
3. **Effortless-to-Read Model Documentation**
   - **Interactive Star-Schema Diagram:** Automatically classifies **Fact** vs. **Dimension** tables with zoom, pan, fullscreen, and click-to-pin relationship highlighting (contributed by `@jakubpokusa`).
   - **Visual Power Query Pipelines:** Displays an easy-to-scan transformation step ribbon (`1. Source -> 2. Filtered Rows -> 3. Typed Columns`) above collapsible syntax-highlighted M code, recognizing 28+ enterprise connectors (SAP HANA, SAP BW, Snowflake, Databricks, Microsoft Fabric, SQL Server, SharePoint, Excel, BigQuery, and more).
   - **Auto-Formatted & Structured DAX Catalog:** Defaults to a fast **Compact Table** overview with a 1-click toggle to **Formatted Cards** organized by `Table -> Display Folder -> Dependency Tier`, pretty-printing single-line DAX formulas and linking `Reads:` / `Used by:` dependencies.
4. **Interactive 3-Panel Live Lineage Explorer**
   - Click any upstream database/view, Power Query table, column, DAX measure, or Power BI report to trace live upstream origins and downstream impact with smooth SVG connectors.
5. **Built-In Model Context Protocol (MCP) Server for AI Assistants**
   - Connect **VS Code GitHub Copilot**, **Claude Desktop**, **Cursor**, or **Antigravity** directly to your local catalog to run instant cross-workspace impact analysis with automatic secret masking.

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

## Community & Support

Special thanks to community contributors `@jakubpokusa` (interactive Mermaid relationship viewer), `@okiyuki99` (Xpress9 `pbixray` support), and `@nblankes` (TMDL table doc-comment bug report).

If `pbi-doc-generator` saves your BI team hours of manual documentation or impact analysis, consider starring the repository or supporting ongoing open-source development via **GitHub Sponsors** on this repository.

## License

MIT License - Copyright (c) Rien Scheerlinck.
