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
| **Observations** | Automatically detected points of attention |

## Quick Start

### Option 1: Download the installer (recommended)
1. Go to [Releases](https://github.com/djrien-ai/pbi-doc-generator/releases)
2. Download the latest `PBI_Doc_Generator_Setup.exe`
3. Install → launch from Start Menu
4. Select your file → done

### Option 2: Run via pipx (recommended for devs)
```bash
pipx install git+https://github.com/djrien-ai/pbi-doc-generator.git
pbi-doc-generator-gui
```

### Option 3: Run from source
```bash
git clone https://github.com/djrien-ai/pbi-doc-generator.git
cd pbi-doc-generator
pip install -e .
python gui.py
```

### Option 4: Command line
```bash
python extract.py "MyReport.pbix"
python extract.py "MyReport.pbip" --output "docs/output.html"
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

**Rien Scheerlinck** — [GitHub](https://github.com/djrien-ai) · [Email](mailto:dj.rien@gmail.com)
