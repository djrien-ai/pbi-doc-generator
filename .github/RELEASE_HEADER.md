![pbi-doc-generator v1.1 Interactive Portal, Report X-Ray & Live Lineage Walkthrough](https://raw.githubusercontent.com/djrien-ai/pbi-doc-generator/main/docs/media/v1_1_showcase_walkthrough.gif)

## Download & Start in 30 Seconds (Windows - No Python Required)

1. **Download:** Click **`PBI_Doc_Generator_Windows_Portable.zip`** under **Assets** at the bottom of this page *(ignore `Source code (zip)` and `Source code (tar.gz)`, which GitHub adds automatically for developers)*.
2. **Extract:** Right-click the downloaded ZIP file and choose **Extract All...**
3. **Launch:** Open the extracted folder and double-click **`PBI_Doc_Generator.exe`**. Your default browser will open automatically at **`http://127.0.0.1:8765`**.
   - *First-run Windows SmartScreen note:* Because this free open-source executable is not signed with a paid EV certificate, Windows may show *"Windows protected your PC"* on first launch. Click **More info** -> **Run anyway**.
   - *Power BI Service workspace note:* Documenting workspaces in the Power BI Service requires at least **Contributor** (or **Member** / **Admin**) access in the target workspace. Documenting local `.pbix`, `.pbip`, and `.xlsx` files works 100% offline.
   - *Upgrading from v1.0.0?* Version 1.1 automatically detects any existing local `v1.0` scan cache on your PC and gives you a 1-click **Start Clean for v1.1** prompt (automatically backing up `catalog_state.v1_0.bak.json`) so new Report X-Ray layouts, thin-report DAX, and Dataflow Gen1/Gen2 M-lineage are captured from a clean state.

> **Try in Browser First:** [**Explore the Live Interactive `v1.1` Demo Portal**](https://djrien-ai.github.io/pbi-doc-generator/)
>
> **Prefer Python / macOS / Linux?** Run `pip install --upgrade "git+https://github.com/djrien-ai/pbi-doc-generator.git"` and start with `pbi-doc-generator`.
>
> **Saves your team time?** Consider [**supporting ongoing open-source development on Ko-fi**](https://ko-fi.com/rienscheerlinck) or starring the repository!

---
