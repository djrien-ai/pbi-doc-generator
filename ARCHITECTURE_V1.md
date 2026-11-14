# PBI Doc Generator v1.0 - Technical Architecture

## 1. Product Vision
**PBI Doc Generator v1.0** transforms Power BI documentation from a single-file `.pbix` utility into a **Zero-Admin Workspace Documentation Portal & Local MCP Server**:

- **No `.pbix` downloads required:** Reads semantic models (including DirectQuery, thin reports, cross-workspace models, paginated reports, and dataflows) directly via the official Power BI REST API and Microsoft Fabric `getDefinition?format=TMDL` API.
- **No Tenant Admin or Entra App Registration required:** Works immediately inside locked-down corporate tenants using the user's own read-only Power BI session token in memory (with optional Azure CLI and Service Principal modes).
- **100% Pure Python Core (Defender-Safe):** No unsigned PyInstaller `.exe` bootloaders or mandatory compiled C-extensions. Runs cleanly on Python 3.10+ across Windows, macOS, and Linux without triggering SmartScreen or EDR false positives.
- **Built-in Local MCP Server:** Exposes your scanned Power BI estate safely (with automatic secret redaction) to VS Code GitHub Copilot, Claude Desktop, Cursor, and Antigravity via standard JSON-RPC 2.0 over `stdio`.
- **Offline File Mode Preserved:** Continues to support local `.pbip` / `.SemanticModel` directories, `.xlsx` Power Query files, and optional `.pbix` archives (`pip install pbi-doc-generator[pbix]`).

---

## 2. Package Architecture (`pbi_catalog/`)

```text
pbi-doc-generator/
├── pbi_catalog/
│   ├── __init__.py          # Version & public API
│   ├── security.py          # Secret redaction (API keys, tokens, passwords) & anonymization helpers
│   ├── auth.py              # In-memory token provider (Browser SSO, Paste/Env Token, Azure CLI, Service Principal)
│   ├── api.py               # Read-only Power BI & Fabric LRO client (urllib + corporate proxy curl fallback)
│   ├── store.py             # Incremental, resumable local JSON + TMDL state manager, workspace scope (scoped_state)
│   ├── scanner.py           # Workspace, Report, Semantic Model, Access, Refresh & Dataflow orchestrator
│   ├── analyzer.py          # Lossless TMDL parser, 28+ M source detectors, DAX AST lineage & Health Audit rules
│   ├── dataflows.py         # Dataflow Gen1 model.json / M section parser, dataflow reference & source resolver
│   ├── mparse.py            # Power Query M tokenizer helpers: let steps, call arguments, native SQL extraction
│   ├── sql_format.py        # Readable formatting of native SQL found in Power Query
│   ├── pq_steps.py          # Power Query step interpreter (plain-language step summaries for the step browser)
│   ├── reports.py           # Report definitions: report-level measures + page / visual layout (no data)
│   ├── e2e_lineage.py       # Cross-model + cross-dataflow + thin-report lineage graph, trace & measure documentation
│   ├── e2e_explorer.py      # End-to-End Lineage explorer (portal tab 7) with filters, step browser & exports
│   ├── report_explorer.py   # Report Explorer (portal tab 3): page wireframes, visual fields, click-through lineage
│   ├── portal_xref.py       # Model <-> dataflow <-> thin-report cross references used by all portal pages
│   ├── portal_export.py     # Context-aware documentation exports, "Export all data", embedded explorer tab
│   ├── portal.py            # Searchable multi-workspace index.html + rich per-model HTML with Mermaid diagrams
│   ├── site_export.py       # "Export all data": static portal .zip for file shares / web servers
│   ├── sharepoint_single.py # Single-file portal that runs inside SharePoint Online's sandboxed file viewer
│   ├── trace.py             # Optional diagnostics trace (API calls, Studio log, browser errors) - PBI_TRACE_DIR
│   ├── diagnose.py          # `diagnose` report: metadata-only verification, errors, lineage health
│   ├── mcp_server.py        # Pure-Python MCP server (stdio JSON-RPC 2.0) with 10 Power BI intelligence tools
│   ├── web_ui.py            # Modern localhost Web Studio (replaces legacy Tkinter + PyInstaller .exe)
│   └── cli.py               # Unified CLI entrypoint (`pbi-doc-generator`)
├── extract.py               # Offline single-file extractor (.pbip, .pbix, .xlsx)
├── tmdl_parser.py           # Local PBIP folder parser
├── dax_parser.py            # DAX lexer & AST dependency analyzer
├── html_template.py         # Offline single-file HTML renderer
├── mermaid_js.py            # Bundled offline Mermaid.js runtime
└── tests/
    ├── test_v1_suite.py           # End-to-end automated verification suite
    ├── test_dataflow_lineage.py   # Dataflows, end-to-end lineage, thin reports, workspace scope, exports
    ├── test_report_layout.py      # Report layouts (PBIR + legacy), Report Explorer assets, MCP report tool
    ├── test_sql_steps.py          # Native SQL extraction / formatting and the Power Query step interpreter
    └── test_trace_diagnostics.py  # Diagnostics trace, metadata-only check, concurrent catalog writes
```

---

## 3. Security & Privacy Guarantees
1. **Read-Only API Contract:** Only `GET` requests and the Fabric `POST .../getDefinition` metadata reads (semantic models as TMDL, reports as PBIR / `report.json`) are executed. Nothing in Power BI or Fabric is ever modified, and no DAX or SQL query is ever run - the catalog holds structure (DAX, Power Query, relationships, dataflow definitions, report layouts), never table rows or measure results. `pbi-doc-generator diagnose` verifies this against a recorded trace.
2. **Ephemeral In-Memory Tokens:** Access tokens live strictly in process memory (`RAM`), are passed to `curl` via `stdin` (`-H @-`) rather than command-line arguments when proxy fallback is active, and are never written to disk.
3. **Automatic Secret Redaction:** Every HTML page, search index, and MCP tool response passes through `mask_secrets()`, scrubbing API keys, bearer tokens, SAS signatures, and passwords embedded in Power Query M expressions or URLs.
4. **One-Flag Anonymization (`--anonymous`):** Replaces all user names and email addresses in ownership and permission views with generic principal roles for safe sharing and demos.
