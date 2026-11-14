"""
Portal-wide export buttons ("Export ... documentation" + "Export all data") and the embedded
End-to-End explorer tab.

- `build_portal_meta` writes `assets/portal_meta.js`: the small, page-independent facts the documentation
  builders need besides the lineage graph (relationships, findings, report bindings, dataflow usage).
- `PORTAL_EXPORT_JS` (`assets/portal_export.js`) is loaded by the portal home page and every model page. The
  documentation offered depends on where the user is: models, workspaces & reports, dataflows, lineage,
  governance & health, or (End-to-End tab) measures. It lazy-loads the lineage graph and reuses the explorer's
  Markdown/HTML/Word writers, so every export works offline (file share, SharePoint) as well as in Studio.
"""

from __future__ import annotations

import json
from pathlib import Path


def build_portal_meta(analyses: list[tuple[str, dict]], xref: dict, state: dict, health_items: list[dict], anonymous: bool = False) -> dict:
    models = {}
    for slug, a in analyses:
        ds_id = a.get("dataset_id", "")
        mx = xref["models"].get(ds_id) or {"tables": {}, "dataflows": {}}
        nodes = xref["nodes"]
        models[ds_id] = {
            "name": a["name"],
            "workspace": a["workspace"],
            "slug": slug,
            "format": a.get("storage_mode", ""),
            "owner": "Redacted" if anonymous else (a.get("configured_by") or ""),
            "stats": a["stats"],
            "source_types": a["source_types"],
            "relationships": a["parsed"]["relationships"],
            "rls_roles": [r["name"] for r in a["parsed"].get("roles", [])],
            "findings": [{"severity": f["severity"], "title": f["title"], "detail": f["detail"]} for f in a["findings"]],
            "reports": [
                {"id": r.get("id", ""), "name": r.get("name", ""), "workspace": r.get("workspace", ""), "status": r.get("measures_status", "")}
                for r in a["reports"]
            ],
            "tables": {
                t: {
                    "direct": info["direct"],
                    "dfs": sorted({(nodes[q].get("group_id", ""), mx["dataflows"].get(nodes[q].get("group_id", ""), {}).get("layer", 1)) for q in info["dataflow_queries"] if q in nodes}),
                    "sources": info["sources"][:60],
                }
                for t, info in mx["tables"].items()
            },
            "dataflows": [
                {"id": gid, "layer": i["layer"], "entities": sorted(i["entities"]), "tables": sorted(i["tables"])}
                for gid, i in sorted(mx["dataflows"].items(), key=lambda kv: kv[1]["layer"])
            ],
        }
    dataflows = {
        gid: {
            "name": d["name"],
            "workspace": d["workspace"],
            "status": d["status"],
            "outside": d["outside"],
            "configured_by": "Redacted" if anonymous else d.get("configured_by", ""),
            "roles": dict(d["roles"]),
            "connectors": sorted(d["connectors"]),
            "sql": d["sql_queries"],
            "upstream": sorted(d["upstream"]),
            "downstream": sorted(d["downstream"]),
            "models": [
                {"id": mid, "name": m["name"], "workspace": m["workspace"], "tables": sorted(m["tables"]), "direct": m["direct"]}
                for mid, m in sorted(d["models"].items(), key=lambda kv: kv[1]["name"].lower())
            ],
        }
        for gid, d in xref["dataflows"].items()
    }
    reports = []
    for r in sorted(state.get("reports", {}).values(), key=lambda r: (r.get("workspace", "").lower(), r.get("name", "").lower())):
        ds = r.get("dataset_id", "")
        dm = state.get("models", {}).get(ds) or (state.get("out_of_scope_models") or {}).get(ds) or {}
        xr = xref["reports"].get(r.get("id", ""))
        reports.append(
            {
                "id": r.get("id", ""),
                "name": r.get("name", ""),
                "workspace": r.get("workspace", ""),
                "model_id": ds,
                "model": dm.get("name", ""),
                "model_workspace": dm.get("workspace", ""),
                "status": r.get("measures_status", ""),
                "report_measures": len(xr["measures"]) if xr else 0,
            }
        )
    workspaces = []
    for ws_id, ws in sorted(state.get("workspaces", {}).items(), key=lambda kv: kv[1].get("name", "").lower()):
        workspaces.append(
            {
                "name": ws.get("name", ""),
                "sku": ws.get("capacity_sku") or ("Dedicated" if ws.get("is_dedicated") else "Shared (Pro)"),
                "models": sum(1 for m in state.get("models", {}).values() if m.get("workspace_id") == ws_id),
                "reports": sum(1 for r in state.get("reports", {}).values() if r.get("workspace_id") == ws_id),
                "dataflows": sum(1 for d in state.get("dataflows", {}).values() if d.get("workspace_id") == ws_id),
            }
        )
    return {"models": models, "dataflows": dataflows, "reports": reports, "workspaces": workspaces, "health": health_items}


def write_portal_meta(out_root: Path, meta: dict) -> None:
    payload = json.dumps(meta, ensure_ascii=False, separators=(",", ":"), default=list).replace("</", "<\\/")
    (out_root / "assets" / "portal_meta.js").write_text(f"window.PORTAL_META = {payload};\n", encoding="utf-8")
    (out_root / "assets" / "portal_export.js").write_text(PORTAL_EXPORT_JS, encoding="utf-8")


HEADER_BUTTONS = (
    '<button type="button" class="pd-hbtn" id="pdExportDocBtn">Export model documentation</button>'
    '<button type="button" class="pd-hbtn primary studio-only-link" id="pdExportSiteBtn" style="display:none" '
    'title="Download the complete portal as a folder you can store in SharePoint">Export all data</button>'
)

PORTAL_EXPORT_CSS = r"""
.pd-hbtn { border: 1px solid rgba(255,255,255,.45); background: rgba(255,255,255,.12); color: #fff; border-radius: 8px; padding: 7px 12px; font: inherit; font-size: 12.5px; font-weight: 600; cursor: pointer; }
.pd-hbtn:hover { background: rgba(255,255,255,.22); }
/* Stable header: the export label changes per tab, so the button keeps one width and nothing re-wraps */
.topbar .pd-hbtn { white-space: nowrap; flex-shrink: 0; }
.topbar #pdExportDocBtn { width: 21.5em; overflow: hidden; text-overflow: ellipsis; text-align: center; }
.topbar-row { flex-wrap: nowrap; }
.topbar-row > div:first-child { flex: 1 1 auto; min-width: 0; }
.topbar-row > div:first-child h1, .topbar-row > div:first-child p { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.topbar-row > div:last-child { flex: 0 0 auto; flex-wrap: nowrap !important; }
.top-tabs { flex-wrap: nowrap; overflow-x: auto; overflow-y: hidden; scrollbar-width: none; }
.top-tabs::-webkit-scrollbar { display: none; }
.top-tab { white-space: nowrap; flex-shrink: 0; padding: 10px 15px; }
@media (max-width: 900px) {
  .topbar-row { flex-wrap: wrap; }
  .topbar-row > div:last-child { flex-wrap: wrap !important; }
  .topbar #pdExportDocBtn { width: auto; }
}
.pd-hbtn.primary { background: #fff; color: #0b3d91; border-color: #fff; }
.doc-sidebar .pd-hbtn { border-color: var(--border); background: var(--surface-alt); color: var(--fg); }
.doc-sidebar .pd-hbtn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.pd-modal-bg { position: fixed; inset: 0; background: rgba(15,23,42,.5); display: none; align-items: center; justify-content: center; z-index: 2147483000; padding: 16px; }
.pd-modal-bg.open { display: flex; }
.pd-modal { background: var(--surface); color: var(--fg); border-radius: 12px; padding: 18px; width: min(560px, 100%); border: 1px solid var(--border); box-shadow: 0 12px 40px rgba(0,0,0,.25); }
.pd-modal h3 { margin: 0 0 6px; font-size: 17px; }
.pd-modal p { font-size: 13px; color: var(--fg-muted); margin: 0 0 8px; }
.pd-modal label.f { display: block; font-size: 12.5px; margin: 10px 0 4px; color: var(--fg-muted); font-weight: 600; }
.pd-modal select { width: 100%; padding: 7px 10px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg); font: inherit; font-size: 13px; }
.pd-modal .row { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; flex-wrap: wrap; }
.pd-modal .row button { border: 1px solid var(--border); background: var(--surface-alt); color: var(--fg); border-radius: 8px; padding: 7px 13px; font: inherit; font-size: 13px; cursor: pointer; }
.pd-modal .row button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
.pd-modal .row button:disabled { opacity: .6; cursor: progress; }
.pd-status { font-size: 12.5px; color: var(--fg-muted); margin-top: 10px; min-height: 16px; }
#tab-e2e { margin: 0 -18px; }
#e2eFrame { width: 100%; border: 0; display: block; background: var(--bg); }
"""

PORTAL_EXPORT_JS = r"""
(function () {
  "use strict";
  var me = document.currentScript;
  var BASE = (me && me.getAttribute("data-base")) || "";
  var PAGE_MODEL = (me && me.getAttribute("data-model")) || "";
  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function log(ev) { try { if (window.pbidocLog) window.pbidocLog(ev); } catch (e) { /* ignore */ } }

  // ---------------- lazy data loading ----------------
  function loadScript(src) {
    if (window.PBIDOC_SHELL) {
      // Single-file SharePoint export: files come from the shell, run them as inline scripts
      return window.PBIDOC_SHELL.load(src).then(function (text) {
        var s = document.createElement("script");
        s.textContent = text;
        document.head.appendChild(s);
      });
    }
    return new Promise(function (res, rej) {
      var s = document.createElement("script");
      s.src = src; s.onload = function () { res(); }; s.onerror = function () { rej(new Error("Could not load " + src)); };
      document.head.appendChild(s);
    });
  }
  var metaP = null, allP = null;
  function ensureMeta() { return metaP || (metaP = window.PORTAL_META ? Promise.resolve() : loadScript(BASE + "assets/portal_meta.js")); }
  function ensureAll() {
    return allP || (allP = ensureMeta()
      .then(function () { return window.E2E_GRAPH ? null : loadScript(BASE + "assets/e2e_graph.js"); })
      .then(function () { return window.E2E_API ? null : loadScript(BASE + "assets/e2e_explorer.js"); }));
  }

  // ---------------- what to export depends on where the user is ----------------
  var CTX = {
    "tab-portfolio": { kind: "model", label: "Export model documentation", title: "Export semantic model documentation",
      hint: "Tables and columns, Power Query and native SQL, upstream dataflows and sources, relationships, every DAX measure, thin-report measures, reports and health findings." },
    "tab-workspaces": { kind: "workspace", label: "Export workspace & report documentation", title: "Export workspace & report documentation",
      hint: "Semantic models, reports and the models they connect to, report-level measures of thin reports (with DAX) and dataflows per workspace." },
    "tab-reports": { kind: "report", label: "Export report documentation", title: "Export report documentation",
      hint: "Every page with its filters, every visual with its type, fields, visual filters and slicer selections, plus the DAX of every measure the report uses." },
    "tab-dataflows": { kind: "dataflow", label: "Export dataflow documentation", title: "Export dataflow documentation",
      hint: "Every query with its role, Power Query steps, native SQL, sources, linked entities, upstream / downstream dataflows and the semantic models it feeds." },
    "tab-lineage": { kind: "lineage", label: "Export lineage documentation", title: "Export data lineage documentation",
      hint: "Per model table: the dataflow entity it loads, every upstream dataflow layer and the original sources with their native SQL." },
    "tab-health": { kind: "health", label: "Export governance & health report", title: "Export governance & health report",
      hint: "All findings (models, dataflows, report definitions) with severity and recommended action." },
    "tab-e2e": { kind: "measure", label: "Export measure documentation", title: "", hint: "" }
  };
  function context() {
    if (PAGE_MODEL) return CTX["tab-portfolio"];
    var pane = document.querySelector(".tab-pane.active");
    return CTX[pane && pane.id] || CTX["tab-portfolio"];
  }
  function updateLabel() { var b = $("pdExportDocBtn"); if (b) b.textContent = context().label; }

  // ---------------- modals ----------------
  function injectModals() {
    var d = document.createElement("div");
    d.innerHTML =
      '<div class="pd-modal-bg" id="pdDocModal"><div class="pd-modal" role="dialog" aria-modal="true" aria-labelledby="pdDocTitle">' +
      '<h3 id="pdDocTitle"></h3><p id="pdDocHint"></p>' +
      '<label class="f" for="pdDocScope">Scope</label><select id="pdDocScope"><option>Loading...</option></select>' +
      '<label class="f" for="pdDocFmt">Format</label><select id="pdDocFmt"><option value="html">HTML (open in browser, print to PDF)</option>' +
      '<option value="doc">Word (.doc)</option><option value="md">Markdown (.md)</option></select>' +
      '<div class="pd-status" id="pdDocStatus"></div>' +
      '<div class="row"><button type="button" id="pdDocCancel">Cancel</button><button type="button" class="primary" id="pdDocGo">Download</button></div></div></div>' +
      '<div class="pd-modal-bg" id="pdSiteModal"><div class="pd-modal" role="dialog" aria-modal="true" aria-labelledby="pdSiteTitle">' +
      '<h3 id="pdSiteTitle">Export all data</h3>' +
      '<p>Exports the complete documentation portal: workspaces, semantic model pages, dataflows, DAX and Power Query catalogs, lineage, ' +
      'governance checks and the end-to-end explorer. It works offline and never contacts Power BI.</p>' +
      '<label style="display:flex;gap:8px;align-items:flex-start;font-size:13px;margin-top:8px"><input type="radio" name="pdSiteFmt" value="single" checked style="margin-top:3px">' +
      '<span><b>Single file for SharePoint (.html)</b> - recommended <span style="color:var(--fg-muted)">- upload this one file to a document library and click it; ' +
      'it opens in the SharePoint viewer with everything inside</span></span></label>' +
      '<label style="display:flex;gap:8px;align-items:flex-start;font-size:13px;margin-top:8px"><input type="radio" name="pdSiteFmt" value="zip" style="margin-top:3px">' +
      '<span><b>Complete folder (.zip)</b> <span style="color:var(--fg-muted)">- for a synced SharePoint / OneDrive folder, file share or web server (also contains the single file)</span></span></label>' +
      '<label style="display:flex;gap:8px;align-items:flex-start;font-size:13px;margin:8px 0 0 22px"><input type="checkbox" id="pdSiteAspx" style="margin-top:3px">' +
      '<span>Add <b>.aspx</b> page copies to the .zip <span style="color:var(--fg-muted)">- only for SharePoint sites that still allow custom scripts</span></span></label>' +
      '<label style="display:flex;gap:8px;align-items:flex-start;font-size:13px;margin-top:8px"><input type="checkbox" id="pdSiteAnon" style="margin-top:3px">' +
      '<span>Anonymize people names <span style="color:var(--fg-muted)">- hide owners and user permission lists</span></span></label>' +
      '<div class="pd-status" id="pdSiteStatus"></div>' +
      '<div class="row"><button type="button" id="pdSiteCancel">Close</button><button type="button" class="primary" id="pdSiteGo">Download</button></div></div></div>';
    while (d.firstChild) document.body.appendChild(d.firstChild);
  }

  function opt(v, label, sel) { return '<option value="' + esc(v) + '"' + (sel ? " selected" : "") + ">" + esc(label) + "</option>"; }
  function byName(a, b) { return String(a.name).toLowerCase().localeCompare(String(b.name).toLowerCase()); }
  function wsList() { return (window.PORTAL_META.workspaces || []).map(function (w) { return w.name; }); }
  function activeWs() {
    var chip = document.querySelector("[data-ws-chip].active");
    if (chip) return chip.textContent.replace(/^Workspace:\s*/, "");
    var dfWs = $("dfWs");
    if (dfWs && dfWs.value && dfWs.options[dfWs.selectedIndex]) return dfWs.options[dfWs.selectedIndex].text;
    return "";
  }
  function scopeOptions(kind) {
    var M = window.PORTAL_META, ws = activeWs(), h = [];
    var models = Object.keys(M.models).map(function (id) { var m = M.models[id]; return { id: id, name: m.name, ws: m.workspace }; }).sort(byName);
    if (kind === "model" || kind === "lineage") {
      if (PAGE_MODEL && M.models[PAGE_MODEL]) h.push(opt("model:" + PAGE_MODEL, "This model: " + M.models[PAGE_MODEL].name, true));
      wsList().forEach(function (w) { h.push(opt("ws:" + w, "All models in workspace " + w + " (one document)", !PAGE_MODEL && w === ws)); });
      h.push('<optgroup label="Single semantic model">' + models.map(function (m) { return opt("model:" + m.id, m.name + " — " + m.ws); }).join("") + "</optgroup>");
    } else if (kind === "workspace") {
      h.push(opt("all", "All workspaces (one document)", !ws));
      wsList().forEach(function (w) { h.push(opt("ws:" + w, "Workspace " + w, w === ws)); });
    } else if (kind === "dataflow") {
      var dfs = Object.keys(M.dataflows).filter(function (g) { return !M.dataflows[g].outside; })
        .map(function (g) { var d = M.dataflows[g]; return { id: g, name: d.name, ws: d.workspace }; }).sort(byName);
      wsList().forEach(function (w) { if (dfs.some(function (d) { return d.ws === w; })) h.push(opt("ws:" + w, "All dataflows in workspace " + w + " (one document)", w === ws)); });
      h.push('<optgroup label="Single dataflow">' + dfs.map(function (d) { return opt("df:" + d.id, d.name + " — " + d.ws); }).join("") + "</optgroup>");
    } else if (kind === "report") {
      var cr = window.REPORT_EXPLORER_CURRENT || "", RI = window.REPORT_INDEX || [];
      var rx = RI.filter(function (r) { return r.id === cr; })[0];
      if (rx) h.push(opt("rpt:" + rx.id, "This report: " + rx.name, true));
      var rws = {}; RI.forEach(function (r) { rws[r.workspace] = 1; });
      Object.keys(rws).sort().forEach(function (w) { h.push(opt("ws:" + w, "All reports in workspace " + w + " (one document)", !rx && w === ws)); });
      h.push('<optgroup label="Single report">' + RI.slice().sort(byName).map(function (r) { return opt("rpt:" + r.id, r.name + " \u2014 " + r.workspace); }).join("") + "</optgroup>");
    } else if (kind === "health") {
      h.push(opt("all", "All workspaces", !ws));
      wsList().forEach(function (w) { h.push(opt("ws:" + w, "Workspace " + w, w === ws)); });
    }
    return h.join("");
  }

  function openDocModal() {
    var c = context();
    if (c.kind === "measure") { sendToFrame({ type: "pbidoc-e2e-export", mode: "auto" }); return; }
    $("pdDocTitle").textContent = c.title;
    $("pdDocHint").textContent = c.hint;
    $("pdDocStatus").textContent = "";
    $("pdDocScope").innerHTML = "<option>Loading...</option>";
    $("pdDocModal").classList.add("open");
    ensureMeta().then(function () { $("pdDocScope").innerHTML = scopeOptions(c.kind); })
      .catch(function (err) { $("pdDocStatus").textContent = err.message; });
  }

  // ---------------- documentation builders (Markdown; HTML / Word via the explorer's writer) ----------------
  var IDX = null;
  function index() {
    if (IDX) return IDX;
    var N = window.E2E_GRAPH.nodes, byModel = {}, byDf = {};
    Object.keys(N).forEach(function (id) {
      var n = N[id];
      if (n.model_id) (byModel[n.model_id] = byModel[n.model_id] || []).push(n);
      if (n.kind === "dataflow_query" && !n.external) (byDf[n.group_id] = byDf[n.group_id] || []).push(n);
    });
    return (IDX = { N: N, byModel: byModel, byDf: byDf });
  }
  function cell(s) { return window.E2E_API.mdEsc(s == null ? "" : s); }
  function fence(code, lang) { return window.E2E_API.fence(code, lang); }
  function tableMd(head, rows) {
    if (!rows.length) return ["_None._", ""];
    return ["| " + head.join(" | ") + " |", "|" + head.map(function () { return "---"; }).join("|") + "|"]
      .concat(rows.map(function (r) { return "| " + r.map(cell).join(" | ") + " |"; })).concat([""]);
  }
  function srcLabel(n) { return n ? (n.source_type || "Source") + ": " + n.name + (n.subtitle ? " (" + n.subtitle + ")" : "") : ""; }
  function dfName(gid) { var d = window.PORTAL_META.dataflows[gid]; return d ? d.name + " (" + d.workspace + ")" : gid; }
  function sqlBlocks(n, idx) {
    var o = [];
    (n.sql || []).forEach(function (q, i) {
      var s = idx.N[q.source_id];
      if (!s || !s.code) return;
      o.push("", "**Native SQL" + ((n.sql || []).length > 1 ? " " + (i + 1) : "") + "** (" + [q.connector, q.database].filter(Boolean).join(" · ") + (q.via ? ", via " + q.via : "") + "):", "", fence(s.code, "sql"));
    });
    return o;
  }
  function stepLines(n) {
    var st = n.steps || [];
    if (!st.length) return [];
    var o = ["", "**Power Query steps (" + st.length + "):**", ""];
    st.forEach(function (x, i) { o.push("- **" + (i + 1) + ". " + x.name + "** [" + x.category_label + "] - " + x.summary + (x.is_output ? " _(final output)_" : "")); });
    return o;
  }
  function header(title, rows) {
    var o = ["# " + title, "", "| Property | Value |", "|---|---|"];
    rows.forEach(function (r) { if (r[1] !== "" && r[1] != null) o.push("| " + cell(r[0]) + " | " + cell(r[1]) + " |"); });
    o.push("| Generated | " + cell(window.E2E_GRAPH.generated_at) + " |", "");
    return o;
  }

  function modelDoc(id) {
    var M = window.PORTAL_META, m = M.models[id], idx = index(), nodes = idx.byModel[id] || [], st = m.stats;
    var rms = nodes.filter(function (n) { return n.kind === "measure" && n.report_id; });
    var o = header(m.name + " - Semantic Model Documentation", [["Workspace", m.workspace], ["Format", m.format], ["Owner", m.owner], ["Tables", st.tables], ["Columns", st.columns],
      ["DAX measures", st.measures], ["Relationships", st.relationships], ["RLS roles", (m.rls_roles || []).join(", ") || "None"], ["Bound reports", m.reports.length],
      ["Upstream dataflows", m.dataflows.length], ["Report-level measures (thin reports)", rms.length], ["Source connectors", (m.source_types || []).join(", ")]]);
    o.push("## 1. Upstream Dataflows & Sources", "");
    o = o.concat(tableMd(["Layer", "Dataflow", "Workspace", "Entities loaded", "Feeds tables"], m.dataflows.map(function (d) {
      var x = M.dataflows[d.id] || {};
      return ["L" + d.layer, x.name || d.id, x.workspace || "", d.entities.join(", ") || "(via upstream)", d.tables.join(", ")];
    })));
    var srcs = {};
    Object.keys(m.tables).forEach(function (t) { m.tables[t].sources.forEach(function (s) { (srcs[s] = srcs[s] || []).push(t); }); });
    o.push("**Original sources:**", "");
    var sl = Object.keys(srcs).map(function (s) { return "- " + srcLabel(idx.N[s]) + " - used by " + srcs[s].join(", "); });
    o = o.concat(sl.length ? sl : ["_None recorded._"], [""]);

    o.push("## 2. Tables", "");
    var tables = nodes.filter(function (n) { return n.kind === "table" || n.kind === "calc_table"; }).sort(window.E2E_API ? function (a, b) { return a.name.toLowerCase().localeCompare(b.name.toLowerCase()); } : null);
    tables.forEach(function (t, i) {
      var ti = m.tables[t.name] || { direct: [], dfs: [], sources: [] };
      o.push("### 2." + (i + 1) + " " + t.name, "");
      if (t.description) o.push("> " + t.description, "");
      o.push("- **Type / storage mode:** " + (t.kind === "calc_table" ? "Calculated table" : (t.storage_mode || "import")));
      if (ti.direct.length) o.push("- **Loads dataflow entity:** " + ti.direct.map(function (q) { var n = idx.N[q]; return n ? n.group + " › " + n.name : q; }).join(", "));
      var up = ti.dfs.filter(function (x) { return x[1] > 1; });
      if (up.length) o.push("- **Upstream dataflows:** " + up.map(function (x) { return "L" + x[1] + " " + dfName(x[0]); }).join(", "));
      if (ti.sources.length) o.push("- **Original sources:** " + ti.sources.slice(0, 12).map(function (s) { return srcLabel(idx.N[s]); }).join("; ") + (ti.sources.length > 12 ? "; ..." : ""));
      o.push("");
      if ((t.columns || []).length) o = o.concat(tableMd(["Column", "Type", "Source column", "Calculated"], t.columns.map(function (c) { return [c.name, c.type, c.source, c.calculated ? "yes" : ""]; })));
      nodes.filter(function (c) { return c.kind === "calc_column" && c.table === t.name; }).forEach(function (c) {
        o.push("**Calculated column " + c.name + ":**", "", fence(c.code, "dax"), "");
      });
      o = o.concat(sqlBlocks(t, idx), stepLines(t));
      if (t.code) o.push("", t.kind === "calc_table" ? "**DAX:**" : "**Power Query (M):**", "", fence(t.code, t.kind === "calc_table" ? "dax" : "powerquery"));
      o.push("");
    });
    var exprs = nodes.filter(function (n) { return n.kind === "expression"; });
    if (exprs.length) {
      o.push("### Shared dataset queries & functions", "");
      exprs.forEach(function (x) { o.push("#### " + x.name + " (" + (x.role || "Query") + ")", ""); o = o.concat(sqlBlocks(x, idx)); o.push("", fence(x.code, "powerquery"), ""); });
    }
    o.push("## 3. Relationships", "");
    o = o.concat(tableMd(["From", "To", "Cardinality", "Cross filter", "Active"], (m.relationships || []).map(function (r) {
      return [r.from_table + "[" + r.from_column + "]", r.to_table + "[" + r.to_column + "]", r.cardinality, r.bidirectional ? "Both" : "Single", r.active ? "yes" : "no"];
    })));
    o.push("## 4. DAX Measures", "");
    var byT = {};
    nodes.filter(function (n) { return n.kind === "measure" && !n.report_id; }).forEach(function (n) { (byT[n.table] = byT[n.table] || []).push(n); });
    Object.keys(byT).sort().forEach(function (t) {
      o.push("### Table " + t, "");
      byT[t].sort(function (a, b) { return String(a.folder || "").localeCompare(b.folder || "") || a.name.toLowerCase().localeCompare(b.name.toLowerCase()); }).forEach(function (n) {
        o.push("#### [" + n.name + "]", "");
        var meta = [n.folder ? "Folder: `" + n.folder + "`" : "", n.format ? "Format: `" + n.format + "`" : "", n.hidden ? "Hidden" : ""].filter(Boolean).join(" · ");
        if (meta) o.push(meta, "");
        if (n.description) o.push("> " + n.description, "");
        o.push(fence(n.code, "dax"), "");
      });
    });
    o.push("## 5. Report-level Measures (Thin Reports)", "");
    if (!rms.length) o.push("_No thin report adds measures to this model._", "");
    var byR = {};
    rms.forEach(function (n) { (byR[n.report] = byR[n.report] || []).push(n); });
    Object.keys(byR).sort().forEach(function (r) {
      o.push("### Report " + r + " (" + (byR[r][0].workspace || "") + ")", "");
      byR[r].forEach(function (n) { o.push("#### [" + n.name + "]", ""); if (n.description) o.push("> " + n.description, ""); o.push(fence(n.code, "dax"), ""); });
    });
    o.push("## 6. Reports Using This Model", "");
    o = o.concat(tableMd(["Report", "Workspace", "Report-level measures"], m.reports.map(function (r) { return [r.name, r.workspace, String((byR[r.name] || []).length)]; })));
    o.push("## 7. Health Findings", "");
    o = o.concat(tableMd(["Severity", "Finding", "Recommended action"], m.findings.map(function (f) { return [f.severity.toUpperCase(), f.title, f.detail]; })));
    return o.join("\n");
  }

  function lineageDoc(id) {
    var M = window.PORTAL_META, m = M.models[id], idx = index();
    var o = header(m.name + " - Data Lineage", [["Workspace", m.workspace], ["Tables", m.stats.tables], ["Upstream dataflows", m.dataflows.length],
      ["Dataflow layers", m.dataflows.reduce(function (a, d) { return Math.max(a, d.layer); }, 0)]]);
    o.push("## 1. Lineage by Table", "");
    o = o.concat(tableMd(["Table", "Dataflow entity (L1)", "Upstream dataflows (L2+)", "Original sources"], Object.keys(m.tables).sort().map(function (t) {
      var ti = m.tables[t];
      return [t, ti.direct.map(function (q) { var n = idx.N[q]; return n ? n.group + " › " + n.name : q; }).join(", ") || "-",
        ti.dfs.filter(function (x) { return x[1] > 1; }).map(function (x) { return "L" + x[1] + " " + dfName(x[0]); }).join(", ") || "-",
        ti.sources.slice(0, 8).map(function (s) { return srcLabel(idx.N[s]); }).join("; ") + (ti.sources.length > 8 ? "; ..." : "") || "-"];
    })));
    o.push("## 2. Dataflow Layers", "");
    var layers = {};
    m.dataflows.forEach(function (d) { (layers[d.layer] = layers[d.layer] || []).push(d); });
    Object.keys(layers).sort().forEach(function (l) {
      o.push("### Layer " + l + (l === "1" ? " (loaded by the model)" : ""), "");
      o = o.concat(tableMd(["Dataflow", "Workspace", "Upstream", "Entities loaded", "Feeds tables"], layers[l].map(function (d) {
        var x = M.dataflows[d.id] || {};
        return [x.name || d.id, x.workspace || "", (x.upstream || []).map(dfName).join(", "), d.entities.join(", "), d.tables.join(", ")];
      })));
    });
    o.push("## 3. Sources & Native SQL", "");
    var seen = {};
    Object.keys(m.tables).forEach(function (t) { m.tables[t].sources.forEach(function (s) { seen[s] = 1; }); });
    Object.keys(seen).forEach(function (s, i) {
      var n = idx.N[s]; if (!n) return;
      o.push("### 3." + (i + 1) + " " + srcLabel(n), "");
      if (n.server) o.push("- Server / endpoint: `" + n.server + "`");
      if (n.database) o.push("- Database: `" + n.database + "`");
      if (n.object) o.push("- Object: `" + n.object + "`");
      (n.files || []).forEach(function (f) { o.push("- File: " + f); });
      if (n.code) o.push("", fence(n.code, "sql"));
      o.push("");
    });
    return o.join("\n");
  }

  function dataflowDoc(gid) {
    var M = window.PORTAL_META, d = M.dataflows[gid], idx = index(), qs = (idx.byDf[gid] || []).slice();
    var o = header(d.name + " - Dataflow Documentation", [["Workspace", d.workspace], ["Dataflow id", gid], ["Definition", d.status], ["Configured by", d.configured_by],
      ["Queries by role", Object.keys(d.roles).map(function (r) { return d.roles[r] + " " + r; }).join(", ")], ["Connectors", d.connectors.join(", ")],
      ["Native SQL queries", d.sql], ["Upstream dataflows", d.upstream.map(dfName).join(", ") || "None"], ["Feeds dataflows", d.downstream.map(dfName).join(", ") || "None"],
      ["Feeds semantic models", d.models.map(function (x) { return x.name + " (" + x.workspace + (x.direct ? "" : ", indirect") + ")"; }).join(", ") || "None"]]);
    var ORDER = { "Linked entity": 0, "Linked query": 1, "Staging": 2, "Computed entity": 3, "Entity": 4, "Function": 5 };
    qs.sort(function (a, b) { return ((ORDER[a.role] == null ? 9 : ORDER[a.role]) - (ORDER[b.role] == null ? 9 : ORDER[b.role])) || a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
    o.push("## Queries (" + qs.length + ")", "");
    qs.forEach(function (q, i) {
      o.push("### " + (i + 1) + ". " + q.name + " (" + (q.role || "Query") + ")", "");
      if (q.description) o.push("> " + q.description, "");
      var reads = (window.E2E_API.OUT[q.id] || []).map(function (e) {
        var t = idx.N[e.to]; if (!t) return "";
        if (t.kind === "source") return "- Reads source " + srcLabel(t);
        if (t.kind === "dataflow_query") return t.group_id === gid ? "- Reads query `" + t.name + "`" : "- Linked entity: " + t.group + " › " + t.name + " (" + (t.workspace || "") + ")" + (t.external ? " - not scanned" : "");
        return "";
      }).filter(Boolean);
      var used = (window.E2E_API.IN[q.id] || []).map(function (e) {
        var f = idx.N[e.from]; if (!f) return "";
        if (f.kind === "dataflow_query" && f.group_id !== gid) return "- Used by dataflow " + f.group + " › " + f.name;
        if (f.kind === "table" || f.kind === "expression") return "- Loaded by " + (f.model || "") + " › " + f.name;
        return "";
      }).filter(Boolean);
      o = o.concat(reads, used);
      if (q.parameters && Object.keys(q.parameters).length) o.push("- Parameters: " + Object.keys(q.parameters).map(function (k) { return "`" + k + "` = `" + q.parameters[k] + "`"; }).join(", "));
      if ((q.columns || []).length) o.push("- Output columns: " + q.columns.map(function (c) { return "`" + c.name + "` (" + c.type + ")"; }).join(", "));
      o = o.concat(sqlBlocks(q, idx), stepLines(q));
      if (q.code) o.push("", "**Power Query (M):**", "", fence(q.code, "powerquery"));
      else if (q.role === "Linked entity") o.push("", "_Linked entity: reads the upstream dataflow entity listed above (no Power Query of its own)._");
      o.push("");
    });
    return o.join("\n");
  }

  function workspaceDoc(ws) {
    var M = window.PORTAL_META, idx = index(), w = (M.workspaces || []).filter(function (x) { return x.name === ws; })[0] || {};
    var models = Object.keys(M.models).filter(function (id) { return M.models[id].workspace === ws; }).sort(function (a, b) { return M.models[a].name.localeCompare(M.models[b].name); });
    var reps = M.reports.filter(function (r) { return r.workspace === ws; });
    var dfs = Object.keys(M.dataflows).filter(function (g) { return M.dataflows[g].workspace === ws && !M.dataflows[g].outside; });
    var o = header("Workspace " + ws + " - Documentation", [["Capacity / SKU", w.sku], ["Semantic models", models.length], ["Reports", reps.length],
      ["Thin reports with report-level measures", reps.filter(function (r) { return r.report_measures; }).length],
      ["Report-level measures", reps.reduce(function (a, r) { return a + r.report_measures; }, 0)], ["Dataflows", dfs.length]]);
    o.push("## 1. Semantic Models", "");
    o = o.concat(tableMd(["Model", "Tables", "Measures", "Relationships", "Reports", "Upstream dataflows", "Health"], models.map(function (id) {
      var m = M.models[id], bad = m.findings.filter(function (f) { return f.severity === "bad"; }).length, warn = m.findings.length - bad;
      return [m.name, m.stats.tables, m.stats.measures, m.stats.relationships, m.reports.length, m.dataflows.length, bad ? bad + " critical" : warn ? warn + " warning(s)" : "Healthy"];
    })));
    o.push("## 2. Reports", "");
    o = o.concat(tableMd(["Report", "Semantic model", "Model workspace", "Binding", "Report-level measures"], reps.map(function (r) {
      return [r.name, r.model || (r.model_id ? "External model " + r.model_id.slice(0, 8) : "Unbound"), r.model_workspace,
        r.model_workspace && r.model_workspace !== ws ? "Cross-workspace shared model" : "Same workspace",
        r.report_measures ? String(r.report_measures) : (/^error/.test(r.status || "") ? "Not readable" : "0")];
    })));
    o.push("## 3. Report-level Measures (Thin Reports)", "");
    var any = false;
    reps.filter(function (r) { return r.report_measures; }).forEach(function (r) {
      any = true;
      o.push("### " + r.name + " → " + (r.model || "?") + (r.model_workspace ? " (" + r.model_workspace + ")" : ""), "");
      Object.keys(idx.N).forEach(function (id) {
        var n = idx.N[id];
        if (n.report_id === r.id) { o.push("#### [" + n.name + "]", ""); if (n.description) o.push("> " + n.description, ""); o.push(fence(n.code, "dax"), ""); }
      });
    });
    if (!any) o.push("_No report-level measures in this workspace._", "");
    o.push("## 4. Dataflows", "");
    o = o.concat(tableMd(["Dataflow", "Definition", "Queries", "Connectors", "Native SQL", "Feeds models"], dfs.sort(function (a, b) { return M.dataflows[a].name.localeCompare(M.dataflows[b].name); }).map(function (g) {
      var d = M.dataflows[g];
      return [d.name, d.status, Object.keys(d.roles).reduce(function (a, r) { return a + d.roles[r]; }, 0), d.connectors.join(", "), d.sql, d.models.map(function (x) { return x.name; }).join(", ")];
    })));
    return o.join("\n");
  }

  function healthDoc(ws) {
    var M = window.PORTAL_META;
    var items = (M.health || []).filter(function (h) { return !ws || h.workspace === ws; });
    var rank = { bad: 0, warn: 1 };
    items.sort(function (a, b) { return (rank[a.severity] - rank[b.severity]) || a.workspace.localeCompare(b.workspace) || a.item.localeCompare(b.item); });
    var o = header("Governance & Health Report" + (ws ? " - " + ws : ""), [["Scope", ws || "All selected workspaces"], ["Findings", items.length],
      ["Critical", items.filter(function (h) { return h.severity === "bad"; }).length], ["Warnings", items.filter(function (h) { return h.severity !== "bad"; }).length]]);
    o = o.concat(tableMd(["Severity", "Item", "Type", "Workspace", "Finding", "Recommended action"], items.map(function (h) {
      return [h.severity === "bad" ? "CRITICAL" : "WARN", h.item, h.type, h.workspace, h.title, h.detail];
    })));
    return o.join("\n");
  }

  function reportDoc(r) {
    var idx = index(), o = header(r.name + " - Report Documentation", [["Workspace", r.workspace], ["Semantic model", (r.model || "not in catalog") + (r.model_workspace ? " (" + r.model_workspace + ")" : "")],
      ["Format", r.format], ["Pages", r.pages.length], ["Visuals", r.visual_count]]);
    function fl(f) { return f ? f.table + "[" + f.name + "]" : ""; }
    function fieldTxt(f) { return (f.agg ? f.agg + "(" + fl(f) + ")" : fl(f)) + (f.level ? " (" + f.level + ")" : "") + (f.kind === "measure" ? " (measure)" : ""); }
    function filters(list) { return tableMd(["Field", "Type", "Condition / selected values"], (list || []).map(function (x) { return [fl(x.field), x.type, x.condition || "(all)"]; })); }
    o.push("## Report-level filters", ""); o = o.concat(filters(r.filters));
    var used = {};
    r.pages.forEach(function (p, i) {
      o.push("## " + (i + 1) + ". Page: " + p.display + (p.hidden ? " (hidden)" : ""), "", "- Size: " + Math.round(p.width) + " x " + Math.round(p.height) + " \u00b7 " + p.visuals.length + " visuals", "");
      if ((p.filters || []).length) { o.push("**Page filters:**", ""); o = o.concat(filters(p.filters)); }
      var rows = p.visuals.filter(function (v) { return v.type !== "group"; }).map(function (v) {
        var roles = Object.keys(v.roles || {}).map(function (role) {
          return role + ": " + v.roles[role].map(function (f) { if (f.node) used[f.node] = 1; return fieldTxt(f); }).join(", ");
        }).join("; ");
        var flt = (v.filters || []).map(function (x) { return x.condition; }).concat(v.selection ? ["Slicer selection: " + v.selection.condition] : []).join("; ");
        return [v.title || "-", v.type + (v.hidden ? " (hidden)" : ""), roles || (v.text ? "Text: " + v.text.slice(0, 120) : "-"), flt || "-"];
      });
      o = o.concat(tableMd(["Visual", "Type", "Fields by role", "Filters / selection"], rows));
    });
    var ms = Object.keys(used).map(function (id) { return idx.N[id]; }).filter(function (n) { return n && n.kind === "measure"; })
      .sort(function (a, b) { return a.name.toLowerCase().localeCompare(b.name.toLowerCase()); });
    o.push("## Measures used by this report (" + ms.length + ")", "");
    ms.forEach(function (n) { o.push("### [" + n.name + "]" + (n.report ? " (report-level)" : " - " + (n.table || "")), ""); if (n.description) o.push("> " + n.description, ""); o.push(fence(n.code, "dax"), ""); });
    return o.join("\n");
  }

  function buildDocs(kind, scope) {
    var M = window.PORTAL_META, parts = [], title = "";
    var ws = scope.indexOf("ws:") === 0 ? scope.slice(3) : "";
    if (kind === "model" || kind === "lineage") {
      var fn = kind === "model" ? modelDoc : lineageDoc, suffix = kind === "model" ? " - Model Documentation" : " - Data Lineage";
      var ids = ws ? Object.keys(M.models).filter(function (id) { return M.models[id].workspace === ws; }) : [scope.slice(6)];
      ids.sort(function (a, b) { return M.models[a].name.localeCompare(M.models[b].name); });
      parts = ids.map(function (id) { return { name: M.models[id].name, md: fn(id) }; });
      title = (ws ? ws : M.models[ids[0]].name) + suffix;
    } else if (kind === "dataflow") {
      var gids = ws ? Object.keys(M.dataflows).filter(function (g) { return M.dataflows[g].workspace === ws && !M.dataflows[g].outside; }) : [scope.slice(3)];
      gids.sort(function (a, b) { return M.dataflows[a].name.localeCompare(M.dataflows[b].name); });
      parts = gids.map(function (g) { return { name: M.dataflows[g].name, md: dataflowDoc(g) }; });
      title = (ws ? ws : M.dataflows[gids[0]].name) + " - Dataflow Documentation";
    } else if (kind === "workspace") {
      var wss = ws ? [ws] : wsList();
      parts = wss.map(function (w) { return { name: w, md: workspaceDoc(w) }; });
      title = (ws || "All Workspaces") + " - Workspace & Report Documentation";
    } else if (kind === "report") {
      var RR = window.PBIDOC_REPORTS || {}, RI = window.REPORT_INDEX || [];
      var rids = ws ? RI.filter(function (r) { return r.workspace === ws; }).map(function (r) { return r.id; }) : [scope.slice(4)];
      parts = rids.filter(function (id) { return RR[id]; }).map(function (id) { return { name: RR[id].name, md: reportDoc(RR[id]) }; });
      title = (ws ? ws + " - Reports" : (parts[0] || {}).name || "Report") + " - Report Documentation";
    } else if (kind === "health") {
      parts = [{ name: "Health", md: healthDoc(ws) }];
      title = "Governance & Health Report" + (ws ? " - " + ws : "");
    }
    return { title: title, parts: parts };
  }

  function exportDocs(res, fmt) {
    var A = window.E2E_API, safe = String(res.title).replace(/[^A-Za-z0-9_-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 90) || "documentation";
    if (fmt === "md") {
      var md = res.parts.length > 1
        ? "# " + res.title + "\n\n" + res.parts.map(function (p, i) { return (i + 1) + ". " + p.name; }).join("\n") + "\n\n---\n\n" + res.parts.map(function (p) { return p.md; }).join("\n\n---\n\n")
        : res.parts[0].md;
      A.download(safe + ".md", md, "text/markdown");
      return;
    }
    var body = res.parts.map(function (p, i) { return '<section id="doc' + i + '">' + A.mdToHtml(p.md, function () { return ""; }) + "</section>"; }).join('<hr style="margin:40px 0">');
    var toc = res.parts.length > 1 ? "<h1>" + esc(res.title) + '</h1><ol class="toc">' + res.parts.map(function (p, i) { return '<li><a href="#doc' + i + '">' + esc(p.name) + "</a></li>"; }).join("") + "</ol>" : "";
    var html = '<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>' + esc(res.title) + "</title><style>" + A.DOC_CSS +
      "</style></head><body>" + toc + body + "</body></html>";
    if (fmt === "doc") A.download(safe + ".doc", html, "application/msword");
    else A.download(safe + ".html", html, "text/html");
  }

  function runDocExport(btn) {
    var c = context(), scope = $("pdDocScope").value, fmt = $("pdDocFmt").value, t0 = Date.now();
    btn.disabled = true;
    $("pdDocStatus").textContent = "Loading the catalog and building the document...";
    ensureAll().then(function () {
      if (c.kind !== "report" || !window.REPORT_EXPLORER) return null;
      var ws = scope.indexOf("ws:") === 0 ? scope.slice(3) : "";
      var ids = ws ? (window.REPORT_INDEX || []).filter(function (r) { return r.workspace === ws; }).map(function (r) { return r.id; }) : [scope.slice(4)];
      return Promise.all(ids.map(function (id) { return window.REPORT_EXPLORER.loadReport(id); }));
    }).then(function () {
      var res = buildDocs(c.kind, scope);
      if (!res.parts.length) throw new Error("Nothing to export for this scope.");
      exportDocs(res, fmt);
      $("pdDocStatus").textContent = "Downloaded " + res.parts.length + " document section(s).";
      log({ type: "portal-doc-export", kind: c.kind, scope: scope, format: fmt, parts: res.parts.length, ms: Date.now() - t0 });
      setTimeout(function () { $("pdDocModal").classList.remove("open"); }, 600);
    }).catch(function (err) {
      $("pdDocStatus").textContent = "Export failed: " + err.message;
      log({ type: "portal-doc-export-failed", kind: c.kind, message: String(err.message) });
    }).then(function () { btn.disabled = false; });
  }

  function exportSite(btn) {
    var fmtEl = document.querySelector('input[name="pdSiteFmt"]:checked'), fmt = fmtEl ? fmtEl.value : "single";
    var qs = "?format=" + fmt + "&aspx=" + ($("pdSiteAspx").checked ? "1" : "0") + "&anonymous=" + ($("pdSiteAnon").checked ? "1" : "0"), t0 = Date.now();
    btn.disabled = true;
    $("pdSiteStatus").textContent = "Building the export (regenerates every page - this can take a minute or two)...";
    log({ type: "export-site-start", aspx: $("pdSiteAspx").checked, anonymous: $("pdSiteAnon").checked });
    fetch("/api/export-site" + qs).then(function (r) {
      if (!r.ok) return r.json().then(function (j) { throw new Error(j.error || ("HTTP " + r.status)); });
      var name = ((r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/) || [])[1] || (fmt === "single" ? "PBI_Documentation_Portal_SharePoint.html" : "PBI_Documentation_Portal.zip");
      return r.blob().then(function (b) { return { blob: b, name: name }; });
    }).then(function (res) {
      var a = document.createElement("a");
      a.href = URL.createObjectURL(res.blob); a.download = res.name;
      document.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
      $("pdSiteStatus").innerHTML = "Downloaded <b>" + esc(res.name) + "</b> (" + (res.blob.size / 1e6).toFixed(1) + " MB). " +
        (/[.]html$/i.test(res.name) ? "Upload it to a SharePoint document library and click it to browse the portal." : "Unzip it and see README.html inside for the SharePoint options.");
      log({ type: "export-site-done", mb: +(res.blob.size / 1e6).toFixed(1), seconds: Math.round((Date.now() - t0) / 1000) });
    }).catch(function (err) {
      $("pdSiteStatus").textContent = "Export failed: " + err.message;
      log({ type: "export-site-failed", message: String(err.message) });
    }).then(function () { btn.disabled = false; });
  }

  // ---------------- End-to-End tab: the explorer page embedded in the portal ----------------
  var frame = null, frameBase = "", frameHash = null;
  function sendToFrame(msg) {
    if (!frame) return;
    if (frameHash === null) loadFrame("");
    var go = function () { try { frame.contentWindow.postMessage(msg, "*"); } catch (e) { /* ignore */ } };
    if (frame.getAttribute("data-ready")) go(); else frame.addEventListener("load", go, { once: true });
  }
  function hashFromUrl() { var m = location.hash.match(/^#e2e(?::(.*))?$/); return m ? (m[1] || "") : null; }
  function sizeFrame() { if (frame) frame.style.height = Math.max(560, window.innerHeight - 8) + "px"; }
  function loadFrame(h) {
    if (window.PBIDOC_SHELL) {
      var first = frameHash === null || !frame.getAttribute("data-ready");
      frameHash = h;
      if (!first) { try { frame.contentWindow.postMessage({ type: "pbidoc-set-hash", hash: h }, "*"); } catch (e) { /* ignore */ } return; }
      window.PBIDOC_SHELL.render(frameBase, h, "embed=1").then(function (html) { frame.srcdoc = html; });
      return;
    }
    frameHash = h;
    frame.src = frameBase + (frameBase.indexOf("?") >= 0 ? "&" : "?") + "embed=1" + (h ? "#" + h : "");
  }
  function setUrl(h) {
    try { history.replaceState(null, "", h === null ? location.pathname + location.search : "#e2e" + (h ? ":" + h : "")); } catch (e) { /* ignore */ }
  }
  function onTab(id) {
    var kpis = document.querySelector("main.catalog-wrap > .kpi-grid");
    if (kpis) kpis.style.display = id === "tab-e2e" || id === "tab-reports" ? "none" : "";
    if (id === "tab-e2e" && frame) {
      if (frameHash === null) loadFrame(hashFromUrl() || "");
      sizeFrame();
      setUrl(frameHash);
    } else if (hashFromUrl() !== null) setUrl(null);
    updateLabel();
  }
  function showE2E(h) {
    var btn = document.querySelector('.top-tab[data-tab="tab-e2e"]');
    var pane = $("tab-e2e");
    if (pane && !pane.classList.contains("active") && btn) { frameHash = frameHash === null ? null : frameHash; btn.click(); }
    if (frameHash === null || h !== frameHash) loadFrame(h);
    setUrl(h);
  }

  document.addEventListener("DOMContentLoaded", function () {
    injectModals();
    frame = $("e2eFrame");
    if (frame) {
      var link = $("e2eFrameLink");
      frameBase = link ? link.getAttribute("href") : "e2e_lineage.html";
      frame.addEventListener("load", function () {
        frame.setAttribute("data-ready", "1");
        var th = document.documentElement.getAttribute("data-theme");
        if (th) try { frame.contentWindow.postMessage({ type: "pbidoc-theme", theme: th }, "*"); } catch (e) { /* ignore */ }
      });
      window.addEventListener("resize", sizeFrame);
      window.addEventListener("message", function (ev) {
        var d = ev.data || {};
        if (d.type === "pbidoc-open-hash" && typeof d.hash === "string") { location.hash = d.hash; return; }
        if (d.type === "pbidoc-e2e-hash" && typeof d.hash === "string") {
          frameHash = d.hash;
          if ($("tab-e2e").classList.contains("active")) setUrl(d.hash);
        }
      });
      window.addEventListener("hashchange", function () { var h = hashFromUrl(); if (h !== null) showE2E(h); });
      var h0 = hashFromUrl();
      if (h0 !== null) showE2E(h0);
    }
    updateLabel();
  });
  document.addEventListener("click", function (e) {
    var t;
    if ((t = e.target.closest(".top-tab[data-tab]"))) { var id = t.getAttribute("data-tab"); setTimeout(function () { onTab(id); }, 0); return; }
    if ((t = e.target.closest("[data-toggle-theme]")) && frame && frame.getAttribute("data-ready")) {
      setTimeout(function () { try { frame.contentWindow.postMessage({ type: "pbidoc-theme", theme: document.documentElement.getAttribute("data-theme") || "light" }, "*"); } catch (err) { /* ignore */ } }, 0);
    }
    if (e.target.closest("#pdExportDocBtn")) { openDocModal(); return; }
    if (e.target.closest("#pdExportSiteBtn")) { $("pdSiteStatus").textContent = ""; $("pdSiteModal").classList.add("open"); return; }
    if (e.target.closest("#pdDocCancel") || e.target === $("pdDocModal")) { $("pdDocModal").classList.remove("open"); return; }
    if ((t = e.target.closest("#pdDocGo")) && !t.disabled) { runDocExport(t); return; }
    if (e.target.closest("#pdSiteCancel") || e.target === $("pdSiteModal")) { $("pdSiteModal").classList.remove("open"); return; }
    if ((t = e.target.closest("#pdSiteGo")) && !t.disabled) { exportSite(t); return; }
  });
  window.PORTAL_EXPORT = { buildDocs: buildDocs, ensureAll: ensureAll, scopeOptions: scopeOptions };
})();
"""
