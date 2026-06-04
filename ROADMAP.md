# Roadmap

## v0.2 Current Release ✅

### Measure Lineage Diagram
Parse DAX expressions to trace **measure → measure** and **measure → column** dependencies, then visualize them as an interactive Mermaid.js dependency graph. This gives instant insight into which measures build on top of each other and which columns they rely on.

### Full TMDL / PBIP Support
Support for **Power BI Project files** (`.pbip`) and their `.SemanticModel` folders. Parses the full TMDL semantic model natively (tables, Power Query/M, measures, calculated columns, relationships, and calculation groups).

### Calculation Groups
Extract calculation group items and their expressions from the data model (currently TMDL only). Useful for models that use calculation groups for time intelligence or other dynamic calculations.

### English UI
The GUI has been switched from Dutch to English to make the tool accessible to a wider audience.

### Hide System Tables
Auto-generated Power BI tables (`LocalDateTable_*`, `DateTableTemplate_*`, `RowNumber-*`) are hidden by default. Optional checkbox to include them.

### Multi-threaded XPrs9 Support
Large PBIX files using multithreaded compression now decompress correctly.

## v0.1 Previous Release ✅

- Extract data documentation from `.pbix` files
- Data sources, Power Query, relationships, DAX measures, calculated columns
- Interactive relationship diagram (Mermaid.js)
- Standalone `.exe` — no installation required
- GitHub-style HTML output

## v0.3 Planned 🚧

### Output Format Choice
Let users choose between **HTML** (current default) or **Markdown** output. Markdown makes it easy to drop documentation straight into a Git repo, wiki, or Confluence page.

---

Have a feature request? [Open an issue](https://github.com/djrien-ai/pbi-doc-generator/issues) or join the discussion on [Reddit](https://reddit.com/r/PowerBI).
