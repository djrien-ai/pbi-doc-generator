# PBI Doc Generator

> Automatically generate complete data documentation from any Power BI `.pbix` file. No installation required.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-brightgreen.svg)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey.svg)

## What it does

Drop a `.pbix` file → get a **standalone HTML documentation page** containing:

| Section | Contents |
|---------|----------|
| **Data Sources** | HANA views, manual tables, parameters, helper functions |
| **Power Query Transformations** | Step-by-step M query logic per table |
| **Relationships** | Relationship table + interactive Mermaid.js diagram |
| **DAX Measures** | All measures grouped by table with full expressions |
| **DAX Calculated Columns** | Calculated columns per table |
| **Observations** | Automatically detected points of attention |

## Quick Start

### Option 1: Download the installer (recommended)
1. Go to [Releases](https://github.com/djrien-ai/pbi-doc-generator/releases)
2. Download `PBI_Doc_Generator_Setup.exe`
3. Install → launch from Start Menu
4. Select your `.pbix` file → done

### Option 2: Run from source
```bash
pip install pbixray
python gui.py
```

### Option 3: Command line
```bash
python extract.py "MyReport.pbix"
python extract.py "MyReport.pbix" --output "docs/output.html"
```

## How it works

```
┌─────────────┐     ┌──────────┐     ┌────────────┐     ┌──────────────────┐
│  .pbix file │ ──► │ PBIXRay  │ ──► │ extract.py │ ──► │ Standalone .html │
└─────────────┘     └──────────┘     └────────────┘     └──────────────────┘
                   Reads DataModel   Classifies &        GitHub-style CSS
                   from ZIP archive  parses metadata     Mermaid.js diagrams
```

## Project structure

| File | Description |
|------|-------------|
| `gui.py` | Tkinter GUI with file picker |
| `extract.py` | Main extraction engine (PBIXRay → HTML) |
| `html_template.py` | HTML/CSS/JS template (GitHub-style) |
| `LICENSE` | MIT License |

## Requirements (source only)

- Python 3.10+
- `pbixray` — `pip install pbixray`

The standalone installer/exe has **no requirements** — everything is bundled.

## Credits

- [PBIXRay](https://github.com/Hugoberry/pbixray) by Igor Cotruta — PBIX parsing engine (MIT)
- [Mermaid.js](https://mermaid.js.org/) — Relationship diagrams

## License

MIT — see [LICENSE](LICENSE)

## Author

**Rien Scheerlinck** — [GitHub](https://github.com/djrien-ai) · [Email](mailto:dj.rien@gmail.com)
