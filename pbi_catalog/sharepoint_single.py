"""
Single-file portal for SharePoint Online (`PBI_Documentation_Portal_SharePoint.html`).

SharePoint Online opens an uploaded `.html` file in its file viewer by injecting the file's text into a
sandboxed `<iframe srcdoc>` (no `allow-same-origin`). In that sandbox relative links to `assets/*.css`,
`assets/*.js` and other pages cannot load and `localStorage` throws, so a multi-file portal shows up as an
unstyled page with a script error.

This module packs every portal page, stylesheet, script and data file (gzip + base64) into ONE html file
with a tiny "shell" that:
- decompresses files on demand (`DecompressionStream`), inlines each page's stylesheets / scripts and shows
  the page in a child `srcdoc` frame,
- turns relative links (`models/x.html#sec`, `../index.html#e2e:...`) into in-shell navigation,
- serves lazy loads (lineage graph / export metadata) and the embedded End-to-End explorer over postMessage,
- replaces `localStorage` with an in-memory store when the sandbox blocks it.

Opened from a normal location (local disk, synced folder, web server) the same file works too.
"""

from __future__ import annotations

import base64
import gzip
import json
from pathlib import Path

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
  if (typeof DecompressionStream === "undefined") { fail("this browser is too old (needs Edge / Chrome 80+, Firefox 113+ or Safari 16.4+)."); return; }

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

  // Runs inside every rendered page (stringified): link handling, storage shim, bridge to this shell
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
      render: function (rel, hash, query) { return ask({ type: "pbidoc-shell-render", path: rel, from: cfg.path, hash: hash || "", query: query || "", depth: cfg.depth + 1 }); }
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
    if (/(^|\/)e2e_lineage\.html$/.test(p)) { hash = "e2e" + (hash ? ":" + hash : ""); p = "index.html"; }
    if (!Object.prototype.hasOwnProperty.call(VFS, p)) { alert("This page is not part of the export: " + p); return; }
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
    else if (d.type === "pbidoc-shell-render") render(resolve(d.from, d.path), { hash: d.hash, query: d.query, depth: d.depth }).then(function (t) { reply(t); }, function (e) { reply(null, e.message); });
    else if (d.type === "pbidoc-shell-store") store[d.key] = d.value;
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
html, body { margin: 0; height: 100%; background: #f5f7fb; font-family: Segoe UI, Arial, sans-serif; color: #0f172a; }
#view { border: 0; width: 100%; height: 100%; display: none; }
#boot { padding: 40px; font-size: 15px; }
</style>
</head>
<body>
<div id="boot">Loading the Power BI documentation portal (@@SIZE@@ MB)...</div>
<iframe id="view" title="Power BI documentation portal"></iframe>
<script type="application/json" id="pbidoc-vfs">@@VFS@@</script>
<script>@@SHELL_JS@@</script>
</body>
</html>
"""


def build_single_file(portal_dir: str | Path, out_file: str | Path, level: int = 6) -> Path:
    """Pack a generated portal folder into one self-contained, SharePoint-viewer-compatible html file."""
    portal_dir = Path(portal_dir)
    out_file = Path(out_file)
    files: dict[str, str] = {}
    for f in sorted(portal_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in PACKED_SUFFIXES and f.name.lower() != "readme.html":
            rel = f.relative_to(portal_dir).as_posix()
            files[rel] = base64.b64encode(gzip.compress(f.read_bytes(), level)).decode("ascii")
    if "index.html" not in files:
        raise FileNotFoundError(f"No index.html in {portal_dir}")
    payload = json.dumps(files, separators=(",", ":"))
    size_mb = f"{(len(payload) + len(SHELL_JS)) / 1e6:.0f}"
    html = SHELL_HTML.replace("@@SIZE@@", size_mb).replace("@@SHELL_JS@@", SHELL_JS).replace("@@VFS@@", payload)
    out_file.write_text(html, encoding="utf-8")
    return out_file
