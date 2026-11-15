# Roadmap

## In Public Preview (`v1.1` branch)

- **Multi-Layer Dataflow Gen1 & Fabric Dataflow Gen2 Lineage:** Chained `L1` / `L2+` Dataflows, Native SQL formatting, Power Query step explanations, OneLake Lakehouse/Warehouse destinations, and Direct Lake entity binding.
- **Slide-Over Report X-Ray Inspector:** Cloud `PBIR` and `report.json` extraction, interactive 16:9 SVG page wireframes, thin-report local DAX measures, and broken visual field detection.
- **End-to-End Measure Lineage & 10 MCP Tools:** Full `Visual -> DAX -> Column -> Power Query -> Dataflow -> SQL` impact tracing in the Portal, CLI (`measure-doc`), and MCP server.
- **Unified Export & SharePoint Online Publishing:** Per-model or full-catalog PDF, standalone HTML, `.zip`, Word/Markdown/CSV Data Dictionary, compressed single-file SharePoint HTML, and 1-click SharePoint URL upload.

---

## Delivered in v1.0.0 (`main`)

- **Multi-Workspace Power BI Service Scanner:** Incremental TMDL extraction, workspace capacity inventory, and cross-workspace thin-report mapping.
- **Interactive 3-Panel Live Lineage Explorer:** Upstream source -> table -> column -> DAX measure -> downstream report impact tracing.
- **Unified Local + Service Studio (`http://127.0.0.1:8765`):** Single web workflow supporting Power BI Service, `.pbix`, `.pbip` / `.SemanticModel`, and Excel PowerPivot `.xlsx`.
- **Structured DAX & Visual Power Query Catalog:** Auto-formatted DAX formulas, Compact Table & Formatted Cards views, and step-by-step M pipelines.
- **Built-in MCP Server & Zero-Install Windows Portable ZIP:** Automated cloud builds via GitHub Actions.

---

## Planned Next Milestones (v1.2+)

1. **Historical Semantic Model Drift & Diff Snapshots:** Track added, removed, or modified DAX measures, columns, and relationships between catalog scans.
2. **PyPI Package Publication (`pip install pbi-doc-generator`):** Publish official wheels directly to PyPI.org once `v1.1` graduates from preview to `main`.
3. **Fabric Notebook & Pipeline Upstream Lineage:** Extend OneLake lineage to Fabric Data Pipelines and Spark Notebooks feeding Lakehouses/Warehouses.
4. **Confluence & Microsoft Purview Connectors:** Optional automated governance catalog sync for CI/CD pipelines.

---

Have a feature request? [Open an issue](https://github.com/djrien-ai/pbi-doc-generator/issues/new/choose).
