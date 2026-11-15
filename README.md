# Power BI Documentation, Report X-Ray & Live Lineage Studio (`pbi-doc-generator` v1.1)

[![CI](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml/badge.svg?branch=v1.1)](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![100% Local & Read-Only](https://img.shields.io/badge/Privacy-100%25_Local_%26_Read--Only-0f766e.svg)](SECURITY.md)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-Rien_Scheerlinck-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/rienscheerlinck/)
[![Support on Ko-fi](https://img.shields.io/badge/Support_on_Ko--fi-Buy_me_a_coffee-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/rienscheerlinck)

> [!IMPORTANT]
> **`v1.1.0-rc.1` Public Preview (Early Access)**
> You are viewing the active **`v1.1` preview branch**, open for early testing ahead of next week's official `v1.1.0` release.
> - **Windows Portable (No Python required):** [**Download `PBI_Doc_Generator_Windows_Portable.zip` (`v1.1.0-rc.1`)**](https://github.com/djrien-ai/pbi-doc-generator/releases/download/v1.1.0-rc.1/PBI_Doc_Generator_Windows_Portable.zip) -> Extract All -> run `PBI_Doc_Generator.exe`
> - **Via `pip`:** `pip install --upgrade "git+https://github.com/djrien-ai/pbi-doc-generator.git@v1.1"` -> run `pbi-doc-generator`
> - **Share feedback & get credited in `v1.1.0`:** Drop a quick test note in [**Early Access Hub (#20)**](https://github.com/djrien-ai/pbi-doc-generator/issues/20).
> - **Looking for the current stable release (`v1.0.0`)?** Switch to [`main`](https://github.com/djrien-ai/pbi-doc-generator/tree/main) or [Latest Stable Release](https://github.com/djrien-ai/pbi-doc-generator/releases/latest).

Turn **Power BI Service / Microsoft Fabric Workspaces** and local **`.pbix` / `.pbip` / `.xlsx`** files into an interactive, searchable architecture portal. Trace any number on a report page from **Visual -> Report-Level DAX -> Semantic Model -> Power Query & Native SQL -> Dataflow Gen1 / Fabric Gen2 -> OneLake / Source Database**, 100% locally and read-only.

---

## Why BI & Fabric Teams Upgrade to `v1.1`

Most Power BI documentation tools stop at a single `.pbix` file, while Power BI's native Workspace Lineage View stops at the container boundary (`Dataflow -> Semantic Model -> Report`) without showing *which* SQL query, Dataflow entity, column, or DAX measure drives *which* visual.

`pbi-doc-generator v1.1` connects the entire estate inside a calm, zero-clutter **4-tab portal**:

1. **Slide-Over Report & Dataflow X-Ray Inspector (No Tab Sprawl)**
   - Click any Power BI report (`PBIR` or legacy `report.json`) to open a slide-over X-Ray drawer without losing your place in the catalog.
   - Renders **16:9 SVG page wireframes** with chart-type schematics, visual group containers, bound measures/columns, report/page/visual filters, slicer selections, **thin-report local DAX measures** (`reportExtensions.json`), and a **1-click Broken Visual Binding Stepper** that highlights visuals pointing to renamed or deleted fields.
2. **Deep Dataflow Gen1, Fabric Dataflow Gen2 & Direct Lake Lineage**
   - Follows multi-layer **Dataflow Gen1** chains (`L1` / `L2+` linked `ReferenceEntity` tables across workspaces) and **Fabric Dataflow Gen2** (`mashup.pq` + OneLake **Lakehouse** and **Warehouse** table destinations), connected directly to **Direct Lake** and Import semantic models.
   - Automatically extracts and formats embedded **Native SQL** (`Value.NativeQuery`, `Sql.Database`, `SapHana`, `Snowflake`, `Odbc.Query`) and translates Power Query M into clickable plain-English transformation steps.
3. **Zero-Dependency Star-Schema Explorer & SQLBI-Formatted DAX Catalog**
   - Native HTML+SVG **Star-Schema Explorer** with **Focused Star** tabs per Fact table, zoom, pan, fullscreen, and click-to-pin relationship highlighting.
   - Pretty-prints single-line DAX into clean **SQLBI-style formatting**, grouped by `Table -> Display Folder -> Dependency Tier`, with instant filter pills (`All`, `Used in Reports`, `Unused`) and end-to-end upstream/downstream trace links.
4. **Scoped Export & 1-Click SharePoint Online Publishing**
   - Click **Export / Publish** from the catalog or from any individual semantic model page and choose your scope (**This Semantic Model** or **Entire Catalog**):
     - **Print / Save as PDF** (clean A4 portrait executive layout)
     - **Standalone HTML** or **Offline Portal `.zip`**
     - **Data Dictionary** (`Word .doc`, `Markdown`, or `CSV`)
     - **SharePoint Online:** either upload directly in 1 click to a SharePoint Document Library URL or download a compressed `srcdoc`-safe single-file HTML portal (`export-site`).
5. **Guided 3-Step Local Web Studio (`http://127.0.0.1:8765`)**
   - **Zero Azure Admin Setup:** Sign in with your normal Microsoft work account (`Sign in with Microsoft` OAuth PKCE in your default browser, corporate `Power BI Web Window` SSO fallback, Azure CLI, or Service Principal).
   - **Safe & Fast at Scale:** Progressive `1. Connect -> 2. Choose Workspaces -> 3. Scan & Build` workflow, parallel extraction (4 models / 8 reports concurrently), optional `--follow-outside` cross-workspace resolution, and explicit `Update Catalog` vs. `Clean Slate` scan modes.
   - **100% Offline Local Mode:** Drag and drop local `.pbix`, `.pbip` / `.SemanticModel`, and Excel PowerPivot `.xlsx` files without signing in.
6. **10-Tool Local Model Context Protocol (MCP) Server for AI Assistants**
   - Connect **VS Code GitHub Copilot**, **Claude Desktop**, **Cursor**, or **Antigravity** to your local catalog (`pbi-doc-generator mcp`) for instant visual-to-SQL impact analysis, DAX explanations, report layout inspection, and governance audits with automatic secret masking.

---

## Quick Start (`v1.1.0-rc.1` Preview)

### Option 1: Portable Windows Download (No Python Required)

1. [**Download `PBI_Doc_Generator_Windows_Portable.zip` (`v1.1.0-rc.1` Pre-release)**](https://github.com/djrien-ai/pbi-doc-generator/releases/download/v1.1.0-rc.1/PBI_Doc_Generator_Windows_Portable.zip) *(or view the [v1.1.0-rc.1 Pre-release page](https://github.com/djrien-ai/pbi-doc-generator/releases/tag/v1.1.0-rc.1))*.
2. Right-click the downloaded ZIP file and choose **Extract All...**
3. Open the extracted folder and double-click **`PBI_Doc_Generator.exe`** -> your browser opens **`http://127.0.0.1:8765`** automatically.

### Option 2: Install via `pip` (Python 3.10+ on Windows, macOS & Linux)

```bash
pip install --upgrade "git+https://github.com/djrien-ai/pbi-doc-generator.git@v1.1"
pbi-doc-generator
```

*(Or on Windows with Python installed: `git clone -b v1.1 https://github.com/djrien-ai/pbi-doc-generator.git` and double-click **`Start_Studio.cmd`**.)*

> [!NOTE]
> **Power BI Service Workspace Role Prerequisite (`Contributor` or higher)**
> Extracting semantic model TMDL, Dataflow definitions, and cloud report layouts via Microsoft's read-only `getDefinition` API requires at least **Contributor** (**Contributor**, **Member**, or **Admin**) in the target workspace. `Viewer`-only workspaces still return workspace and report inventory. Local `.pbix`, `.pbip`, and `.xlsx` files require no Power BI Service permissions.

---

## Command-Line Usage (CLI & CI/CD)

```bash
# Launch the interactive Web Studio on http://127.0.0.1:8765 (default)
pbi-doc-generator

# Scan specific workspaces (add --follow-outside to resolve upstream models/dataflows in other workspaces)
pbi-doc-generator scan --workspace "Supply Chain" --follow-outside

# Generate an anonymized portal safe for external sharing (redacts owner/user names)
pbi-doc-generator portal --anonymous

# Package the entire portal into a single SharePoint-safe HTML file
pbi-doc-generator export-site --out ./PBI_Catalog_SharePoint.html

# Export a deep end-to-end SQL -> Power Query -> DAX -> Visual lineage spec for one measure
pbi-doc-generator measure-doc "Global Supply Chain & OTIF Core" "OTIF %" --out ./OTIF_Lineage.md

# Import a local .pbip, .SemanticModel, .pbix, or .xlsx into the catalog
pbi-doc-generator import-local ./SalesModel.pbip

# Start the local stdio MCP server (10 read-only tools) for AI assistants
pbi-doc-generator mcp
```

---

## Security & Privacy by Design

- **100% Local Execution:** Metadata, TMDL/PBIR definitions, and generated HTML stay on your machine (`127.0.0.1`). Zero telemetry or external CDN calls.
- **Hardcoded Read-Only Power BI API Guard:** `PowerBiReadOnlyClient` blocks `DELETE`, `PATCH`, `PUT`, and mutating `POST` calls at the transport layer, allowing only `GET` metadata endpoints and read-only `getDefinition` calls.
- **In-Memory Tokens Only:** OAuth access tokens live strictly in Python RAM for the active session and are never written to disk.
- **Automatic Secret & Storage Redaction:** Connection passwords, SAS signatures, API keys, bearer tokens, and internal Dataflow storage URLs are automatically masked or stripped. See [SECURITY.md](SECURITY.md) for details.

---

## Enterprise Integrations & Architecture Audits

The core of `pbi-doc-generator` is and remains 100% free and open-source under the MIT License. Organizations looking for custom enterprise integrations (automated CI/CD lineage publishing to SharePoint, Confluence, or Microsoft Purview, historical semantic-model drift monitoring, or white-label governance portals) or an independent **Power BI Estate & Semantic Model Architecture Audit** can connect with **Rien Scheerlinck** ([LinkedIn](https://www.linkedin.com/in/rienscheerlinck/) | **Bohan VOF**):

[![Connect on LinkedIn](https://img.shields.io/badge/LinkedIn-Rien_Scheerlinck-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/rienscheerlinck/)
[![Inquire via Email - Bohan VOF](https://img.shields.io/badge/Enterprise_&_Advisory_Inquiries-Email_Bohan_VOF-0b63ce?logo=gmail&logoColor=white)](mailto:dj.rien@gmail.com?subject=Power%20BI%20Enterprise%20%26%20Architecture%20Inquiry)

---

## Community & Support

Created and maintained by [Rien Scheerlinck](https://www.linkedin.com/in/rienscheerlinck/) (`@djrien-ai`), with thanks to community contributors `@andreasfelder` (PR #19 contributions toward #13/#14 Dataflow Gen1, thin-report parsing & single-file SharePoint export), `@jakubpokusa` (PR #10 relationship viewer), `@okiyuki99` (PR #11 Xpress9 `pbixray` support), and `@nblankes` (Issue #12 TMDL table doc-comment report).

If `pbi-doc-generator` saves your BI team hours of manual documentation or impact analysis, consider starring the repository or [**supporting ongoing open-source development on Ko-fi**](https://ko-fi.com/rienscheerlinck).

## License

MIT License - Copyright (c) 2024-2026 Rien Scheerlinck. See [LICENSE](LICENSE) for full text.
