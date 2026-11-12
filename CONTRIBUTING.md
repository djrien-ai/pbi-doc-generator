# Contributing to PBI Doc Generator

Thank you for your interest in contributing! Bug reports, connector improvements, UI polish, and pull requests are all welcome.

## Ways to Contribute

### Report a Bug
- [Open a bug report](https://github.com/djrien-ai/pbi-doc-generator/issues/new/choose) with steps to reproduce.
- Mention whether the issue occurred with Power BI Service scanning, `.pbip` / TMDL folders, `.pbix`, or `.xlsx` files.

### Suggest an Enhancement
- Check [ROADMAP.md](ROADMAP.md) to see planned capabilities.
- Open a feature request issue describing your use case.

### Submit a Pull Request

1. Fork this repository and create a feature branch:
   ```bash
   git checkout -b feat/my-improvement
   ```
2. Install in editable development mode:
   ```bash
   python -m venv .venv
   # Windows: .venv\Scripts\activate | macOS/Linux: source .venv/bin/activate
   pip install -e .
   ```
3. Run the automated test suite before opening your PR:
   ```bash
   python tests/test_v1_suite.py
   ```
4. Launch the local Studio to verify UI changes:
   ```bash
   pbi-doc-generator
   ```

## Project Architecture

- `pbi_catalog/auth.py` - Zero-admin in-memory OAuth2 PKCE, Edge/Chrome Web Window, Azure CLI, and Service Principal auth.
- `pbi_catalog/api.py` - Enforced read-only Power BI & Fabric REST client.
- `pbi_catalog/scanner.py` - Incremental multi-workspace inventory, TMDL extraction, and local `.pbix`/`.pbip`/`.xlsx` importer.
- `pbi_catalog/analyzer.py` - TMDL parser, 28+ source connector recognizer, Power Query step parser, DAX dependency analyzer, and governance checks.
- `pbi_catalog/portal.py` - Offline HTML catalog, Grid/List/Workspace views, Star-Schema viewer, DAX/M catalog, and 3-panel Live Lineage Explorer.
- `pbi_catalog/mcp_server.py` - Zero-dependency JSON-RPC stdio Model Context Protocol (MCP) server.
- `pbi_catalog/web_ui.py` - Localhost Web Studio (`http://127.0.0.1:8765`).
- `extract.py` / `pbip_adapter.py` / `tmdl_parser.py` / `excel_extractor.py` - Standalone single-file `.pbix`, `.pbip`, and `.xlsx` extraction engine.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
