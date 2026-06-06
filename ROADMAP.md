# Roadmap

## v0.5 Upcoming Release 🚀

### Native DAX-to-English Translation
A custom shape-aware parser that auto-translates complex DAX measures into plain, readable English sentences. It understands variables (`VAR`/`RETURN`), iterators (`SUMX`, `FILTER`), and nested `CALCULATE` blocks, formatting them automatically into clean bullet points.

### Report Page & Visual Mapping
Parses the complete visual layout of the report. It extracts all hidden and visible pages, identifies exactly which visuals use which fields/measures, and maps this directly into the DAX measure documentation (e.g. "Used in X Visuals").

## Planned Features 🚧

### Excel (.xlsx) Auto-Documentation
*   **Power Query (M-Code):** Extracting Power Query directly from Excel files. Excel wraps the exact same `DataMashup` container as Power BI, so full extraction is highly feasible and coming soon.
*   **Data Model (Power Pivot / DAX):** Investigating extracting the Excel Data Model by unpacking the internal Analysis Services Backup File (`.abf` cabinet format) from the Excel ZIP structure.

### Output Format Choice
Let users choose between **HTML** (current default) or **Markdown** output. Markdown makes it easy to drop documentation straight into a Git repo, wiki, or Confluence page.

---

## Previous Releases ✅

### v0.2
*   **Measure Lineage Diagram:** Interactive Mermaid.js dependency graph parsing DAX expressions to trace **measure → measure** and **measure → column** dependencies.
*   **Full TMDL / PBIP Support:** Parses the full TMDL semantic model natively directly from `.pbip` and `.SemanticModel` folders.
*   **Calculation Groups:** Extract calculation group items and expressions (TMDL).
*   **Multi-threaded XPrs9 Support:** Fixes decompression for large PBIX files.

### v0.1
*   Extract data documentation from `.pbix` files.
*   Data sources, Power Query, relationships, DAX measures, calculated columns.
*   Standalone `.exe` — no installation required.
*   GitHub-style HTML output.

---

Have a feature request? [Open an issue](https://github.com/djrien-ai/pbi-doc-generator/issues) or join the discussion on [Reddit](https://reddit.com/r/PowerBI).
