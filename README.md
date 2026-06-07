# PBI Doc Generator

> Automatically generate complete data documentation from any Power BI `.pbix` or `.pbip` file. No installation required.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

## What it does

Drop a `.pbix` file, a `.pbip` project, or a `.SemanticModel` folder → get a **standalone HTML documentation page** containing:

| Section | Contents |
|---------|----------|
| **Data Sources** | HANA views, manual tables, parameters, helper functions |
| **Power Query Transformations** | Step-by-step M query logic per table |
| **Relationships** | Relationship table + interactive Mermaid.js diagram |
| **DAX Measures** | All measures grouped by table with full expressions |
| **Measure Lineage** | Measure→measure and measure→column Mermaid.js dependency graph |
| **DAX Calculated Columns** | Calculated columns per table |
| **Calculation Groups** | Calculation groups and items (for TMDL models) |
| **Observations** | Hardcoded connections, bidirectional filters, unused measures, duplicate DAX |
| **Report Pages & Visuals** | Per-page visual inventory with semantic data-role labels (X-axis, Y-axis, Legend, …) |

## Quick Start

### Portable .exe (no install)
[Download from GitHub Releases (v0.6.0)](https://github.com/djrien-ai/pbi-doc-generator/releases/tag/v0.6.0)

### To run it without an .exe
Install Python 3.10+ from python.org (I'm sure you already have that).

Open a terminal and run:
```bash
python -m venv pbidoc
pbidoc\Scripts\activate
pip install git+https://github.com/djrien-ai/pbi-doc-generator.git
```

Launch the tool:
```bash
pbi-doc-generator
```

## How it works

```
┌─────────────┐     ┌─────────────┐     ┌────────────┐     ┌──────────────────┐
│  .pbix /    │ ──► │ PBIXRay or  │ ──► │ extract.py │ ──► │ Standalone .html │
│  .pbip      │     │ TMDL parser │     └────────────┘     └──────────────────┘
└─────────────┘     └─────────────┘     Classifies &        GitHub-style CSS
                   Reads DataModel      parses metadata     Mermaid.js diagrams
```

## Project structure

| File | Description |
|------|-------------|
| `gui.py` | Tkinter GUI with file picker |
| `extract.py` | Main extraction engine (DataModel → HTML) |
| `pbip_adapter.py` | Connects TMDL parsing to the extraction engine |
| `tmdl_parser.py` | Natively parses PBIP SemanticModel folders |
| `html_template.py` | HTML/CSS/JS template (GitHub-style) |
| `installer.iss` | Inno Setup compile script for Windows |

## Requirements (source only)

- Python 3.10+
- `pbixray` and `pandas`

The standalone installer/exe has **no requirements** — everything is bundled.

## Credits

- [PBIXRay](https://github.com/Hugoberry/pbixray) by Igor Cotruta — PBIX parsing engine (MIT)
- [Mermaid.js](https://mermaid.js.org/) — Relationship diagrams

## License

MIT — see [LICENSE](LICENSE)

## Author

**Rien Scheerlinck** — [GitHub](https://github.com/djrien-ai) · [LinkedIn](https://www.linkedin.com/in/rienscheerlinck/) · [Email](mailto:dj.rien@gmail.com)

## What's New in v0.6.0

- **Enhanced Report Pages** — Full to-scale SVG wireframe layouts for every page in the report. See exactly where visuals are placed without opening Power BI.
- **Data Fields Detection** — The report page visual inventory now lists the exact fields assigned to each visual's data roles (e.g., X-axis, Y-axis, Values, Legend).
- **Collapsible Sidebar & Smart Search** — The sidebar now features nested collapsible groups for cleaner navigation. A lightning-fast, client-side search automatically finds and expands matching items.
- **Matrix Startup Splash & Progress** — Say goodbye to static loading screens! The generator now features a dynamic, hacker-style Matrix terminal that shows real-time extraction progress.
- **Excel Power Query Extraction** — You can now drop `.xlsx` files into the generator to extract and document Excel Power Query (M-code) scripts!
- **Bulletproof Crash Safety** — The extraction pipeline is now fully crash-safe. If an error occurs, it falls back to rendering a safe HTML report containing the error logs, without crashing the app.
- **Zero-Network Strict Mode** — The generator makes absolutely zero network connections. Fully offline, enterprise-safe.
