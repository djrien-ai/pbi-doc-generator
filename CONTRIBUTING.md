# Contributing to PBI Doc Generator

Thanks for your interest in contributing! Whether it's a bug report, feature idea, or code contribution — all input is welcome.

## Ways to contribute

### 🐛 Report a bug
- [Open an issue](https://github.com/djrien-ai/pbi-doc-generator/issues/new) with steps to reproduce
- Include the error message and which `.pbix` file type you used (if possible)

### 💡 Suggest a feature
- Check the [Roadmap](ROADMAP.md) to see what's already planned
- Open an issue with the `enhancement` label, or start a Discussion

### 🔧 Submit code

1. **Fork** this repository
2. **Create a branch** for your feature or fix:
   ```bash
   git checkout -b feature/my-feature
   ```
3. **Make your changes** — keep them focused on one thing
4. **Test** with a `.pbix` file to make sure the output looks correct
5. **Submit a Pull Request** with a clear description of what you changed and why

### 📖 Improve documentation
Typos, better explanations, screenshots of generated output — all appreciated.

## Project structure

| File | What it does |
|------|-------------|
| `gui.py` | Tkinter GUI — file picker and progress display |
| `extract.py` | Core engine — reads data models, builds HTML sections |
| `pbip_adapter.py` | Connects TMDL parsing to the extraction engine |
| `tmdl_parser.py` | Natively parses PBIP SemanticModel folders |
| `html_template.py` | HTML/CSS/JS template (GitHub-style design) |
| `installer.iss` | Inno Setup compile script for Windows executable |

## Development setup

```bash
# Clone your fork
git clone https://github.com/YOUR-USERNAME/pbi-doc-generator.git
cd pbi-doc-generator

# Install dependencies in editable mode
pip install -e .

# Run the GUI
python gui.py

# Or run from command line
python extract.py "path/to/your/file.pbix"
# (Also supports "path/to/project.pbip" or "path/to/*.SemanticModel")
```

## Code style

- Keep it simple — this project is intentionally lightweight
- No additional frameworks unless absolutely necessary
- Comments in English

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
