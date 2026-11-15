"""
SharePoint Online Single-File HTML Packer & Offline Site Bundle Exporter.

SharePoint Online opens uploaded `.html` files inside a sandboxed `<iframe srcdoc>` without `allow-same-origin`.
In that viewer, relative links to `assets/*.css`, `assets/*.js`, and `models/*.html` are blocked and `localStorage`
throws a `SecurityError`.

`build_single_file()` packs every generated portal page, stylesheet, and script (gzip + base64) into ONE
self-contained `.html` file (`PBI_Documentation_Portal_SharePoint.html`) with a lightweight browser shell that:
- decompresses files on demand via standard `DecompressionStream`,
- inlines CSS/JS per page, intercepts relative `models/*.html` links for seamless in-shell navigation,
- shims `localStorage` in memory when blocked by the SharePoint sandbox.

`build_site_export()` packages either that single SharePoint `.html` file or a complete `.zip` static site
archive (including `index.html`, `models/*.html`, `assets/`, `PBI_Documentation_Portal_SharePoint.html`,
optional `.aspx` copies, and `README.html`). Zero telemetry, zero network calls.
"""

from __future__ import annotations

import base64
import datetime
import gzip
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from .security import esc
from .store import CatalogStore

PACKED_SUFFIXES = (".html", ".js", ".css")

SHELL_JS = r"""
(function () {
  "use strict";
  var holder = document.getElementById("pbidoc-vfs");
  var VFS = JSON.parse(holder.textContent);
  holder.textContent = "";
  var view = document.getElementById("view"), boot = document.getElementById("boot");
  var cache = {}, store = {}, cur = { path: "", hash: "" };

  function fail(msg) { boot.style.display = "block"; boot.innerHTML = "<b>Could not open the portal:</b> " + String(msg).replace(/</g, "&lt;"); }
  if (typeof DecompressionStream === "undefined") { fail("Please open in a modern browser (Edge / Chrome 80+, Firefox 113+, or Safari 16.4+)."); return; }

  function bytes(b64) { var bin = atob(b64), n = bin.length, u = new Uint8Array(n); for (var i = 0; i < n; i++) u[i] = bin.charCodeAt(i); return u; }
  function file(path) {
    if (cache[path]) return cache[path];
    if (!Object.prototype.hasOwnProperty.call(VFS, path)) return Promise.reject(new Error("Not part of this export: " + path));
    var p = new Response(new Blob([bytes(VFS[path])]).stream().pipeThrough(new DecompressionStream("gzip"))).text();
    cache[path] = p;
    return p;
  }
  function resolve(from, rel) {
    rel = String(rel || "").split("?")[0];
    var base = from && from.lastIndexOf("/") >= 0 ? from.slice(0, from.lastIndexOf("/") + 1) : "";
    var out = [];
    (base + rel).split("/").forEach(function (s) { if (s === "..") out.pop(); else if (s && s !== ".") out.push(s); });
    return out.join("/");
  }

  function prelude(cfg) {
    var root = window;
    for (var i = 0; i < cfg.depth; i++) root = root.parent;
    var seq = 0, waits = {};
    window.addEventListener("message", function (ev) {
      var d = ev.data || {};
      if (d.type === "pbidoc-shell-reply" && waits[d.id]) {
        var w = waits[d.id]; delete waits[d.id];
        if (d.error) w[1](new Error(d.error)); else w[0](d.text);
      } else if (d.type === "pbidoc-set-hash" && typeof d.hash === "string") {
        if (location.hash.slice(1) !== d.hash) location.hash = d.hash;
      }
    });
    function ask(msg) {
      return new Promise(function (res, rej) {
        msg.id = "r" + (++seq) + "_" + Math.random().toString(36).slice(2);
        waits[msg.id] = [res, rej];
        root.postMessage(msg, "*");
      });
    }
    var mem = cfg.store || {};
    var shim = {
      getItem: function (k) { return Object.prototype.hasOwnProperty.call(mem, k) ? mem[k] : null; },
      setItem: function (k, v) { mem[k] = String(v); root.postMessage({ type: "pbidoc-shell-store", key: k, value: String(v) }, "*"); },
      removeItem: function (k) { delete mem[k]; },
      clear: function () { mem = {}; },
      key: function (n) { return Object.keys(mem)[n] || null; }
    };
    try { window.localStorage.getItem("pbidoc"); } catch (e) {
      try { Object.defineProperty(window, "localStorage", { value: shim, configurable: true }); } catch (e2) { /* ignore */ }
    }
    window.PBIDOC_SHELL = {
      path: cfg.path, query: cfg.query || "", depth: cfg.depth,
      load: function (rel) { return ask({ type: "pbidoc-shell-load", path: rel, from: cfg.path }); },
      nav: function (rel, hash) { root.postMessage({ type: "pbidoc-shell-nav", path: rel, hash: hash || "", from: cfg.path }, "*"); },
      print: function () { root.postMessage({ type: "pbidoc-shell-print" }, "*"); }
    };
    if (cfg.hash) { try { history.replaceState(null, "", "#" + cfg.hash); } catch (e) { try { location.hash = cfg.hash; } catch (e2) { /* ignore */ } } }
    document.addEventListener("click", function (e) {
      var a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
      if (!a) return;
      var href = a.getAttribute("href") || "";
      if (!href || /^(#|[a-z][a-z0-9+.-]*:)/i.test(href) || a.hasAttribute("download")) return;
      e.preventDefault();
      var k = href.indexOf("#");
      root.postMessage({ type: "pbidoc-shell-nav", path: k < 0 ? href : href.slice(0, k), hash: k < 0 ? "" : href.slice(k + 1), from: cfg.path }, "*");
    }, true);
  }

  var REF_RE = /<link\b[^>]*\brel="stylesheet"[^>]*\bhref="([^"]+)"[^>]*>|<script\b([^>]*?)\bsrc="([^"]+)"([^>]*)><\/script>/gi;
  function render(path, opts) {
    return file(path).then(function (html) {
      var out = [], jobs = [], last = 0, m;
      REF_RE.lastIndex = 0;
      while ((m = REF_RE.exec(html))) {
        out.push(html.slice(last, m.index));
        last = REF_RE.lastIndex;
        var ref = m[1] || m[3], target = resolve(path, ref);
        if (/^[a-z][a-z0-9+.-]*:/i.test(ref) || !Object.prototype.hasOwnProperty.call(VFS, target)) { out.push(m[0]); continue; }
        var slot = out.length;
        out.push("");
        jobs.push(file(target).then((function (i, isCss, attrs) {
          return function (t) {
            out[i] = isCss ? "<style>" + t + "</style>" : "<script " + attrs + ">" + t.replace(/<\/script/gi, "<\\/script") + "<\/script>";
          };
        })(slot, !!m[1], ((m[2] || "") + " " + (m[4] || "")).trim())));
      }
      out.push(html.slice(last));
      return Promise.all(jobs).then(function () {
        var cfg = { path: path, hash: opts.hash || "", query: opts.query || "", depth: opts.depth || 1, store: store };
        var pre = "<script>(" + prelude.toString() + ")(" + JSON.stringify(cfg).replace(/</g, "\\u003c") + ");<\/script>";
        var doc = out.join("");
        return /<head[^>]*>/i.test(doc) ? doc.replace(/<head[^>]*>/i, function (h) { return h + pre; }) : pre + doc;
      });
    });
  }

  function nav(path, hash, from) {
    var p = from != null ? resolve(from, path) : path;
    hash = hash || "";
    if (!Object.prototype.hasOwnProperty.call(VFS, p)) { return; }
    if (p === cur.path && view.getAttribute("data-ready")) {
      cur.hash = hash;
      view.contentWindow.postMessage({ type: "pbidoc-set-hash", hash: hash }, "*");
      return;
    }
    cur = { path: p, hash: hash };
    view.removeAttribute("data-ready");
    render(p, { hash: hash, depth: 1 }).then(function (doc) {
      view.srcdoc = doc;
      view.style.display = "block";
      boot.style.display = "none";
    }, function (err) { fail(err.message); });
  }
  view.addEventListener("load", function () { if (view.srcdoc) view.setAttribute("data-ready", "1"); });

  window.addEventListener("message", function (ev) {
    var d = ev.data || {}, src = ev.source;
    function reply(text, err) { try { src.postMessage({ type: "pbidoc-shell-reply", id: d.id, text: text, error: err || "" }, "*"); } catch (e) { /* ignore */ } }
    if (d.type === "pbidoc-shell-nav") nav(d.path, d.hash, d.from);
    else if (d.type === "pbidoc-shell-load") file(resolve(d.from, d.path)).then(function (t) { reply(t); }, function (e) { reply(null, e.message); });
    else if (d.type === "pbidoc-shell-store") store[d.key] = d.value;
    else if (d.type === "pbidoc-shell-print") { if (view && view.contentWindow) { view.contentWindow.focus(); view.contentWindow.print(); } }
  });
  nav("index.html", "", null);
})();
"""

SHELL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Power BI Documentation Portal</title>
<style>
html, body { margin: 0; height: 100%; background: #f8fafc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #0f172a; }
#view { border: 0; width: 100%; height: 100%; display: none; }
#boot { padding: 40px; font-size: 15px; color: #334155; }
</style>
</head>
<body>
<div id="boot">Loading Power BI Documentation Portal (@@SIZE@@ MB)...</div>
<iframe id="view" title="Power BI Documentation Portal"></iframe>
<script type="application/json" id="pbidoc-vfs">@@VFS@@</script>
<script>@@SHELL_JS@@</script>
</body>
</html>
"""

_HTML_LINK_RE = re.compile(
    r"""((?:href|src)\s*=\s*["'])(?!https?:|mailto:|#|data:|javascript:)([^"'#?]+?)\.html(?=[#?"'])""",
    re.I,
)
_JSON_LINK_RE = re.compile(r'("href"\s*:\s*")(?!https?:|#)([^"#?]+?)\.html(?=[#?"])')


def _to_aspx_links(html: str) -> str:
    html = _HTML_LINK_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}.aspx", html)
    html = _JSON_LINK_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}.aspx", html)
    return html.replace("<%", "\\u003c%")


README_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Portal Export Guide</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;line-height:1.55;color:#0f172a;background:#fff}}
h1{{font-size:22px}}h2{{font-size:17px;margin-top:26px}}code{{background:#f1f5f9;padding:1px 5px;border-radius:4px}}
.box{{border:1px solid #dce3ee;border-radius:10px;padding:10px 14px;background:#f8fafc}}
</style></head><body>
<h1>Power BI Documentation Portal - Offline Export</h1>
<p class="box">Exported {when} | {models} semantic model(s) | {dataflows} dataflow(s) | {measures} DAX measure(s){anon}.<br>
Start page: <a href="index.html">index.html</a>. Single-file SharePoint version: <code>PBI_Documentation_Portal_SharePoint.html</code>.</p>

<h2>Option 1: Browse directly inside SharePoint Online (recommended)</h2>
<ol>
<li>Upload <b>only</b> <code>PBI_Documentation_Portal_SharePoint.html</code> to any SharePoint Document Library.</li>
<li>Click the file in SharePoint. It opens inside SharePoint's viewer with all tabs, model pages, star schemas, dataflow queries, report X-ray drawers, and end-to-end lineage intact.</li>
</ol>

<h2>Option 2: Synced SharePoint / OneDrive folder or Local Disk</h2>
<ol>
<li>Extract this folder (or sync your SharePoint library via OneDrive) and open <code>index.html</code> in Edge, Chrome, Firefox, or Safari.</li>
</ol>

<h2>Privacy &amp; Metadata Guarantee</h2>
<p>This package contains only model structure, DAX formulas, Power Query M scripts, native SQL text, relationships, report layout wireframes, and lineage metadata. Zero table rows or query results are stored, and zero external network calls are made.</p>
</body></html>
"""


def build_single_file(portal_dir: str | Path, out_file: str | Path, level: int = 6) -> Path:
    """Pack a generated portal directory into one SharePoint-compatible single `.html` file."""
    portal_dir = Path(portal_dir)
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for f in sorted(portal_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in PACKED_SUFFIXES and f.name.lower() != "readme.html":
            if f.name.lower().startswith("pbi_documentation_portal_"):
                continue
            rel = f.relative_to(portal_dir).as_posix()
            files[rel] = base64.b64encode(gzip.compress(f.read_bytes(), level)).decode("ascii")
    if "index.html" not in files:
        raise FileNotFoundError(f"No index.html in {portal_dir}")
    payload = json.dumps(files, separators=(",", ":"))
    size_mb = f"{max(0.1, (len(payload) + len(SHELL_JS)) / 1e6):.1f}"
    html = SHELL_HTML.replace("@@SIZE@@", size_mb).replace("@@SHELL_JS@@", SHELL_JS).replace("@@VFS@@", payload)
    out_file.write_text(html, encoding="utf-8")
    return out_file


_STORAGE_SHIM_SCRIPT = """<script>
(function(){
  var mem={};
  try{window.localStorage.getItem("pbidoc");}catch(e){
    try{Object.defineProperty(window,"localStorage",{value:{
      getItem:function(k){return Object.prototype.hasOwnProperty.call(mem,k)?mem[k]:null;},
      setItem:function(k,v){mem[k]=String(v);},
      removeItem:function(k){delete mem[k];},
      clear:function(){mem={};}
    },configurable:true});}catch(e2){}
  }
})();
</script>"""


def _scope_e2e_js_for_model(raw_e2e_js: str, model_name: str) -> str:
    """Trim `window.PBI_E2E_GRAPH` to only the nodes, edges, and dataflows relevant to `model_name`."""
    prefix = "window.PBI_E2E_GRAPH ="
    idx = raw_e2e_js.find(prefix)
    if idx == -1:
        return raw_e2e_js
    json_part = raw_e2e_js[idx + len(prefix):].strip().rstrip(";").strip()
    try:
        g = json.loads(json_part)
    except Exception:
        return raw_e2e_js
    nodes = g.get("nodes") or {}
    edges = g.get("edges") or []
    seed_ids = {nid for nid, n in nodes.items() if (n.get("model") or "") == model_name}
    if not seed_ids:
        return raw_e2e_js
    adj: dict[str, list[str]] = {}
    for e in edges:
        u, v = e.get("from", ""), e.get("to", "")
        adj.setdefault(u, []).append(v)
        adj.setdefault(v, []).append(u)
    keep = set(seed_ids)
    queue = list(seed_ids)
    while queue:
        cur = queue.pop(0)
        for nxt in adj.get(cur, []):
            nxt_node = nodes.get(nxt) or {}
            # Traverse into shared sources / dataflows, not into unrelated sibling semantic models
            if nxt not in keep and (not nxt_node.get("model") or nxt_node.get("model") == model_name):
                keep.add(nxt)
                queue.append(nxt)
    scoped = {
        "models": [m for m in (g.get("models") or []) if m.get("name") == model_name],
        "dataflows": g.get("dataflows") or [],
        "nodes": {nid: nodes[nid] for nid in keep if nid in nodes},
        "edges": [e for e in edges if e.get("from") in keep and e.get("to") in keep],
    }
    payload = json.dumps(scoped, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"window.PBI_E2E_GRAPH = {payload};\n"


def pack_single_model_from_portal(portal_dir: str | Path, slug: str, out_file: str | Path) -> Path:
    """
    Pack ONE semantic model (`models/<slug>.html`) into a 100% standalone, flat, SharePoint- and
    print-compatible `.html` (or `.aspx`) file with zero external CSS/JS dependencies and zero sibling model leakage.
    """
    portal_dir = Path(portal_dir)
    out_file = Path(out_file)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    model_path = portal_dir / "models" / f"{slug}.html"
    if not model_path.is_file():
        raise FileNotFoundError(f"Model documentation page not found: {model_path}")

    html = model_path.read_text(encoding="utf-8")
    title_m = re.search(r"<title>(.*?)\s*-\s*Semantic Model Documentation</title>", html, re.S)
    raw_title = title_m.group(1) if title_m else slug
    model_name = (
        raw_title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').strip()
    )

    assets_dir = portal_dir / "assets"
    css_txt = (assets_dir / "portal.css").read_text(encoding="utf-8") if (assets_dir / "portal.css").is_file() else ""
    standalone_css = (
        "\n/* Standalone Single-Model Export Overrides */\n"
        "[data-standalone-model='1'] .studio-only-link,"
        "[data-standalone-model='1'] .doc-sidebar .doc-back,"
        "[data-standalone-model='1'] .model-switcher-select,"
        "[data-standalone-model='1'] .doc-crumbs a,"
        "[data-standalone-model='1'] .doc-crumbs .crumb-sep { display: none !important; }\n"
    )

    html = html.replace('<html lang="en">', '<html lang="en" data-standalone-model="1">', 1)
    html = re.sub(
        r'<link\s+rel="stylesheet"\s+href="\.\./assets/portal\.css"\s*/?>',
        lambda _m: _STORAGE_SHIM_SCRIPT + "\n<style>\n" + css_txt + standalone_css + "\n</style>",
        html,
        count=1,
    )

    def _inline_script(match: re.Match) -> str:
        rel_name = match.group(1)
        js_file = assets_dir / rel_name
        if not js_file.is_file():
            return ""
        js_txt = js_file.read_text(encoding="utf-8")
        if rel_name == "e2e_graph.js":
            js_txt = _scope_e2e_js_for_model(js_txt, model_name)
        safe_js = js_txt.replace("</script", "<\\/script").replace("<%", "\\u003c%")
        return f"<script>\n{safe_js}\n</script>"

    html = re.sub(r'<script\s+src="\.\./assets/([^"]+)"></script>', _inline_script, html)
    out_file.write_text(html, encoding="utf-8")
    return out_file


def build_single_model_export(
    store: CatalogStore,
    slug: str,
    out_path: str | Path,
    anonymous: bool = False,
    as_aspx: bool = False,
    log_fn=None,
) -> Path:
    """Generate/refresh portal (if needed) and export ONE standalone single-model `.html` or `.aspx` file."""
    from .portal import generate_portal

    log = log_fn or (lambda _m: None)
    out_path = Path(out_path)
    if as_aspx and out_path.suffix.lower() != ".aspx":
        out_path = out_path.with_suffix(".aspx")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if anonymous:
        tmp = Path(tempfile.mkdtemp(prefix="pbidoc_model_"))
        try:
            site = tmp / "portal"
            generate_portal(store, output_dir=site, anonymous=True)
            res = pack_single_model_from_portal(site, slug, out_path)
            log(f"Single-model export complete: {res.name} ({res.stat().st_size / 1024:.1f} KB)")
            return res
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    portal_dir = store.portal_dir
    if not (portal_dir / "models" / f"{slug}.html").is_file():
        generate_portal(store, anonymous=False)
    res = pack_single_model_from_portal(portal_dir, slug, out_path)
    log(f"Single-model export complete: {res.name} ({res.stat().st_size / 1024:.1f} KB)")
    return res


def build_site_export(
    store: CatalogStore,
    out_path: str | Path,
    anonymous: bool = False,
    include_aspx: bool = False,
    log_fn=None,
    single_file_only: bool = False,
) -> Path:
    """Generate a clean offline portal and package it as either a single SharePoint `.html` or a `.zip` bundle."""
    from .portal import generate_portal

    log = log_fn or (lambda _m: None)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M")
    folder_name = f"PBI_Documentation_Portal_{stamp}"
    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_site_"))
    try:
        site = tmp / folder_name
        log("Exporting portal: generating static HTML pages...")
        generate_portal(store, output_dir=site, anonymous=anonymous)

        state = store.load_scoped()
        e2e_js = site / "assets" / "e2e_graph.js"
        measures_cnt = 0
        if e2e_js.is_file():
            measures_cnt = e2e_js.read_text(encoding="utf-8").count('"kind":"measure"')

        (site / "README.html").write_text(
            README_HTML.format(
                when=esc(datetime.datetime.now().strftime("%Y-%m-%d %H:%M")),
                models=len(state.get("models", {})),
                dataflows=len(state.get("dataflows", {})),
                measures=measures_cnt,
                anon=" | Personal names & filter literals redacted" if anonymous else "",
            ),
            encoding="utf-8",
        )

        log("Exporting portal: packing single-file SharePoint HTML...")
        single = build_single_file(site, tmp / "PBI_Documentation_Portal_SharePoint.html")
        if single_file_only:
            shutil.move(str(single), str(out_path))
            log(f"Export complete: {out_path.name} ({out_path.stat().st_size / 1e6:.2f} MB single HTML file)")
            return out_path

        pages = sorted(site.rglob("*.html"))
        shutil.move(str(single), str(site / single.name))
        if include_aspx:
            log(f"Exporting portal: creating {len(pages)} .aspx copies...")
            for page in pages:
                page.with_suffix(".aspx").write_text(
                    _to_aspx_links(page.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )

        log("Exporting portal: compressing .zip archive...")
        tmp_zip = out_path.with_suffix(".zip.part")
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for f in sorted(site.rglob("*")):
                if f.is_file():
                    zf.write(f, f.relative_to(tmp).as_posix())
        tmp_zip.replace(out_path)
        log(f"Export complete: {out_path.name} ({out_path.stat().st_size / 1e6:.2f} MB, {len(pages)} pages)")
        return out_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
