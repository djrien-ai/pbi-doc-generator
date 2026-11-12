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

## Quick Start

### 1. Install via `pip`

```bash
# Core Studio, Power BI Service Scanner, TMDL (.pbip), Live Lineage & MCP Server (Zero external dependencies!)
pip install pbi-doc-generator

# Optional: add local binary .pbix & Excel PowerPivot (.xlsx) extraction + corporate browser fallback
pip install "pbi-doc-generator[all]"
```

### 2. Launch the Local Web Studio

```bash
pbi-doc-generator
```

Your browser opens **`http://127.0.0.1:8765`** where you can:
- **Mode 1 - Power BI Service:** Click **Sign in with Microsoft**, select your workspaces, pick a preset (*Documentation & Lineage*, *Full Governance Audit*, or *Anonymized / External Share*), and build your portal.
- **Mode 2 - Local File or Project:** Point to any local `.pbip` / `.SemanticModel` folder, `.pbix` file, or `.xlsx` workbook.
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
