# Roadmap

## Delivered in `v1.1.0` (Latest Stable - `main`)

- **10x-15x Faster Parallel Enterprise Scanner + Live ETA:** Concurrent workspace inventory, semantic model TMDL extraction, and report layout retrieval with a real-time 5-stage progress bar, percentage, ETA, and automatic `v1.0 -> v1.1` cache upgrade detection.
- **Slide-Over Report & Dataflow X-Ray Inspector ([#14](https://github.com/djrien-ai/pbi-doc-generator/issues/14)):** Cloud `PBIR` and legacy `report.json` extraction, interactive `16:9` SVG page wireframes, thin-report local DAX measures (`reportExtensions.json`), and a 1-click **Broken Visual Binding Stepper**.
- **Multi-Layer Dataflow Gen1, Fabric Dataflow Gen2 & Direct Lake Lineage ([#13](https://github.com/djrien-ai/pbi-doc-generator/issues/13)):** Chained `L1` / `L2+` Dataflow Gen1 entities across workspaces, Fabric Dataflow Gen2 (`mashup.pq` + OneLake Lakehouse/Warehouse destinations), Direct Lake `entityName` binding, Native SQL formatting, and plain-English Power Query step explanations.
- **End-to-End Measure Lineage & 10 Read-Only MCP Tools:** Full `Visual -> DAX -> Column -> Power Query -> Dataflow -> SQL` impact tracing in the Portal, CLI (`measure-doc`), and MCP server (`pbi_trace_measure_end_to_end`, `pbi_report_layout`).
- **Scoped Export & 1-Click SharePoint Online Publishing:** Per-model or full-catalog executive A4 portrait PDF (with stacked vector Star-Schema diagrams), standalone HTML, `.zip`, Word/Markdown/CSV Data Dictionary, single-file SharePoint HTML (`export-site`), and direct 1-click SharePoint Document Library upload.

---

## Delivered in `v1.0.0`

- **Multi-Workspace Power BI Service Scanner:** Incremental TMDL extraction, workspace capacity inventory, and cross-workspace thin-report mapping.
- **Interactive Live Lineage Explorer:** Upstream source -> table -> column -> DAX measure -> downstream report impact tracing.
- **Unified Local + Service Studio (`http://127.0.0.1:8765`):** Single web workflow supporting Power BI Service, `.pbix`, `.pbip` / `.SemanticModel`, and Excel PowerPivot `.xlsx`.
- **Structured DAX & Visual Power Query Catalog:** Auto-formatted SQLBI-style DAX formulas, Star-Schema SVG Explorer, and step-by-step M pipelines.
- **Built-in MCP Server & Zero-Install Windows Portable ZIP:** Automated cloud builds and clean-VM end-to-end verification via GitHub Actions.

---

## Planned for `v1.2` ([Vote on GitHub Issues](https://github.com/djrien-ai/pbi-doc-generator/milestone/3))

1. **Fabric PySpark / Spark SQL Notebook & Standalone Lakehouse/Warehouse Table Lineage ([#18](https://github.com/djrien-ai/pbi-doc-generator/issues/18)):** Trace Medallion `Bronze -> Silver -> Gold` transformations across `notebook-content.py` / `.ipynb` (`spark.read.table`, `saveAsTable`, `MERGE INTO`) and inventory standalone Lakehouse/Warehouse Delta tables.
2. **Advanced Report & RLS-Bypass Security Governance Rules ([#17](https://github.com/djrien-ai/pbi-doc-generator/issues/17)):** Flag hidden/locked hardcoded filters & stale bookmarks, cross-check RLS models against workspace `Admin`/`Member`/`Contributor` roles that bypass RLS, flag implicit column aggregations, and inventory third-party Custom Visuals.
3. **Granular MCP Table Inspection, `.csx` Cleanup Scripts, `DEV` vs. `PROD` Diffs & Bundled `SKILL.md` ([#15](https://github.com/djrien-ai/pbi-doc-generator/issues/15)):** Add `pbi_inspect_table`, Tabular Editor `.csx` unused-field cleanup scripts, `pbi_diff_model` environment comparisons, built-in MCP `Prompts`, and a ready-to-install agent `SKILL.md`.
4. **Opt-In REST `.pbix` Export Fallback for Restricted Pro Models ([#16](https://github.com/djrien-ai/pbi-doc-generator/issues/16)):** Optional `--pro-export-fallback` bridge via `Export?downloadType=IncludeModel` when tenant switches or legacy metadata block `getDefinition`.
5. **Direct PyPI Publication (`pip install pbi-doc-generator`):** Official signed wheel publication on `pypi.org` alongside the zero-Python Windows Portable `.zip`.

---

Have a feature request or real-world Fabric/Power BI edge case? [Open an issue](https://github.com/djrien-ai/pbi-doc-generator/issues/new/choose).
