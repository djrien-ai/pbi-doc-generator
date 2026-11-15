# Power BI Documentation & Live Lineage Studio (`pbi-doc-generator` v1.1 Preview)

[![CI](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml/badge.svg?branch=v1.1)](https://github.com/djrien-ai/pbi-doc-generator/actions/workflows/ci.yml)
[![Live Demo Portal](https://img.shields.io/badge/Live_Demo-Stable_v1.0_Portal-0b63ce?logo=github)](https://djrien-ai.github.io/pbi-doc-generator/)
[![Download Windows ZIP](https://img.shields.io/badge/Windows_Download-Stable_v1.0_Portable_.zip-15803d?logo=windows)](https://github.com/djrien-ai/pbi-doc-generator/releases/latest/download/PBI_Doc_Generator_Windows_Portable.zip)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](https://www.python.org/)
[![100% Local & Read-Only](https://img.shields.io/badge/Privacy-100%25_Local_%26_Read--Only-0f766e.svg)](SECURITY.md)
[![Support on Ko-fi](https://img.shields.io/badge/Support_on_Ko--fi-Buy_me_a_coffee-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/rienscheerlinck)

> [!TIP]
> **You are viewing the `v1.1` Public Preview branch**
> - **Stable Release (`v1.0.0`):** Remains the default on [`main`](https://github.com/djrien-ai/pbi-doc-generator/tree/main) and in the [latest Windows Portable `.zip`](https://github.com/djrien-ai/pbi-doc-generator/releases/latest).
> - **What is new in `v1.1`:** Multi-layer **Dataflow Gen1** & **Fabric Dataflow Gen2** (`OneLake` / `Direct Lake`), **Slide-Over Report X-Ray Inspector** (16:9 SVG page wireframes, thin-report DAX, and broken visual bindings), **End-to-End Visual-to-SQL Lineage**, **Unified Export & 1-Click SharePoint Online Publishing** (entire catalog or per semantic model), **10 MCP tools**, and parallel enterprise scanning.
> - **Test `v1.1` right now & share feedback in [PR #19](https://github.com/djrien-ai/pbi-doc-generator/pull/19):**
>   - **Via `pip`:** `pip install --upgrade "git+https://github.com/djrien-ai/pbi-doc-generator.git@v1.1"`
>   - **Via Git / Source ZIP on Windows:** `git clone -b v1.1 https://github.com/djrien-ai/pbi-doc-generator.git` and double-click **`Start_Studio.cmd`** *(or open `docs/index.html` directly in your browser to explore the generated `v1.1` demo portal offline)*.

Turn **Power BI Service / Microsoft Fabric Workspaces** and local **`.pbix` / `.pbip` / `.xlsx`** files into clean, searchable HTML documentation with **interactive Star-Schema diagrams**, **SQLBI-formatted DAX catalogs**, **Dataflow Gen1 & Gen2 + Native SQL pipelines**, **Slide-Over Report X-Ray wireframes**, **end-to-end Visual-to-SQL Live Lineage**, and a **built-in local Model Context Protocol (MCP) server** for AI assistants.

👉 [**Explore the Live Interactive v1.0 Stable Demo Portal**](https://djrien-ai.github.io/pbi-doc-generator/) *(for the `v1.1` preview demo, clone/download branch `v1.1` and open `docs/index.html` locally)*

---

## Quick Start

### Option 1: Test `v1.1` Preview (Python 3.10+ on Windows, macOS & Linux)

```bash
pip install --upgrade "git+https://github.com/djrien-ai/pbi-doc-generator.git@v1.1"
```

Launch the local Web Studio from anywhere:

```bash
pbi-doc-generator
```

*(On Windows with Python installed, you can also download or `git clone -b v1.1` this branch and double-click **`Start_Studio.cmd`** - it installs `requirements.txt` automatically on first launch.)*

### Option 2: Stable `v1.0.0` Portable Windows Download (No Python Required)

*(Note: Official `v1.1` zero-install Portable `.zip` binaries will be published to Releases once community preview testing concludes. Until then, the link below serves the stable `v1.0.0` executable.)*

1. [**Download `PBI_Doc_Generator_Windows_Portable.zip` (Stable v1.0.0)**](https://github.com/djrien-ai/pbi-doc-generator/releases/latest/download/PBI_Doc_Generator_Windows_Portable.zip) *(or view the [Release page](https://github.com/djrien-ai/pbi-doc-generator/releases/latest))*.
2. Right-click the downloaded ZIP file and choose **Extract All...**
3. Open the extracted folder and double-click **`PBI_Doc_Generator.exe`** -> your browser opens **`http://127.0.0.1:8765`** automatically.
   *(If Windows SmartScreen asks for confirmation on first launch: click **More info** -> **Run anyway**.)*

> [!IMPORTANT]
> **Power BI Service Workspace Role Prerequisite (`Contributor` or higher)**
> To extract full semantic model, dataflow, and PBIR report definitions from Power BI Service workspaces, your Microsoft account must have at least the **Contributor** role (**Contributor**, **Member**, or **Admin**) in each workspace you want to document.
> - Workspaces where you only have the **Viewer** role will list basic workspace and report inventory, because Microsoft's Fabric `getDefinition` API blocks `Viewer`-only accounts (`HTTP 403`).
> - Documenting local `.pbix`, `.pbip`, and `.xlsx` files works 100% offline and requires no Power BI Service permissions.

---

## What Is Inside v1.1

1. **Power BI Service & Microsoft Fabric Multi-Workspace Scanner (Zero Azure Admin Setup)**
   - Sign in with your normal Microsoft account (`Sign in with Microsoft` OAuth 2.0 PKCE in your default browser, plus a fallback `Power BI Web Window` mode for locked-down corporate tenants, Azure CLI, and Service Principal support for CI/CD).
   - Parallel extraction across 1 to 50+ workspaces (`--follow-outside` optionally resolves upstream shared models and chained dataflows in external workspaces).
2. **Multi-Layer Dataflow Gen1, Fabric Dataflow Gen2 & Direct Lake Lineage**
   - Extracts **Power BI Dataflow Gen1** (`model.json`, `L1` / `L2+` chained dataflows, `ReferenceEntity` linked entities) and **Fabric Dataflow Gen2** (`mashup.pq` + Lakehouse / Warehouse OneLake destinations) alongside **Direct Lake** OneLake entity bindings.
   - Pretty-prints embedded **Native SQL** (`Value.NativeQuery` / `[Query=...]`) and interprets Power Query M steps into clickable plain-English transformation ribbons.
3. **Slide-Over Report X-Ray Inspector & Broken Visual Detection**
   - Inspects cloud thin reports (`PBIR` and legacy `report.json`) without leaving your place in the catalog: interactive **16:9 SVG page wireframes** with visual type schematics, field & filter bindings, report-local DAX measures traced through shared models, and automatic flagging of **broken visual field references**.
4. **Effortless Model Documentation & End-to-End Measure Lineage**
   - **Zero-Dependency Interactive Star-Schema Explorer:** Focused Star tabs per Fact table, zoom, pan, fullscreen, and click-to-pin relationship highlighting.
   - **SQLBI-Formatted DAX Catalog & End-to-End Trace:** Pretty-printed DAX grouped by `Table -> Display Folder -> Dependency Tier`, plus full trace from report visual -> DAX -> model column -> Power Query M -> Dataflow -> source SQL table (`measure-doc`).
5. **Unified Export & 1-Click SharePoint Online Publishing**
   - Export **either the entire catalog or a single semantic model**: A4 PDF / Print, self-contained standalone HTML, offline `.zip` bundle, Data Dictionary (`Markdown` / `CSV` / `Word`), compressed `srcdoc`-safe SharePoint HTML (`export-site`), or **direct 1-click upload to a SharePoint Online Document Library URL**.
6. **Built-In Local Model Context Protocol (MCP) Server (10 Read-Only Tools)**
   - Connects **VS Code GitHub Copilot**, **Claude Desktop**, **Cursor**, or **Antigravity** to your local catalog (`pbi_list_models`, `pbi_search_catalog`, `pbi_model_summary`, `pbi_get_dax_measure`, `pbi_trace_lineage`, `pbi_trace_measure_end_to_end`, `pbi_report_layout`, `pbi_governance_health`, `pbi_compare_models`, `pbi_workspace_report_map`) with automatic secret redaction.

---

## Command-Line Usage (CLI & CI/CD)

```bash
# Launch the interactive Web Studio (default)
pbi-doc-generator

# Scan specific workspaces (add --follow-outside to resolve cross-workspace upstream dataflows/models)
pbi-doc-generator scan --workspace "Supply Chain" --follow-outside

# Generate an anonymized portal safe for external sharing (hides personal/owner names)
pbi-doc-generator portal --anonymous

# Export a single self-contained HTML file (safe for SharePoint Online / Teams / email)
pbi-doc-generator export-site --out ./PBI_Catalog_SharePoint.html

# Generate a deep end-to-end Markdown lineage doc for a specific DAX measure
pbi-doc-generator measure-doc "Global Supply Chain & OTIF Core" "OTIF %" --out ./OTIF_Lineage.md

# Import a local .pbip, .SemanticModel, .pbix, or .xlsx into the multi-model catalog
pbi-doc-generator import-local ./SalesModel.pbip

# Start the stdio MCP server (10 read-only tools) for AI assistants
pbi-doc-generator mcp
```

---

## Security & Privacy by Design

- **100% Local Execution:** Metadata, TMDL definitions, and generated HTML files stay on your machine (`127.0.0.1`). Zero telemetry or external CDN calls.
- **Enforced Read-Only Power BI API Guard:** `PowerBiReadOnlyClient` blocks `DELETE`, `PATCH`, `PUT`, and mutating `POST` requests in code, allowing only `GET` metadata calls and the read-only Fabric `getDefinition` endpoint.
- **In-Memory Tokens Only:** OAuth access tokens live strictly in Python RAM for the active session and are never written to disk.
- **Automatic Secret Redaction:** Connection passwords, SAS tokens, API keys, bearer tokens, and internal dataflow storage URLs are automatically masked/stripped in HTML pages and MCP responses. See [SECURITY.md](SECURITY.md) for details.

---

## Enterprise Integrations & Architecture Audits

The core of `pbi-doc-generator` is and remains 100% free and open-source under the MIT License. Organizations looking for custom enterprise integrations (automated CI/CD lineage publishing to SharePoint, Confluence, or Microsoft Purview, historical semantic-model drift monitoring, or white-label governance portals) or an independent **Power BI Estate & Semantic Model Architecture Audit** can connect with **Rien Scheerlinck** ([LinkedIn](https://www.linkedin.com/in/rienscheerlinck/) | **Bohan VOF**):

[![Connect on LinkedIn](https://img.shields.io/badge/LinkedIn-Rien_Scheerlinck-0A66C2?logo=linkedin&logoColor=white)](https://www.linkedin.com/in/rienscheerlinck/)
[![Inquire via Email - Bohan VOF](https://img.shields.io/badge/Enterprise_&_Advisory_Inquiries-Email_Bohan_VOF-0b63ce?logo=gmail&logoColor=white)](mailto:dj.rien@gmail.com?subject=Power%20BI%20Enterprise%20%26%20Architecture%20Inquiry)

---

## Community & Support

Special thanks to community contributors `@andreasfelder` (multi-layer Dataflow Gen1 lineage, cloud PBIR/report layout extraction, Native SQL & M step interpreter, end-to-end measure lineage, parallel scanning, and single-file SharePoint export in PR #19), `@jakubpokusa` (interactive relationship viewer in PR #10), `@okiyuki99` (Xpress9 `pbixray` support in PR #11), and `@nblankes` (TMDL table doc-comment report in Issue #12).

If `pbi-doc-generator` saves your BI team hours of manual documentation or impact analysis, consider starring the repository or [**supporting ongoing open-source development on Ko-fi**](https://ko-fi.com/rienscheerlinck).

## License

MIT License - Copyright (c) 2024-2026 Rien Scheerlinck. See [LICENSE](LICENSE) for full text.
