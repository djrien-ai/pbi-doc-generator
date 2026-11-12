"""
Modern Localhost Web Studio for Power BI Documentation, Live Lineage & MCP Setup.
100% Pure Python stdlib (`http.server`), clean English UI, designed for both non-technical users and BI teams.
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

from .api import PowerBiReadOnlyClient
from .auth import TokenProvider
from .portal import generate_portal
from .scanner import WorkspaceScanner
from .store import CatalogStore


STUDIO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PBI Doc Generator v1.0 - Studio</title>
  <style>
    :root {
      --bg: #f4f7fb;
      --surface: #ffffff;
      --surface-alt: #eef3f9;
      --fg: #0f172a;
      --fg-muted: #526077;
      --border: #dce3ee;
      --accent: #0b63ce;
      --accent-hover: #084fa6;
      --accent-soft: #e7f0fd;
      --ok: #15803d;
      --ok-bg: #dcfce7;
      --radius: 14px;
      --shadow: 0 3px 14px rgba(15, 23, 42, 0.06);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", Inter, -apple-system, BlinkMacSystemFont, Roboto, sans-serif;
      background: var(--bg);
      color: var(--fg);
      font-size: 14px;
      line-height: 1.55;
    }
    .hero {
      background: linear-gradient(135deg, #072854 0%, #0b63ce 100%);
      color: #fff;
      padding: 26px 32px 0 32px;
    }
    .hero-inner {
      max-width: 1120px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
    }
    .hero h1 { margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.015em; }
    .hero p { margin: 4px 0 0 0; opacity: 0.9; font-size: 13.5px; }
    .mode-tabs {
      max-width: 1120px;
      margin: 20px auto 0 auto;
      display: flex;
      gap: 8px;
    }
    .mode-tab {
      border: none;
      background: rgba(255,255,255,0.14);
      color: #fff;
      padding: 11px 20px;
      border-radius: 11px 11px 0 0;
      font-size: 13.5px;
      font-weight: 600;
      cursor: pointer;
    }
    .mode-tab:hover { background: rgba(255,255,255,0.24); }
    .mode-tab.active { background: var(--bg); color: var(--fg); }

    .wrap { max-width: 1120px; margin: 0 auto; padding: 26px 32px 64px 32px; }
    .pane { display: none; }
    .pane.active { display: block; }

    .step-card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      padding: 22px 24px;
      margin-bottom: 18px;
      box-shadow: var(--shadow);
    }
    .step-hdr {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .step-title {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 16px;
      font-weight: 700;
      margin: 0;
    }
    .step-num {
      width: 26px;
      height: 26px;
      border-radius: 50%;
      background: var(--accent-soft);
      color: var(--accent);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 13px;
      font-weight: 750;
    }
    .btn {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border: 1px solid transparent;
      border-radius: 9px;
      padding: 10px 18px;
      font-size: 13.5px;
      font-weight: 650;
      cursor: pointer;
      text-decoration: none;
    }
    .btn-primary { background: var(--accent); color: #fff; }
    .btn-primary:hover { background: var(--accent-hover); }
    .btn-secondary { background: var(--surface-alt); color: var(--fg); border-color: var(--border); }
    .btn-secondary:hover { border-color: var(--accent); color: var(--accent); }
    .btn-success { background: var(--ok); color: #fff; }

    .status-pill {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 650;
      background: var(--surface-alt);
      color: var(--fg-muted);
    }
    .status-pill.connected { background: var(--ok-bg); color: var(--ok); }

    .preset-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-bottom: 14px;
    }
    .preset-box {
      border: 1.5px solid var(--border);
      border-radius: 11px;
      padding: 13px 15px;
      cursor: pointer;
      background: var(--surface);
      text-align: left;
    }
    .preset-box.active {
      border-color: var(--accent);
      background: var(--accent-soft);
    }
    .preset-box b { display: block; font-size: 13.5px; margin-bottom: 3px; }
    .preset-box span { font-size: 12px; color: var(--fg-muted); }

    .ws-list {
      max-height: 240px;
      overflow-y: auto;
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 8px;
      background: var(--surface-alt);
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
      gap: 6px;
    }
    .ws-item {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      background: var(--surface);
      padding: 7px 10px;
      border-radius: 8px;
      border: 1px solid var(--border);
      font-size: 12.5px;
    }
    .sku-tag {
      font-size: 10.5px;
      font-weight: 650;
      padding: 1px 7px;
      border-radius: 999px;
      background: var(--surface-alt);
      color: var(--fg-muted);
    }
    input[type="text"], input[type="search"], textarea {
      width: 100%;
      padding: 9px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      font-size: 13px;
      font-family: inherit;
    }
    .log-box {
      background: #0f172a;
      color: #e2e8f0;
      font-family: "Cascadia Code", Consolas, monospace;
      font-size: 12px;
      padding: 14px;
      border-radius: 10px;
      max-height: 220px;
      overflow-y: auto;
      white-space: pre-wrap;
      margin-top: 14px;
    }
    details.subtle {
      margin-top: 12px;
      font-size: 12.5px;
      color: var(--fg-muted);
    }
    details.subtle > summary { cursor: pointer; font-weight: 600; color: var(--accent); }
    pre.cfg {
      background: #0f172a;
      color: #e2e8f0;
      padding: 14px;
      border-radius: 10px;
      overflow-x: auto;
      font-size: 12px;
    }
  </style>
</head>
<body>
<header class="hero">
  <div class="hero-inner">
    <div>
      <h1>Power BI Documentation &amp; Live Lineage Studio</h1>
      <p>Zero-admin workspace catalog, auto-formatted DAX, Star-Schema diagrams, and AI MCP server &bull; Runs 100% locally</p>
    </div>
    <a class="btn btn-secondary" href="/portal/index.html" target="_blank" id="topOpenPortalBtn" style="background:rgba(255,255,255,0.16);color:#fff;border-color:rgba(255,255,255,0.3)">Open Portal &rarr;</a>
  </div>
  <nav class="mode-tabs">
    <button type="button" class="mode-tab active" data-pane="pane-service">1. Power BI Service (Workspaces &amp; Catalog)</button>
    <button type="button" class="mode-tab" data-pane="pane-local">2. Local File or Project (.pbix, .pbip, .xlsx)</button>
    <button type="button" class="mode-tab" data-pane="pane-mcp">3. AI Assistant (MCP Server)</button>
  </nav>
</header>

<main class="wrap">
  <!-- MODE 1: POWER BI SERVICE -->
  <section class="pane active" id="pane-service">
    <div class="step-card">
      <div class="step-hdr">
        <h2 class="step-title"><span class="step-num">1</span> Sign in to Power BI</h2>
        <span class="status-pill" id="authStatusPill">Not connected</span>
      </div>
      <p style="margin:0 0 14px 0;color:var(--fg-muted);font-size:13px">
        Sign in with your Microsoft work account in your default browser. Read-only metadata access; credentials are never stored on disk.
      </p>
      <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
        <button type="button" class="btn btn-primary" onclick="connectAuth('oauth')">Sign in with Microsoft</button>
        <button type="button" class="btn btn-secondary" onclick="loadWorkspaces()">Refresh Workspace List</button>
      </div>

      <details class="subtle">
        <summary>Corporate tenant restricts standard OAuth apps? Alternative sign-in options</summary>
        <div style="margin-top:10px;padding:12px;background:var(--surface-alt);border-radius:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">
          <button type="button" class="btn btn-secondary" onclick="connectAuth('browser')">Sign in via Power BI Web Window (Edge/Chrome)</button>
          <button type="button" class="btn btn-secondary" onclick="connectAuth('az')">Use Azure CLI (az login)</button>
        </div>
      </details>
    </div>

    <div class="step-card">
      <div class="step-hdr">
        <h2 class="step-title"><span class="step-num">2</span> Choose Workspaces to Document</h2>
        <div style="display:flex;gap:6px">
          <button type="button" class="btn btn-secondary" style="padding:5px 10px;font-size:12px" onclick="toggleAllWs(true)">Select All</button>
          <button type="button" class="btn btn-secondary" style="padding:5px 10px;font-size:12px" onclick="toggleAllWs(false)">Clear</button>
        </div>
      </div>
      <input type="search" id="wsFilter" placeholder="Filter workspaces by name (e.g. Finance, Sales, PROD)..." oninput="filterWs()" style="margin-bottom:10px">
      <div class="ws-list" id="wsList">
        <div style="color:var(--fg-muted);padding:8px;font-size:12.5px">Sign in above to load your visible Power BI workspaces.</div>
      </div>
      <label style="display:inline-flex;align-items:center;gap:8px;margin-top:12px;font-size:13px;cursor:pointer">
        <input type="checkbox" id="chkIncremental" checked>
        <b>Incremental scan (Recommended):</b> only fetch TMDL definitions for new or previously unscanned models
      </label>
    </div>

    <div class="step-card">
      <div class="step-hdr">
        <h2 class="step-title"><span class="step-num">3</span> Select Output Preset &amp; Generate Portal</h2>
      </div>
      <div class="preset-grid">
        <button type="button" class="preset-box active" data-preset="standard" onclick="selectPreset('standard', this)">
          <b>Documentation &amp; Live Lineage</b>
          <span>Models, reports map, Star-Schema diagrams, auto-formatted DAX, visual Power Query &amp; interactive lineage.</span>
        </button>
        <button type="button" class="preset-box" data-preset="governance" onclick="selectPreset('governance', this)">
          <b>Full Governance &amp; Access Audit</b>
          <span>Includes workspace roles, dataset permissions, refresh health checks &amp; cross-workspace thin report audit.</span>
        </button>
        <button type="button" class="preset-box" data-preset="anonymous" onclick="selectPreset('anonymous', this)">
          <b>Anonymized / External Share</b>
          <span>Automatically hides owner names, user emails &amp; access tables while masking connection secrets.</span>
        </button>
      </div>

      <div style="display:flex;flex-wrap:wrap;gap:16px;margin-bottom:16px;font-size:13px">
        <label><input type="checkbox" id="chkAccess"> Include workspace &amp; model user permissions</label>
        <label><input type="checkbox" id="chkAnon"> Redact personal &amp; owner names (<code>--anonymous</code>)</label>
      </div>

      <div style="display:flex;flex-wrap:wrap;gap:10px">
        <button type="button" class="btn btn-primary" onclick="runScanAndBuild()">Scan Selected Workspaces &amp; Build Portal</button>
        <button type="button" class="btn btn-secondary" onclick="rebuildPortalOnly()">Rebuild HTML Portal from Local Cache</button>
        <a class="btn btn-success" href="/portal/index.html" target="_blank">Open Generated Portal &rarr;</a>
      </div>

      <div class="log-box" id="logBox">Ready. Catalog folder: {{CATALOG_DIR}}</div>
    </div>
  </section>

  <!-- MODE 2: LOCAL FILE OR PROJECT -->
  <section class="pane" id="pane-local">
    <div class="step-card">
      <h2 class="step-title" style="margin-bottom:8px">Document a Local Power BI File or Git Project (Offline)</h2>
      <p style="margin:0 0 14px 0;color:var(--fg-muted);font-size:13px">
        Works completely offline for reports still in development on your laptop. Supports Power BI Project folders (<code>.pbip</code> / <code>.SemanticModel</code>), <code>.pbix</code> files, and Excel PowerPivot (<code>.xlsx</code>).
      </p>
      <div style="display:flex;gap:8px;margin-bottom:12px">
        <input type="text" id="localPathInput" placeholder="Paste path to .pbip folder, .SemanticModel folder, .pbix, or .xlsx...">
        <button type="button" class="btn btn-secondary" onclick="browseLocal()">Browse...</button>
      </div>
      <div style="display:flex;gap:10px">
        <button type="button" class="btn btn-primary" onclick="importLocalPath()">Generate Documentation</button>
        <a class="btn btn-success" href="/portal/index.html" target="_blank">Open Portal &rarr;</a>
      </div>
      <div class="log-box" id="localLogBox">Select a local .pbip / .SemanticModel folder or .pbix / .xlsx file above.</div>
    </div>
  </section>

  <!-- MODE 3: MCP SERVER -->
  <section class="pane" id="pane-mcp">
    <div class="step-card">
      <h2 class="step-title" style="margin-bottom:8px">Connect AI Assistants via Model Context Protocol (MCP)</h2>
      <p style="margin:0 0 14px 0;color:var(--fg-muted);font-size:13px">
        Once your catalog is built, VS Code GitHub Copilot, Claude Desktop, Cursor, or Antigravity can answer instant impact-analysis questions across all your semantic models, DAX formulas, and upstream views (with automatic secret masking).
      </p>
      <pre class="cfg" id="mcpConfigBlock">{{MCP_JSON}}</pre>
      <button type="button" class="btn btn-secondary" onclick="navigator.clipboard.writeText(document.getElementById('mcpConfigBlock').textContent)">Copy MCP Configuration JSON</button>
    </div>
  </section>
</main>

<script>
document.querySelectorAll(".mode-tab").forEach(function(btn) {
  btn.addEventListener("click", function() {
    var target = btn.getAttribute("data-pane");
    document.querySelectorAll(".mode-tab").forEach(function(b) { b.classList.toggle("active", b === btn); });
    document.querySelectorAll(".pane").forEach(function(p) { p.classList.toggle("active", p.id === target); });
  });
});

function selectPreset(name, el) {
  document.querySelectorAll(".preset-box").forEach(function(b) { b.classList.toggle("active", b === el); });
  document.getElementById("chkAccess").checked = (name === "governance");
  document.getElementById("chkAnon").checked = (name === "anonymous");
}

function appendLog(msg, boxId) {
  var box = document.getElementById(boxId || "logBox");
  box.textContent += "\n" + msg;
  box.scrollTop = box.scrollHeight;
}

async function apiPost(path, payload) {
  var res = await fetch(path, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload || {}) });
  return await res.json();
}

async function refreshStatus() {
  var st = await (await fetch("/api/status")).json();
  var pill = document.getElementById("authStatusPill");
  if (st.auth && st.auth.authenticated) {
    pill.className = "status-pill connected";
    pill.textContent = "Connected" + (st.auth.principal ? " (" + st.auth.principal + ")" : "") + " - " + st.auth.minutes_remaining + "m remaining";
  } else {
    pill.className = "status-pill";
    pill.textContent = "Not connected";
  }
  if (st.logs && st.logs.length) {
    document.getElementById("logBox").textContent = st.logs.join("\n");
    document.getElementById("logBox").scrollTop = document.getElementById("logBox").scrollHeight;
  }
}

async function connectAuth(mode) {
  appendLog("Starting sign-in (" + mode + ")...");
  var data = await apiPost("/api/connect", { mode: mode });
  await refreshStatus();
  if (data.ok) await loadWorkspaces();
  else appendLog("Sign-in error: " + (data.error || "Unknown error"));
}

async function loadWorkspaces() {
  var data = await apiPost("/api/workspaces", {});
  var list = document.getElementById("wsList");
  if (!data.ok) {
    appendLog("Could not fetch workspaces: " + data.error);
    return;
  }
  if (!data.workspaces.length) {
    list.innerHTML = '<div style="padding:8px;color:var(--fg-muted)">No workspaces returned for this account.</div>';
    return;
  }
  list.innerHTML = data.workspaces.map(function(w) {
    return '<label class="ws-item" data-wsname="' + w.name.toLowerCase().replace(/"/g, '') + '">' +
      '<span style="display:flex;align-items:center;gap:8px"><input type="checkbox" class="ws-chk" value="' + w.id + '" checked> <b>' + w.name + '</b></span>' +
      '<span class="sku-tag">' + w.sku + '</span></label>';
  }).join("");
}

function filterWs() {
  var q = (document.getElementById("wsFilter").value || "").toLowerCase();
  document.querySelectorAll("#wsList .ws-item").forEach(function(el) {
    el.style.display = (!q || el.getAttribute("data-wsname").indexOf(q) !== -1) ? "" : "none";
  });
}

function toggleAllWs(val) {
  document.querySelectorAll("#wsList .ws-item").forEach(function(el) {
    if (el.style.display !== "none") el.querySelector(".ws-chk").checked = val;
  });
}

async function runScanAndBuild() {
  var ids = Array.from(document.querySelectorAll(".ws-chk:checked")).map(function(c) { return c.value; });
  appendLog("Launching background scan for " + ids.length + " workspace(s)...");
  await apiPost("/api/scan", {
    workspace_ids: ids,
    refresh: !document.getElementById("chkIncremental").checked,
    include_access: document.getElementById("chkAccess").checked,
    anonymous: document.getElementById("chkAnon").checked
  });
}

async function rebuildPortalOnly() {
  var res = await apiPost("/api/portal", { anonymous: document.getElementById("chkAnon").checked });
  appendLog(res.ok ? "Portal regenerated: " + res.index : "Error: " + res.error);
}

async function browseLocal() {
  var res = await apiPost("/api/browse-local", {});
  if (res.path) document.getElementById("localPathInput").value = res.path;
}

async function importLocalPath() {
  var p = document.getElementById("localPathInput").value.trim();
  if (!p) return;
  appendLog("Processing " + p + " ...", "localLogBox");
  var res = await apiPost("/api/import-local", { path: p });
  appendLog(res.ok ? "Done! Output: " + res.output : "Error: " + res.error, "localLogBox");
}

setInterval(refreshStatus, 2500);
refreshStatus();
</script>
</body>
</html>
"""


class StudioState:
    def __init__(self, catalog_dir: str | Path):
        self.store = CatalogStore(catalog_dir)
        self.logs: list[str] = [f"Studio initialized. Catalog directory: {self.store.root}"]
        self.auth = TokenProvider(mode="oauth", log_fn=self.log)
        self.busy = False

    def log(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {msg}")
        if len(self.logs) > 200:
            self.logs = self.logs[-200:]


def run_web_studio(catalog_dir: str | Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    state = StudioState(catalog_dir)
    # Ensure initial portal exists if store already has models
    if (state.store.root / "state.json").exists():
        try:
            generate_portal(state.store)
        except Exception:
            pass

    mcp_cfg = json.dumps(
        {
            "mcpServers": {
                "powerbi-catalog": {
                    "command": sys.executable,
                    "args": ["-m", "pbi_catalog.cli", "mcp", "--catalog", str(state.store.root)],
                }
            }
        },
        indent=2,
    )

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def _json(self, payload: dict, code: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in ("/", "/index.html"):
                html = STUDIO_HTML.replace("{{CATALOG_DIR}}", str(state.store.root)).replace("{{MCP_JSON}}", mcp_cfg)
                raw = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(raw)
                return

            if parsed.path == "/api/status":
                self._json({"auth": state.auth.status(), "busy": state.busy, "logs": state.logs[-80:]})
                return

            if parsed.path.startswith("/portal/"):
                rel = parsed.path[len("/portal/"):].lstrip("/") or "index.html"
                portal_root = (state.store.root / "portal").resolve()
                target = (portal_root / rel).resolve()
                if str(target).startswith(str(portal_root)) and target.is_file():
                    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                    data = target.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Portal not generated yet. Run a scan or import a local project first.")
                return

            self.send_response(404)
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or "0")
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}

            if self.path == "/api/connect":
                try:
                    state.auth.mode = body.get("mode", "oauth")
                    state.auth.get_token(force_refresh=True)
                    state.log(f"Connected successfully ({state.auth.status().get('principal') or state.auth.mode}).")
                    self._json({"ok": True, "status": state.auth.status()})
                except Exception as exc:
                    state.log(f"Sign-in failed: {exc}")
                    self._json({"ok": False, "error": str(exc)})
                return

            if self.path == "/api/workspaces":
                try:
                    client = PowerBiReadOnlyClient(state.auth)
                    caps = {}
                    try:
                        for c in client.pbi_get_list("capacities"):
                            caps[c["id"]] = c.get("sku", "")
                    except Exception:
                        pass
                    groups = client.pbi_get_list("groups?$top=5000")
                    ws = [
                        {
                            "id": g["id"],
                            "name": g.get("name", ""),
                            "sku": caps.get(g.get("capacityId", ""), "Dedicated" if g.get("isOnDedicatedCapacity") else "Pro"),
                        }
                        for g in sorted(groups, key=lambda x: x.get("name", "").lower())
                    ]
                    state.log(f"Loaded {len(ws)} visible workspace(s).")
                    self._json({"ok": True, "workspaces": ws})
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)})
                return

            if self.path == "/api/scan":
                if state.busy:
                    self._json({"ok": False, "error": "A scan is already running."})
                    return

                def _worker() -> None:
                    state.busy = True
                    try:
                        client = PowerBiReadOnlyClient(state.auth)
                        scanner = WorkspaceScanner(client, state.store, log_fn=state.log)
                        ws_ids = body.get("workspace_ids") or None
                        scanner.scan_inventory(workspace_ids=ws_ids)
                        scanner.scan_model_definitions(
                            workspace_ids=ws_ids,
                            refresh=bool(body.get("refresh")),
                            include_access=bool(body.get("include_access")),
                        )
                        idx = generate_portal(state.store, anonymous=bool(body.get("anonymous")))
                        state.log(f"Portal ready! Click 'Open Generated Portal' ({idx})")
                    except Exception as exc:
                        state.log(f"Scan error: {exc}")
                    finally:
                        state.busy = False

                threading.Thread(target=_worker, daemon=True).start()
                self._json({"ok": True})
                return

            if self.path == "/api/portal":
                try:
                    idx = generate_portal(state.store, anonymous=bool(body.get("anonymous")))
                    self._json({"ok": True, "index": str(idx)})
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)})
                return

            if self.path == "/api/browse-local":
                chosen = ""
                if sys.platform == "win32":
                    ps = (
                        "Add-Type -AssemblyName System.Windows.Forms; "
                        "$d = New-Object System.Windows.Forms.OpenFileDialog; "
                        "$d.Filter = 'Power BI Files (*.pbip;*.pbix;*.xlsx;*.bim)|*.pbip;*.pbix;*.xlsx;*.bim|All files (*.*)|*.*'; "
                        "if ($d.ShowDialog() -eq 'OK') { Write-Output $d.FileName }"
                    )
                    res = subprocess.run(["powershell", "-NoProfile", "-Sta", "-Command", ps], capture_output=True, text=True)
                    chosen = (res.stdout or "").strip()
                self._json({"path": chosen})
                return

            if self.path == "/api/import-local":
                p = Path(body.get("path", "")).expanduser()
                try:
                    if p.is_dir() or p.suffix.lower() in (".pbip", ".tmdl"):
                        target_dir = p.parent if p.is_file() else p
                        WorkspaceScanner.register_local_tmdl(state.store, str(target_dir))
                        idx = generate_portal(state.store)
                        state.log(f"Imported local TMDL project into portal: {idx}")
                        self._json({"ok": True, "output": str(idx)})
                    else:
                        # Single .pbix or .xlsx via extract.py
                        root_dir = str(Path(__file__).resolve().parent.parent)
                        if root_dir not in sys.path:
                            sys.path.insert(0, root_dir)
                        from extract import generate_documentation  # type: ignore

                        out_html = generate_documentation(str(p))
                        self._json({"ok": True, "output": out_html})
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)})
                return

            self.send_response(404)
            self.end_headers()

    httpd = http.server.ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    print(f"Power BI Documentation Studio running at {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Studio.")
    finally:
        httpd.server_close()
