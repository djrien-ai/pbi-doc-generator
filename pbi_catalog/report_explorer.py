"""
Report Explorer: Power BI reports drawn as wireframes (no data) with click-through lineage.

Built automatically at portal generation from the report layouts the scanner stores
(`catalog/report_layouts/{report_id}.json`, see `reports.parse_report_layout`):

- every visual field / filter / slicer is resolved to its node in the end-to-end lineage graph
  (model measure, thin-report measure, calculated column or table);
- `assets/reports/{id}.js`   one file per report, loaded when the report is opened;
- `assets/report_index.js`   the report list (workspace, model, pages, visuals);
- `assets/report_usage.js`   field -> visuals that use it (for "where used" in the explorers).

The UI (tab "3. Report Explorer" of the portal home page) is `REPORT_JS`: pick a workspace / semantic model /
report, then a page; the page is drawn to scale from the stored positions with a neutral placeholder per visual
type. Clicking a visual lists its fields, filters and slicer selections; clicking any of those shows its DAX /
column details and the upstream lineage map (measures, tables, Power Query, dataflow layers, SQL sources).
"""

from __future__ import annotations

import collections
import json
from pathlib import Path

from .store import CatalogStore


def _js_assign(target: str, data) -> str:
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return f"{target} = {payload};\n"


class _Resolver:
    """Map report fields (table + name) to end-to-end lineage node ids of the report's semantic model."""

    def __init__(self, nodes: dict):
        self.nodes = nodes
        self.measures: dict[tuple[str, str], str] = {}
        for nid, n in nodes.items():
            if n.get("kind") == "measure" and not n.get("report_id") and n.get("model_id"):
                self.measures[(n["model_id"], n["name"].lower())] = nid

    def node(self, f: dict, ds: str, rid: str) -> str:
        if not f or not ds:
            return ""
        t, name = f.get("table", ""), f.get("name", "")
        if f.get("kind") == "measure":
            for cand in (f"m:{ds}:rpt:{rid}:{t}[{name}]", f"m:{ds}:{t}[{name}]"):
                if cand in self.nodes:
                    return cand
            return self.measures.get((ds, name.lower()), "")
        cc = f"c:{ds}:{t}[{name}]"
        if f.get("kind") == "column" and cc in self.nodes:
            return cc
        tid = f"t:{ds}:{t}"
        return tid if tid in self.nodes else ""


def usage_key(f: dict, ds: str, node: str) -> str:
    if f.get("kind") == "measure":
        return node or f"m?:{ds}:{f.get('table', '')}[{f.get('name', '')}]"
    return f"col:{ds}:{f.get('table', '')}[{f.get('name', '')}]"


def build_report_assets(out_root: Path, store: CatalogStore, state: dict, graph: dict) -> dict:
    """Write report index / per-report layout / usage assets. Returns summary counts."""
    assets = out_root / "assets"
    rdir = assets / "reports"
    rdir.mkdir(parents=True, exist_ok=True)
    for old in rdir.glob("*.js"):
        old.unlink()
    nodes = graph["nodes"]
    res = _Resolver(nodes)
    models = state.get("models", {})
    oos = state.get("out_of_scope_models") or {}
    index, usage_reports = [], []
    use: dict[str, list] = collections.defaultdict(list)
    totals = collections.Counter()
    broken: dict[str, dict] = {}  # report id -> fields that no longer exist in its semantic model

    for rid, rep in sorted(state.get("reports", {}).items(), key=lambda kv: (kv[1].get("workspace", "").lower(), kv[1].get("name", "").lower())):
        lay = store.read_report_layout(rid)
        if not lay.get("pages"):
            continue
        ds = rep.get("dataset_id") or lay.get("dataset_id", "")
        dm = models.get(ds) or oos.get(ds) or {}
        ri = len(usage_reports)
        usage_reports.append([rid, rep.get("name", ""), rep.get("workspace", "")])

        page_names = {p["name"]: p.get("display", p["name"]) for p in lay["pages"]}

        def bind(f: dict | None, page: str, vid: str, vlabel: str, role: str) -> None:
            if not f:
                return
            f["node"] = res.node(f, ds, rid)
            totals["fields"] += 1
            totals["resolved"] += bool(f["node"])
            if not f["node"] and ds in models:
                b = broken.setdefault(rid, {"name": rep.get("name", ""), "workspace": rep.get("workspace", ""), "model": dm.get("name", ""), "fields": collections.Counter()})
                b["fields"][f"{f.get('table', '')}[{f.get('name', '')}]"] += 1
            use[usage_key(f, ds, f["node"])].append([ri, page, vid, vlabel, role, page_names.get(page, "")])

        for p in lay["pages"]:
            for fl in p.get("filters") or []:
                bind(fl.get("field"), p["name"], "", "Page filter", "Page filter")
            for v in p["visuals"]:
                vlabel = v.get("title") or v.get("type", "")
                for role, fields in (v.get("roles") or {}).items():
                    for f in fields:
                        bind(f, p["name"], v["id"], vlabel, role)
                for fl in v.get("filters") or []:
                    bind(fl.get("field"), p["name"], v["id"], vlabel, "Visual filter")
        for fl in lay.get("filters") or []:
            bind(fl.get("field"), "", "", "Report filter", "Report filter")

        lay.update({
            "report_id": rid, "name": rep.get("name", ""), "workspace": rep.get("workspace", ""), "dataset_id": ds,
            "model": dm.get("name", ""), "model_workspace": dm.get("workspace", ""), "model_in_catalog": ds in models,
            "web_url": rep.get("web_url", ""),
        })
        (rdir / f"{rid}.js").write_text(_js_assign(f"(window.PBIDOC_REPORTS = window.PBIDOC_REPORTS || {{}})[{json.dumps(rid)}]", lay), encoding="utf-8")
        index.append({
            "id": rid, "name": rep.get("name", ""), "workspace": rep.get("workspace", ""), "model_id": ds, "model": dm.get("name", ""),
            "model_workspace": dm.get("workspace", ""), "format": lay.get("format", ""), "pages": len(lay["pages"]),
            "visible_pages": sum(1 for p in lay["pages"] if not p.get("hidden")), "visuals": lay.get("visual_count", 0),
            "report_measures": rep.get("report_measure_count", 0),
        })
        totals["reports"] += 1
        totals["pages"] += len(lay["pages"])
        totals["visuals"] += lay.get("visual_count", 0)

    (assets / "report_index.js").write_text(_js_assign("window.REPORT_INDEX", index), encoding="utf-8")
    (assets / "report_usage.js").write_text(_js_assign("window.REPORT_USAGE", {"reports": usage_reports, "use": use}), encoding="utf-8")
    (assets / "report_explorer.js").write_text(REPORT_JS, encoding="utf-8")
    out = dict(totals)
    out["broken"] = broken
    return out


PANE_HTML = """
  <section class="tab-pane" id="tab-reports">
    <div class="rx-wrap">
      <aside class="rx-side">
        <label class="rx-flbl" for="rxWs">1. Workspace</label>
        <select id="rxWs" aria-label="Filter reports by workspace"></select>
        <label class="rx-flbl" for="rxModel">2. Semantic model</label>
        <select id="rxModel" aria-label="Filter reports by semantic model"></select>
        <label class="rx-flbl" for="rxSearch">3. Report</label>
        <input id="rxSearch" type="search" placeholder="Search reports...">
        <div class="rx-count" id="rxCount"></div>
        <div class="rx-list" id="rxList"></div>
      </aside>
      <section class="rx-main">
        <div class="rx-card rx-empty" id="rxWelcome">
          <h2>Pick a report</h2>
          Choose a report on the left (filter by workspace and semantic model first). Its pages are drawn from the report definition -
          layout, visual types, fields, filters and slicer selections, never data. Click a visual, then any field, filter or slicer to see its
          DAX and full end-to-end lineage.
        </div>
        <div id="rxMain" style="display:none">
          <div class="rx-card">
            <div class="rx-head">
              <div><h2 id="rxTitle"></h2><div class="sub" id="rxSub"></div></div>
              <div class="rx-actions">
                <label class="rx-toggle"><input type="checkbox" id="rxShowHidden"> Hidden visuals</label>
                <label class="rx-toggle"><input type="checkbox" id="rxShowFields" checked> Field names</label>
                <button type="button" class="rx-btn" id="rxReportFilters">Report filters</button>
              </div>
            </div>
            <div class="rx-pages" id="rxPages"></div>
          </div>
          <div class="rx-stage">
            <div class="rx-card rx-canvas-card">
              <div class="rx-canvas-wrap"><div class="rx-canvas" id="rxCanvas"></div></div>
              <div class="rx-legend"><span><i class="m"></i>Measure</span><span><i class="c"></i>Column</span><span><i class="r"></i>Report-level measure</span>
                <span><i class="f"></i>Filter / slicer</span><span><i class="x"></i>Not in the semantic model</span><span>Click a visual, then a field for its lineage</span></div>
            </div>
            <div class="rx-card rx-inspect" id="rxInspect"></div>
          </div>
          <div class="rx-card" id="rxLineage"><div class="rx-empty">Select a field, filter or slicer to see its full lineage here.</div></div>
        </div>
      </section>
    </div>
  </section>
"""

REPORT_CSS = r"""
#tab-reports { margin: 0 -18px; }
.rx-wrap { display: grid; grid-template-columns: 300px minmax(0, 1fr); gap: 14px; }
@media (max-width: 900px) { .rx-wrap { grid-template-columns: minmax(0, 1fr); } }
.rx-side { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; display: flex; flex-direction: column; gap: 8px; max-height: calc(100vh - 40px); position: sticky; top: 10px; align-self: start; }
.rx-side select, .rx-side input { width: 100%; padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-alt); color: var(--fg); font: inherit; font-size: 13px; }
.rx-flbl { font-size: 11px; font-weight: 650; text-transform: uppercase; letter-spacing: .03em; color: var(--fg-muted); margin: 2px 0 -4px; }
.rx-count { font-size: 11.5px; color: var(--fg-muted); }
.rx-list { overflow: auto; flex: 1; min-height: 160px; margin: 0 -4px; }
.rx-item { display: block; width: 100%; text-align: left; border: 0; background: none; color: var(--fg); font: inherit; padding: 6px 8px; border-radius: 8px; cursor: pointer; }
.rx-item:hover { background: var(--surface-alt); }
.rx-item.active { background: var(--accent-soft); }
.rx-item b { display: block; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rx-item span { display: block; font-size: 11.5px; color: var(--fg-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.rx-main { min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.rx-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; min-width: 0; }
.rx-empty { color: var(--fg-muted); font-size: 13.5px; }
.rx-empty h2 { margin: 0 0 6px; color: var(--fg); font-size: 18px; }
.rx-head { display: flex; flex-wrap: wrap; gap: 10px; justify-content: space-between; align-items: center; }
.rx-head h2 { margin: 0; font-size: 18px; }
.rx-head .sub { font-size: 12.5px; color: var(--fg-muted); }
.rx-head .sub a { color: var(--accent); }
.rx-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 12.5px; }
.rx-toggle { display: inline-flex; gap: 5px; align-items: center; color: var(--fg-muted); cursor: pointer; }
.rx-btn { border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg); border-radius: 8px; padding: 5px 11px; font: inherit; font-size: 12.5px; cursor: pointer; }
.rx-btn:hover { border-color: var(--accent); }
.rx-pages { display: flex; gap: 6px; overflow-x: auto; margin-top: 12px; padding-bottom: 2px; }
.rx-page { flex: 0 0 auto; border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg); border-radius: 8px; padding: 6px 12px; font: inherit; font-size: 12.5px; cursor: pointer; white-space: nowrap; }
.rx-page.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.rx-page.hid { border-style: dashed; opacity: .75; }
.rx-canvas-card { padding: 12px; }
.rx-canvas-wrap { overflow: auto; }
.rx-canvas { position: relative; isolation: isolate; background: #fff; border: 1px solid #cbd5e1; box-shadow: 0 2px 10px rgba(15,23,42,.08); margin: 0 auto; }
[data-theme="dark"] .rx-canvas { background: #1e293b; border-color: #334155; }
.rx-v { position: absolute; box-sizing: border-box; border: 1px solid #cbd5e1; background: rgba(248,250,252,.92); border-radius: 4px; overflow: hidden; cursor: pointer; display: flex; flex-direction: column; font-size: 10.5px; color: #334155; }
[data-theme="dark"] .rx-v { background: rgba(30,41,59,.92); border-color: #475569; color: #cbd5e1; }
.rx-v:hover { border-color: #0b63ce; box-shadow: 0 0 0 1px #0b63ce; z-index: 100000 !important; }
.rx-v.sel { border-color: #0b63ce; box-shadow: 0 0 0 2px #0b63ce; z-index: 100001 !important; }
.rx-v.deco { background: transparent; border-style: dashed; border-color: rgba(148,163,184,.55); }
.rx-v.group { background: transparent; border: 1px dotted rgba(148,163,184,.6); pointer-events: none; }
.rx-v.hidden-v { opacity: .45; border-style: dashed; }
.rx-v .vt { padding: 3px 6px; font-weight: 650; font-size: 10.5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #0f172a; flex: 0 0 auto; }
[data-theme="dark"] .rx-v .vt { color: #e2e8f0; }
.rx-v .vt small { font-weight: 500; color: #64748b; margin-left: 4px; }
.rx-v .vb { flex: 1 1 auto; position: relative; min-height: 0; overflow: hidden; }
.rx-v .vb svg { position: absolute; inset: 4px 6px; width: calc(100% - 12px); height: calc(100% - 8px); }
.rx-v .vb svg * { vector-effect: non-scaling-stroke; }
.rx-v .vf { flex: 0 0 auto; padding: 2px 4px 3px; display: flex; flex-wrap: wrap; gap: 2px; max-height: 45%; overflow: hidden; }
.rx-f { display: inline-block; border-radius: 7px; padding: 0 5px; font-size: 9.5px; line-height: 15px; white-space: nowrap; max-width: 100%; overflow: hidden; text-overflow: ellipsis; background: #e2e8f0; color: #334155; cursor: pointer; border: 0; font-family: inherit; }
.rx-f.m { background: #fce7f3; color: #9d174d; }
.rx-f.r { background: #ede9fe; color: #5b21b6; }
.rx-f.x { background: #fee2e2; color: #991b1b; }
.rx-f.flt { background: #fef3c7; color: #92400e; }
.rx-f:hover { outline: 1px solid #0b63ce; }
.rx-v .card-val { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; font-weight: 700; color: #94a3b8; font-size: 13px; text-align: center; padding: 2px 6px; }
.rx-v .slc { padding: 2px 6px; font-size: 10px; line-height: 1.35; }
.rx-v .slc .on { color: #0b63ce; font-weight: 600; }
.rx-v .txt { padding: 2px 6px; white-space: pre-wrap; font-size: 10px; color: #475569; }
.rx-legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 12px; color: var(--fg-muted); margin-top: 8px; }
.rx-legend i { display: inline-block; width: 12px; height: 10px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; background: #e2e8f0; }
.rx-legend i.x { background: #fee2e2; }
.rx-legend i.m { background: #fce7f3; } .rx-legend i.r { background: #ede9fe; } .rx-legend i.f { background: #fef3c7; }
.rx-stage { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
@media (max-width: 1200px) { .rx-stage { grid-template-columns: minmax(0, 1fr); } }
.rx-inspect { overflow: auto; max-height: calc(62vh + 70px); }
@media (max-width: 1200px) { .rx-inspect { max-height: 420px; } }
.rx-inspect h3, #rxLineage h3 { margin: 0 0 4px; font-size: 15px; word-break: break-word; }
.rx-inspect h4, #rxLineage h4 { margin: 12px 0 4px; font-size: 12.5px; text-transform: uppercase; letter-spacing: .03em; color: var(--fg-muted); }
#rxLineage .e2e-map { max-height: 60vh; }
#rxLineage .rx-detail { border-top: 1px solid var(--border); margin-top: 14px; padding-top: 12px; }
.rx-detail-hint { font-size: 12px; color: var(--fg-muted); margin: 0 0 6px; }
.rx-role { margin: 6px 0; font-size: 12.5px; }
.rx-role > b { display: block; font-size: 11.5px; color: var(--fg-muted); margin-bottom: 3px; }
.rx-chip { display: inline-flex; gap: 4px; align-items: center; border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg); border-radius: 999px; padding: 3px 10px; font: inherit; font-size: 12px; cursor: pointer; margin: 0 5px 5px 0; max-width: 100%; text-align: left; }
.rx-chip:hover { border-color: var(--accent); }
.rx-chip.on { border-color: var(--accent); background: var(--accent-soft); }
.rx-chip i { font-style: normal; font-size: 10.5px; border-radius: 6px; padding: 0 5px; background: #e2e8f0; color: #334155; }
.rx-chip i.m { background: #fce7f3; color: #9d174d; } .rx-chip i.r { background: #ede9fe; color: #5b21b6; } .rx-chip i.x { background: #fee2e2; color: #991b1b; }
.rx-chip small { color: var(--fg-muted); }
.rx-flt { border: 1px solid var(--border); border-left: 3px solid #f59e0b; border-radius: 8px; padding: 6px 10px; margin: 0 0 6px; font-size: 12.5px; cursor: pointer; background: var(--surface-alt); }
.rx-flt:hover { border-color: var(--accent); border-left-color: #f59e0b; }
.rx-flt code { font-size: 11.5px; word-break: break-word; }
.rx-flt b { word-break: break-word; overflow-wrap: anywhere; }
.rx-flt small { color: var(--fg-muted); }
.rx-vlist { columns: 2 220px; font-size: 12.5px; }
.rx-vlist button { display: block; border: 0; background: none; color: var(--accent); font: inherit; cursor: pointer; padding: 1px 0; text-align: left; }
.rx-lin-head { display: flex; justify-content: space-between; gap: 10px; flex-wrap: wrap; align-items: flex-start; }
.rx-lin-head a { font-size: 12.5px; color: var(--accent); text-decoration: none; font-weight: 600; white-space: nowrap; }
#rxLineage pre.rx-code { background: var(--code-bg); color: var(--code-fg); border: 1px solid var(--code-border); border-left: 3px solid var(--code-accent-bar); border-radius: 8px; padding: 10px 12px; font-size: 12px; overflow: auto; max-height: 320px; white-space: pre-wrap; word-break: break-word; }
.rx-used { font-size: 12.5px; max-height: 220px; overflow: auto; }
.rx-used button { border: 0; background: none; color: var(--accent); font: inherit; cursor: pointer; padding: 1px 0; text-align: left; display: block; }
"""

REPORT_JS = r"""
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  if (!$("tab-reports")) return;
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function log(ev) { try { if (window.pbidocLog) window.pbidocLog(ev); } catch (e) { /* ignore */ } }
  var IDX = window.REPORT_INDEX || [];
  var cur = { rid: "", page: "", vid: "", field: null, lineageNode: "" };
  var loaded = false;

  function loadScript(src) {
    if (window.PBIDOC_SHELL) return window.PBIDOC_SHELL.load(src).then(function (t) { var s = document.createElement("script"); s.textContent = t; document.head.appendChild(s); });
    return new Promise(function (res, rej) { var s = document.createElement("script"); s.src = src; s.onload = function () { res(); }; s.onerror = function () { rej(new Error("Could not load " + src)); }; document.head.appendChild(s); });
  }
  function loadReport(rid) {
    var R = window.PBIDOC_REPORTS || {};
    if (R[rid]) return Promise.resolve(R[rid]);
    return loadScript("assets/reports/" + rid + ".js").then(function () { return (window.PBIDOC_REPORTS || {})[rid]; });
  }
  var graphP = null;
  function ensureGraph() {
    if (!graphP) graphP = (window.PORTAL_EXPORT ? window.PORTAL_EXPORT.ensureAll() : Promise.reject(new Error("export module missing")))
      .then(function () { return loadScript("assets/report_usage.js").catch(function () { return null; }); });
    return graphP;
  }

  // ---------------- report list (workspace -> model -> report) ----------------
  function opts(sel, list, allLabel) {
    var v = sel.value;
    sel.innerHTML = '<option value="">' + esc(allLabel) + "</option>" + list.map(function (x) { return '<option value="' + esc(x[0]) + '">' + esc(x[1]) + "</option>"; }).join("");
    sel.value = v; if (sel.value !== v) sel.value = "";
  }
  function renderFilters() {
    var ws = {}; IDX.forEach(function (r) { ws[r.workspace] = (ws[r.workspace] || 0) + 1; });
    opts($("rxWs"), Object.keys(ws).sort(function (a, b) { return a.toLowerCase().localeCompare(b.toLowerCase()); }).map(function (w) { return [w, w + " (" + ws[w] + ")"]; }), "All workspaces (" + Object.keys(ws).length + ")");
    var w = $("rxWs").value, ms = {};
    IDX.forEach(function (r) { if (!w || r.workspace === w) { var k = r.model_id || "-"; ms[k] = ms[k] || { n: 0, name: r.model ? r.model + (r.model_workspace && r.model_workspace !== r.workspace ? " (" + r.model_workspace + ")" : "") : (r.model_id ? "Model " + r.model_id.slice(0, 8) + " (not in catalog)" : "No model"), c: 0 }; ms[k].c++; } });
    opts($("rxModel"), Object.keys(ms).sort(function (a, b) { return ms[a].name.toLowerCase().localeCompare(ms[b].name.toLowerCase()); }).map(function (k) { return [k, ms[k].name + " (" + ms[k].c + ")"]; }), "All semantic models");
  }
  function renderList() {
    var w = $("rxWs").value, m = $("rxModel").value, q = $("rxSearch").value.trim().toLowerCase();
    var items = IDX.filter(function (r) {
      return (!w || r.workspace === w) && (!m || (r.model_id || "-") === m) && (!q || (r.name + " " + r.model + " " + r.workspace).toLowerCase().indexOf(q) >= 0);
    });
    $("rxCount").textContent = items.length + " report(s)";
    $("rxList").innerHTML = items.map(function (r) {
      return '<button type="button" class="rx-item' + (r.id === cur.rid ? " active" : "") + '" data-rx-report="' + esc(r.id) + '"><b>' + esc(r.name) + "</b><span>" +
        esc((r.model || "?") + " · " + r.visible_pages + " page(s) · " + r.visuals + " visuals" + (r.report_measures ? " · " + r.report_measures + " report measures" : "") + (w ? "" : " · " + r.workspace)) + "</span></button>";
    }).join("") || '<div class="rx-empty">No reports match.</div>';
  }

  // ---------------- canvas ----------------
  var DECO = { shape: 1, image: 1, actionButton: 1, basicShape: 1, bookmarkNavigator: 1, pageNavigator: 1 };
  var TYPE_LABEL = { slicer: "Slicer", advancedSlicerVisual: "Slicer", textSlicer: "Text slicer", listSlicer: "List slicer", pivotTable: "Matrix", tableEx: "Table", card: "Card", cardVisual: "Card",
    multiRowCard: "Multi-row card", kpi: "KPI", gauge: "Gauge", columnChart: "Stacked column", clusteredColumnChart: "Clustered column", hundredPercentStackedColumnChart: "100% column",
    barChart: "Stacked bar", clusteredBarChart: "Clustered bar", hundredPercentStackedBarChart: "100% bar", lineChart: "Line chart", areaChart: "Area chart", stackedAreaChart: "Stacked area",
    lineClusteredColumnComboChart: "Line & column", lineStackedColumnComboChart: "Line & stacked column", donutChart: "Donut", pieChart: "Pie", funnel: "Funnel", treemap: "Treemap",
    waterfallChart: "Waterfall", scatterChart: "Scatter", map: "Map", filledMap: "Filled map", azureMap: "Azure map", ribbonChart: "Ribbon", decompositionTreeVisual: "Decomposition tree",
    textbox: "Text box", shape: "Shape", image: "Image", actionButton: "Button", bookmarkNavigator: "Bookmark navigator", pageNavigator: "Page navigator", group: "Group", qnaVisual: "Q&A" };
  function typeLabel(t) { return TYPE_LABEL[t] || (/^[a-z]+[A-F0-9]{20,}/i.test(t) ? "Custom visual (" + t.replace(/[A-F0-9]{20,}$/i, "") + ")" : t); }
  function fieldName(f) { return (f.agg ? f.agg + " of " : "") + (f.label || f.name) + (f.level ? " (" + f.level + ")" : ""); }
  function fcls(f) { return !f.node ? "x" : f.kind === "measure" ? (/:rpt:/.test(f.node) ? "r" : "m") : ""; }
  function silhouette(t) {
    var g = "#cbd5e1";
    if (/column|ribbon|waterfall/i.test(t)) return '<svg viewBox="0 0 100 60" preserveAspectRatio="none"><g fill="' + g + '"><rect x="8" y="30" width="10" height="26"/><rect x="24" y="18" width="10" height="38"/><rect x="40" y="26" width="10" height="30"/><rect x="56" y="10" width="10" height="46"/><rect x="72" y="22" width="10" height="34"/></g></svg>';
    if (/bar/i.test(t)) return '<svg viewBox="0 0 100 60" preserveAspectRatio="none"><g fill="' + g + '"><rect x="4" y="6" width="70" height="8"/><rect x="4" y="19" width="52" height="8"/><rect x="4" y="32" width="86" height="8"/><rect x="4" y="45" width="40" height="8"/></g></svg>';
    if (/line|area/i.test(t)) return '<svg viewBox="0 0 100 60" preserveAspectRatio="none"><polyline points="4,48 20,36 36,40 52,22 68,28 84,12 96,18" fill="none" stroke="' + g + '" stroke-width="3"/></svg>';
    if (/donut|pie/i.test(t)) return '<svg viewBox="0 0 100 60"><circle cx="50" cy="30" r="22" fill="none" stroke="' + g + '" stroke-width="' + (/donut/i.test(t) ? 10 : 22) + '"/></svg>';
    if (/funnel/i.test(t)) return '<svg viewBox="0 0 100 60" preserveAspectRatio="none"><g fill="' + g + '"><rect x="8" y="6" width="84" height="9"/><rect x="18" y="19" width="64" height="9"/><rect x="28" y="32" width="44" height="9"/><rect x="38" y="45" width="24" height="9"/></g></svg>';
    if (/pivot|table/i.test(t)) return '<svg viewBox="0 0 100 60" preserveAspectRatio="none"><g stroke="' + g + '" stroke-width="1" opacity=".8"><line x1="0" y1="10" x2="100" y2="10"/><line x1="0" y1="22" x2="100" y2="22"/><line x1="0" y1="34" x2="100" y2="34"/><line x1="0" y1="46" x2="100" y2="46"/><line x1="34" y1="0" x2="34" y2="60"/><line x1="67" y1="0" x2="67" y2="60"/></g></svg>';
    if (/gauge/i.test(t)) return '<svg viewBox="0 0 100 60"><path d="M20 50 A30 30 0 0 1 80 50" fill="none" stroke="' + g + '" stroke-width="10"/></svg>';
    if (/map/i.test(t)) return '<svg viewBox="0 0 100 60" preserveAspectRatio="none"><path d="M10 20 Q30 5 50 18 T90 16 L88 48 Q60 56 40 46 T12 50 Z" fill="' + g + '"/></svg>';
    if (/scatter/i.test(t)) return '<svg viewBox="0 0 100 60"><g fill="' + g + '"><circle cx="20" cy="40" r="3"/><circle cx="35" cy="28" r="4"/><circle cx="52" cy="34" r="3"/><circle cx="66" cy="18" r="5"/><circle cx="80" cy="24" r="3"/></g></svg>';
    return "";
  }
  function allFields(v) { var o = []; Object.keys(v.roles || {}).forEach(function (r) { (v.roles[r] || []).forEach(function (f) { o.push(f); }); }); return o; }
  function body(v) {
    var t = v.type || "";
    if (t === "textbox") return '<div class="txt">' + esc(v.text || "") + "</div>";
    if (/slicer/i.test(t)) {
      var vals = (v.selection && v.selection.values) || [];
      return '<div class="slc">' + (vals.length ? vals.slice(0, 12).map(function (x) { return '<div class="on">☑ ' + esc(x) + "</div>"; }).join("") + (vals.length > 12 ? "<div>+" + (vals.length - 12) + " more</div>" : "") : "<div>☐ All</div>") + "</div>";
    }
    if (/card|kpi/i.test(t)) { var f0 = allFields(v).filter(function (f) { return f.kind === "measure" || f.agg; })[0] || allFields(v)[0]; return f0 ? '<div class="card-val">' + esc(fieldName(f0)) + "</div>" : ""; }
    return silhouette(t);
  }
  var page = null, rep = null;
  function renderCanvas() {
    if (!rep || !page) return;
    var wrap = $("rxCanvas").parentElement, maxH = Math.max(320, window.innerHeight * 0.62);
    var scale = Math.min((Math.max(320, wrap.clientWidth - 4)) / page.width, maxH / page.height), width = page.width * scale;
    var showHidden = $("rxShowHidden").checked, showFields = $("rxShowFields").checked;
    $("rxCanvas").style.width = width + "px";
    $("rxCanvas").style.height = Math.round(page.height * scale) + "px";
    var html = page.visuals.slice().sort(function (a, b) { return (a.z || 0) - (b.z || 0); }).map(function (v, i) {
      if (v.hidden && !showHidden) return "";
      var t = v.type || "?", deco = DECO[t], fields = allFields(v);
      var cls = "rx-v" + (t === "group" ? " group" : "") + (deco ? " deco" : "") + (v.hidden ? " hidden-v" : "") + (v.id === cur.vid ? " sel" : "");
      var style = "left:" + (v.x * scale).toFixed(1) + "px;top:" + (v.y * scale).toFixed(1) + "px;width:" + Math.max(6, v.w * scale).toFixed(1) + "px;height:" + Math.max(6, v.h * scale).toFixed(1) + "px;z-index:" + (i + 1);
      if (t === "group") return '<div class="' + cls + '" style="' + style + '"></div>';
      var chips = showFields && v.h * scale > 46 ? fields.slice(0, 8).map(function (f, j) {
        return '<button type="button" class="rx-f ' + fcls(f) + '" data-rx-vfield="' + esc(v.id) + ":" + j + '" title="' + esc(f.table + "[" + f.name + "]") + '">' + esc(fieldName(f)) + "</button>";
      }).join("") + (fields.length > 8 ? '<span class="rx-f">+' + (fields.length - 8) + "</span>" : "") + ((v.filters || []).length ? '<span class="rx-f flt">' + v.filters.length + " filter(s)</span>" : "") : "";
      return '<div class="' + cls + '" style="' + style + '" data-rx-visual="' + esc(v.id) + '" title="' + esc(typeLabel(t) + (v.title ? ": " + v.title : "")) + '">' +
        (v.h * scale > 16 ? '<div class="vt">' + esc(v.title || typeLabel(t)) + (v.title ? "<small>" + esc(typeLabel(t)) + "</small>" : "") + "</div>" : "") +
        '<div class="vb">' + (v.h * scale > 40 ? body(v) : "") + "</div>" + (chips ? '<div class="vf">' + chips + "</div>" : "") + "</div>";
    }).join("");
    $("rxCanvas").innerHTML = html;
  }

  // ---------------- inspector ----------------
  function chip(f, ref, extra) {
    return '<button type="button" class="rx-chip' + (cur.field && cur.field.ref === ref ? " on" : "") + '" data-rx-field="' + esc(ref) + '"><i class="' + fcls(f) + '">' +
      (f.kind === "measure" ? (/:rpt:/.test(f.node || "") ? "report measure" : "measure") : f.kind) + "</i>" + esc(fieldName(f)) + " <small>" + esc(f.table) + "</small>" + (extra || "") + "</button>";
  }
  function filterBlock(fl, ref) {
    return '<div class="rx-flt" data-rx-field="' + esc(ref) + '"><b>' + esc(fl.field ? fl.field.table + "[" + fl.field.name + "]" : fl.name) + "</b> <small>" + esc(fl.level + " filter" + (fl.type ? " · " + fl.type : "") + (fl.hidden ? " · hidden" : "") + (fl.locked ? " · locked" : "")) +
      "</small><br>" + (fl.condition ? "<code>" + esc(fl.condition) + "</code>" : "<small>No value selected (all)</small>") + "</div>";
  }
  var REFS = {};
  function renderInspector() {
    REFS = {};
    var h = "";
    if (!cur.vid) {
      h += "<h3>" + esc(page.display) + "</h3><div style='font-size:12.5px;color:var(--fg-muted)'>Page " + (page.hidden ? "(hidden) " : "") + "· " + page.visuals.length + " visuals · " + Math.round(page.width) + " × " + Math.round(page.height) + "</div>";
      h += "<h4>Page filters (" + (page.filters || []).length + ")</h4>" + ((page.filters || []).map(function (fl, i) { var ref = "pf:" + i; REFS[ref] = fl.field; return filterBlock(fl, ref); }).join("") || "<div class='rx-empty'>None</div>");
      var sl = page.visuals.filter(function (v) { return /slicer/i.test(v.type); });
      if (sl.length) {
        h += "<h4>Slicers (" + sl.length + ")</h4>" + sl.map(function (v) {
          return '<div class="rx-flt" data-rx-visual="' + esc(v.id) + '"><b>' + esc(v.title || allFields(v).map(fieldName).join(", ") || "Slicer") + "</b><br>" + (v.selection ? "<code>" + esc(v.selection.condition) + "</code>" : "<small>No selection (all)</small>") + "</div>";
        }).join("");
      }
      var data = page.visuals.filter(function (v) { return v.type !== "group" && !DECO[v.type] && v.type !== "textbox"; });
      h += "<h4>Visuals (" + data.length + ")</h4><div class='rx-vlist'>" + data.map(function (v) { return '<button type="button" data-rx-visual="' + esc(v.id) + '">' + esc((v.title || typeLabel(v.type)) + (v.title ? " · " + typeLabel(v.type) : "")) + "</button>"; }).join("") + "</div>";
    } else {
      var v = page.visuals.filter(function (x) { return x.id === cur.vid; })[0];
      if (!v) { cur.vid = ""; return renderInspector(); }
      h += "<h3>" + esc(v.title || typeLabel(v.type)) + "</h3><div style='font-size:12.5px;color:var(--fg-muted)'>" + esc(typeLabel(v.type)) + (v.hidden ? " · hidden" : "") + " · " + Math.round(v.w) + " × " + Math.round(v.h) + " at (" + Math.round(v.x) + ", " + Math.round(v.y) + ")" +
        ' · <a href="#" data-rx-back="1">back to page</a></div>';
      Object.keys(v.roles || {}).forEach(function (role) {
        h += '<div class="rx-role"><b>' + esc(role) + "</b>" + v.roles[role].map(function (f, j) { var ref = "v:" + role + ":" + j; REFS[ref] = f; return chip(f, ref); }).join("") + "</div>";
      });
      if (!Object.keys(v.roles || {}).length) h += "<div class='rx-empty' style='margin-top:8px'>This visual is not bound to any field.</div>";
      if (v.selection) { REFS["sel"] = (allFields(v)[0]); h += "<h4>Slicer selection</h4>" + '<div class="rx-flt" data-rx-field="sel"><code>' + esc(v.selection.condition) + "</code></div>"; }
      if ((v.filters || []).length) h += "<h4>Visual filters (" + v.filters.length + ")</h4>" + v.filters.map(function (fl, i) { var ref = "vf:" + i; REFS[ref] = fl.field; return filterBlock(fl, ref); }).join("");
      if (v.text) h += "<h4>Text</h4><div style='white-space:pre-wrap;font-size:12.5px'>" + esc(v.text) + "</div>";
    }
    $("rxInspect").innerHTML = h;
  }

  // ---------------- lineage panel ----------------
  function usedIn(f) {
    var U = window.REPORT_USAGE; if (!U || !f) return "";
    var key = f.kind === "measure" ? (f.node || "") : "col:" + rep.dataset_id + ":" + f.table + "[" + f.name + "]";
    var list = (U.use || {})[key] || [];
    if (!list.length) return "";
    var byReport = {};
    list.forEach(function (u) { (byReport[u[0]] = byReport[u[0]] || []).push(u); });
    return "<h4>Used in " + list.length + " place(s) across " + Object.keys(byReport).length + " report(s)</h4><div class='rx-used'>" + Object.keys(byReport).slice(0, 60).map(function (ri) {
      var r = U.reports[ri];
      return "<div><b>" + esc(r[1]) + "</b> <small style='color:var(--fg-muted)'>" + esc(r[2]) + "</small>" + byReport[ri].slice(0, 8).map(function (u) {
        return '<button type="button" data-rx-goto="' + esc(r[0] + "|" + u[1] + "|" + u[2]) + '">→ ' + esc((u[5] ? u[5] + " › " : "") + (TYPE_LABEL[u[3]] || u[3] || "") + " · " + u[4]) + "</button>";
      }).join("") + "</div>";
    }).join("") + "</div>";
  }
  function renderLineage(f) {
    var box = $("rxLineage");
    if (!f) { box.innerHTML = '<div class="rx-empty">Select a field, filter or slicer to see its lineage.</div>'; return; }
    var head = '<div class="rx-lin-head"><div><h3>' + esc(fieldName(f)) + '</h3><div style="font-size:12.5px;color:var(--fg-muted)">' + esc((f.kind === "measure" ? "Measure" : f.kind === "hierarchy" ? "Hierarchy" : "Column") + " · " + f.table + "[" + f.name + "]" + (f.agg ? " · aggregated with " + f.agg : "")) + "</div></div>";
    if (!f.node) {
      box.innerHTML = head + "</div><p class='rx-empty'>Not found in the catalog: " + (rep.model_in_catalog ? "the field does not exist in the semantic model definition (renamed or removed?)." : "the semantic model of this report is not in the catalog (outside the selected workspaces or not readable).") + "</p>" + usedIn(f);
      return;
    }
    box.innerHTML = head + '<a href="index.html#e2e:node=' + encodeURIComponent(f.node) + '">Open in End-to-End explorer →</a></div><div class="rx-empty" style="margin-top:8px">Loading lineage...</div>';
    ensureGraph().then(function () {
      var A = window.E2E_API, N = window.E2E_GRAPH.nodes, n = N[f.node];
      if (!n) { box.innerHTML = head + "</div><p class='rx-empty'>Lineage node not found.</p>"; return; }
      cur.lineageNode = f.node;
      var col = null;
      if (f.kind !== "measure" && n.kind !== "calc_column") col = (n.columns || []).filter(function (c) { return c.name.toLowerCase() === String(f.name).toLowerCase(); })[0];
      var kv = [["Object", (A.KIND_LABEL[n.kind] || n.kind) + (n.report ? " (report-level, " + n.report + ")" : "")], ["Semantic model", n.model || n.group], ["Workspace", n.workspace]];
      if (col) kv.push(["Column", col.name + " · " + col.type + (col.source ? " · source column " + col.source : "") + (col.calculated ? " · calculated" : "")]);
      if (n.format) kv.push(["Format", n.format]);
      if (n.folder) kv.push(["Display folder", n.folder]);
      if (n.description) kv.push(["Description", n.description]);
      var tr = A.trace(f.node, "up"), counts = {};
      tr.order.forEach(function (x) { var k = N[x].kind; counts[k] = (counts[k] || 0) + 1; });
      var maxL = 0; Object.keys(tr.layer || {}).forEach(function (k) { maxL = Math.max(maxL, tr.layer[k]); });
      var summary = Object.keys(counts).map(function (k) { return counts[k] + " " + (A.KIND_LABEL[k] || k); }).join(" · ") + (maxL ? " · " + maxL + " dataflow layer(s)" : "");
      box.innerHTML = head + '<a href="index.html#e2e:node=' + encodeURIComponent(f.node) + '">Open in End-to-End explorer \u2192</a></div>' +
        (col ? '<dl class="e2e-kv">' + kv.filter(function (r) { return r[0] === "Column"; }).map(function (r) { return "<dt>" + esc(r[0]) + "</dt><dd>" + esc(r[1]) + "</dd>"; }).join("") + "</dl>" : "") +
        "<h4>Upstream lineage</h4><div style='font-size:12px;color:var(--fg-muted);margin-bottom:6px'>" + esc(summary) + " \u00b7 click any box to show its details, DAX, Power Query steps and SQL below</div>" +
        '<div class="e2e-map" id="rxMap">' + A.mapSvg(tr, { fit: true, sel: f.node }) + "</div>" +
        '<div class="rx-detail"><div class="e2e-detail" id="rxNodeDetail"></div></div>' + usedIn(f);
      showNode(f.node, true);
      var svgEl = $("rxMap").querySelector("svg"), natW = svgEl && svgEl.viewBox && svgEl.viewBox.baseVal ? svgEl.viewBox.baseVal.width : 0;
      if (natW && svgEl.getBoundingClientRect().width / natW < 0.7) $("rxMap").innerHTML = A.mapSvg(tr, { zoom: 0.7, sel: f.node });
      document.querySelectorAll("#rxMap .nd").forEach(function (g) { g.classList.toggle("sel", g.getAttribute("data-id") === f.node); });
      log({ type: "report-explorer-lineage", report: cur.rid, node: f.node, nodes: tr.order.length });
    }).catch(function (err) { box.innerHTML = head + "</div><p class='rx-empty'>Could not load the lineage graph: " + esc(err.message) + "</p>"; });
  }

  // Details of one lineage object (DAX / M with step browser / native SQL / dependencies), rendered by the
  // End-to-End explorer's own panel code but kept inside the Report Explorer
  function showNode(id, isField) {
    var A = window.E2E_API, el = $("rxNodeDetail");
    if (!A || !el || !window.E2E_GRAPH.nodes[id]) return;
    cur.lineageNode = id;
    A.renderDetail(id, { target: el, map: "#rxMap", usage: !isField, reroot: false });
    log({ type: "report-explorer-node", report: cur.rid, node: id });
  }

  // ---------------- navigation / state ----------------
  function setHash() {
    var parts = ["r=" + encodeURIComponent(cur.rid)];
    if (cur.page) parts.push("p=" + encodeURIComponent(cur.page));
    if (cur.vid) parts.push("v=" + encodeURIComponent(cur.vid));
    try { history.replaceState(null, "", "#rpt:" + parts.join("&")); } catch (e) { /* ignore */ }
  }
  function openReport(rid, pageName, vid) {
    cur.rid = rid; cur.vid = vid || ""; cur.field = null;
    window.REPORT_EXPLORER_CURRENT = rid;
    renderList();
    $("rxWelcome").style.display = "none"; $("rxMain").style.display = "";
    $("rxTitle").textContent = "Loading...";
    return loadReport(rid).then(function (r) {
      if (!r) throw new Error("Report layout not found");
      rep = r;
      var pg = r.pages.filter(function (p) { return p.name === pageName; })[0] || r.pages.filter(function (p) { return !p.hidden; })[0] || r.pages[0];
      $("rxTitle").textContent = r.name;
      $("rxSub").innerHTML = esc(r.workspace) + " · semantic model: <b>" + esc(r.model || "not in catalog") + "</b>" + (r.model_workspace && r.model_workspace !== r.workspace ? " (" + esc(r.model_workspace) + ")" : "") +
        " · " + r.pages.length + " page(s), " + r.visual_count + " visuals · " + esc(r.format) + (r.web_url ? ' · <a href="' + esc(r.web_url) + '" target="_blank" rel="noopener">Open in Power BI</a>' : "");
      $("rxReportFilters").textContent = "Report filters (" + (r.filters || []).length + ")";
      showPage(pg ? pg.name : "", vid);
      log({ type: "report-explorer-open", report: rid, pages: r.pages.length, visuals: r.visual_count });
    }).catch(function (err) { $("rxTitle").textContent = "Could not open report: " + err.message; });
  }
  function showPage(name, vid) {
    page = rep.pages.filter(function (p) { return p.name === name; })[0];
    if (!page) return;
    cur.page = name; cur.vid = vid || ""; cur.field = null;
    $("rxPages").innerHTML = rep.pages.map(function (p) {
      return '<button type="button" class="rx-page' + (p.name === name ? " active" : "") + (p.hidden ? " hid" : "") + '" data-rx-page="' + esc(p.name) + '" title="' + (p.hidden ? "Hidden page · " : "") + p.visuals.length + ' visuals">' + esc(p.display) + "</button>";
    }).join("");
    renderCanvas(); renderInspector(); renderLineage(null); setHash();
  }
  function selectVisual(vid) {
    cur.vid = vid; cur.field = null;
    document.querySelectorAll("#rxCanvas .rx-v").forEach(function (el) { el.classList.toggle("sel", el.getAttribute("data-rx-visual") === vid); });
    renderInspector(); renderLineage(null); setHash();
  }
  function selectField(ref, f) {
    cur.field = { ref: ref };
    document.querySelectorAll("#rxInspect [data-rx-field]").forEach(function (el) { el.classList.toggle("on", el.getAttribute("data-rx-field") === ref); });
    renderLineage(f);
  }
  function showReportFilters() {
    cur.vid = ""; REFS = {};
    $("rxInspect").innerHTML = "<h3>Report-level filters</h3>" + ((rep.filters || []).map(function (fl, i) { var ref = "rf:" + i; REFS[ref] = fl.field; return filterBlock(fl, ref); }).join("") || "<div class='rx-empty'>None</div>") +
      '<div style="margin-top:8px"><a href="#" data-rx-back="1">back to page</a></div>';
  }

  function init() {
    if (loaded) return;
    loaded = true;
    renderFilters(); renderList();
    ensureGraph();  // start loading the lineage graph in the background
    $("rxWs").addEventListener("change", function () { $("rxModel").value = ""; renderFilters(); renderList(); });
    $("rxModel").addEventListener("change", renderList);
    $("rxSearch").addEventListener("input", renderList);
    $("rxShowHidden").addEventListener("change", renderCanvas);
    $("rxShowFields").addEventListener("change", renderCanvas);
    window.addEventListener("resize", function () { if ($("tab-reports").classList.contains("active")) renderCanvas(); });
  }
  function fromHash() {
    var m = location.hash.match(/^#rpt(?::(.*))?$/);
    if (!m) return false;
    var o = {};
    (m[1] || "").split("&").forEach(function (kv) { var i = kv.indexOf("="); if (i > 0) { try { o[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* ignore */ } } });
    var tab = document.querySelector('.top-tab[data-tab="tab-reports"]');
    if (tab && !$("tab-reports").classList.contains("active")) tab.click();
    init();
    var r = IDX.filter(function (x) { return x.id === o.r; })[0];
    if (r) {
      if ($("rxWs").value && $("rxWs").value !== r.workspace) { $("rxWs").value = ""; renderFilters(); }
      if (o.r !== cur.rid || !rep) openReport(o.r, o.p, o.v);
      else if (o.p && o.p !== cur.page) showPage(o.p, o.v);
      else if (o.v && o.v !== cur.vid) selectVisual(o.v);
    }
    return true;
  }

  document.addEventListener("click", function (e) {
    var t;
    if ((t = e.target.closest('.top-tab[data-tab]'))) {
      var id = t.getAttribute("data-tab");
      setTimeout(function () {
        if (id === "tab-reports") { init(); if (cur.rid) { setHash(); renderCanvas(); } else { try { history.replaceState(null, "", "#rpt"); } catch (err) { /* ignore */ } } }
        else if (/^#rpt/.test(location.hash)) { try { history.replaceState(null, "", location.pathname + location.search); } catch (err) { /* ignore */ } }
      }, 0);
      return;
    }
    if (!e.target.closest("#tab-reports")) return;
    if ((t = e.target.closest("[data-rx-report]"))) { openReport(t.getAttribute("data-rx-report")); return; }
    if ((t = e.target.closest("[data-rx-page]"))) { showPage(t.getAttribute("data-rx-page")); return; }
    if ((t = e.target.closest("[data-rx-vfield]"))) {
      e.stopPropagation();
      var p = t.getAttribute("data-rx-vfield"), k = p.lastIndexOf(":"), vid = p.slice(0, k), j = +p.slice(k + 1);
      selectVisual(vid);
      var v = page.visuals.filter(function (x) { return x.id === vid; })[0], f = allFields(v)[j];
      var ref = null;
      Object.keys(REFS).forEach(function (r) { if (REFS[r] === f) ref = r; });
      selectField(ref || "x", f);
      return;
    }
    if ((t = e.target.closest("[data-rx-visual]"))) { selectVisual(t.getAttribute("data-rx-visual")); return; }
    if ((t = e.target.closest("[data-rx-field]"))) { var ref2 = t.getAttribute("data-rx-field"); selectField(ref2, REFS[ref2]); return; }
    if ((t = e.target.closest("[data-rx-back]"))) { e.preventDefault(); cur.vid = ""; selectVisual(""); return; }
    if (e.target.closest("#rxReportFilters")) { showReportFilters(); return; }
    if ((t = e.target.closest("[data-rx-goto]"))) {
      var g = t.getAttribute("data-rx-goto").split("|");
      if (g[0] === cur.rid) { if (g[1] !== cur.page) showPage(g[1], g[2]); else selectVisual(g[2]); }
      else openReport(g[0], g[1], g[2]);
      return;
    }
    if ((t = e.target.closest("#rxMap .nd"))) { showNode(t.getAttribute("data-id")); return; }
    if ((t = e.target.closest("#rxLineage [data-step-go]"))) { e.preventDefault(); if (!t.disabled) window.E2E_API.selectStep(+t.getAttribute("data-step-go")); return; }
    if ((t = e.target.closest("#rxLineage #e2eMainCode .stp"))) { window.E2E_API.selectStep(+t.getAttribute("data-step")); return; }
    if ((t = e.target.closest("#rxLineage [data-goto]"))) {
      e.preventDefault();
      var gid = t.getAttribute("data-goto");
      showNode(gid);
      var inMap = Array.prototype.some.call(document.querySelectorAll("#rxMap .nd"), function (g) { return g.getAttribute("data-id") === gid; });
      if (!inMap) $("rxNodeDetail").insertAdjacentHTML("afterbegin", "<p class='rx-detail-hint'>Not part of the upstream map above (it uses the selected object).</p>");
      $("rxNodeDetail").scrollIntoView({ block: "nearest" });
      return;
    }
    if ((t = e.target.closest("#rxLineage [data-copy-code]"))) {
      var pre = t.parentElement.querySelector("pre");
      if (pre && navigator.clipboard) { navigator.clipboard.writeText(pre.textContent); t.textContent = "Copied!"; setTimeout(function () { t.textContent = "Copy"; }, 1200); }
      return;
    }
    if ((t = e.target.closest("#rxLineage [data-open-report]"))) {
      var o = t.getAttribute("data-open-report").split("|");
      if (o[0] === cur.rid) { if (o[1] !== cur.page) showPage(o[1], o[2]); else selectVisual(o[2]); } else openReport(o[0], o[1], o[2]);
      return;
    }
  });
  window.addEventListener("hashchange", fromHash);
  document.addEventListener("DOMContentLoaded", function () { fromHash(); });
  window.REPORT_EXPLORER = { loadReport: loadReport, openReport: openReport };
})();
"""
