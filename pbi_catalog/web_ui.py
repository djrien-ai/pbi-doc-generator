"""
Modern Localhost Web Studio for Power BI Documentation, Live Lineage & MCP Setup.
100% Pure Python stdlib (`http.server`), clean English UI, designed for both non-technical users and BI teams.
"""

from __future__ import annotations

import collections
import hashlib
import http.server
import json
import mimetypes
import os
import shutil
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
      --code-bg: #f8fafc;
      --code-fg: #1e293b;
      --code-border: #dce4f0;
      --radius: 14px;
      --shadow: 0 3px 14px rgba(15, 23, 42, 0.06);
    }
    [data-theme="dark"] {
      --bg: #0b1120;
      --surface: #111827;
      --surface-alt: #1e293b;
      --fg: #e5e7eb;
      --fg-muted: #94a3b8;
      --border: #283548;
      --accent: #60a5fa;
      --accent-hover: #3b82f6;
      --accent-soft: #172554;
      --ok: #4ade80;
      --ok-bg: #052e16;
      --code-bg: #172235;
      --code-fg: #e2e8f0;
      --code-border: #2b3b54;
      --shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
    }
    .theme-icon-btn {
      width: 34px;
      height: 34px;
      border-radius: 9px;
      background: rgba(255,255,255,0.14);
      border: 1px solid rgba(255,255,255,0.26);
      color: #fff;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      padding: 0;
      flex-shrink: 0;
    }
    .theme-icon-btn:hover { background: rgba(255,255,255,0.26); }
    .theme-icon-btn .icon-sun { display: none; }
    [data-theme="dark"] .theme-icon-btn .icon-moon { display: none; }
    [data-theme="dark"] .theme-icon-btn .icon-sun { display: block; }
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
    .btn:disabled { opacity: 0.6; cursor: not-allowed; pointer-events: none; }

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
    .status-pill.connecting { background: #fef3c7; color: #b45309; }
    .status-pill.failed { background: #fee2e2; color: #b91c1c; }

    @keyframes spin { to { transform: rotate(360deg); } }
    .spin {
      width: 14px;
      height: 14px;
      border: 2px solid currentColor;
      border-right-color: transparent;
      border-radius: 50%;
      display: inline-block;
      animation: spin 0.7s linear infinite;
      flex-shrink: 0;
    }

    .inline-banner {
      margin-top: 12px;
      padding: 11px 14px;
      border-radius: 10px;
      font-size: 13px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
      border: 1px solid var(--border);
    }
    .inline-banner.info { background: var(--accent-soft); border-color: #bfdbfe; color: #1e40af; }
    .inline-banner.ok { background: var(--ok-bg); border-color: #bbf7d0; color: var(--ok); }
    .inline-banner.err { background: #fef2f2; border-color: #fecaca; color: #b91c1c; }

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
      background: var(--surface);
      color: var(--fg);
      font-size: 13px;
      font-family: inherit;
    }
    .log-box {
      background: var(--code-bg);
      color: var(--code-fg);
      border: 1px solid var(--code-border);
      font-family: "Cascadia Code", Consolas, monospace;
      font-size: 12px;
      padding: 14px;
      border-radius: 10px;
      max-height: 220px;
      overflow-y: auto;
      overflow-x: hidden;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      margin-top: 14px;
    }
    details.subtle {
      margin-top: 12px;
      font-size: 12.5px;
      color: var(--fg-muted);
    }
    details.subtle > summary { cursor: pointer; font-weight: 600; color: var(--accent); }
    pre.cfg {
      background: var(--code-bg);
      color: var(--code-fg);
      border: 1px solid var(--code-border);
      padding: 14px;
      border-radius: 10px;
      overflow-x: hidden;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      font-size: 12px;
    }
  </style>
  <script>
    (function() {
      var saved = localStorage.getItem("pbidoc-v1-theme");
      if (saved) document.documentElement.setAttribute("data-theme", saved);
    })();
  </script>
</head>
<body>
<header class="hero">
  <div class="hero-inner">
    <div>
      <h1>Power BI Documentation &amp; Live Lineage</h1>
      <p>Step 1: Scan Power BI workspaces or import local files here &bull; Step 2: Explore &amp; share in the Documentation Portal</p>
    </div>
    <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
      <div style="display:inline-flex;background:rgba(255,255,255,0.12);padding:4px;border-radius:11px;border:1px solid rgba(255,255,255,0.24);gap:4px;align-items:center">
        <span style="padding:7px 13px;border-radius:8px;background:#fff;color:#072854;font-weight:700;font-size:12.5px">1. Scanner &amp; Setup</span>
        <a href="/portal/index.html" id="topOpenPortalBtn" style="padding:7px 13px;border-radius:8px;color:#fff;text-decoration:none;font-weight:650;font-size:12.5px">2. Documentation Portal &rarr;</a>
      </div>
      <button type="button" class="theme-icon-btn" onclick="toggleStudioTheme()" title="Toggle Light / Dark theme" aria-label="Toggle Light / Dark theme">
        <svg class="icon-moon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
        <svg class="icon-sun" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      </button>
    </div>
  </div>
  <nav class="mode-tabs">
    <button type="button" class="mode-tab active" data-pane="pane-service">1. Power BI Service (Workspaces &amp; Catalog)</button>
    <button type="button" class="mode-tab" data-pane="pane-local">2. Local Power BI Files (.pbix, .pbip, .xlsx)</button>
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
        <button type="button" class="btn btn-primary" id="btnAuthOauth" onclick="connectAuth('oauth')">Sign in with Microsoft</button>
        <button type="button" class="btn btn-secondary" id="btnRefreshWs" onclick="loadWorkspaces(true)">Refresh Workspace List</button>
      </div>

      <div id="authBanner" class="inline-banner info" style="display:none"></div>

      <details class="subtle" id="altAuthDetails">
        <summary>Corporate tenant restricts standard OAuth apps? Alternative sign-in options</summary>
        <div style="margin-top:10px;padding:12px;background:var(--surface-alt);border-radius:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">
          <button type="button" class="btn btn-secondary" id="btnAuthBrowser" onclick="connectAuth('browser')">Sign in via Power BI Web Window (Edge/Chrome)</button>
          <button type="button" class="btn btn-secondary" id="btnAuthAz" onclick="connectAuth('az')">Use Azure CLI (az login)</button>
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
      <p style="margin:0 0 10px 0;color:var(--fg-muted);font-size:12.5px">
        <b>Workspace permission required:</b> You need at least <b>Contributor</b> (or Member / Admin) access in a workspace to extract full semantic model definitions (tables, DAX &amp; Power Query). Workspaces where you only have <b>Viewer</b> access return basic inventory only.
      </p>
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
        <h2 class="step-title"><span class="step-num">3</span> Generate Documentation Portal</h2>
      </div>
      <p style="margin:0 0 14px 0;color:var(--fg-muted);font-size:13px">
        Builds the complete interactive HTML portal: Semantic Models, Star-Schema diagrams, formatted DAX &amp; Power Query catalogs, Workspaces &amp; Reports mapping, Governance Health checks, and Live Lineage.
      </p>

      <div style="display:grid;gap:10px;margin-bottom:16px;padding:12px 14px;background:var(--surface-alt);border:1px solid var(--border);border-radius:10px;font-size:13px">
        <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
          <input type="checkbox" id="chkAccess" style="margin-top:3px">
          <span><b>Include user permissions &amp; refresh history</b> <span style="color:var(--fg-muted)">- also fetches who has Admin/Member/Viewer access on each workspace &amp; dataset plus latest refresh status (takes slightly longer on large tenants).</span></span>
        </label>
        <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
          <input type="checkbox" id="chkAnon" style="margin-top:3px">
          <span><b>Anonymize personal names &amp; emails</b> <span style="color:var(--fg-muted)">- replaces owner names and user emails with <code>Redacted</code> when sharing the HTML folder externally (e.g. with external consultants or auditors).</span></span>
        </label>
      </div>

      <div id="scanBanner" class="inline-banner info" style="display:none;margin-top:0;margin-bottom:14px"></div>

      <div style="display:flex;flex-wrap:wrap;gap:10px">
        <button type="button" class="btn btn-primary" id="btnScanBuild" onclick="runScanAndBuild()">Scan Selected Workspaces &amp; Build Portal</button>
        <button type="button" class="btn btn-secondary" id="btnRebuildOnly" onclick="rebuildPortalOnly()">Rebuild HTML Portal from Local Cache</button>
        <a class="btn btn-success" href="/portal/index.html">Open Documentation Portal &rarr;</a>
      </div>

      <div class="log-box" id="logBox">Ready. Catalog folder: {{CATALOG_DIR}}</div>
    </div>
  </section>

  <!-- MODE 2: LOCAL POWER BI FILES -->
  <section class="pane" id="pane-local">
    <div class="step-card">
      <h2 class="step-title" style="margin-bottom:8px">Document Local Power BI Files &amp; Projects</h2>
      <p style="margin:0 0 14px 0;color:var(--fg-muted);font-size:13px">
        Select local Power BI files directly from your computer (works 100% offline, no Power BI Service sign-in needed): Power BI Desktop files (<code>.pbix</code>), Power BI Project folders (<code>.pbip</code> / <code>.SemanticModel</code>), or Excel PowerPivot workbooks (<code>.xlsx</code>).
      </p>

      <input type="file" id="nativeFilePicker" accept=".pbix,.pbip,.xlsx,.bim" multiple style="display:none" onchange="handleNativeFiles(this.files)">
      <input type="file" id="nativeFolderPicker" webkitdirectory directory multiple style="display:none" onchange="handleNativeFolder(this.files)">

      <div id="localDropZone" style="border:2px dashed var(--border);border-radius:12px;padding:22px 20px;background:var(--surface-alt);text-align:center;margin-bottom:14px;transition:border-color 0.15s,background 0.15s">
        <div style="font-weight:700;font-size:14.5px;margin-bottom:6px">Choose or drag &amp; drop your Power BI file(s) here</div>
        <div style="font-size:12.5px;color:var(--fg-muted);margin-bottom:14px">Supports <code>.pbix</code>, <code>.pbip</code> (automatically loads its companion <code>.SemanticModel</code>), and Excel PowerPivot <code>.xlsx</code></div>
        <div style="display:flex;justify-content:center;gap:10px;flex-wrap:wrap">
          <button type="button" class="btn btn-primary" id="btnPickFile" onclick="document.getElementById('nativeFilePicker').click()">Select Power BI File (.pbix, .pbip, .xlsx)...</button>
          <a class="btn btn-success" href="/portal/index.html">Open Documentation Portal &rarr;</a>
        </div>
      </div>

      <div id="localBanner" class="inline-banner info" style="display:none;margin-bottom:12px"></div>

      <details class="subtle">
        <summary>Advanced: select a standalone .SemanticModel folder or paste a path</summary>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          <input type="text" id="localPathInput" style="flex:1;min-width:260px" placeholder="e.g. C:\Reports\Sales.pbip or C:\Projects\Sales.SemanticModel">
          <button type="button" class="btn btn-primary" id="btnImportLocal" onclick="importLocalPath()">Generate from Path</button>
          <button type="button" class="btn btn-secondary" id="btnPickFolder" onclick="document.getElementById('nativeFolderPicker').click()">Browse .SemanticModel Folder...</button>
        </div>
      </details>

      <div class="log-box" id="localLogBox">Ready. Click 'Select Power BI File (.pbix, .pbip, .xlsx)...' or drop a file above.</div>
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

<footer style="max-width:1120px;margin:24px auto 14px auto;padding:14px 24px;border-top:1px solid var(--border);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;font-size:12px;color:var(--fg-muted)">
  <span><a href="https://github.com/djrien-ai/pbi-doc-generator" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;font-weight:600">PBI Doc Generator v1.0</a> &bull; 100% Local &amp; Read-Only (MIT Open Source)</span>
  <span>Created by <a href="https://www.linkedin.com/in/rien-scheerlinck/" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;font-weight:600">Rien Scheerlinck</a></span>
</footer>

<script>
var uiConnecting = false;
var wsLoadedOnce = false;
var wasBusy = false;

function toggleStudioTheme() {
  var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", cur);
  localStorage.setItem("pbidoc-v1-theme", cur);
}

document.querySelectorAll(".mode-tab").forEach(function(btn) {
  btn.addEventListener("click", function() {
    var target = btn.getAttribute("data-pane");
    document.querySelectorAll(".mode-tab").forEach(function(b) { b.classList.toggle("active", b === btn); });
    document.querySelectorAll(".pane").forEach(function(p) { p.classList.toggle("active", p.id === target); });
  });
});

function escHtml(s) {
  return String(s || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function setBanner(id, kind, html) {
  var el = document.getElementById(id);
  if (!el) return;
  if (!html) { el.style.display = "none"; el.innerHTML = ""; return; }
  el.className = "inline-banner " + kind;
  el.style.display = "flex";
  el.innerHTML = html;
}

function setAuthButtonsDisabled(disabled) {
  ["btnAuthOauth", "btnAuthBrowser", "btnAuthAz", "btnRefreshWs"].forEach(function(id) {
    var b = document.getElementById(id);
    if (b) b.disabled = disabled;
  });
}

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

async function cancelAuth() {
  await apiPost("/api/cancel-auth", {});
  setBanner("authBanner", "err",
    "<span>Sign-in cancelled. If standard Microsoft OAuth is restricted by your IT policy, use <b>Power BI Web Window</b>.</span>" +
    "<button type='button' class='btn btn-secondary' style='padding:6px 12px;font-size:12px' onclick=\"connectAuth('browser')\">Use Power BI Web Window &rarr;</button>"
  );
}

async function refreshStatus() {
  try {
    var st = await (await fetch("/api/status")).json();
    var pill = document.getElementById("authStatusPill");

    if (uiConnecting || (st.auth && st.auth.auth_in_progress)) {
      pill.className = "status-pill connecting";
      pill.innerHTML = "<span class='spin'></span> Connecting...";
      if (st.auth && st.auth.pending_auth_url) {
        setBanner("authBanner", "info",
          "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span>" +
          "<span><b>Waiting for Microsoft sign-in in your browser...</b> Complete login in the opened tab, or <a href='" + escHtml(st.auth.pending_auth_url) + "' target='_blank' style='color:inherit;font-weight:700'>click here if no tab appeared</a>.</span></span>" +
          "<button type='button' class='btn btn-secondary' style='padding:5px 12px;font-size:12px' onclick='cancelAuth()'>Cancel</button>"
        );
      }
    } else if (st.auth && st.auth.authenticated) {
      pill.className = "status-pill connected";
      pill.textContent = "Connected" + (st.auth.principal ? " (" + st.auth.principal + ")" : "") + " - " + st.auth.minutes_remaining + "m remaining";
      if (!wsLoadedOnce) {
        wsLoadedOnce = true;
        loadWorkspaces(false);
      }
    } else if (st.auth && st.auth.last_error) {
      pill.className = "status-pill failed";
      pill.textContent = "Sign-in failed";
    } else {
      pill.className = "status-pill";
      pill.textContent = "Not connected";
    }

    if (st.logs && st.logs.length) {
      document.getElementById("logBox").textContent = st.logs.join("\n");
      document.getElementById("logBox").scrollTop = document.getElementById("logBox").scrollHeight;
    }

    var topPortalBtn = document.getElementById("topOpenPortalBtn");
    if (topPortalBtn && typeof st.models_count === "number") {
      topPortalBtn.innerHTML = "2. Documentation Portal" + (st.models_count > 0 ? " (" + st.models_count + ")" : "") + " &rarr;";
    }

    var azBtn = document.getElementById("btnAuthAz");
    if (azBtn && st.auth && st.auth.az_available === false) {
      azBtn.disabled = true;
      azBtn.title = "Optional: requires Microsoft Azure CLI ('az') to be installed on this PC.";
      azBtn.textContent = "Azure CLI (not installed on this PC)";
    }

    var scanBtn = document.getElementById("btnScanBuild");
    if (st.busy) {
      wasBusy = true;
      if (scanBtn) scanBtn.disabled = true;
      var lastLine = (st.logs && st.logs.length) ? st.logs[st.logs.length - 1] : "Scanning workspaces...";
      setBanner("scanBanner", "info",
        "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span><b>Scan in progress:</b> " + escHtml(lastLine) + "</span></span>"
      );
    } else if (wasBusy) {
      wasBusy = false;
      if (scanBtn) scanBtn.disabled = false;
      if (st.last_scan_error) {
        setBanner("scanBanner", "err", "<span><b>Scan failed:</b> " + escHtml(st.last_scan_error) + "</span>");
      } else {
        setBanner("scanBanner", "ok",
          "<span><b>Portal ready!</b> All selected workspaces and models have been documented.</span>" +
          "<a class='btn btn-success' style='padding:6px 14px;font-size:12.5px' href='/portal/index.html'>Open Documentation Portal &rarr;</a>"
        );
      }
    }
  } catch (e) {}
}

async function connectAuth(mode) {
  uiConnecting = true;
  setAuthButtonsDisabled(true);
  var pill = document.getElementById("authStatusPill");
  pill.className = "status-pill connecting";
  pill.innerHTML = "<span class='spin'></span> Connecting...";

  var msg = mode === "oauth"
    ? "Opening Microsoft sign-in in your default browser... Complete sign-in there."
    : (mode === "browser"
        ? "Checking your Power BI Web session (Edge/Chrome)... This takes ~5-15 seconds."
        : "Requesting Power BI token from Azure CLI (`az account get-access-token`)...");

  setBanner("authBanner", "info",
    "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>" + escHtml(msg) + "</span></span>" +
    (mode === "oauth" ? "<button type='button' class='btn btn-secondary' style='padding:5px 12px;font-size:12px' onclick='cancelAuth()'>Cancel</button>" : "")
  );
  appendLog("Starting sign-in (" + mode + ")...");

  try {
    var data = await apiPost("/api/connect", { mode: mode });
    uiConnecting = false;
    await refreshStatus();
    if (data.ok) {
      var who = (data.status && data.status.principal) ? data.status.principal : mode;
      setBanner("authBanner", "info",
        "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span><b>Signed in as " + escHtml(who) + "!</b> Fetching your Power BI workspaces...</span></span>"
      );
      wsLoadedOnce = true;
      var count = await loadWorkspaces(false);
      if (count !== null) {
        setBanner("authBanner", "ok",
          "<span><b>Connected as " + escHtml(who) + "</b> - " + count + " workspace(s) loaded in Step 2 below.</span>"
        );
      }
    } else {
      var errTxt = data.error || "Unknown sign-in error";
      appendLog("Sign-in error: " + errTxt);
      var altBtn = (mode !== "browser")
        ? "<button type='button' class='btn btn-secondary' style='padding:6px 12px;font-size:12px;background:#fff' onclick=\"connectAuth('browser')\">Try Power BI Web Window &rarr;</button>"
        : "";
      setBanner("authBanner", "err",
        "<span><b>Sign-in failed:</b> " + escHtml(errTxt) + "</span>" + altBtn
      );
      if (mode !== "browser") {
        var det = document.getElementById("altAuthDetails");
        if (det) det.open = true;
      }
    }
  } catch (err) {
    uiConnecting = false;
    setBanner("authBanner", "err", "<span><b>Connection error:</b> " + escHtml(err) + "</span>");
  } finally {
    setAuthButtonsDisabled(false);
  }
}

async function loadWorkspaces(showBanner) {
  var btn = document.getElementById("btnRefreshWs");
  if (btn) btn.disabled = true;
  var list = document.getElementById("wsList");
  list.innerHTML = "<div style='padding:10px;color:var(--fg-muted);display:flex;align-items:center;gap:8px'><span class='spin'></span> Loading your Power BI workspaces...</div>";
  try {
    var data = await apiPost("/api/workspaces", {});
    if (!data.ok) {
      appendLog("Could not fetch workspaces: " + data.error);
      list.innerHTML = "<div style='padding:10px;color:#b91c1c'>Could not load workspaces: " + escHtml(data.error) + "</div>";
      if (showBanner) {
        setBanner("authBanner", "err", "<span><b>Could not refresh workspaces:</b> " + escHtml(data.error) + " (Sign in first in Step 1).</span>");
      }
      return null;
    }
    if (!data.workspaces.length) {
      list.innerHTML = "<div style='padding:8px;color:var(--fg-muted)'>No workspaces returned for this account.</div>";
      return 0;
    }
    list.innerHTML = data.workspaces.map(function(w) {
      return '<label class="ws-item" data-wsname="' + escHtml(w.name.toLowerCase()) + '">' +
        '<span style="display:flex;align-items:center;gap:8px"><input type="checkbox" class="ws-chk" value="' + escHtml(w.id) + '" checked> <b>' + escHtml(w.name) + '</b></span>' +
        '<span class="sku-tag">' + escHtml(w.sku) + '</span></label>';
    }).join("");
    if (showBanner) {
      setBanner("authBanner", "ok", "<span>Refreshed workspace list: <b>" + data.workspaces.length + " workspace(s)</b> available below.</span>");
    }
    return data.workspaces.length;
  } finally {
    if (btn) btn.disabled = false;
  }
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
  if (!ids.length) {
    setBanner("scanBanner", "err", "<span>Please sign in and select at least one workspace in Step 2 before scanning.</span>");
    return;
  }
  setBanner("scanBanner", "info",
    "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>Starting background scan for <b>" + ids.length + " workspace(s)</b>...</span></span>"
  );
  appendLog("Launching background scan for " + ids.length + " workspace(s)...");
  var res = await apiPost("/api/scan", {
    workspace_ids: ids,
    refresh: !document.getElementById("chkIncremental").checked,
    include_access: document.getElementById("chkAccess").checked,
    anonymous: document.getElementById("chkAnon").checked
  });
  if (!res.ok) {
    setBanner("scanBanner", "err", "<span><b>Could not start scan:</b> " + escHtml(res.error) + "</span>");
  } else {
    wasBusy = true;
    await refreshStatus();
  }
}

async function rebuildPortalOnly() {
  var btn = document.getElementById("btnRebuildOnly");
  if (btn) btn.disabled = true;
  setBanner("scanBanner", "info", "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>Rebuilding HTML portal from local catalog cache...</span></span>");
  try {
    var res = await apiPost("/api/portal", { anonymous: document.getElementById("chkAnon").checked });
    appendLog(res.ok ? "Portal regenerated: " + res.index : "Error: " + res.error);
    if (res.ok) {
      setBanner("scanBanner", "ok",
        "<span><b>Portal regenerated!</b> Ready to view.</span>" +
        "<a class='btn btn-success' style='padding:6px 14px;font-size:12.5px' href='/portal/index.html'>Open Documentation Portal &rarr;</a>"
      );
    } else {
      setBanner("scanBanner", "err", "<span><b>Error rebuilding portal:</b> " + escHtml(res.error) + "</span>");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function handleNativeFiles(fileList) {
  if (!fileList || !fileList.length) return;
  var files = Array.from(fileList);
  var btn1 = document.getElementById("btnPickFile");
  var btn2 = document.getElementById("btnPickFolder");
  if (btn1) btn1.disabled = true;
  if (btn2) btn2.disabled = true;
  var imported = [];
  try {
    for (var i = 0; i < files.length; i++) {
      var f = files[i];
      setBanner("localBanner", "info", "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>Importing <b>" + escHtml(f.name) + "</b> (" + (i + 1) + "/" + files.length + ") and building v1.0 Portal...</span></span>");
      appendLog("Importing " + f.name + " ...", "localLogBox");
      var resp = await fetch("/api/upload-local-file?name=" + encodeURIComponent(f.name), {
        method: "POST",
        headers: { "Content-Type": "application/octet-stream" },
        body: f
      });
      var res = await resp.json();
      if (!res.ok) {
        appendLog("Error: " + res.error, "localLogBox");
        var extraBtn = res.needs_folder
          ? "<button type='button' class='btn btn-secondary' style='padding:5px 12px;font-size:12px' onclick=\"document.getElementById('nativeFolderPicker').click()\">Select Project Folder...</button>"
          : "";
        setBanner("localBanner", "err", "<span><b>Import failed for " + escHtml(f.name) + ":</b> " + escHtml(res.error) + "</span>" + extraBtn);
        return;
      }
      imported.push(res.model_name || f.name);
      appendLog("Done! Imported '" + (res.model_name || f.name) + "'.", "localLogBox");
    }
    await refreshStatus();
    setBanner("localBanner", "ok",
      "<span><b>Imported " + escHtml(imported.join(", ")) + "!</b> Added to your v1.0 Documentation &amp; Live Lineage Portal.</span>" +
      "<a class='btn btn-success' style='padding:6px 14px;font-size:12.5px' href='/portal/index.html'>Open Documentation Portal &rarr;</a>"
    );
  } catch (err) {
    setBanner("localBanner", "err", "<span><b>Upload error:</b> " + escHtml(err) + "</span>");
  } finally {
    if (btn1) btn1.disabled = false;
    if (btn2) btn2.disabled = false;
    document.getElementById("nativeFilePicker").value = "";
  }
}

async function handleNativeFolder(fileList) {
  if (!fileList || !fileList.length) return;
  var btn1 = document.getElementById("btnPickFile");
  var btn2 = document.getElementById("btnPickFolder");
  if (btn1) btn1.disabled = true;
  if (btn2) btn2.disabled = true;
  try {
    setBanner("localBanner", "info", "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>Reading Power BI Project metadata files...</span></span>");
    var payloadFiles = [];
    var allowedExt = [".tmdl", ".pbip", ".pbir", ".pbi", ".bim", ".json", ".m", ".pq"];
    for (var i = 0; i < fileList.length; i++) {
      var f = fileList[i];
      var rel = (f.webkitRelativePath || f.name).replace(/\\/g, "/");
      var low = rel.toLowerCase();
      if (low.indexOf("/.pbi/") !== -1 || low.indexOf("/.git/") !== -1 || low.endsWith(".abf")) continue;
      if (f.size > 15 * 1024 * 1024) continue;
      var keep = allowedExt.some(function(ext) { return low.endsWith(ext); });
      if (!keep) continue;
      var txt = await f.text();
      payloadFiles.push({ path: rel, content: txt });
    }
    if (!payloadFiles.length) {
      setBanner("localBanner", "err", "<span>No Power BI Project (<code>.tmdl</code> / <code>.pbip</code> / <code>model.bim</code>) metadata files found in the selected folder.</span>");
      return;
    }
    appendLog("Uploading " + payloadFiles.length + " project metadata files...", "localLogBox");
    var res = await apiPost("/api/upload-local-folder", { files: payloadFiles });
    if (res.ok) {
      await refreshStatus();
      appendLog("Done! Imported '" + res.model_name + "' into Portal.", "localLogBox");
      setBanner("localBanner", "ok",
        "<span><b>Imported '" + escHtml(res.model_name) + "'!</b> Added to your v1.0 Documentation &amp; Live Lineage Portal.</span>" +
        "<a class='btn btn-success' style='padding:6px 14px;font-size:12.5px' href='/portal/index.html'>Open Documentation Portal &rarr;</a>"
      );
    } else {
      appendLog("Error: " + res.error, "localLogBox");
      setBanner("localBanner", "err", "<span><b>Folder import failed:</b> " + escHtml(res.error) + "</span>");
    }
  } catch (err) {
    setBanner("localBanner", "err", "<span><b>Folder import error:</b> " + escHtml(err) + "</span>");
  } finally {
    if (btn1) btn1.disabled = false;
    if (btn2) btn2.disabled = false;
    document.getElementById("nativeFolderPicker").value = "";
  }
}

(function() {
  var dz = document.getElementById("localDropZone");
  if (!dz) return;
  dz.addEventListener("dragover", function(e) { e.preventDefault(); dz.style.borderColor = "var(--accent)"; dz.style.background = "var(--accent-soft)"; });
  dz.addEventListener("dragleave", function() { dz.style.borderColor = "var(--border)"; dz.style.background = "var(--surface-alt)"; });
  dz.addEventListener("drop", function(e) {
    e.preventDefault();
    dz.style.borderColor = "var(--border)";
    dz.style.background = "var(--surface-alt)";
    if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
      handleNativeFiles(e.dataTransfer.files);
    }
  });
})();

async function importLocalPath() {
  var p = document.getElementById("localPathInput").value.trim();
  if (!p) {
    setBanner("localBanner", "err", "<span>Please select or paste a path to a <code>.pbip</code>, <code>.pbix</code>, or <code>.xlsx</code> file first.</span>");
    return;
  }
  var btn = document.getElementById("btnImportLocal");
  if (btn) btn.disabled = true;
  setBanner("localBanner", "info", "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>Extracting metadata and building v1.0 Portal for <b>" + escHtml(p) + "</b>...</span></span>");
  appendLog("Importing " + p + " into v1.0 Portal ...", "localLogBox");
  try {
    var res = await apiPost("/api/import-local", { path: p });
    if (res.ok) {
      appendLog("Done! Imported '" + (res.model_name || "") + "' into Portal (" + res.output + ").", "localLogBox");
      setBanner("localBanner", "ok",
        "<span><b>Imported '" + escHtml(res.model_name || p) + "'!</b> Added to your v1.0 Documentation &amp; Live Lineage Portal.</span>" +
        "<a class='btn btn-success' style='padding:6px 14px;font-size:12.5px' href='/portal/index.html'>Open Documentation Portal &rarr;</a>"
      );
    } else {
      appendLog("Error: " + res.error, "localLogBox");
      setBanner("localBanner", "err", "<span><b>Import failed:</b> " + escHtml(res.error) + "</span>");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

setInterval(refreshStatus, 1500);
refreshStatus();
</script>
</body>
</html>
"""


def _locate_local_pbip_on_disk(filename: str, raw_bytes: bytes, timeout_sec: float = 3.0) -> Path | None:
    """
    Browsers strip the local directory path (`C:\\fakepath\\...`) when a user picks a `.pbip` pointer file.
    Because Studio runs locally on the same machine, locate the exact `.pbip` file via breadth-first `os.scandir`
    verified by exact filename + byte size + SHA-256 hash so its sibling `.SemanticModel` folder can be read directly.
    """
    want_name = filename.lower()
    want_size = len(raw_bytes)
    want_sha = hashlib.sha256(raw_bytes).hexdigest()
    deadline = time.perf_counter() + timeout_sec
    skip_dirs = {
        "appdata", "node_modules", ".git", ".venv", "venv", "__pycache__",
        "$recycle.bin", "windows", "program files", "program files (x86)",
        "programdata", ".gemini", "library", "music", "pictures", "videos",
    }

    home = Path.home()
    seeds: list[Path] = [Path.cwd(), home / "Desktop", home / "Documents", home / "Downloads", home]
    for env_k in ("OneDrive", "OneDriveCommercial", "OneDriveConsumer"):
        val = os.environ.get(env_k)
        if val:
            seeds.append(Path(val))
    if sys.platform == "win32":
        for drv in ("C:\\", "D:\\", "E:\\", "F:\\", "G:\\"):
            dp = Path(drv)
            if dp.exists():
                try:
                    for sub in os.scandir(dp):
                        if sub.is_dir(follow_symlinks=False) and sub.name.lower() not in skip_dirs and not sub.name.startswith("."):
                            seeds.append(Path(sub.path))
                except OSError:
                    pass

    queue: collections.deque[tuple[str, int]] = collections.deque()
    visited: set[str] = set()
    for s in seeds:
        if s.exists():
            nc = os.path.normcase(str(s))
            if nc not in visited:
                visited.add(nc)
                queue.append((str(s), 0))

    while queue:
        if time.perf_counter() > deadline:
            return None
        cur_dir, depth = queue.popleft()
        try:
            with os.scandir(cur_dir) as it:
                for entry in it:
                    name_low = entry.name.lower()
                    if name_low == want_name and entry.is_file(follow_symlinks=False):
                        st = entry.stat(follow_symlinks=False)
                        cand = Path(entry.path)
                        if st.st_size == want_size and hashlib.sha256(cand.read_bytes()).hexdigest() == want_sha:
                            if any(cand.parent.glob("*.SemanticModel")) or any(cand.parent.glob("*.Dataset")):
                                return cand
                    elif depth < 7 and entry.is_dir(follow_symlinks=False):
                        if name_low not in skip_dirs and not name_low.startswith("."):
                            nc = os.path.normcase(entry.path)
                            if nc not in visited:
                                visited.add(nc)
                                queue.append((entry.path, depth + 1))
        except OSError:
            pass
    return None


class StudioState:
    def __init__(self, catalog_dir: str | Path):
        self.store = CatalogStore(catalog_dir)
        self.logs: list[str] = [f"Studio initialized. Catalog directory: {self.store.root}"]
        self.auth = TokenProvider(mode="oauth", log_fn=self.log)
        self.busy = False
        self.last_scan_error = ""

    def log(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {msg}")
        if len(self.logs) > 200:
            self.logs = self.logs[-200:]


def create_studio_server(catalog_dir: str | Path, host: str = "127.0.0.1", port: int = 8765) -> tuple[http.server.ThreadingHTTPServer, StudioState]:
    state = StudioState(catalog_dir)
    # Ensure initial portal exists if store already has models
    if state.store.state_file.exists():
        try:
            generate_portal(state.store)
        except Exception:
            pass

    mcp_args = (
        ["mcp", "--catalog", str(state.store.root)]
        if getattr(sys, "frozen", False)
        else ["-m", "pbi_catalog.cli", "mcp", "--catalog", str(state.store.root)]
    )
    mcp_cfg = json.dumps(
        {
            "mcpServers": {
                "powerbi-catalog": {
                    "command": sys.executable,
                    "args": mcp_args,
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
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                pass

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
                try:
                    models_cnt = len(state.store.load().get("models", {}))
                except Exception:
                    models_cnt = 0
                self._json(
                    {
                        "auth": state.auth.status(),
                        "busy": state.busy,
                        "last_scan_error": state.last_scan_error,
                        "models_count": models_cnt,
                        "logs": state.logs[-80:],
                    }
                )
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
            parsed = urllib.parse.urlparse(self.path)
            length = int(self.headers.get("Content-Length") or "0")

            if parsed.path == "/api/upload-local-file":
                raw_bytes = self.rfile.read(length) if length else b""
                qs = urllib.parse.parse_qs(parsed.query)
                safe_name = Path(qs.get("name", ["model.pbix"])[0]).name

                if safe_name.lower().endswith(".pbip"):
                    real_pbip = _locate_local_pbip_on_disk(safe_name, raw_bytes)
                    if not real_pbip:
                        self._json(
                            {
                                "ok": False,
                                "needs_folder": True,
                                "error": (
                                    f"Could not automatically locate the companion .SemanticModel folder for '{safe_name}' "
                                    "(browser hides network/deep folder paths). Click 'Select Project Folder...' to choose its folder."
                                ),
                            }
                        )
                        return
                    try:
                        meta = WorkspaceScanner.register_local_any(state.store, str(real_pbip))
                        idx = generate_portal(state.store)
                        state.log(f"Imported PBIP '{meta.get('name', safe_name)}' from {real_pbip}: {idx}")
                        self._json({"ok": True, "model_name": meta.get("name", real_pbip.stem), "output": str(idx)})
                    except Exception as exc:
                        state.log(f"PBIP import error: {exc}")
                        self._json({"ok": False, "error": str(exc)})
                    return

                staging_root = (state.store.root / "_staged_imports").resolve()
                staging_root.mkdir(parents=True, exist_ok=True)
                staged_file = staging_root / safe_name
                try:
                    staged_file.write_bytes(raw_bytes)
                    meta = WorkspaceScanner.register_local_any(state.store, str(staged_file))
                    idx = generate_portal(state.store)
                    state.log(f"Imported '{meta.get('name', safe_name)}' into v1.0 Portal: {idx}")
                    self._json({"ok": True, "model_name": meta.get("name", staged_file.stem), "output": str(idx)})
                except Exception as exc:
                    state.log(f"File upload import error: {exc}")
                    self._json({"ok": False, "error": str(exc)})
                finally:
                    try:
                        staged_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                return

            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}") if length else {}

            if parsed.path == "/api/upload-local-folder":
                files_list = body.get("files") or []
                staging_root = (state.store.root / "_staged_imports").resolve()
                if staging_root.exists():
                    shutil.rmtree(staging_root, ignore_errors=True)
                staging_root.mkdir(parents=True, exist_ok=True)
                try:
                    top_folder_name = ""
                    for item in files_list:
                        rel_str = str(item.get("path") or "").replace("\\", "/").lstrip("/")
                        if not rel_str or ".." in rel_str.split("/"):
                            continue
                        if not top_folder_name:
                            top_folder_name = rel_str.split("/")[0]
                        dest = (staging_root / rel_str).resolve()
                        if not str(dest).startswith(str(staging_root)):
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        dest.write_text(str(item.get("content") or ""), encoding="utf-8")

                    target_root = (staging_root / top_folder_name) if top_folder_name else staging_root
                    sem_dirs = sorted(target_root.rglob("*.SemanticModel"))
                    imported_names: list[str] = []
                    if sem_dirs:
                        for sdir in sem_dirs:
                            meta = WorkspaceScanner.register_local_any(state.store, str(sdir))
                            imported_names.append(meta.get("name", sdir.stem))
                    else:
                        meta = WorkspaceScanner.register_local_any(state.store, str(target_root))
                        imported_names.append(meta.get("name", target_root.name))

                    idx = generate_portal(state.store)
                    joined = ", ".join(imported_names)
                    state.log(f"Imported '{joined}' into v1.0 Portal: {idx}")
                    self._json({"ok": True, "model_name": joined, "output": str(idx)})
                except Exception as exc:
                    state.log(f"Folder upload import error: {exc}")
                    self._json({"ok": False, "error": str(exc)})
                finally:
                    shutil.rmtree(staging_root, ignore_errors=True)
                return

            if self.path == "/api/cancel-auth":
                state.auth.cancel_pending()
                state.log("Sign-in cancelled by user.")
                self._json({"ok": True})
                return

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
                    state.last_scan_error = ""
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
                        state.last_scan_error = str(exc)
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

            if self.path == "/api/import-local":
                p = Path(body.get("path", "")).expanduser()
                try:
                    meta = WorkspaceScanner.register_local_any(state.store, str(p))
                    idx = generate_portal(state.store)
                    state.log(f"Imported '{meta.get('name', p.name)}' into v1.0 Portal: {idx}")
                    self._json({"ok": True, "model_name": meta.get("name", p.stem), "output": str(idx)})
                except Exception as exc:
                    state.log(f"Local import error: {exc}")
                    self._json({"ok": False, "error": str(exc)})
                return

            self.send_response(404)
            self.end_headers()

    httpd = http.server.ThreadingHTTPServer((host, port), Handler)
    return httpd, state


def run_web_studio(catalog_dir: str | Path, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    httpd, _ = create_studio_server(catalog_dir, host=host, port=port)
    actual_port = httpd.server_address[1]
    url = f"http://{host}:{actual_port}"
    print(f"Power BI Documentation Studio running at {url}")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Studio.")
    finally:
        httpd.server_close()
