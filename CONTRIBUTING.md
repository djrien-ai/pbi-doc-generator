# Contributing to PBI Doc Generator

Thank you for your interest in contributing! Bug reports, connector improvements, governance checks, UI polish, and pull requests are all welcome.

## Ways to Contribute

### Report a Bug
- [Open a bug report](https://github.com/djrien-ai/pbi-doc-generator/issues/new/choose) with steps to reproduce.
- Mention whether the issue occurred with Power BI Service / Microsoft Fabric scanning, `.pbip` / TMDL folders, `.pbix`, or `.xlsx` files.

### Suggest an Enhancement
- Check [ROADMAP.md](ROADMAP.md) and the open [`v1.2` Milestone Issues](https://github.com/djrien-ai/pbi-doc-generator/milestone/3) to see planned capabilities and vote with 👍.
- [Open a feature request](https://github.com/djrien-ai/pbi-doc-generator/issues/new/choose) describing your real-world Power BI or Fabric use case.

### Submit a Pull Request

1. Fork this repository and create a feature branch from `main` (or from the active `v1.x` release branch if noted on the issue):
   ```bash
   git checkout -b feat/my-improvement
   ```
2. Install in editable development mode:
   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
   pip install -e .
   ```
3. Run the automated 13-suite verification harness before opening your PR:
   ```bash
   python tests/test_v1_suite.py
   ```
4. Launch the local Studio to verify UI and portal changes:
   ```bash
   pbi-doc-generator
   ```

## Project Architecture (`v1.1`)

- `pbi_catalog/auth.py` - Zero-admin in-memory OAuth2 PKCE (with auto-refresh), Web SSO fallback, Azure CLI, and Service Principal auth.
- `pbi_catalog/api.py` - Enforced read-only Power BI & Fabric REST client with HTTP/1.1 keep-alive pooling.
- `pbi_catalog/scanner.py` - Parallel multi-workspace inventory, TMDL/PBIR/Dataflow extraction, 5-stage progress & ETA, and local `.pbix`/`.pbip`/`.xlsx` importer.
- `pbi_catalog/analyzer.py` - Lossless TMDL parser, Direct Lake & 28+ source connector recognizer, DAX lineage, and Broken Visual Reference audit.
- `pbi_catalog/report_parser.py` & `pbi_catalog/dataflows.py` - Cloud/local `PBIR` & `report.json` visual layout parser and multi-layer Dataflow Gen1 / Fabric Gen2 parser.
- `pbi_catalog/e2e_lineage.py`, `pbi_catalog/pq_steps.py` & `pbi_catalog/sql_format.py` - End-to-end Visual-to-SQL lineage tracer, plain-English M step translator, and Native SQL formatter.
- `pbi_catalog/portal.py` & `pbi_catalog/portal_widgets.py` - Zero-CDN 4-tab HTML catalog, SVG Star-Schema Explorer, Slide-Over Report/Dataflow X-Ray, and Estate Lineage Explorer.
- `pbi_catalog/export_bundle.py` & `pbi_catalog/sharepoint_publisher.py` - Scoped A4 PDF, standalone HTML, `.zip`, Word/Markdown/CSV Data Dictionary, single-file SharePoint HTML, and 1-click SharePoint upload.
- `pbi_catalog/mcp_server.py` - Zero-dependency JSON-RPC `stdio` Model Context Protocol (MCP) server (10 read-only tools).
- `pbi_catalog/web_ui.py` - Guided 3-step localhost Web Studio (`http://127.0.0.1:8765`).
- `extract.py` / `pbip_adapter.py` / `tmdl_parser.py` / `excel_extractor.py` - Standalone single-file `.pbix`, `.pbip`, and `.xlsx` extraction engine.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
