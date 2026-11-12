# Roadmap

## Delivered in v1.0.0

- **Multi-Workspace Power BI Service Scanner:** Incremental TMDL extraction, workspace capacity inventory, and cross-workspace thin-report mapping.
- **Interactive 3-Panel Live Lineage Explorer:** Upstream source -> table -> column -> DAX measure -> downstream report impact tracing.
- **Unified Local + Service Studio (`http://127.0.0.1:8765`):** Single web workflow supporting Power BI Service, `.pbix`, `.pbip` / `.SemanticModel`, and Excel PowerPivot `.xlsx`.
- **Structured DAX & Visual Power Query Catalog:** Auto-formatted DAX formulas, Compact Table & Formatted Cards views, and step-by-step M pipelines.
- **Interactive Star-Schema Mermaid Viewer:** Zoom, pan, fullscreen, and relationship highlighting.
- **Built-in MCP Server:** Instant AI impact analysis in VS Code Copilot, Claude Desktop, Cursor, and Antigravity.
- **Zero-Install Windows Portable ZIP:** Automated cloud builds via GitHub Actions.

---

## Planned Next Milestones (v1.1+)

1. **Report Page & Visual-to-Measure Lineage in Multi-Workspace Portal:** Extend PBIR / `report.json` visual bindings directly into the 3-panel Live Lineage Explorer (`Source -> Table -> Measure -> Report Page -> Visual`).
2. **Markdown & Confluence / Wiki Export:** Optional clean Markdown catalog export alongside the interactive HTML portal for Git wikis and Azure DevOps / GitHub Pages.
3. **PyPI Package Publication:** Publish `pbi-doc-generator` directly to PyPI.org for `pip install pbi-doc-generator` and `uvx pbi-doc-generator`.
4. **Fabric Lakehouse & Warehouse Shortcut Lineage:** Parse Microsoft Fabric OneLake shortcuts and Dataflow Gen2 upstream dependencies.

---

Have a feature request? [Open an issue](https://github.com/djrien-ai/pbi-doc-generator/issues/new/choose).
