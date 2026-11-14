"""
Offline End-to-End Lineage Explorer page (`portal/e2e_lineage.html`).

Click any DAX measure (or table, dataset query, dataflow query, source) to see a layered reference
map from physical sources through every dataflow layer and the dataset's Power Query to the DAX
calculation chain, inspect the code of every step, and export measure documentation
(Markdown / HTML / Word) that walks from SQL scripts to Power Query to DAX.
"""

from __future__ import annotations

import json
from pathlib import Path

E2E_CSS = r"""
.e2e-wrap { display: grid; grid-template-columns: 320px minmax(0, 1fr); gap: 14px; padding: 14px 18px 24px; max-width: 1800px; margin: 0 auto; }
@media (max-width: 900px) { .e2e-wrap { grid-template-columns: minmax(0, 1fr); padding: 12px 16px; } }
.e2e-side { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 12px; display: flex; flex-direction: column; gap: 8px; max-height: calc(100vh - 120px); position: sticky; top: 100px; }
@media (max-width: 900px) { .e2e-side { position: static; max-height: 420px; } }
.e2e-side input, .e2e-side select { width: 100%; padding: 7px 10px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface-alt); color: var(--fg); font: inherit; font-size: 13px; }
.e2e-kpiwrap { max-width: 1800px; margin: 0 auto; padding: 14px 18px 0; }
.e2e-kpiwrap .kpi-grid { grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); margin-bottom: 0; }
.e2e-kpiwrap .kpi-card { padding: 10px 13px; }
.e2e-kpiwrap .kpi-card .val { font-size: 20px; }
html.e2e-embed header.topbar { display: none; }
html.e2e-embed body { background: var(--bg); }
html.e2e-embed .e2e-kpiwrap { padding-top: 2px; }
html.e2e-embed .e2e-kpiwrap .kpi-grid { grid-template-columns: repeat(auto-fit, minmax(112px, 1fr)); gap: 10px; }
html.e2e-embed .e2e-kpiwrap .kpi-card { padding: 9px 11px; }
html.e2e-embed .e2e-kpiwrap .kpi-card .lbl { font-size: 11.5px; }
html.e2e-embed .e2e-side { top: 10px; max-height: calc(100vh - 20px); }
.e2e-flbl { font-size: 11px; font-weight: 650; text-transform: uppercase; letter-spacing: .03em; color: var(--fg-muted); margin: 2px 0 -4px; }
.e2e-flbl a { color: var(--accent); text-transform: none; letter-spacing: 0; }
.e2e-kinds { display: flex; flex-wrap: wrap; gap: 4px; }
.e2e-kinds button { border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg-muted); border-radius: 999px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
.e2e-kinds button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
.e2e-list { overflow: auto; flex: 1; min-height: 120px; margin: 0 -4px; }
.e2e-item { padding: 6px 8px; border-radius: 8px; cursor: pointer; display: block; width: 100%; text-align: left; border: 0; background: none; color: var(--fg); font: inherit; }
.e2e-item:hover { background: var(--surface-alt); }
.e2e-item.active { background: var(--accent-soft); }
.e2e-item b { font-size: 13px; display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.e2e-item span { font-size: 11.5px; color: var(--fg-muted); display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.e2e-count { font-size: 11.5px; color: var(--fg-muted); }
.e2e-main { min-width: 0; display: flex; flex-direction: column; gap: 14px; }
.e2e-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 14px 16px; }
.e2e-head { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; justify-content: space-between; }
.e2e-head h2 { margin: 0; font-size: 18px; word-break: break-word; }
.e2e-head .sub { font-size: 12.5px; color: var(--fg-muted); }
.e2e-actions { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.e2e-btn { border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg); border-radius: 8px; padding: 6px 11px; font: inherit; font-size: 12.5px; cursor: pointer; }
.e2e-btn:hover { border-color: var(--accent); }
.e2e-btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.e2e-seg { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.e2e-seg button { border: 0; background: var(--surface-alt); color: var(--fg-muted); padding: 6px 11px; font: inherit; font-size: 12.5px; cursor: pointer; }
.e2e-seg button.active { background: var(--accent); color: #fff; }
.e2e-stats { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.e2e-stats span { font-size: 12px; padding: 3px 9px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface-alt); }
.e2e-map { overflow: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface-alt); max-height: 70vh; min-height: 120px; color: var(--fg); }
.e2e-map svg { display: block; }
.e2e-map .nd { cursor: pointer; }
.e2e-map .nd:hover rect.box { stroke-width: 2.5; }
.e2e-map .nd.sel rect.box { stroke-width: 3; }
.e2e-map path.ed { fill: none; stroke: #94a3b8; stroke-width: 1.4; opacity: .75; }
.e2e-map path.ed.hl { stroke: #0b63ce; stroke-width: 2.4; opacity: 1; }
.e2e-map.dim path.ed:not(.hl) { opacity: .15; }
.e2e-legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; color: var(--fg-muted); margin-top: 8px; }
.e2e-legend i { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: 5px; vertical-align: -1px; border: 1.5px solid; }
.e2e-detail h3 { margin: 0 0 4px; font-size: 16px; word-break: break-word; }
.e2e-kv { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 4px 14px; font-size: 13px; margin: 10px 0; }
.e2e-kv dt { color: var(--fg-muted); }
.e2e-kv dd { margin: 0; word-break: break-word; }
.e2e-chips { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 10px; }
.e2e-chip { border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg); border-radius: 999px; padding: 3px 10px; font-size: 12px; cursor: pointer; }
.e2e-chip:hover { border-color: var(--accent); }
.e2e-chip small { color: var(--fg-muted); }
.e2e-code { position: relative; }
.e2e-code pre { background: var(--code-bg); color: var(--code-fg); border: 1px solid var(--code-border); border-left: 3px solid var(--code-accent-bar); border-radius: 8px; padding: 12px 14px; overflow: auto; max-height: 460px; font-size: 12.5px; line-height: 1.5; margin: 6px 0 0; white-space: pre; }
.e2e-code .e2e-btn { position: absolute; top: 8px; right: 8px; font-size: 11.5px; padding: 3px 8px; }
.e2e-sec { margin-top: 16px; font-size: 13px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.e2e-sec b { font-size: 14px; }
.e2e-sec .hint { color: var(--fg-muted); }
.e2e-link { color: var(--accent); word-break: break-all; }
.e2e-code pre .stp { border-radius: 3px; cursor: pointer; }
.e2e-code pre .stp:hover { background: rgba(11, 99, 206, .08); }
.e2e-code pre .stp.on { background: rgba(250, 204, 21, .35); outline: 1px solid rgba(202, 138, 4, .6); }
.e2e-sqlhead { font-size: 12.5px; color: var(--fg-muted); margin-top: 10px; }
.e2e-sqlhead b { color: var(--fg); }
.e2e-steps { display: grid; grid-template-columns: minmax(220px, 34%) minmax(0, 1fr); gap: 12px; margin-top: 8px; }
@media (max-width: 760px) { .e2e-steps { grid-template-columns: minmax(0, 1fr); } }
.e2e-steplist { border: 1px solid var(--border); border-radius: 10px; max-height: 460px; overflow: auto; background: var(--surface-alt); }
.e2e-stepitem { display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 8px; width: 100%; text-align: left; border: 0; border-bottom: 1px solid var(--border);
  background: none; color: var(--fg); font: inherit; padding: 7px 9px; cursor: pointer; }
.e2e-stepitem:last-child { border-bottom: 0; }
.e2e-stepitem:hover { background: var(--surface); }
.e2e-stepitem.on { background: var(--accent-soft); }
.e2e-stepnum { width: 24px; height: 24px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-size: 11.5px; font-weight: 700; color: #fff; }
.e2e-stepitem b { display: block; font-size: 12.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.e2e-stepitem span.s { display: block; font-size: 11.5px; color: var(--fg-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.e2e-stepcard { border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; min-width: 0; }
.e2e-stepcard h4 { margin: 4px 0 6px; font-size: 15px; word-break: break-word; }
.e2e-cat { display: inline-block; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 999px; color: #fff; }
.e2e-stepsum { font-size: 13.5px; margin: 6px 0; word-break: break-word; }
.e2e-stepcard ul { margin: 6px 0; padding-left: 18px; font-size: 12.5px; max-height: 180px; overflow: auto; }
.e2e-stepnav { display: flex; gap: 6px; justify-content: space-between; margin-top: 10px; flex-wrap: wrap; }
.e2e-empty { color: var(--fg-muted); font-size: 13.5px; padding: 30px 10px; text-align: center; }
.e2e-modal-bg { position: fixed; inset: 0; background: rgba(15,23,42,.5); display: none; align-items: center; justify-content: center; z-index: 100; padding: 16px; }
.e2e-modal-bg.open { display: flex; }
.e2e-modal { background: var(--surface); color: var(--fg); border-radius: 12px; padding: 18px; width: min(520px, 100%); border: 1px solid var(--border); }
.e2e-modal h3 { margin-top: 0; }
.e2e-modal label { display: block; font-size: 13px; margin: 10px 0 4px; color: var(--fg-muted); }
.e2e-modal select { width: 100%; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg); font: inherit; }
.e2e-modal .row { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; flex-wrap: wrap; }
"""

E2E_JS = r"""
(function () {
  "use strict";
  var G = window.E2E_GRAPH || { nodes: {}, edges: [], models: [], dataflows: [] };
  var N = G.nodes;
  var OUT = {}, IN = {};
  G.edges.forEach(function (e) {
    (OUT[e.from] = OUT[e.from] || []).push(e);
    (IN[e.to] = IN[e.to] || []).push(e);
  });
  var KIND_LABEL = { measure: "DAX measure", calc_column: "Calculated column", calc_table: "Calculated table", table: "Model table",
    expression: "Dataset query (Power Query)", dataflow_query: "Dataflow query", source: "Data source" };
  var KIND_ORDER = { source: 0, dataflow_query: 1, expression: 2, table: 3, calc_table: 3, calc_column: 4, measure: 5 };
  var COLORS = { source: ["#fef3c7", "#b45309"], dataflow_query: ["#ede9fe", "#6d28d9"], expression: ["#e0f2fe", "#0369a1"],
    table: ["#dcfce7", "#15803d"], calc_table: ["#dcfce7", "#15803d"], calc_column: ["#ccfbf1", "#0f766e"], measure: ["#fce7f3", "#be185d"] };
  var LIST_KINDS = [["measure", "Measures"], ["table", "Tables"], ["dataflow_query", "Dataflow queries"], ["expression", "Dataset queries"], ["source", "Sources"]];

  var cur = { root: null, sel: null, dir: "up", kind: "measure", zoom: 0 };  // zoom 0 = fit to width
  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function trunc(s, n) { s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function displayName(n) { return n.kind === "measure" ? "[" + n.name + "]" : n.name; }

  // ---------------- Trace ----------------
  function trace(rootId, dir) {
    var adj = dir === "down" ? IN : OUT;
    var key = dir === "down" ? "from" : "to";
    var level = {}; level[rootId] = 0;
    var order = [rootId], edges = [], seenE = {}, frontier = [rootId];
    var cap = Object.keys(N).length + 1;
    for (var it = 0; it < cap && frontier.length; it++) {
      var nxt = [];
      frontier.forEach(function (nid) {
        (adj[nid] || []).forEach(function (e) {
          var other = e[key];
          if (!N[other]) return;
          var ek = e.from + "\u0001" + e.to;
          if (!seenE[ek]) { seenE[ek] = 1; edges.push(e); }
          if (!(other in level)) order.push(other);
          var cand = level[nid] + 1;
          if (cand > (level[other] == null ? -1 : level[other]) && cand <= cap) { level[other] = cand; nxt.push(other); }
        });
      });
      frontier = nxt.filter(function (v, i, a) { return a.indexOf(v) === i; });
    }
    var layer = {}, changed = true, guard = 0;
    while (changed && guard++ < 50) {
      changed = false;
      edges.forEach(function (e) {
        var a = N[e.from], b = N[e.to];
        if (!a || !b || b.kind !== "dataflow_query") return;
        var want = a.kind !== "dataflow_query" ? 1 : ((layer[a.group_id] || 1) + (a.group_id === b.group_id ? 0 : 1));
        if (want > (layer[b.group_id] || 0)) { layer[b.group_id] = want; changed = true; }
      });
    }
    return { root: rootId, dir: dir, order: order, level: level, edges: edges, layer: layer };
  }

  // ---------------- Reference map (pure SVG string) ----------------
  function mapSvg(tr, opts) {
    opts = opts || {};
    var W = 236, H = 54, GX = 96, GY = 14, PADX = 20, PADY = 46;
    // Stage layout: every object sits one column right of its right-most input, so sources line up on the left
    // and data always flows left -> right (same rule for upstream and downstream views).
    var prov = {}, cons = {};
    tr.edges.forEach(function (e) { (prov[e.from] = prov[e.from] || []).push(e.to); (cons[e.to] = cons[e.to] || []).push(e.from); });
    var stage = {}, onStack = {};
    function st(id) {
      if (stage[id] != null) return stage[id];
      if (onStack[id]) return 0;
      onStack[id] = 1;
      var v = 0;
      (prov[id] || []).forEach(function (p) { v = Math.max(v, st(p) + 1); });
      onStack[id] = 0; stage[id] = v; return v;
    }
    tr.order.forEach(st);
    tr.order.forEach(function (id) {
      // Pull input-less helper objects (not sources) next to their first consumer
      if (!(prov[id] || []).length && N[id].kind !== "source" && (cons[id] || []).length) {
        var m = Infinity;
        cons[id].forEach(function (c) { m = Math.min(m, stage[c]); });
        stage[id] = Math.max(0, m - 1);
      }
    });
    var cols = [];
    tr.order.forEach(function (id) { var c = stage[id]; (cols[c] = cols[c] || []).push(id); });
    cols = cols.filter(Boolean);
    var pos = {}, maxRows = 0;
    cols.forEach(function (ids, c) {
      ids.sort(function (a, b) {
        var na = N[a], nb = N[b];
        return (KIND_ORDER[na.kind] - KIND_ORDER[nb.kind]) || String(na.group || "").localeCompare(nb.group || "") || String(na.name).localeCompare(nb.name);
      });
      ids.forEach(function (id, r) { pos[id] = { x: PADX + c * (W + GX), y: PADY + r * (H + GY) }; });
      maxRows = Math.max(maxRows, ids.length);
    });
    var width = PADX * 2 + cols.length * W + Math.max(0, cols.length - 1) * GX;
    var height = PADY + maxRows * (H + GY) + 10;
    var s = [];
    var dims = opts.fit ? 'width="100%" style="max-width:' + width + 'px;height:auto"'
      : 'width="' + Math.round(width * (opts.zoom || 1)) + '" height="' + Math.round(height * (opts.zoom || 1)) + '"';
    s.push('<svg xmlns="http://www.w3.org/2000/svg" ' + dims + ' viewBox="0 0 ' + width + " " + height + '" font-family="Segoe UI, Arial, sans-serif">');
    cols.forEach(function (ids, c) {
      var counts = {};
      ids.forEach(function (id) { var k = N[id].kind; counts[k] = (counts[k] || 0) + 1; });
      var top = Object.keys(counts).sort(function (a, b) { return counts[b] - counts[a]; })[0];
      var lbl = (KIND_LABEL[top] || top) + (Object.keys(counts).length > 1 ? " +" : "");
      s.push('<text x="' + (PADX + c * (W + GX)) + '" y="22" font-size="12" font-weight="600" fill="' + (opts.textColor || "currentColor") + '">' + esc(lbl) + "</text>");
    });
    tr.edges.forEach(function (e) {
      var prov = tr.dir === "down" ? e.from : e.to, cons = tr.dir === "down" ? e.to : e.from;
      var a = pos[prov], b = pos[cons];
      if (!a || !b) return;
      // Provider -> consumer, left to right
      var x1 = a.x + W, y1 = a.y + H / 2, x2 = b.x, y2 = b.y + H / 2;
      if (x2 <= x1) { x1 = a.x; x2 = b.x + W; }
      var mx = (x1 + x2) / 2;
      s.push('<path class="ed" data-a="' + esc(e.from) + '" data-b="' + esc(e.to) + '" d="M' + x1 + "," + y1 + " C" + mx + "," + y1 + " " + mx + "," + y2 + " " + x2 + "," + y2 +
        '" fill="none" stroke="#94a3b8" stroke-width="1.4"><title>' + esc((e.labels || []).join(", ")) + "</title></path>");
    });
    tr.order.forEach(function (id) {
      var n = N[id], p = pos[id], col = COLORS[n.kind] || ["#f1f5f9", "#475569"];
      var sub = n.kind === "dataflow_query"
        ? "DF L" + (tr.layer[n.group_id] || 1) + " · " + (n.group || "")
        : n.kind === "source" ? (n.source_type || "Source") + (n.subtitle ? " · " + n.subtitle : "")
        : n.report ? "Report measure · " + n.report
        : (KIND_LABEL[n.kind] || n.kind) + " · " + (n.group || "");
      s.push('<g class="nd' + (id === (opts.sel || "") ? " sel" : "") + '" data-id="' + esc(id) + '" transform="translate(' + p.x + "," + p.y + ')">' +
        '<rect class="box" width="' + W + '" height="' + H + '" rx="9" fill="' + col[0] + '" stroke="' + col[1] + '" stroke-width="' + (id === tr.root ? 3 : 1.5) + '"' +
        (n.external ? ' stroke-dasharray="5 3"' : "") + "/>" +
        '<rect width="5" height="' + H + '" rx="2" fill="' + col[1] + '"/>' +
        '<text x="14" y="22" font-size="13" font-weight="600" fill="#0f172a">' + esc(trunc(displayName(n), 31)) + "</text>" +
        '<text x="14" y="40" font-size="11" fill="#475569">' + esc(trunc(sub, 40)) + "</text>" +
        "<title>" + esc(displayName(n) + "\n" + sub + (n.role ? "\n" + n.role : "")) + "</title></g>");
    });
    s.push("</svg>");
    return s.join("");
  }

  // ---------------- Documentation (mirrors e2e_lineage.render_measure_doc_markdown) ----------------
  function fence(code, lang) {
    var body = String(code || "").replace(/\s+$/, "");
    var t = body.indexOf("```") >= 0 ? "````" : "```";
    return t + lang + "\n" + body + "\n" + t;
  }
  function mdVal(v) { var t = String(v || ""); return /^https?:\/\//i.test(t) ? "[" + t.replace(/[\[\]]/g, "") + "](" + t.replace(/ /g, "%20").replace(/\)/g, "%29") + ")" : "`" + t + "`"; }
  function mdEsc(s) { return String(s || "").replace(/\|/g, "\\|").replace(/\n/g, " "); }
  function buildDoc(rootId) {
    var tr = trace(rootId, "up"), root = N[rootId], lvl = tr.level, layers = tr.layer;
    var by = {}; tr.order.forEach(function (id) { var n = N[id]; (by[n.kind] = by[n.kind] || []).push(n); });
    ["source", "dataflow_query", "expression", "table", "calc_table", "calc_column", "measure"].forEach(function (k) { by[k] = by[k] || []; });
    var depsOf = {}; tr.edges.forEach(function (e) { (depsOf[e.from] = depsOf[e.from] || []).push(e); });
    var o = [];
    o.push("# Measure Documentation: " + displayName(root), "");
    var rows = [["Object type", root.report ? "DAX measure (report-level, thin report)" : KIND_LABEL[root.kind]], ["Report", root.report], ["Semantic model", root.model || root.group], ["Workspace", root.workspace], ["Home table", root.table],
      ["Display folder", root.folder], ["Format string", root.format], ["Generated", G.generated_at]];
    o.push("| Property | Value |", "|---|---|");
    rows.forEach(function (r) { if (r[1]) o.push("| " + r[0] + " | " + mdEsc(r[1]) + " |"); });
    if (root.description) o.push("", "> " + root.description);
    var dfIds = {}; by.dataflow_query.forEach(function (n) { dfIds[n.group_id] = 1; });
    var nDf = Object.keys(dfIds).length, maxLayer = 0;
    Object.keys(layers).forEach(function (k) { maxLayer = Math.max(maxLayer, layers[k]); });
    o.push("", "## Summary", "",
      "- **" + by.source.length + "** data source object(s) / SQL script(s)",
      "- **" + by.dataflow_query.length + "** dataflow quer(ies) across **" + nDf + "** dataflow(s)" + (maxLayer ? " in **" + maxLayer + "** dataflow layer(s)" : ""),
      "- **" + by.expression.length + "** dataset Power Query helper quer(ies)",
      "- **" + (by.table.length + by.calc_table.length) + "** model table(s), **" + by.calc_column.length + "** calculated column(s)",
      "- **" + by.measure.length + "** DAX measure(s) in the calculation chain (including this one)", "",
      "Data flows: **Sources** -> " + (nDf ? "**Dataflows** -> " : "") + "**Dataset Power Query** -> **Model tables** -> **DAX**");
    o.push("", "## Reference Map", "", "@@MAP@@", "");
    function depList(n) {
      var items = (depsOf[n.id] || []).map(function (e) {
        var d = N[e.to];
        return "  - " + KIND_LABEL[d.kind] + ": **" + d.name + "** - " + (d.group || "") + (e.labels && e.labels.length ? " (" + e.labels.join(", ") + ")" : "");
      });
      return items.length ? ["- Depends on:"].concat(items) : [];
    }
    o.push("## 1. Source Systems & SQL Scripts", "");
    if (!by.source.length) o.push("_No physical source detected (data may be entered manually or come from an unscanned dataflow)._");
    var secOf = {};
    by.source.slice().sort(function (a, b) { return String(a.source_type).localeCompare(b.source_type) || String(a.name).localeCompare(b.name); }).forEach(function (n, i) {
      secOf[n.id] = "1." + (i + 1);
      o.push("### 1." + (i + 1) + " " + (n.source_type || "Source") + ": " + n.name, "");
      [["Server / endpoint", n.server], ["Database", n.database], ["Object / sheet", n.object]].forEach(function (kv) {
        if (kv[1]) o.push("- **" + kv[0] + ":** " + mdVal(kv[1]));
      });
      (n.files || []).forEach(function (f) { o.push("- **File:** " + mdVal(f)); });
      var cons = {}; tr.edges.forEach(function (e) { if (e.to === n.id) cons[N[e.from].name] = 1; });
      var cl = Object.keys(cons).sort(); if (cl.length) o.push("- **Read by:** " + cl.join(", "));
      if ((n.sql_parameters || []).length) o.push("- **Parameters inserted by Power Query:** " + n.sql_parameters.map(function (x) { return "`{{" + x + "}}`"; }).join(", "));
      if (n.code) o.push("", "**Native SQL:**", "", fence(n.code, "sql"));
      o.push("");
    });
    function sqlRefs(q) {
      return (q.sql || []).filter(function (x) { return secOf[x.source_id]; }).map(function (x) {
        return "- **Native SQL:** see section " + secOf[x.source_id] + " (" + [x.connector, x.database].filter(Boolean).join(" \u00b7 ") + (x.via ? ", via " + x.via : "") + ")";
      });
    }
    function stepLines(q) {
      var st = q.steps || [];
      if (!st.length) return [];
      var out = ["", "**Transformation steps (" + st.length + "):**", ""];
      st.forEach(function (x, i) {
        out.push("- **" + (i + 1) + ". " + x.name + "** [" + x.category_label + "] - " + x.summary + (x.is_output ? " _(final output)_" : ""));
        (x.details || []).slice(0, 15).forEach(function (d) { out.push("  - " + d); });
        if ((x.details || []).length > 15) out.push("  - ... " + (x.details.length - 15) + " more");
      });
      return out;
    }
    o.push("## 2. Dataflow Transformations (Power Query in Dataflows Gen1)", "");
    if (!by.dataflow_query.length) o.push("_This measure does not depend on any dataflow._");
    var byDf = {}; by.dataflow_query.forEach(function (n) { (byDf[n.group_id] = byDf[n.group_id] || []).push(n); });
    Object.keys(byDf).sort(function (a, b) { return ((layers[b] || 1) - (layers[a] || 1)) || String(byDf[a][0].group).localeCompare(byDf[b][0].group); }).forEach(function (gid, i) {
      var qs = byDf[gid];
      o.push("### 2." + (i + 1) + " Dataflow (layer " + (layers[gid] || 1) + "): " + (qs[0].group || ""), "", "- **Workspace:** " + (qs[0].workspace || ""), "- **Dataflow id:** `" + gid + "`", "");
      qs.sort(function (a, b) { return (lvl[b.id] || 0) - (lvl[a.id] || 0); }).forEach(function (q) {
        o.push("#### " + q.name + " (" + (q.role || "Query") + ")", "");
        if (q.external) { o.push("_Definition not available: " + (q.note || "") + "_", ""); return; }
        if (q.description) o.push("> " + q.description, "");
        o = o.concat(depList(q));
        if (q.parameters && Object.keys(q.parameters).length) o.push("- Parameters: " + Object.keys(q.parameters).map(function (k) { return "`" + k + "` = `" + q.parameters[k] + "`"; }).join(", "));
        if (q.columns && q.columns.length) o.push("- Output columns: " + q.columns.map(function (c) { return "`" + c.name + "` (" + c.type + ")"; }).join(", "));
        o = o.concat(sqlRefs(q), stepLines(q));
        if (q.code) o.push("", "**Power Query (M):**", "", fence(q.code, "powerquery"));
        else if (q.role === "Linked entity") o.push("", "_Linked entity: reads the upstream dataflow entity listed above (no Power Query of its own)._");
        o.push("");
      });
    });
    o.push("## 3. Semantic Model Power Query (Dataset Tables & Queries)", "");
    var desc = function (a, b) { return (lvl[b.id] || 0) - (lvl[a.id] || 0); };
    var pq = by.expression.slice().sort(desc).concat(by.table.slice().sort(desc));
    if (!pq.length) o.push("_No Power Query tables involved._");
    pq.forEach(function (n, i) {
      o.push("### 3." + (i + 1) + " " + n.name + " - " + (n.kind === "expression" ? "Shared query" : "Table (" + (n.storage_mode || "import") + " mode)"), "", "- **Model:** " + (n.model || ""));
      o = o.concat(depList(n), sqlRefs(n), stepLines(n));
      if (n.code) o.push("", "**Power Query (M):**", "", fence(n.code, "powerquery"));
      o.push("");
    });
    o.push("## 4. Model Tables & Columns Used", "", "| Table | Columns referenced by DAX | Storage |", "|---|---|---|");
    by.table.concat(by.calc_table).sort(function (a, b) { return a.name.toLowerCase().localeCompare(b.name.toLowerCase()); }).forEach(function (n) {
      var cols = {}; tr.edges.forEach(function (e) { if (e.to === n.id) (e.labels || []).forEach(function (l) { if (l.indexOf("[") >= 0) cols[l] = 1; }); });
      o.push("| " + mdEsc(n.name) + " | " + mdEsc(Object.keys(cols).sort().join(", ") || "-") + " | " + (n.storage_mode || (n.kind === "calc_table" ? "calculated" : "")) + " |");
    });
    by.calc_table.forEach(function (n) { o.push("", "**Calculated table " + n.name + ":**", "", fence(n.code, "dax")); });
    by.calc_column.forEach(function (n) { o.push("", "**Calculated column " + n.name + ":**", "", fence(n.code, "dax")); });
    o.push("", "## 5. DAX Calculation Chain", "", "Measures are listed from base calculations to the final measure.", "");
    by.measure.slice().sort(function (a, b) { return ((lvl[b.id] || 0) - (lvl[a.id] || 0)) || a.name.toLowerCase().localeCompare(b.name.toLowerCase()); }).forEach(function (n, i) {
      o.push("### 5." + (i + 1) + " [" + n.name + "]" + (n.id === rootId ? " (documented measure)" : ""), "");
      var bits = ["Table: `" + (n.table || "") + "`"];
      if (n.format) bits.push("Format: `" + n.format + "`");
      if (n.folder) bits.push("Folder: `" + n.folder + "`");
      o.push(bits.join(" | "));
      if (n.description) o.push("", "> " + n.description);
      o = o.concat([""], depList(n), ["", fence(n.code, "dax"), ""]);
    });
    return { md: o.join("\n").replace(/\s+$/, "") + "\n", trace: tr };
  }
  function mermaidFor(tr) {
    var ids = {}, k = 0, out = ["```mermaid", "flowchart LR"];
    tr.order.forEach(function (id) { ids[id] = "n" + (k++); var n = N[id];
      out.push("  " + ids[id] + '["' + (displayName(n) + "<br/><small>" + KIND_LABEL[n.kind] + " - " + (n.group || "") + "</small>").replace(/"/g, "'") + '"]'); });
    tr.edges.forEach(function (e) { out.push("  " + ids[e.to] + " --> " + ids[e.from]); });
    out.push("```");
    return out.join("\n");
  }

  // Minimal Markdown -> HTML for the exported document
  function inline(s) {
    return esc(s).replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>').replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>").replace(/(^|\s)_([^_]+)_(?=\s|$)/g, "$1<i>$2</i>");
  }
  function mdToHtml(md, mapHtmlFor) {
    var lines = md.split("\n"), h = [], i = 0;
    while (i < lines.length) {
      var l = lines[i];
      var f = l.match(/^(`{3,4})(\w*)$/);
      if (f) {
        var buf = [], j = i + 1;
        while (j < lines.length && lines[j] !== f[1]) { buf.push(lines[j]); j++; }
        h.push('<pre class="code lang-' + esc(f[2]) + '"><code>' + esc(buf.join("\n")) + "</code></pre>");
        i = j + 1; continue;
      }
      if (l.indexOf("@@MAP@@") === 0) { h.push(mapHtmlFor(l)); i++; continue; }
      var hd = l.match(/^(#{1,4})\s+(.*)$/);
      if (hd) { var lv = hd[1].length; h.push("<h" + lv + ">" + inline(hd[2]) + "</h" + lv + ">"); i++; continue; }
      if (/^\|/.test(l)) {
        var rows = [];
        while (i < lines.length && /^\|/.test(lines[i])) { rows.push(lines[i]); i++; }
        var cells = function (r) { return r.replace(/^\||\|$/g, "").split(/(?<!\\)\|/).map(function (c) { return c.trim().replace(/\\\|/g, "|"); }); };
        var t = "<table><thead><tr>" + cells(rows[0]).map(function (c) { return "<th>" + inline(c) + "</th>"; }).join("") + "</tr></thead><tbody>";
        rows.slice(2).forEach(function (r) { t += "<tr>" + cells(r).map(function (c) { return "<td>" + inline(c) + "</td>"; }).join("") + "</tr>"; });
        h.push(t + "</tbody></table>"); continue;
      }
      if (/^\s*- /.test(l)) {
        var items = [];
        while (i < lines.length && /^\s*- /.test(lines[i])) { items.push(lines[i]); i++; }
        var html = "<ul>", depth = 0;
        items.forEach(function (it) {
          var d = it.match(/^\s*/)[0].length >= 2 ? 1 : 0;
          if (d > depth) html += "<ul>"; else if (d < depth) html += "</ul>";
          depth = d; html += "<li>" + inline(it.replace(/^\s*- /, "")) + "</li>";
        });
        h.push(html + (depth ? "</ul>" : "") + "</ul>"); continue;
      }
      if (/^> /.test(l)) { h.push("<blockquote>" + inline(l.slice(2)) + "</blockquote>"); i++; continue; }
      if (l.trim()) h.push("<p>" + inline(l) + "</p>");
      i++;
    }
    return h.join("\n");
  }
  var DOC_CSS = "body{font-family:Segoe UI,Arial,sans-serif;color:#0f172a;background:#fff;max-width:1100px;margin:24px auto;padding:0 16px;line-height:1.5;font-size:14px}" +
    "h1{font-size:24px;border-bottom:2px solid #0b63ce;padding-bottom:6px}h2{font-size:19px;margin-top:28px;border-bottom:1px solid #dce3ee;padding-bottom:4px}" +
    "h3{font-size:16px;margin-top:20px}h4{font-size:14px;margin-top:16px}table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #dce3ee;padding:4px 9px;text-align:left;vertical-align:top}" +
    "th{background:#eef3f9}pre.code{background:#f8fafc;border:1px solid #dce4f0;border-left:3px solid #93c5fd;padding:10px 12px;overflow:auto;font-size:12px;white-space:pre-wrap;word-break:break-word}" +
    "code{font-family:Consolas,monospace;font-size:12.5px}blockquote{margin:8px 0;padding:6px 12px;border-left:3px solid #94a3b8;color:#475569}.map{overflow:auto;border:1px solid #dce3ee;border-radius:8px;padding:6px;margin:8px 0}" +
    ".toc a{color:#0b63ce;text-decoration:none}@media print{.map{overflow:visible}h2,h3{page-break-after:avoid}pre{page-break-inside:avoid}}";

  function download(name, text, mime) {
    var blob = new Blob([text], { type: mime + ";charset=utf-8" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob); a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
  }
  function safeName(s) { return String(s || "measure").replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 80) || "measure"; }

  function exportDocs(ids, format, title) {
    var docs = ids.map(function (id) { return buildDoc(id); });
    if (format === "md") {
      var md = docs.map(function (d) { return d.md.replace("@@MAP@@", mermaidFor(d.trace)); });
      var body = md.length > 1
        ? "# " + title + "\n\n" + ids.map(function (id, i) { return (i + 1) + ". " + displayName(N[id]); }).join("\n") + "\n\n---\n\n" + md.join("\n\n---\n\n")
        : md[0];
      download(safeName(title) + ".md", body, "text/markdown");
      return;
    }
    var parts = docs.map(function (d, i) {
      return '<section id="doc' + i + '">' + mdToHtml(d.md, function () {
        return '<div class="map">' + mapSvg(d.trace, { textColor: "#0f172a", fit: true }) + "</div>";
      }) + "</section>";
    });
    var toc = ids.length > 1 ? "<h1>" + esc(title) + '</h1><ol class="toc">' + ids.map(function (id, i) { return '<li><a href="#doc' + i + '">' + esc(displayName(N[id])) + "</a></li>"; }).join("") + "</ol>" : "";
    var html = '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(title) + "</title><style>" + DOC_CSS +
      "</style></head><body>" + toc + parts.join('<hr style="margin:40px 0">') + "</body></html>";
    if (format === "doc") download(safeName(title) + ".doc", html, "application/msword");
    else download(safeName(title) + ".html", html, "text/html");
  }

  // ---------------- UI ----------------
  function renderKinds() {
    $("e2eKinds").innerHTML = LIST_KINDS.map(function (k) {
      return '<button type="button" data-kind="' + k[0] + '" class="' + (cur.kind === k[0] ? "active" : "") + '">' + k[1] + "</button>";
    }).join("");
  }
  // ---------------- Filters: workspace -> model / thin report / dataflow -> details ----------------
  // Group key of a node: the semantic model, thin report or dataflow it belongs to (sources belong to their consumers)
  function gkey(n) {
    if (n.kind === "dataflow_query") return "df:" + (n.group_id || n.group);
    if (n.report_id) return "rpt:" + n.report_id;
    if (n.model_id) return "model:" + n.model_id;
    return "";
  }
  var GROUPS = {}, WORKSPACES = {};
  var GROUP_TYPE_LABEL = { model: "Semantic models", rpt: "Thin reports (report-level measures)", df: "Dataflows (Gen1)" };
  Object.keys(N).forEach(function (id) {
    var n = N[id], k = gkey(n);
    if (n.outside) return;  // placeholder for a dataflow outside the selected workspaces: only shown inside traces
    if (n.workspace) WORKSPACES[n.workspace] = (WORKSPACES[n.workspace] || 0) + 1;
    if (!k) return;
    var g = GROUPS[k] || (GROUPS[k] = { key: k, type: k.split(":")[0], name: n.report_id ? (n.report || n.group) : n.kind === "dataflow_query" ? n.group : (n.model || n.group),
      ws: n.workspace || "", model: n.report_id ? (n.model || "") : "", model_ws: n.model_workspace || "", count: 0, external: true });
    g.count++;
    if (!n.external) g.external = false;
    if (!g.ws && n.workspace) g.ws = n.workspace;
  });
  // Picking a model / report / dataflow lists its own objects plus everything upstream of it (all dataflow
  // layers, dataset queries, sources); a dataflow also lists what depends on it downstream (impact).
  var REL = {}, WSREL = {};
  function related(grp) {
    if (REL[grp]) return REL[grp];
    var set = {}, start = [];
    Object.keys(N).forEach(function (id) { var n = N[id]; if (gkey(n) === grp || (n.report_id && grp === "model:" + n.model_id)) { set[id] = 1; start.push(id); } });
    function walk(fr, adj, key) {
      while (fr.length) {
        var nx = [];
        fr.forEach(function (id) { (adj[id] || []).forEach(function (e) { var t = e[key]; if (!set[t] && N[t]) { set[t] = 1; nx.push(t); } }); });
        fr = nx;
      }
    }
    walk(start.slice(), OUT, "to");
    if (grp.indexOf("df:") === 0) walk(start.slice(), IN, "from");
    return (REL[grp] = set);
  }
  function inWorkspace(n, ws) {
    if (n.kind !== "source") return n.workspace === ws;
    if (!WSREL[ws]) {
      var u = {};
      Object.keys(GROUPS).forEach(function (k) { if (GROUPS[k].ws === ws) { var r = related(k); Object.keys(r).forEach(function (id) { if (N[id].kind === "source") u[id] = 1; }); } });
      WSREL[ws] = u;
    }
    return !!WSREL[ws][n.id];
  }
  function inGroup(n, grp) { return !!related(grp)[n.id]; }
  function detailTags(n) {
    var t = [];
    if (n.kind === "measure") {
      if (n.table) t.push("Table: " + n.table);
      if (n.folder) t.push("Folder: " + n.folder);
      t.push(n.report_id ? "Report-level measure (thin report)" : "Model measure");
      if (n.hidden) t.push("Hidden");
    } else if (n.kind === "table" || n.kind === "calc_table") {
      t.push(n.kind === "calc_table" ? "Calculated table" : "Mode: " + (n.storage_mode || "import"));
      if ((OUT[n.id] || []).some(function (e) { return e.kind === "dataflow" || (N[e.to] && N[e.to].kind === "dataflow_query"); })) t.push("Loads from a dataflow");
    } else if (n.kind === "dataflow_query" || n.kind === "expression") {
      if (n.role) t.push("Role: " + n.role);
      if (n.kind === "dataflow_query") t.push("Dataflow: " + n.group + (n.workspace ? " (" + n.workspace + ")" : ""));
      (n.source_types || []).forEach(function (x) { t.push("Connector: " + x); });
    } else if (n.kind === "source") {
      t.push("Type: " + (n.source_type || "?"));
    }
    if ((n.sql || []).length || (n.kind === "source" && n.lang === "sql")) t.push("Has native SQL");
    if (n.external) t.push("Not scanned");
    return t;
  }
  function setOptions(sel, html, value) {
    sel.innerHTML = html;
    sel.value = value;
    if (sel.value !== value) sel.value = "";
    return sel.value;
  }
  function renderWsFilter() {
    var cur_ws = $("e2eWs").value;
    var html = '<option value="">All workspaces (' + Object.keys(WORKSPACES).length + ")</option>" + Object.keys(WORKSPACES).sort(function (a, b) { return a.toLowerCase().localeCompare(b.toLowerCase()); })
      .map(function (w) { return '<option value="' + esc(w) + '">' + esc(w) + "</option>"; }).join("");
    setOptions($("e2eWs"), html, cur_ws);
  }
  function renderGroupFilter() {
    var ws = $("e2eWs").value, val = $("e2eModel").value;
    var byType = { model: [], rpt: [], df: [] };
    Object.keys(GROUPS).forEach(function (k) {
      var g = GROUPS[k];
      if (ws && g.ws !== ws) return;
      (byType[g.type] || (byType[g.type] = [])).push(g);
    });
    var total = 0;
    var html = ["model", "rpt", "df"].map(function (t) {
      var list = byType[t] || [];
      total += list.length;
      if (!list.length) return "";
      list.sort(function (a, b) { return a.name.toLowerCase().localeCompare(b.name.toLowerCase()) || a.ws.localeCompare(b.ws); });
      return '<optgroup label="' + esc(GROUP_TYPE_LABEL[t]) + " (" + list.length + ')">' + list.map(function (g) {
        var lbl = g.name + (ws ? "" : " \u2014 " + (g.ws || "?")) + (g.type === "rpt" ? " \u2192 " + (g.model || "?") : "") + (g.external ? " (not scanned)" : "");
        return '<option value="' + esc(g.key) + '">' + esc(lbl) + "</option>";
      }).join("") + "</optgroup>";
    }).join("");
    setOptions($("e2eModel"), '<option value="">' + (ws ? "All models, reports &amp; dataflows in this workspace" : "All models, reports &amp; dataflows") + " (" + total + ")</option>" + html, val);
  }
  function baseItems() {
    var q = $("e2eSearch").value.trim().toLowerCase(), ws = $("e2eWs").value, grp = $("e2eModel").value;
    var kinds = cur.kind === "table" ? ["table", "calc_table"] : [cur.kind];
    return Object.keys(N).map(function (id) { return N[id]; }).filter(function (n) {
      if (kinds.indexOf(n.kind) < 0 || n.outside) return false;
      if (grp) { if (!inGroup(n, grp)) return false; }
      else if (ws && !inWorkspace(n, ws)) return false;
      if (!q) return true;
      return (n.name + " " + (n.group || "") + " " + (n.table || "") + " " + (n.folder || "") + " " + (n.report || "") + " " + (n.model || "") + " " + (n.source_type || "") + " " + (n.subtitle || "")).toLowerCase().indexOf(q) >= 0;
    });
  }
  function renderDetailFilter(items) {
    var counts = {};
    items.forEach(function (n) { detailTags(n).forEach(function (t) { counts[t] = (counts[t] || 0) + 1; }); });
    var html = '<option value="">Any detail</option>' + Object.keys(counts).sort(function (a, b) { return a.toLowerCase().localeCompare(b.toLowerCase()); })
      .map(function (t) { return '<option value="' + esc(t) + '">' + esc(t) + " (" + counts[t] + ")</option>"; }).join("");
    return setOptions($("e2eDetailF"), html, $("e2eDetailF").value);
  }
  function filtersActive() { return !!($("e2eWs").value || $("e2eModel").value || $("e2eDetailF").value || $("e2eSearch").value); }
  function writeHash(push) {
    var parts = [];
    [["ws", $("e2eWs").value], ["grp", $("e2eModel").value], ["kind", cur.kind !== "measure" ? cur.kind : ""], ["detail", $("e2eDetailF").value], ["node", cur.root || ""]]
      .forEach(function (kv) { if (kv[1]) parts.push(kv[0] + "=" + encodeURIComponent(kv[1])); });
    var h = parts.length ? "#" + parts.join("&") : location.pathname + location.search;
    if (EMBED && !parts.length) h = location.pathname + location.search;
    try { if (push) history.pushState(null, "", h); else history.replaceState(null, "", h); } catch (e) { if (parts.length) location.hash = parts.join("&"); }
    toParent({ type: "pbidoc-e2e-hash", hash: parts.join("&") });
  }
  function readHash() {
    var o = {};
    location.hash.replace(/^#/, "").split("&").forEach(function (kv) {
      var i = kv.indexOf("=");
      if (i > 0) { try { o[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* ignore */ } }
    });
    return o;
  }
  function applyHash(h) {
    if (h.grp && GROUPS[h.grp] && !h.ws) h.ws = GROUPS[h.grp].ws;
    $("e2eWs").value = h.ws || "";
    if ($("e2eWs").value !== (h.ws || "")) $("e2eWs").value = "";
    renderGroupFilter();
    $("e2eModel").value = h.grp || "";
    if ($("e2eModel").value !== (h.grp || "")) $("e2eModel").value = "";
    var k = h.kind && LIST_KINDS.some(function (x) { return x[0] === h.kind; }) ? h.kind : "measure";
    if (k !== cur.kind) { cur.kind = k; renderKinds(); }
    $("e2eDetailF").value = "";
    renderList();
    if (h.detail) { $("e2eDetailF").value = h.detail; renderList(); }
  }
  function renderList() {
    var base = baseItems();
    var detail = renderDetailFilter(base);
    var items = (detail ? base.filter(function (n) { return detailTags(n).indexOf(detail) >= 0; }) : base)
      .sort(function (a, b) { return String(a.group || "").localeCompare(b.group || "") || a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
    $("e2eReset").style.display = filtersActive() ? "" : "none";
    $("e2eCount").textContent = items.length + " item(s)" + ($("e2eModel").value ? " incl. upstream" + ($("e2eModel").value.indexOf("df:") === 0 ? " & downstream" : "") : "") +
      (items.length > 500 ? " - showing first 500, refine the search" : "");
    $("e2eList").innerHTML = items.slice(0, 500).map(function (n) {
      var sub = n.kind === "measure" ? (n.report ? "Report measure · " + n.report + " → model " + (n.model || "?") : (n.group + " · " + n.table + (n.folder ? " · " + n.folder : ""))) : n.kind === "source" ? (n.source_type + (n.subtitle ? " · " + n.subtitle : "")) : (n.group || "") + (n.role ? " · " + n.role : "");
      return '<button type="button" class="e2e-item' + (n.id === cur.root ? " active" : "") + '" data-id="' + esc(n.id) + '"><b>' + esc(displayName(n)) + "</b><span>" + esc(sub) + "</span></button>";
    }).join("") || '<div class="e2e-empty">No matches.</div>';
  }

  function chips(edges, key) {
    return edges.map(function (e) {
      var n = N[e[key]]; if (!n) return "";
      return '<button type="button" class="e2e-chip" data-goto="' + esc(n.id) + '" title="' + esc((n.group || "") + (n.workspace ? " / " + n.workspace : "")) + '">' +
        esc(displayName(n)) + " <small>" + esc(KIND_LABEL[n.kind]) + (n.group && n.kind !== "source" ? " \u00b7 " + esc(n.group) : "") +
        ((e.labels || []).length ? " · " + esc(e.labels.join(", ")) : "") + "</small></button>";
    }).join("");
  }
  var CAT_COLOR = { source: "#b45309", sql: "#b45309", navigate: "#0369a1", reference: "#0369a1", filter: "#dc2626", columns: "#7c3aed",
    rename: "#4f46e5", type: "#64748b", add: "#15803d", transform: "#0f766e", merge: "#c2410c", expand: "#c2410c", append: "#a16207",
    group: "#be185d", pivot: "#9333ea", sort: "#475569", dedupe: "#e11d48", rows: "#dc2626", headers: "#0891b2", replace: "#0d9488",
    split: "#0e7490", buffer: "#64748b", other: "#334155" };
  function isUrl(v) { return /^https?:\/\//i.test(String(v || "")); }
  function linkify(v) {
    var t = String(v == null ? "" : v);
    return isUrl(t) ? '<a class="e2e-link" href="' + esc(t) + '" target="_blank" rel="noopener noreferrer">' + esc(decodeURIComponentSafe(t)) + "</a>" : esc(t);
  }
  function decodeURIComponentSafe(t) { try { return decodeURI(t); } catch (e) { return t; } }
  function codeWithSteps(n) {
    var code = n.code || "", steps = n.steps || [];
    if (!steps.length) return esc(code);
    var out = "", pos = 0;
    steps.forEach(function (st, i) {
      if (st.start < pos || st.end > code.length) return;
      out += esc(code.slice(pos, st.start)) + '<span class="stp" data-step="' + i + '" title="Step ' + (i + 1) + ": " + esc(st.name) + '">' + esc(code.slice(st.start, st.end)) + "</span>";
      pos = st.end;
    });
    return out + esc(code.slice(pos));
  }
  function sqlBlocks(n) {
    var entries = (n.sql || []).filter(function (q) { return N[q.source_id]; });
    if (!entries.length) return "";
    var h = "<div class='e2e-sec'><b>Native SQL (" + entries.length + ")</b><span class='hint'>SQL sent to the source by this query, formatted for reading</span></div>";
    entries.forEach(function (q, i) {
      var src = N[q.source_id];
      h += "<div class='e2e-sqlhead'>" + (entries.length > 1 ? "<b>Query " + (i + 1) + "</b> \u00b7 " : "") + "<b>" + esc(q.connector || src.source_type || "SQL") + "</b>" +
        (q.server ? " \u00b7 " + esc(q.server) : "") + (q.database ? " \u00b7 " + esc(q.database) : "") + (q.via ? " \u00b7 via " + esc(q.via) : "") +
        ((q.parameters || []).length ? " \u00b7 Power Query parameters inserted: " + q.parameters.map(function (x) { return "<code>{{" + esc(x) + "}}</code>"; }).join(", ") : "") +
        " \u00b7 <a href='#' data-goto='" + esc(src.id) + "'>source</a></div>" +
        "<div class='e2e-code'><button type='button' class='e2e-btn' data-copy-code='1'>Copy SQL</button><pre>" + esc(src.code) + "</pre></div>";
    });
    return h;
  }
  function stepCard(n, i) {
    var steps = n.steps || [], st = steps[i];
    if (!st) return "";
    var col = CAT_COLOR[st.category] || CAT_COLOR.other;
    var h = "<div style='font-size:12px;color:var(--fg-muted)'>Step " + (i + 1) + " of " + steps.length + (st.is_output ? " \u00b7 <b>final output</b>" : "") + "</div>" +
      "<h4>" + esc(st.name) + "</h4><span class='e2e-cat' style='background:" + col + "'>" + esc(st.category_label) + "</span>" +
      "<div class='e2e-stepsum'>" + esc(st.summary) + "</div>";
    if ((st.details || []).length) h += "<ul>" + st.details.map(function (d) { return "<li>" + esc(d) + "</li>"; }).join("") + "</ul>";
    if (st.input) {
      var j = steps.findIndex(function (x) { return x.name === st.input; });
      h += "<div style='font-size:12.5px'>Builds on: " + (j >= 0 ? "<a href='#' data-step-go='" + j + "'>step " + (j + 1) + " \u2013 " + esc(st.input) + "</a>" : esc(st.input)) + "</div>";
    }
    if ((st.query_ids || []).length) {
      h += "<div style='font-size:12.5px;margin-top:4px'>Pulls in: " + st.query_ids.map(function (qid, k) {
        return N[qid] ? "<button type='button' class='e2e-chip' data-goto='" + esc(qid) + "'>" + esc(N[qid].name) + " <small>" + esc(KIND_LABEL[N[qid].kind]) + "</small></button>" : esc(st.queries[k]);
      }).join(" ") + "</div>";
    }
    h += "<div class='e2e-code'><pre style='max-height:200px'>" + esc((n.code || "").slice(st.start, st.end)) + "</pre></div>";
    h += "<div class='e2e-stepnav'><button type='button' class='e2e-btn' data-step-go='" + Math.max(0, i - 1) + "'" + (i === 0 ? " disabled" : "") + ">\u2190 Previous step</button>" +
      "<button type='button' class='e2e-btn primary' data-step-go='" + Math.min(steps.length - 1, i + 1) + "'" + (i === steps.length - 1 ? " disabled" : "") + ">Next step \u2192</button></div>";
    return h;
  }
  function stepsBlock(n) {
    var steps = n.steps || [];
    if (!steps.length) return "";
    var list = steps.map(function (st, i) {
      var col = CAT_COLOR[st.category] || CAT_COLOR.other;
      return "<button type='button' class='e2e-stepitem' data-step-go='" + i + "'><span class='e2e-stepnum' style='background:" + col + "'>" + (i + 1) + "</span>" +
        "<span style='min-width:0'><b>" + esc(st.name) + "</b><span class='s'>" + esc(st.category_label) + " \u00b7 " + esc(st.summary) + "</span></span></button>";
    }).join("");
    return "<div class='e2e-sec'><b>Transformation steps (" + steps.length + ")</b><span class='hint'>Click a step (or the code above) to see what it does to the data; use Next / Previous to walk through in order</span></div>" +
      "<div class='e2e-steps'><div class='e2e-steplist' id='e2eStepList'>" + list + "</div><div class='e2e-stepcard' id='e2eStepCard'></div></div>";
  }
  function selectStep(i) {
    var n = N[cur.sel]; if (!n || !(n.steps || [])[i]) return;
    cur.step = i;
    $("e2eStepCard").innerHTML = stepCard(n, i);
    document.querySelectorAll("#e2eStepList .e2e-stepitem").forEach(function (b, k) { b.classList.toggle("on", k === i); });
    var item = document.querySelectorAll("#e2eStepList .e2e-stepitem")[i];
    if (item) { var lst = $("e2eStepList"); if (item.offsetTop < lst.scrollTop || item.offsetTop > lst.scrollTop + lst.clientHeight - 40) lst.scrollTop = item.offsetTop - 40; }
    var pre = $("e2eMainCode");
    if (pre) {
      pre.querySelectorAll(".stp").forEach(function (sp) { sp.classList.toggle("on", +sp.getAttribute("data-step") === i); });
      var on = pre.querySelector(".stp.on");
      if (on) pre.scrollTop = Math.max(0, on.offsetTop - pre.offsetTop - 30);
    }
    log({ type: "explorer-step", id: cur.sel, step: i });
  }

  // opts (used when another page embeds the detail panel, e.g. the Report Explorer):
  //   target: element to render into, map: map container selector, usage: false hides report usage, reroot: false hides "Explore from"
  function renderDetail(id, opts) {
    opts = opts || {};
    var n = N[id]; if (!n) return;
    log({ type: "explorer-detail", id: id });
    cur.sel = id;
    cur.step = 0;
    var kv = [["Type", n.report ? "DAX measure (report-level)" : KIND_LABEL[n.kind]], ["Role", n.role], ["Report", n.report], ["Shared model", n.report ? n.model : ""],
      ["Model / dataflow", n.report ? "" : n.group], ["Workspace", n.workspace], ["Home table", n.table], ["Format", n.format], ["Display folder", n.folder],
      ["Storage mode", n.storage_mode], ["Source type", n.source_type], ["Server / endpoint", n.server], ["Database", n.database], ["Object / sheet", n.object], ["Note", n.note]];
    if (n.parameters && Object.keys(n.parameters).length) kv.push(["Parameters", Object.keys(n.parameters).map(function (k) { return k + " = " + n.parameters[k]; }).join("; ")]);
    if ((n.sql_parameters || []).length) kv.push(["SQL parameters", n.sql_parameters.map(function (x) { return "{{" + x + "}}"; }).join(", ") + " (filled in by Power Query)"]);
    var html = "<h3>" + esc(displayName(n)) + "</h3>";
    if (n.description) html += '<div class="sub" style="color:var(--fg-muted);font-size:13px">' + esc(n.description) + "</div>";
    html += '<dl class="e2e-kv">' + kv.filter(function (r) { return r[1]; }).map(function (r) { return "<dt>" + esc(r[0]) + "</dt><dd>" + linkify(r[1]) + "</dd>"; }).join("");
    if ((n.files || []).length) html += "<dt>Files</dt><dd>" + n.files.map(linkify).join("<br>") + "</dd>";
    html += "</dl>";
    var deps = OUT[id] || [], users = IN[id] || [];
    if (deps.length) html += "<b style='font-size:13px'>Depends on (" + deps.length + ")</b><div class='e2e-chips'>" + chips(deps, "to") + "</div>";
    if (users.length) html += "<b style='font-size:13px'>Used by (" + users.length + ")</b><div class='e2e-chips'>" + chips(users, "from") + "</div>";
    if (opts.usage !== false) html += reportUsage(n);
    if (n.columns && n.columns.length) {
      html += "<details><summary style='cursor:pointer;font-size:13px'><b>Columns (" + n.columns.length + ")</b></summary><div class='e2e-chips'>" +
        n.columns.map(function (c) { return "<span class='e2e-chip' style='cursor:default'>" + esc(c.name) + " <small>" + esc(c.type || "") + (c.calculated ? " \u00b7 calc" : "") + "</small></span>"; }).join("") + "</div></details>";
    }
    if (n.code) {
      var lang = n.lang === "sql" ? "Native SQL" : n.lang === "dax" ? "DAX" : "Power Query (M)";
      html += "<div class='e2e-sec'><b>" + lang + "</b>" + ((n.steps || []).length ? "<span class='hint'>click a step to explain it</span>" : "") + "</div>" +
        "<div class='e2e-code'><button type='button' class='e2e-btn' data-copy-code='1'>Copy</button><pre id='e2eMainCode'>" + (n.lang === "m" ? codeWithSteps(n) : esc(n.code)) + "</pre></div>";
    } else if (n.kind === "dataflow_query" && n.role === "Linked entity") {
      html += "<div class='e2e-sec'><span class='hint'>Linked entity: no Power Query of its own - it reads the upstream dataflow entity shown under Depends on.</span></div>";
    }
    html += sqlBlocks(n);
    html += stepsBlock(n);
    if (id !== cur.root && opts.reroot !== false) html += "<div style='margin-top:12px'><button type='button' class='e2e-btn' data-reroot='" + esc(id) + "'>Explore from this object</button></div>";
    (opts.target || $("e2eDetail")).innerHTML = html;
    if ((n.steps || []).length) selectStep(0);
    document.querySelectorAll((opts.map || "#e2eMap") + " .nd").forEach(function (g) { g.classList.toggle("sel", g.getAttribute("data-id") === id); });
  }

  function renderRoot() {
    var id = cur.root, n = N[id];
    if (!n) { $("e2eMain").style.display = "none"; $("e2eWelcome").style.display = ""; return; }
    $("e2eMain").style.display = "flex"; $("e2eWelcome").style.display = "none";
    var tr = trace(id, cur.dir);
    $("e2eTitle").textContent = displayName(n);
    $("e2eSub").textContent = KIND_LABEL[n.kind] + " · " + (n.group || "") + (n.workspace ? " · " + n.workspace : "");
    var counts = {}; tr.order.forEach(function (x) { var k = N[x].kind; counts[k] = (counts[k] || 0) + 1; });
    var maxLayer = 0; Object.keys(tr.layer).forEach(function (k) { maxLayer = Math.max(maxLayer, tr.layer[k]); });
    $("e2eStats").innerHTML = Object.keys(counts).sort(function (a, b) { return KIND_ORDER[a] - KIND_ORDER[b]; }).map(function (k) {
      var lbl = KIND_LABEL[k];
      if (counts[k] > 1) lbl = /query$/.test(lbl) ? lbl.slice(0, -1) + "ies" : /\)$/.test(lbl) ? lbl.replace(" (", "s (") : lbl + "s";
      return "<span>" + counts[k] + " " + esc(lbl) + "</span>";
    }).join("") + (maxLayer ? "<span>" + maxLayer + " dataflow layer(s)</span>" : "") + (tr.order.length === 1 ? "<span>No " + (cur.dir === "up" ? "upstream dependencies" : "downstream consumers") + "</span>" : "");
    $("e2eMap").innerHTML = mapSvg(tr, cur.zoom ? { zoom: cur.zoom, sel: id } : { fit: true, sel: id });
    if (!cur.zoom) {
      // Fit to width, but never below 70% so labels stay readable (scroll instead)
      var svgEl = $("e2eMap").querySelector("svg");
      var natW = svgEl && svgEl.viewBox && svgEl.viewBox.baseVal ? svgEl.viewBox.baseVal.width : 0;
      if (natW && svgEl.getBoundingClientRect().width / natW < 0.7) $("e2eMap").innerHTML = mapSvg(tr, { zoom: 0.7, sel: id });
    }
    $("e2eZoomLbl").textContent = cur.zoom ? Math.round(cur.zoom * 100) + "%" : "Fit";
    $("e2eExportBtn").style.display = n.kind === "measure" ? "" : "none";
    $("e2eExportAnyBtn").style.display = n.kind === "measure" ? "none" : "";
    renderDetail(id);
    document.querySelectorAll(".e2e-item").forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-id") === id); });
  }
  function log(ev) { try { if (window.pbidocLog) window.pbidocLog(ev); } catch (e) { /* ignore */ } }
  function setRoot(id, push) {
    if (!N[id]) { log({ type: "explorer-missing-node", id: id }); return; }
    cur.root = id;
    var n = N[id];
    var k = n.kind === "calc_table" ? "table" : n.kind;
    if (k !== cur.kind && LIST_KINDS.some(function (x) { return x[0] === k; })) { cur.kind = k; renderKinds(); renderList(); }
    if (push !== false) writeHash(true);
    var t0 = Date.now();
    renderRoot();
    var tr = trace(id, cur.dir), kinds = {};
    tr.order.forEach(function (x) { kinds[N[x].kind] = (kinds[N[x].kind] || 0) + 1; });
    var ext = tr.order.filter(function (x) { return N[x].external; }).length;
    log({ type: "explorer-select", id: id, dir: cur.dir, nodes: tr.order.length, edges: tr.edges.length, kinds: JSON.stringify(kinds),
      unscanned_dataflow_queries: ext, render_ms: Date.now() - t0 });
  }

  function highlight(id) {
    var map = $("e2eMap");
    map.classList.toggle("dim", !!id);
    map.querySelectorAll("path.ed").forEach(function (p) {
      p.classList.toggle("hl", !!id && (p.getAttribute("data-a") === id || p.getAttribute("data-b") === id));
    });
  }

  function exportSite(btn) {
    var qs = "?aspx=" + ($("e2eSiteAspx").checked ? "1" : "0") + "&anonymous=" + ($("e2eSiteAnon").checked ? "1" : "0");
    var t0 = Date.now();
    btn.disabled = true;
    $("e2eSiteStatus").textContent = "Building the export (regenerates every page - this can take a minute or two)...";
    log({ type: "export-site-start", aspx: $("e2eSiteAspx").checked, anonymous: $("e2eSiteAnon").checked });
    fetch("/api/export-site" + qs).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || ("HTTP " + r.status)); });
      var name = ((r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/) || [])[1] || "PBI_Documentation_Portal.zip";
      return r.blob().then(function (b) { return { blob: b, name: name }; });
    }).then(function (res) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(res.blob); a.download = res.name;
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      $("e2eSiteStatus").innerHTML = "Downloaded <b>" + esc(res.name) + "</b> (" + (res.blob.size / 1e6).toFixed(1) + " MB). Unzip it and see README.html inside for SharePoint options.";
      log({ type: "export-site-done", mb: +(res.blob.size / 1e6).toFixed(1), seconds: Math.round((Date.now() - t0) / 1000) });
    }).catch(function (err) {
      $("e2eSiteStatus").textContent = "Export failed: " + err.message;
      log({ type: "export-site-failed", message: String(err.message) });
    }).then(function () { btn.disabled = false; });
  }

  function openExportModal(mode) {
    var n = N[cur.root];
    var want = mode === "one" ? "" : ($("e2eModel").value || (n ? gkey(n) : ""));
    var ws = $("e2eWs").value;
    var one = n ? '<option value="one"' + (mode !== "model" ? " selected" : "") + ">" + (n.kind === "measure" ? "This measure: " : "Lineage of: ") + esc(displayName(n)) + "</option>" : "";
    $("e2eExpScope").innerHTML = one + Object.keys(GROUPS).map(function (k) { return GROUPS[k]; })
          .filter(function (g) { return g.type !== "df" && (!ws || g.ws === ws) && Object.keys(N).some(function (id) { return N[id].kind === "measure" && gkey(N[id]) === g.key; }); })
          .sort(function (a, b) { return a.name.toLowerCase().localeCompare(b.name.toLowerCase()) || a.ws.localeCompare(b.ws); })
          .map(function (g) {
            return '<option value="grp:' + esc(g.key) + '"' + (g.key === want ? " selected" : "") + ">All measures in " + esc(g.name) +
              (g.type === "rpt" ? " (thin report on " + esc(g.model || "?") + ")" : "") + " \u2014 " + esc(g.ws) + "</option>";
          }).join("");
    $("e2eExpModal").classList.add("open");
  }

  // Report visuals that use a measure / the columns of a table (from assets/report_usage.js)
  function reportUsage(n) {
    var U = window.REPORT_USAGE;
    if (!U || !U.use) return "";
    var keys = [];
    if (n.kind === "measure") keys = [n.id];
    else if (n.kind === "table" || n.kind === "calc_table" || n.kind === "calc_column") {
      var pre = "col:" + n.model_id + ":" + (n.kind === "calc_column" ? n.name : n.name + "[");
      keys = Object.keys(U.use).filter(function (k) { return n.kind === "calc_column" ? k === "col:" + n.model_id + ":" + n.name : k.indexOf(pre) === 0; });
    }
    var rows = [];
    keys.forEach(function (k) { (U.use[k] || []).forEach(function (u) { rows.push([k, u]); }); });
    if (!rows.length) return "";
    var byR = {};
    rows.forEach(function (x) { (byR[x[1][0]] = byR[x[1][0]] || []).push(x); });
    return "<b style='font-size:13px'>Used in report visuals (" + rows.length + " in " + Object.keys(byR).length + " report(s))</b><div class='e2e-chips'>" +
      Object.keys(byR).slice(0, 40).map(function (ri) {
        var r = U.reports[ri], u = byR[ri][0][1];
        var col = n.kind === "measure" ? "" : " \u00b7 " + byR[ri].map(function (x) { return x[0].replace(/^col:[^:]+:/, ""); }).filter(function (v, i, a) { return a.indexOf(v) === i; }).slice(0, 3).join(", ");
        return '<button type="button" class="e2e-chip" data-open-report="' + esc(r[0] + "|" + u[1] + "|" + u[2]) + '" title="' + esc(r[2]) + '">' + esc(r[1]) +
          " <small>" + byR[ri].length + " use(s)" + (u[5] ? " · e.g. " + esc(u[5]) : "") + esc(col) + "</small></button>";
      }).join("") + (Object.keys(byR).length > 40 ? "<span class='hint'>+" + (Object.keys(byR).length - 40) + " more</span>" : "") + "</div>";
  }
  function openReportInPortal(spec) {
    var g = spec.split("|"), h = "rpt:r=" + encodeURIComponent(g[0]) + (g[1] ? "&p=" + encodeURIComponent(g[1]) : "") + (g[2] ? "&v=" + encodeURIComponent(g[2]) : "");
    if (EMBED && window.parent !== window) toParent({ type: "pbidoc-open-hash", hash: h });
    else location.href = "index" + (/[.]aspx$/i.test(location.pathname) ? ".aspx" : ".html") + "#" + h;
  }

  function renderKpis() {
    var c = { measure: 0, rmeasure: 0, table: 0, dataflow_query: 0, source: 0, sql: 0 };
    Object.keys(N).forEach(function (id) {
      var n = N[id];
      if (n.outside) return;
      if (n.kind === "measure") { if (n.report_id) c.rmeasure++; else c.measure++; }
      else if (n.kind === "table" || n.kind === "calc_table") c.table++;
      else if (n.kind === "dataflow_query" && !n.external) c.dataflow_query++;
      else if (n.kind === "source") { c.source++; if (n.lang === "sql") c.sql++; }
    });
    var dfOk = (G.dataflows || []).filter(function (d) { return d.status === "ok"; }).length;
    var k = [[(G.models || []).length, "Semantic Models"], [dfOk + (dfOk !== (G.dataflows || []).length ? " / " + (G.dataflows || []).length : ""), "Dataflows (definition read)"],
      [(G.reports || []).length, "Thin Reports with Measures"], [c.measure, "Model Measures"], [c.rmeasure, "Report-level Measures"], [c.table, "Model Tables"],
      [c.dataflow_query, "Dataflow Queries"], [c.source, "Sources"], [c.sql, "Native SQL Queries"], [G.edges.length, "Dependencies"]];
    $("e2eKpis").innerHTML = k.map(function (x) { return '<div class="kpi-card"><div class="val">' + esc(typeof x[0] === "number" ? x[0].toLocaleString() : x[0]) + '</div><div class="lbl">' + esc(x[1]) + "</div></div>"; }).join("");
  }
  var EMBED = /[?&]embed=1/.test(location.search) || !!(window.PBIDOC_SHELL && /(^|&)embed=1/.test(window.PBIDOC_SHELL.query));
  function toParent(msg) { if (EMBED && window.parent !== window) { try { window.parent.postMessage(msg, "*"); } catch (e) { /* ignore */ } } }
  window.addEventListener("message", function (ev) {
    var d = ev.data || {};
    if (d.type === "pbidoc-e2e-export" && $("e2eExpModal")) openExportModal(d.mode || "auto");
    if (d.type === "pbidoc-theme" && d.theme) document.documentElement.setAttribute("data-theme", d.theme);
  });

  document.addEventListener("DOMContentLoaded", function () {
    if (!$("e2eList")) return;  // loaded by another page only for its documentation helpers
    renderKpis();
    var failed = (G.dataflows || []).filter(function (d) { return d.status !== "ok"; });
    if (failed.length) {
      $("e2eDfWarn").style.display = "";
      $("e2eDfWarn").innerHTML = "<b>" + failed.length + " dataflow(s) without a readable definition</b> (lineage stops at these): " +
        failed.slice(0, 12).map(function (d) { return esc(d.name + " (" + d.workspace + "): " + d.status); }).join("; ") + (failed.length > 12 ? "; ..." : "");
    }
    renderKinds(); renderWsFilter(); renderGroupFilter();
    applyHash(readHash());
    $("e2eSearch").addEventListener("input", renderList);
    $("e2eWs").addEventListener("change", function () { $("e2eModel").value = ""; $("e2eDetailF").value = ""; renderGroupFilter(); renderList(); writeHash(false);
      log({ type: "explorer-filter", ws: $("e2eWs").value }); });
    $("e2eModel").addEventListener("change", function () { $("e2eDetailF").value = ""; renderList(); writeHash(false);
      log({ type: "explorer-filter", ws: $("e2eWs").value, grp: $("e2eModel").value }); });
    $("e2eDetailF").addEventListener("change", function () { renderList(); writeHash(false); });
    $("e2eReset").addEventListener("click", function (e) { e.preventDefault(); $("e2eWs").value = ""; $("e2eSearch").value = ""; $("e2eDetailF").value = "";
      renderGroupFilter(); $("e2eModel").value = ""; renderList(); writeHash(false); });
    document.addEventListener("click", function (e) {
      var t;
      if ((t = e.target.closest("[data-open-report]"))) { openReportInPortal(t.getAttribute("data-open-report")); return; }
      if ((t = e.target.closest("[data-step-go]"))) { e.preventDefault(); if (!t.disabled) selectStep(+t.getAttribute("data-step-go")); return; }
      if ((t = e.target.closest("#e2eMainCode .stp"))) { selectStep(+t.getAttribute("data-step")); return; }
      if ((t = e.target.closest("a[data-goto]"))) { e.preventDefault(); renderDetail(t.getAttribute("data-goto")); return; }
      if ((t = e.target.closest("[data-kind]"))) { cur.kind = t.getAttribute("data-kind"); $("e2eDetailF").value = ""; renderKinds(); renderList(); writeHash(false); return; }
      if ((t = e.target.closest(".e2e-item"))) { setRoot(t.getAttribute("data-id")); return; }
      if ((t = e.target.closest("#e2eMap .nd"))) { renderDetail(t.getAttribute("data-id")); return; }
      if ((t = e.target.closest("[data-goto]"))) { renderDetail(t.getAttribute("data-goto")); return; }
      if ((t = e.target.closest("[data-reroot]"))) { setRoot(t.getAttribute("data-reroot")); return; }
      if ((t = e.target.closest("[data-dir]"))) {
        cur.dir = t.getAttribute("data-dir");
        document.querySelectorAll("[data-dir]").forEach(function (b) { b.classList.toggle("active", b === t); });
        renderRoot(); return;
      }
      if ((t = e.target.closest("[data-zoom]"))) {
        var z = t.getAttribute("data-zoom");
        cur.zoom = z === "fit" ? (cur.zoom ? 0 : 1) : Math.max(0.3, Math.min(2.5, (cur.zoom || 1) * (z === "in" ? 1.2 : 1 / 1.2)));
        renderRoot(); return;
      }
      if ((t = e.target.closest("[data-copy-code]"))) {
        var pre = t.parentElement.querySelector("pre");
        if (pre && navigator.clipboard) { navigator.clipboard.writeText(pre.textContent); t.textContent = "Copied!"; setTimeout(function () { t.textContent = "Copy"; }, 1200); }
        return;
      }
      if (e.target.closest("#e2eExportBtn") || e.target.closest("#e2eExportAnyBtn")) { openExportModal("one"); return; }
      if (e.target.closest("#e2eWelcomeExport")) { openExportModal("model"); return; }
      if (e.target.closest("#e2eExportModelBtn")) { openExportModal("model"); return; }
      if (e.target.closest("#e2eExportSiteBtn")) { $("e2eSiteStatus").textContent = ""; $("e2eSiteModal").classList.add("open"); return; }
      if (e.target.closest("#e2eSiteCancel") || e.target === $("e2eSiteModal")) { $("e2eSiteModal").classList.remove("open"); return; }
      if ((t = e.target.closest("#e2eSiteGo")) && !t.disabled) { exportSite(t); return; }
      if (e.target.closest("#e2eExpCancel") || e.target === $("e2eExpModal")) { $("e2eExpModal").classList.remove("open"); return; }
      if (e.target.closest("#e2eExpGo")) {
        var scope = $("e2eExpScope").value, fmt = $("e2eExpFmt").value, ids, title;
        if (scope.indexOf("grp:") === 0) {
          var gk = scope.slice(4);
          ids = Object.keys(N).filter(function (k) { return N[k].kind === "measure" && gkey(N[k]) === gk && !N[k].hidden; })
            .sort(function (a, b) { return N[a].name.toLowerCase().localeCompare(N[b].name.toLowerCase()); });
          title = ((GROUPS[gk] || {}).name || "Model") + " - Measure Documentation";
        } else if (cur.root) { ids = [cur.root]; title = N[cur.root].name + " - Measure Documentation"; } else { ids = []; }
        log({ type: "explorer-export", format: fmt, scope: scope, measures: ids.length });
        if (ids.length) exportDocs(ids, fmt, title);
        $("e2eExpModal").classList.remove("open");
      }
    });
    $("e2eMap").addEventListener("mouseover", function (e) { var g = e.target.closest(".nd"); highlight(g ? g.getAttribute("data-id") : null); });
    $("e2eMap").addEventListener("mouseleave", function () { highlight(null); });
    log({ type: "explorer-loaded", nodes: Object.keys(N).length, edges: G.edges.length, models: (G.models || []).length,
      dataflows: (G.dataflows || []).length, dataflows_not_ok: failed.length });
    var h0 = readHash();
    if (h0.node) setRoot(h0.node, false);
    // Back / forward buttons and pasted links on an open page only change the hash
    function onNav() {
      var h = readHash();
      applyHash(h);
      if (h.node && h.node !== cur.root) setRoot(h.node, false);
    }
    window.addEventListener("hashchange", onNav);
    window.addEventListener("popstate", onNav);
  });
  window.E2E_API = { trace: trace, buildDoc: buildDoc, mapSvg: mapSvg, mdToHtml: mdToHtml, mermaidFor: mermaidFor, exportDocs: exportDocs,
    renderDetail: renderDetail, selectStep: selectStep,
    download: download, DOC_CSS: DOC_CSS, fence: fence, mdEsc: mdEsc, esc: esc, displayName: displayName, KIND_LABEL: KIND_LABEL, OUT: OUT, IN: IN };
})();
"""


def _page_html(stats_line: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>End-to-End Lineage</title>
<script>
// The explorer lives inside the portal home page (tab 6). Opened on its own it forwards there, keeping the deep link.
(function () {{
  var embed = /[?&]embed=1/.test(location.search) || !!(window.PBIDOC_SHELL && /(^|&)embed=1/.test(window.PBIDOC_SHELL.query));
  if (!embed && !window.PBIDOC_SHELL && window.top === window && !/[?&]standalone=1/.test(location.search)) {{
    var ext = /[.]aspx$/i.test(location.pathname) ? ".aspx" : ".html";
    location.replace("index" + ext + "#e2e" + (location.hash.length > 1 ? ":" + location.hash.slice(1) : ""));
  }}
  if (embed) document.documentElement.className += " e2e-embed";
}})();
</script>
<link rel="stylesheet" href="assets/portal.css">
<style>{E2E_CSS}</style>
<script src="assets/portal_common.js"></script>
<script src="assets/e2e_graph.js"></script>
<script src="assets/report_usage.js"></script>
<script src="assets/e2e_explorer.js"></script>
</head>
<body>
<header class="topbar">
  <div class="topbar-row">
    <div>
      <h1>End-to-End Measure Lineage</h1>
      <p>{stats_line}</p>
    </div>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <a class="e2e-btn" href="index.html">&larr; Portal home</a>
      <button type="button" class="e2e-btn" id="e2eExportModelBtn">Export model documentation</button>
      <button type="button" class="e2e-btn primary studio-only-link" id="e2eExportSiteBtn" style="display:none" title="Download the complete portal as a folder you can store in SharePoint">Export all data</button>
      <button type="button" class="theme-icon-btn" data-toggle-theme="1" title="Toggle Light / Dark theme" aria-label="Toggle Light / Dark theme">
        <svg class="icon-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        <svg class="icon-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/></svg>
      </button>
    </div>
  </div>
</header>
<div class="e2e-kpiwrap"><div class="kpi-grid" id="e2eKpis"></div></div>
<div class="e2e-wrap">
  <aside class="e2e-side">
    <label class="e2e-flbl" for="e2eWs">1. Workspace</label>
    <select id="e2eWs" aria-label="Filter by workspace"></select>
    <label class="e2e-flbl" for="e2eModel">2. Semantic model / thin report / dataflow</label>
    <select id="e2eModel" aria-label="Filter by semantic model, thin report or dataflow"></select>
    <label class="e2e-flbl" for="e2eDetailF">3. Details <a href="#" id="e2eReset" style="display:none;float:right;font-weight:500">Reset filters</a></label>
    <select id="e2eDetailF" aria-label="Filter by table, folder, role, connector"></select>
    <input id="e2eSearch" type="search" placeholder="Search measures, tables, queries, sources..." aria-label="Search">
    <div class="e2e-kinds" id="e2eKinds"></div>
    <div class="e2e-count" id="e2eCount"></div>
    <div class="e2e-list" id="e2eList"></div>
  </aside>
  <section class="e2e-main">
    <div class="e2e-card" id="e2eDfWarn" style="display:none;font-size:13px;border-color:var(--warn);background:var(--warn-bg)"></div>
    <div class="e2e-card e2e-empty" id="e2eWelcome">
      <h2 style="margin-top:0;color:var(--fg)">Pick a measure to trace</h2>
      <button type="button" class="e2e-btn primary" id="e2eWelcomeExport" style="float:right;margin:-36px 0 0 10px">Export measure documentation</button>
      Select a DAX measure on the left to see every measure it uses, the tables and columns they read, the dataset Power Query,
      each dataflow layer feeding those tables, and the SQL / Excel / file sources at the bottom of the chain.
    </div>
    <div id="e2eMain" style="display:none;flex-direction:column;gap:14px">
      <div class="e2e-card">
        <div class="e2e-head">
          <div><h2 id="e2eTitle"></h2><div class="sub" id="e2eSub"></div></div>
          <div class="e2e-actions">
            <div class="e2e-seg"><button type="button" data-dir="up" class="active">Upstream (where it comes from)</button><button type="button" data-dir="down">Downstream (what uses it)</button></div>
            <button type="button" class="e2e-btn" data-zoom="out" aria-label="Zoom out">&minus;</button>
            <button type="button" class="e2e-btn" data-zoom="fit" id="e2eZoomLbl" title="Toggle fit-to-width / 100%">Fit</button>
            <button type="button" class="e2e-btn" data-zoom="in" aria-label="Zoom in">+</button>
            <button type="button" class="e2e-btn primary" id="e2eExportBtn">Export measure documentation</button>
            <button type="button" class="e2e-btn" id="e2eExportAnyBtn" style="display:none">Export lineage documentation</button>
          </div>
        </div>
        <div class="e2e-stats" id="e2eStats"></div>
      </div>
      <div class="e2e-card">
        <div class="e2e-map" id="e2eMap"></div>
        <div class="e2e-legend">
          <span><i style="background:#fef3c7;border-color:#b45309"></i>Source / SQL</span>
          <span><i style="background:#ede9fe;border-color:#6d28d9"></i>Dataflow query (DF L1 = closest to the model)</span>
          <span><i style="background:#e0f2fe;border-color:#0369a1"></i>Dataset query</span>
          <span><i style="background:#dcfce7;border-color:#15803d"></i>Model table</span>
          <span><i style="background:#ccfbf1;border-color:#0f766e"></i>Calculated column</span>
          <span><i style="background:#fce7f3;border-color:#be185d"></i>DAX measure</span>
          <span><i style="background:transparent;border-color:#64748b;border-style:dashed"></i>Not scanned</span>
        </div>
      </div>
      <div class="e2e-card e2e-detail" id="e2eDetail"></div>
    </div>
  </section>
</div>
<div class="e2e-modal-bg" id="e2eSiteModal">
  <div class="e2e-modal" role="dialog" aria-modal="true" aria-labelledby="e2eSiteTitle">
    <h3 id="e2eSiteTitle">Export all data</h3>
    <p style="font-size:13px;margin:0 0 8px">Downloads a .zip with the complete documentation portal: every workspace, semantic model page, the DAX and Power Query catalogs,
      lineage, governance checks, and this end-to-end explorer with SQL, step browser and documentation export.
      Unzip it into a SharePoint document library (or any shared folder) and open <b>index</b>. It works offline and never contacts Power BI.</p>
    <label style="display:flex;gap:8px;align-items:flex-start;color:var(--fg)"><input type="checkbox" id="e2eSiteAspx" checked style="margin-top:3px">
      <span>Add SharePoint <b>.aspx</b> page copies <span style="color:var(--fg-muted)">- SharePoint Online downloads .html files instead of opening them; .aspx pages open in the browser on sites that allow custom scripts</span></span></label>
    <label style="display:flex;gap:8px;align-items:flex-start;color:var(--fg)"><input type="checkbox" id="e2eSiteAnon" style="margin-top:3px">
      <span>Anonymize people names <span style="color:var(--fg-muted)">- hide owners and user permission lists</span></span></label>
    <div id="e2eSiteStatus" style="font-size:13px;margin-top:10px;color:var(--fg-muted)"></div>
    <div class="row"><button type="button" class="e2e-btn" id="e2eSiteCancel">Close</button><button type="button" class="e2e-btn primary" id="e2eSiteGo">Download .zip</button></div>
  </div>
</div>
<div class="e2e-modal-bg" id="e2eExpModal">
  <div class="e2e-modal" role="dialog" aria-modal="true" aria-labelledby="e2eExpTitle">
    <h3 id="e2eExpTitle">Export documentation</h3>
    <label for="e2eExpScope">Scope</label>
    <select id="e2eExpScope"></select>
    <label for="e2eExpFmt">Format</label>
    <select id="e2eExpFmt">
      <option value="html">HTML (open in browser, print to PDF)</option>
      <option value="doc">Word (.doc)</option>
      <option value="md">Markdown (.md, with Mermaid reference map)</option>
    </select>
    <div class="row"><button type="button" class="e2e-btn" id="e2eExpCancel">Cancel</button><button type="button" class="e2e-btn primary" id="e2eExpGo">Download</button></div>
  </div>
</div>
</body>
</html>
"""


def write_e2e_explorer(out_root: Path, graph: dict) -> Path:
    """Write `e2e_lineage.html` + its assets into the portal folder."""
    assets = out_root / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(graph, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    (assets / "e2e_graph.js").write_text(f"window.E2E_GRAPH = {payload};\n", encoding="utf-8")
    (assets / "e2e_explorer.js").write_text(E2E_JS, encoding="utf-8")
    stats = f"{len(graph['models'])} semantic model(s) &bull; {len(graph['dataflows'])} dataflow(s)"
    out = out_root / "e2e_lineage.html"
    out.write_text(_page_html(stats), encoding="utf-8")
    return out
