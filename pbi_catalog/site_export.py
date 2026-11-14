"""
"Export all data": package the complete viewing portal (no data collection parts) as a static site
that can be copied into a SharePoint document library (or any file share / web server) and browsed.

The package contains:
- `index.html` + `models/*.html` + `e2e_lineage.html` + `assets/`: the full portal (catalog, model pages,
  star schemas, DAX / Power Query catalogs, live lineage, governance, end-to-end measure lineage with
  SQL, step browser and documentation export). Fully offline: no Studio server, no internet.
- `PBI_Documentation_Portal_SharePoint.html`: the whole portal packed into ONE file that opens in the
  SharePoint Online file viewer (see `sharepoint_single.py`) - the recommended way to browse it in SharePoint.
- optional `*.aspx` twins of every page with links rewritten to `.aspx`. SharePoint Online downloads `.html`
  files instead of rendering them; `.aspx` pages render in the browser on sites where the SharePoint
  admin allows custom scripts.
- `README.html`: how to publish / open it.

The diagnostics trace hook and Studio-only controls are removed. Nothing in the package contacts
Power BI or any other service.
"""

from __future__ import annotations

import datetime
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from .portal import PORTAL_COMMON_JS, generate_portal
from .security import esc
from .store import CatalogStore

_HTML_LINK_RE = re.compile(r'''((?:href|src)\s*=\s*["'])(?!https?:|mailto:|#|data:|javascript:)([^"'#?]+?)\.html(?=[#?"'])''', re.I)


# Links stored in embedded lineage JSON: "href": "models/x.html#..."
_JSON_LINK_RE = re.compile(r'("href"\s*:\s*")(?!https?:|#)([^"#?]+?)\.html(?=[#?"])')


def _to_aspx_links(html: str) -> str:
    html = _HTML_LINK_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}.aspx", html)
    return _JSON_LINK_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}.aspx", html)


README = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portal Export Guide</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;line-height:1.55;color:#0f172a;background:#fff}}
h1{{font-size:22px}}h2{{font-size:17px;margin-top:26px}}code{{background:#f1f5f9;padding:1px 5px;border-radius:4px}}
.box{{border:1px solid #dce3ee;border-radius:10px;padding:10px 14px;background:#f8fafc}}
</style></head><body>
<h1>Power BI Documentation Portal - offline export</h1>
<p class="box">Exported {when} &bull; {models} semantic model(s) &bull; {dataflows} dataflow(s) &bull; {measures} DAX measure(s){anon}.<br>
Start page: <a href="index.html">index.html</a>. Single-file SharePoint version: <code>PBI_Documentation_Portal_SharePoint.html</code>.</p>

<h2>Option 1 - Browse inside SharePoint Online (recommended): the single file</h2>
<ol>
<li>Upload <b>only</b> <code>PBI_Documentation_Portal_SharePoint.html</code> to a document library (no sub-folders needed).</li>
<li>Click it in the library. SharePoint opens it in its file viewer and the complete portal works there: all tabs, model pages,
dataflows, lineage and the end-to-end explorer.</li>
</ol>
<p>Why one file: SharePoint shows uploaded .html files in a locked-down (sandboxed) viewer that cannot load the separate
<code>assets</code> / <code>models</code> files of the folder version - that is what produces an unformatted page. The single file carries
everything inside it (compressed) and needs a current browser (Edge / Chrome, Firefox 113+, Safari 16.4+).
The viewer may block file downloads, so documentation exports (Word / HTML / Markdown) might not download from inside SharePoint -
use option 2 for exports.</p>

<h2>Option 2 - Synced SharePoint / OneDrive folder (works everywhere)</h2>
<ol>
<li>Upload the folder to SharePoint, then click <b>Sync</b> (or "Add shortcut to My files") so it appears in File Explorer.</li>
<li>Open <code>index.html</code> from the synced folder in Edge / Chrome. Everyone with access to the library sees the same, latest export.</li>
</ol>
<p>Clicking an <code>.html</code> file in the SharePoint web view downloads it instead of opening it - that is SharePoint's security policy for HTML files.
Opening the synced or downloaded copy works fully offline.</p>

<h2>Option 3 - Any internal web server / static site host</h2>
<p>Copy the folder as-is. All links are relative; no server-side code is needed.</p>

<h2>Option 4 - .aspx pages (only if exported with .aspx copies)</h2>
<p>SharePoint Online renders .aspx pages only on sites where the admin allows <b>custom scripts</b>
(<code>DenyAddAndCustomizePages</code> off). Microsoft has retired that option for most tenants, so .aspx pages usually download
instead of opening - prefer option 1.</p>

<h2>Updating</h2>
<p>Re-run <b>Export all data</b> after a new scan and replace the folder contents (keep the same folder so links stay valid).</p>

<h2>What is inside</h2>
<p>Only documentation metadata collected by the scanner: model structure, DAX, Power Query M, native SQL text, relationships,
dataflow definitions, source connection names and lineage. No table rows or measure results are included.
Power BI is never contacted when viewing this export.</p>
</body></html>
"""


def build_site_export(store: CatalogStore, out_zip: str | Path, anonymous: bool = False, include_aspx: bool = False,
                      log_fn=None, single_file_only: bool = False) -> Path:
    """Generate the portal into a temporary folder, make it SharePoint-ready and zip it to `out_zip`.

    With `single_file_only`, `out_zip` is an .html path and only the single-file SharePoint version is written.
    """
    from .sharepoint_single import build_single_file

    log = log_fn or (lambda _m: None)
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    folder_name = f"PBI_Documentation_Portal_{stamp}"
    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_site_"))
    try:
        site = tmp / folder_name
        log("Export all data: generating portal pages...")
        generate_portal(store, output_dir=site, anonymous=anonymous)

        # Static copy: drop the Studio diagnostics hook; Studio-only controls stay hidden off localhost
        (site / "assets" / "portal_common.js").write_text(PORTAL_COMMON_JS, encoding="utf-8")

        state = store.load_scoped()
        graph_file = site / "assets" / "e2e_graph.js"
        measures = 0
        if graph_file.exists():
            measures = graph_file.read_text(encoding="utf-8").count('"kind":"measure"')
        (site / "README.html").write_text(
            README.format(
                when=esc(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
                models=len(state.get("models", {})),
                dataflows=len(state.get("dataflows", {})),
                measures=measures,
                anon=" &bull; people names anonymized" if anonymous else "",
            ),
            encoding="utf-8",
        )

        log("Export all data: packing the single-file SharePoint version...")
        single = build_single_file(site, tmp / "PBI_Documentation_Portal_SharePoint.html")
        if single_file_only:
            shutil.move(str(single), str(out_zip))
            log(f"Export all data: {out_zip.name} ({out_zip.stat().st_size / 1e6:.1f} MB single file)")
            return out_zip

        pages = sorted(site.rglob("*.html"))
        shutil.move(str(single), str(site / single.name))
        if include_aspx:
            log(f"Export all data: creating {len(pages)} SharePoint .aspx page copies...")
            for page in pages:
                page.with_suffix(".aspx").write_text(_to_aspx_links(page.read_text(encoding="utf-8")), encoding="utf-8")

        log("Export all data: compressing...")
        tmp_zip = out_zip.with_suffix(".zip.part")
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in sorted(site.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(tmp).as_posix())
        tmp_zip.replace(out_zip)
        log(f"Export all data: {out_zip.name} ({out_zip.stat().st_size / 1e6:.1f} MB, {len(pages)} pages)")
        return out_zip
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
