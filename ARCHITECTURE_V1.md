# PBI Doc Generator v1.1 - Technical Architecture

## 1. Product Vision
**PBI Doc Generator v1.1** is a **Zero-Admin Power BI & Microsoft Fabric Architecture Portal, Report X-Ray Inspector & Local MCP Server**:

- **No manual `.pbix` downloads required:** Reads semantic models, thin & embedded reports, Dataflows Gen1, Fabric Dataflows Gen2, Direct Lake bindings, and workspace permissions directly via the official Power BI REST API and Microsoft Fabric `getDefinition` APIs.
- **No Tenant Admin or Entra App Registration required:** Works immediately inside corporate tenants using the user's own read-only Microsoft session in memory (OAuth2 PKCE with auto-refresh, corporate SSO browser fallback, Azure CLI, or Service Principal).
- **Zero-Install Windows Portable `.zip` + Cross-Platform Python Package:** Ships both as a standalone Windows Portable `.zip` (`PyInstaller --onedir --noupx`, verified on clean Windows VMs in CI) and as a standard Python 3.10+ package (`pip`) across Windows, macOS, and Linux.
- **Built-in 10-Tool Local MCP Server:** Exposes your scanned Power BI & Fabric estate safely (with automatic secret redaction) to VS Code GitHub Copilot, Claude Desktop, Cursor, and Antigravity via standard JSON-RPC 2.0 over `stdio`.
- **100% Offline Local File Mode Included:** Supports local `.pbip` / `.SemanticModel` directories, `.pbix` archives, and Excel PowerPivot `.xlsx` files without network access.

---

## 2. Package Architecture (`pbi_catalog/`)

```text
pbi-doc-generator/
├── pbi_catalog/
│   ├── __init__.py              # Package version (1.1.0) & public API
│   ├── security.py              # Secret redaction, Dataflow storage URL stripping & anonymization
│   ├── auth.py                  # In-memory OAuth2 PKCE (with auto-refresh), Web SSO, Azure CLI & SPN auth
│   ├── api.py                   # Strict read-only Power BI & Fabric LRO client with TLS keep-alive pooling
│   ├── store.py                 # Incremental local JSON + TMDL/PBIR/Dataflow state manager & v1.0 upgrade guard
│   ├── scanner.py               # Parallel 5-stage workspace, model, report & dataflow orchestrator with ETA
│   ├── analyzer.py              # Lossless TMDL parser, Direct Lake resolver, DAX lineage & Broken Visual Audit
│   ├── report_parser.py         # Cloud/local PBIR & legacy report.json parser (visuals, wireframes, local DAX)
│   ├── dataflows.py             # Multi-layer Dataflow Gen1 (model.json) & Fabric Gen2 (mashup.pq + destinations)
│   ├── mparse.py                # Power Query M section/let AST tokenizer & identifier resolver
│   ├── pq_steps.py              # Plain-English Power Query step translator
│   ├── sql_format.py            # Embedded Native SQL extractor & formatter
│   ├── e2e_lineage.py           # End-to-end Visual -> DAX -> Table -> Dataflow/Lakehouse -> SQL tracer
│   ├── portal.py                # Zero-CDN 4-tab HTML catalog, Star-Schema Explorer & Slide-Over X-Ray UI
│   ├── portal_widgets.py        # Native SVG Star-Schema, 16:9 report wireframes & lineage widgets
│   ├── export_bundle.py         # Scoped PDF, standalone HTML, .zip, SharePoint single-file & Data Dictionary export
│   ├── sharepoint_publisher.py  # Opt-in 1-click SharePoint Online Document Library uploader
│   ├── mcp_server.py            # Pure-Python stdio JSON-RPC 2.0 MCP server (10 read-only tools)
│   ├── web_ui.py                # Guided 3-step localhost Web Studio (http://127.0.0.1:8765)
│   └── cli.py                   # Unified CLI entrypoint (`pbi-doc-generator`)
├── launcher.py                  # Studio & Portable Windows launcher entrypoint
├── extract.py                   # Standalone single-file extractor (.pbip, .pbix, .xlsx)
├── pbip_adapter.py              # Local PBIP / TMDL directory adapter
├── tmdl_parser.py               # Standalone TMDL parser
├── dax_parser.py                # DAX lexer, SQLBI-style formatter & dependency analyzer
├── excel_extractor.py           # Excel Power Query & PowerPivot DataModel extractor
├── html_template.py             # Standalone single-file HTML renderer
└── tests/
    └── test_v1_suite.py         # 13-suite automated verification harness
```

---

## 3. Security & Privacy Guarantees
1. **Read-Only Power BI & Fabric API Contract:** Only `GET` requests and read-only Fabric `POST .../getDefinition` metadata calls (`semanticModels`, `reports`, `dataflows`) are permitted. Mutating HTTP verbs against Power BI / Fabric are blocked at the transport layer.
2. **Ephemeral In-Memory Tokens:** Access tokens live strictly in process memory (`RAM`), are passed to `curl` via `stdin` (`-H @-`) rather than command-line arguments when corporate proxy fallback is active, and are never written to disk.
3. **Automatic Secret & Path Redaction:** Every HTML page, search index, and MCP tool response passes through `mask_secrets()` and `strip_data_locations()`, scrubbing API keys, bearer tokens, SAS signatures, passwords, internal storage URLs, and local filesystem paths.
4. **One-Flag Anonymization (`--anonymous`):** Replaces personal names, email addresses, and literal report filter values with generic labels for safe sharing and architecture reviews.
