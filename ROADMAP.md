# Roadmap

## v0.1 — Current Release ✅

- Extract data documentation from `.pbix` files
- Data sources, Power Query, relationships, DAX measures, calculated columns
- Interactive relationship diagram (Mermaid.js)
- Standalone `.exe` — no installation required
- GitHub-style HTML output

## v0.2 — Planned 🚧

### Measure Lineage Diagram
Parse DAX expressions to trace **measure → measure** and **measure → column** dependencies, then visualize them as an interactive Mermaid.js dependency graph. This gives instant insight into which measures build on top of each other and which columns they rely on.

### Calculation Groups
Extract calculation group items and their expressions from the data model. Useful for models that use calculation groups for time intelligence or other dynamic calculations.

### TMDL / PBIP Support
Add support for **Power BI Project files** (`.pbip`) and their TMDL format. This makes the tool useful for teams already using git-based workflows with their Power BI models — no need to convert back to `.pbix` first.

---

Have a feature request? [Open an issue](https://github.com/djrien-ai/pbi-doc-generator/issues) or join the discussion on [Reddit](https://reddit.com/r/PowerBI).
