# Roadmap

## Delivered in v1.0.0

- **Multi-Workspace Power BI Service Scanner:** Incremental TMDL extraction, workspace capacity inventory, and cross-workspace thin-report mapping.
- **Interactive 3-Panel Live Lineage Explorer:** Upstream source -> table -> column -> DAX measure -> downstream report impact tracing.
- **Unified Local + Service Studio (`http://127.0.0.1:8765`):** Single web workflow supporting Power BI Service, `.pbix`, `.pbip` / `.SemanticModel`, and Excel PowerPivot `.xlsx`.
- **Structured DAX & Visual Power Query Catalog:** Auto-formatted DAX formulas, Compact Table & Formatted Cards views, and step-by-step M pipelines.
- **Interactive Star-Schema Mermaid Viewer:** Zoom, pan, fullscreen, and relationship highlighting.
- **Built-in MCP Server:** Instant AI impact analysis in VS Code Copilot, Claude Desktop, Cursor, and Antigravity.
- **Zero-Install Windows Portable ZIP:** Automated cloud builds via GitHub Actions.

## Delivered in v1.1 (Unreleased)

- **Dataflow Gen1 lineage:** Dataflow definitions, multi-layer dataflow -> dataflow chains, dataset table -> dataflow entity links, native SQL and source extraction, Dataflows tab.
- **End-to-End Measure Lineage:** Measure -> referenced measures -> tables -> dataset Power Query -> every dataflow layer -> SQL / Excel / file sources, with a step-by-step Power Query interpreter and measure documentation export.
- **Thin-report measures:** Report-level measures traced through shared models into dataflows and sources.
- **Report page & visual lineage (Report Explorer):** Report pages drawn from the report definition (no data); click a visual, then a field, filter or slicer for its full lineage.
- **Workspace-scoped scans, governance findings for broken references, context-aware documentation exports, single-file SharePoint export, diagnostics trace.**

---

## Planned Next Milestones (v1.1+)

1. **Report visuals in the Live Lineage Explorer:** Add report pages / visuals as a downstream layer of the 3-panel Live Lineage Explorer (the Report Explorer already provides the visual -> field -> source direction).
2. **Markdown & Confluence / Wiki Export:** Optional clean Markdown catalog export alongside the interactive HTML portal for Git wikis and Azure DevOps / GitHub Pages.
3. **PyPI Package Publication:** Publish `pbi-doc-generator` directly to PyPI.org for `pip install pbi-doc-generator` and `uvx pbi-doc-generator`.
4. **Fabric Lakehouse & Warehouse Shortcut Lineage:** Parse Microsoft Fabric OneLake shortcuts and Dataflow Gen2 upstream dependencies (Gen1 is delivered).

---

Have a feature request? [Open an issue](https://github.com/djrien-ai/pbi-doc-generator/issues/new/choose).
