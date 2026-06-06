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
[Download from GitHub Releases (v0.4)](https://github.com/djrien-ai/pbi-doc-generator/releases/tag/v0.4)

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

## What's New in v0.4

- **Report Pages & Visuals** — full visual inventory per page with semantic data-role labels
- **Noise filter** — technical cards (!-prefix, ServerString, etc.) hidden from functional count
- **Observations** — unused measures and duplicate DAX detection
- **No horizontal scroll** — code, tables, and diagrams wrap within page width
- **Full DAX/M** — no truncation, all expressions shown in full
- **Binary payload detection** — inline tables shown as `[binary payload omitted]`
- **.Report folder matching** — correct matching when multiple .pbip files share a directory
- **Clickable links** — LinkedIn and GitHub links in the GUI footer
