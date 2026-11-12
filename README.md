# Power BI Documentation & Live Lineage Studio (`pbi-doc-generator` v1.0)

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![100% Local & Read-Only](https://img.shields.io/badge/Privacy-100%25%20Local%20%26%20Read--Only-15803d.svg)](#security--privacy)

Generate clean, executive-ready HTML documentation, **Star-Schema relationship diagrams**, **auto-formatted DAX catalogs**, **visual Power Query pipelines**, **interactive end-to-end Live Lineage**, and a **local AI Model Context Protocol (MCP) server** from both **Power BI Service Workspaces** and **local `.pbip` / `.pbix` / `.xlsx` files**.

---

## What Is New in v1.0

1. **Power BI Service Multi-Workspace Scanner (Zero Azure Admin Setup Required)**
   - Sign in with your normal Microsoft account (`Sign in with Microsoft` OAuth 2.0 PKCE in your default browser, plus a fallback Web Window mode for locked-down corporate tenants and Azure CLI / Service Principal support for CI/CD).
   - Document 1 or 50+ workspaces into one searchable, 100% offline HTML portal: **Semantic Models**, **Workspaces & Reports Mapping** (highlighting **Cross-Workspace Shared Datasets / Thin Reports** and **Orphan Models**), **Interactive Live Lineage**, and **Governance & Health Audits**.
2. **Effortless-to-Read Model Documentation**
   - **Interactive Star-Schema Diagram:** Automatically classifies **Fact** vs. **Dimension** tables with zoom, pan, fullscreen, and click-to-pin relationship highlighting (contributed by `@jakubpokusa`).
   - **Visual Power Query Pipelines:** Displays an easy-to-scan transformation step ribbon (`1. Source -> 2. Filtered Rows -> 3. Typed Columns`) above collapsible syntax-highlighted M code, recognizing 28+ enterprise connectors (SAP HANA, SAP BW, Snowflake, Databricks, Microsoft Fabric, SQL Server, SharePoint, Excel, BigQuery, and more).
   - **Auto-Formatted & Structured DAX Library:** Organizes measures by `Table -> Display Folder -> Dependency Tier` (**Base Aggregations** first, **Derived & Time-Intelligence KPIs** second), automatically pretty-printing single-line DAX formulas and linking `Reads:` / `Used by:` dependencies.
3. **Interactive 3-Panel Live Lineage Explorer**
   - Click any upstream database/view, Power Query table, column, DAX measure, or Power BI report to trace live upstream origins and downstream impact with smooth SVG connectors.
4. **Built-In Model Context Protocol (MCP) Server for AI Assistants**
   - Connect **VS Code GitHub Copilot**, **Claude Desktop**, **Cursor**, or **Antigravity** directly to your local catalog to run instant cross-workspace impact analysis (`"Which reports break if view CV_SD_DELIVERY_OTIF changes?"`) with automatic secret masking.
5. **100% Pure Python Core (Zero Unsigned `.exe` False Positives)**
   - Core workspace scanning, TMDL parsing, HTML portal generation, and MCP server use **zero third-party runtime packages** (Python standard library only), eliminating Windows SmartScreen and Microsoft Defender `.exe` false positives.

---

## Quick Start (2 Ways to Install & Run)

**Prerequisite:** [Python 3.10+](https://www.python.org/downloads/) (available in 1 click from the Microsoft Store on Windows, or pre-installed on macOS/Linux).

### Option A: Download ZIP & Double-Click (No Terminal Needed - Windows)

1. Click **Code -> Download ZIP** (or download the `v1.0.0` Release ZIP) and extract the folder anywhere on your PC.
2. *(Optional)* If you also want to parse local binary **`.pbix` / `.xlsx`** files or use **Power BI Web Window** sign-in on locked-down corporate tenants, double-click **`Install_Optional_Extras.cmd`** once. *(Core Power BI Service scanning, `.pbip` / TMDL folders, Live Lineage, and MCP require zero extra packages.)*
3. Double-click **`Start_Studio.cmd`** -> your browser opens **`http://127.0.0.1:8765`**.

### Option B: Install via `pip` (CLI & Cross-Platform)

```bash
# Core Studio, Power BI Service Scanner, TMDL (.pbip), Live Lineage & MCP Server (Zero external dependencies!)
pip install "git+https://github.com/djrien-ai/pbi-doc-generator.git"

# Full edition: adds local binary .pbix & Excel PowerPivot (.xlsx) extraction + corporate Web Window fallback
pip install "pbi-doc-generator[all] @ git+https://github.com/djrien-ai/pbi-doc-generator.git"
```

Then launch the local Web Studio from anywhere:

```bash
pbi-doc-generator
```

Your browser opens **`http://127.0.0.1:8765`** where you can switch seamlessly between **`1. Scanner & Setup`** and **`2. Documentation Portal`**:
- **Mode 1 - Power BI Service:** Click **Sign in with Microsoft** (or **Sign in via Power BI Web Window** on restricted corporate tenants), select your workspaces, pick a preset (*Documentation & Lineage*, *Full Governance Audit*, or *Anonymized / External Share*), and build your portal.
- **Mode 2 - Local File or Project:** Click **Browse File...** or **Browse Folder...** to import any local `.pbip` / `.SemanticModel` folder, `.pbix` file, or `.xlsx` workbook into the same unified portal.
- **Mode 3 - AI Assistant (MCP):** Copy the ready-made JSON snippet for Copilot, Claude Desktop, Cursor, or Antigravity.

---

## Command-Line Usage (CLI & CI/CD)

```bash
# Scan specific workspaces incrementally and generate the offline HTML portal
pbi-doc-generator scan --workspace "Supply Chain"

# Generate an anonymized portal safe for external sharing (hides user/owner names)
pbi-doc-generator portal --anonymous

# Import a local Git-backed Power BI Project (.pbip / .SemanticModel) into the catalog
pbi-doc-generator import-local ./SalesModel.SemanticModel

# Document a single standalone .pbix or .xlsx file
pbi-doc-generator file ./Report.pbix

# Start the stdio MCP server for AI assistants
pbi-doc-generator mcp
```

---

## Security & Privacy by Design

- **100% Local Execution:** Metadata, TMDL definitions, and generated HTML files stay on your machine. Zero telemetry or external CDN calls.
- **Enforced Read-Only API Guard:** `PowerBiReadOnlyClient` blocks `DELETE`, `PATCH`, `PUT`, and mutating `POST` requests in code, allowing only `GET` metadata calls and the read-only Fabric `getDefinition` endpoint.
- **In-Memory Tokens Only:** OAuth access tokens live strictly in Python RAM for the active session and are never written to disk.
- **Automatic Secret Redaction:** Connection passwords, SAS tokens, API keys, and bearer tokens are automatically masked in both HTML pages and MCP responses.

---

## Community & Support

Special thanks to community contributors `@jakubpokusa` (interactive Mermaid relationship viewer), `@okiyuki99` (Xpress9 `pbixray` support), and `@nblankes` (TMDL table doc-comment bug report).

If `pbi-doc-generator` saves your BI team hours of manual documentation or impact analysis, consider starring the repository or supporting ongoing open-source development via **GitHub Sponsors** on this repository.

## License

MIT License - Copyright (c) Rien Scheerlinck.
