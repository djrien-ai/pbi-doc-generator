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
│   ├── store.py             # Incremental, resumable local JSON + TMDL state manager
│   ├── scanner.py           # Workspace, Report, Semantic Model, Access, Refresh & Dataflow orchestrator
│   ├── analyzer.py          # Lossless TMDL parser, 28+ M source detectors, DAX AST lineage & Health Audit rules
│   ├── portal.py            # Searchable multi-workspace index.html + rich per-model HTML with Mermaid diagrams
│   ├── mcp_server.py        # Pure-Python MCP server (stdio JSON-RPC 2.0) with 8 Power BI intelligence tools
│   ├── web_ui.py            # Modern localhost Web Studio (replaces legacy Tkinter + PyInstaller .exe)
│   └── cli.py               # Unified CLI entrypoint (`pbi-doc-generator`)
├── extract.py               # Offline single-file extractor (.pbip, .pbix, .xlsx)
├── tmdl_parser.py           # Local PBIP folder parser
├── dax_parser.py            # DAX lexer & AST dependency analyzer
├── html_template.py         # Offline single-file HTML renderer
├── mermaid_js.py            # Bundled offline Mermaid.js runtime
└── tests/
    └── test_v1_suite.py     # End-to-end automated verification suite
```

---

## 3. Security & Privacy Guarantees
1. **Read-Only API Contract:** Only `GET` requests and Fabric `POST .../getDefinition?format=TMDL` metadata reads are executed. Nothing in Power BI or Fabric is ever modified.
2. **Ephemeral In-Memory Tokens:** Access tokens live strictly in process memory (`RAM`), are passed to `curl` via `stdin` (`-H @-`) rather than command-line arguments when proxy fallback is active, and are never written to disk.
3. **Automatic Secret Redaction:** Every HTML page, search index, and MCP tool response passes through `mask_secrets()`, scrubbing API keys, bearer tokens, SAS signatures, and passwords embedded in Power Query M expressions or URLs.
4. **One-Flag Anonymization (`--anonymous`):** Replaces all user names and email addresses in ownership and permission views with generic principal roles for safe sharing and demos.
