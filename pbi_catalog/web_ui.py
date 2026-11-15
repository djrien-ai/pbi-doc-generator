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
from .export_bundle import build_single_model_export, build_site_export
from .portal import generate_portal
from .scanner import WorkspaceScanner
from .sharepoint_publisher import publish_file_to_sharepoint
from .store import CatalogStore


STUDIO_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PBI Doc Generator v1.1 - Studio</title>
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
    .btn:disabled { opacity: 0.55; cursor: not-allowed; pointer-events: none; }
    .step-card { transition: opacity 0.18s ease, border-color 0.18s ease; }
    .step-card.is-locked { opacity: 0.52; pointer-events: none; user-select: none; }
    .step-num.done { background: var(--ok); color: #fff; }

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
        <a href="/portal/index.html" id="topOpenPortalBtn" title="Scan at least one workspace or import a local file first" style="padding:7px 13px;border-radius:8px;color:rgba(255,255,255,0.5);text-decoration:none;font-weight:650;font-size:12.5px;pointer-events:none;cursor:default">2. Documentation Portal (scan first)</a>
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
    <div class="step-card" id="stepCard1">
      <div class="step-hdr">
        <h2 class="step-title"><span class="step-num" id="stepNum1">1</span> Sign in to Power BI</h2>
        <span class="status-pill" id="authStatusPill">Not connected</span>
      </div>

      <div id="authDisconnectedWrap">
        <p style="margin:0 0 14px 0;color:var(--fg-muted);font-size:13px">
          Sign in with your Microsoft work account in your default browser. Read-only metadata access; credentials are never stored on disk.
        </p>
        <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center">
          <button type="button" class="btn btn-primary" id="btnAuthOauth" onclick="connectAuth('oauth')">Sign in with Microsoft</button>
        </div>

        <details class="subtle" id="altAuthDetails">
          <summary>Corporate tenant restricts standard OAuth apps? Alternative sign-in options</summary>
          <div style="margin-top:10px;padding:12px;background:var(--surface-alt);border-radius:10px;display:flex;flex-wrap:wrap;gap:8px;align-items:center">
            <button type="button" class="btn btn-secondary" id="btnAuthBrowser" onclick="connectAuth('browser')">Sign in via Power BI Web Window (Edge/Chrome)</button>
            <button type="button" class="btn btn-secondary" id="btnAuthAz" onclick="connectAuth('az')">Use Azure CLI (az login)</button>
          </div>
        </details>
      </div>

      <div id="authConnectedWrap" style="display:none;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;padding:10px 14px;background:var(--surface-alt);border:1px solid var(--border);border-radius:10px">
        <span style="font-size:13px">Signed in as <b id="authPrincipalLabel">Microsoft account</b></span>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <button type="button" class="btn btn-secondary" style="padding:6px 12px;font-size:12px" onclick="connectAuth('oauth')">Switch Account</button>
          <button type="button" class="btn btn-secondary" style="padding:6px 12px;font-size:12px" onclick="signOutAuth()">Sign Out</button>
        </div>
      </div>

      <div id="authBanner" class="inline-banner info" style="display:none"></div>
    </div>

    <div class="step-card is-locked" id="stepCard2">
      <div class="step-hdr">
        <h2 class="step-title"><span class="step-num" id="stepNum2">2</span> Choose Workspaces to Document</h2>
        <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">
          <span class="status-pill" id="wsSelectedPill" style="display:none">0 selected</span>
          <button type="button" class="btn btn-secondary" id="btnRefreshWs" style="padding:5px 10px;font-size:12px" onclick="loadWorkspaces(true)" disabled>Refresh</button>
          <button type="button" class="btn btn-secondary" id="btnWsAll" style="padding:5px 10px;font-size:12px" onclick="toggleAllWs(true)" disabled>Select All</button>
          <button type="button" class="btn btn-secondary" id="btnWsClear" style="padding:5px 10px;font-size:12px" onclick="toggleAllWs(false)" disabled>Clear</button>
        </div>
      </div>
      <p style="margin:0 0 10px 0;color:var(--fg-muted);font-size:12.5px">
        <b>Workspace permission required:</b> You need at least <b>Contributor</b> (or Member / Admin) access in a workspace to extract full semantic model definitions (tables, DAX &amp; Power Query). Workspaces where you only have <b>Viewer</b> access return basic inventory only.
      </p>
      <input type="search" id="wsFilter" placeholder="Filter workspaces by name (e.g. Finance, Sales, PROD)..." oninput="filterWs()" style="margin-bottom:10px" disabled>
      <div class="ws-list" id="wsList">
        <div style="color:var(--fg-muted);padding:8px;font-size:12.5px">Complete Step 1 above to load your visible Power BI workspaces.</div>
      </div>
    </div>

    <div class="step-card is-locked" id="stepCard3">
      <div class="step-hdr">
        <h2 class="step-title"><span class="step-num" id="stepNum3">3</span> Generate Documentation Portal</h2>
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span class="status-pill" id="activeCatalogPill">Catalog: Empty</span>
          <button type="button" class="btn btn-secondary" id="btnResetCatalog" style="padding:5px 11px;font-size:12px;display:none" onclick="resetCatalogFresh()" title="Wipe local catalog cache and start completely empty">Reset Catalog (Start Fresh)</button>
        </div>
      </div>
      <p style="margin:0 0 12px 0;color:var(--fg-muted);font-size:13px">
        <b>Full Blueprint included by default:</b> Semantic Models (TMDL), Star-Schema diagrams, SQLBI-formatted DAX, Slide-Over Report X-Ray wireframes, Dataflow Gen1/Gen2 pipelines &amp; Live Lineage.
      </p>

      <details class="subtle" id="advScanDetails" style="margin-top:0;margin-bottom:16px">
        <summary>Advanced scan &amp; privacy options (cross-workspace lineage, permissions, anonymization)</summary>
        <div style="display:grid;gap:10px;margin-top:10px;padding:12px 14px;background:var(--surface-alt);border:1px solid var(--border);border-radius:10px;font-size:13px;color:var(--fg)">
          <div id="existingCatalogModeWrap" style="display:none;padding-bottom:10px;border-bottom:1px solid var(--border)">
            <div style="font-weight:700;font-size:12.5px;margin-bottom:6px">Existing catalog update mode:</div>
            <div style="display:flex;flex-wrap:wrap;gap:14px">
              <label style="display:inline-flex;align-items:center;gap:6px;cursor:pointer">
                <input type="radio" name="scanCatalogMode" id="radScanIncremental" value="incremental" checked>
                <span><b>Incremental update (Recommended)</b> - keep cached models &amp; scan new/unscanned</span>
              </label>
              <label style="display:inline-flex;align-items:center;gap:6px;cursor:pointer">
                <input type="radio" name="scanCatalogMode" id="radScanClean" value="clean">
                <span><b>Replace catalog</b> - clear previous scan before running</span>
              </label>
            </div>
          </div>
          <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
            <input type="checkbox" id="chkReports" checked style="margin-top:3px">
            <span><b>Include report visual layouts &amp; report-level DAX</b> <span style="color:var(--fg-muted)">- enables the Slide-Over Report X-Ray Inspector, broken visual field detection, and Used vs. Unused DAX measure tracking.</span></span>
          </label>
          <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
            <input type="checkbox" id="chkDataflows" checked style="margin-top:3px">
            <span><b>Include Dataflow Gen1 &amp; Fabric Dataflow Gen2 M scripts + Native SQL</b> <span style="color:var(--fg-muted)">- parses Power Query transformation pipelines, formatted Native SQL queries, OneLake destinations, and multi-hop Dataflow chains.</span></span>
          </label>
          <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
            <input type="checkbox" id="chkFollowOutside" style="margin-top:3px">
            <span><b>Follow linked models &amp; upstream dataflows outside selected workspaces</b> <span style="color:var(--fg-muted)">- resolves cross-workspace shared semantic models and upstream L2+ staging dataflows in other workspaces where you have access.</span></span>
          </label>
          <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
            <input type="checkbox" id="chkAccess" style="margin-top:3px">
            <span><b>Include user permissions &amp; refresh history</b> <span style="color:var(--fg-muted)">- also fetches who has Admin/Member/Viewer access on each workspace &amp; dataset plus latest refresh status (slower on large tenants).</span></span>
          </label>
          <label style="display:flex;align-items:flex-start;gap:9px;cursor:pointer">
            <input type="checkbox" id="chkAnon" style="margin-top:3px">
            <span><b>Anonymize personal names, emails &amp; report filter literals</b> <span style="color:var(--fg-muted)">- scrubs owner names, user emails, slicer selections, and filter values when sharing externally.</span></span>
          </label>
        </div>
      </details>

      <div id="scanBanner" class="inline-banner info" style="display:none;margin-top:0;margin-bottom:14px"></div>

      <div style="display:flex;flex-wrap:wrap;gap:10px">
        <button type="button" class="btn btn-primary" id="btnScanBuild" onclick="runScanAndBuild()" disabled>Sign in &amp; select workspaces above to scan</button>
        <button type="button" class="btn btn-secondary" id="btnRebuildOnly" style="display:none" onclick="rebuildPortalOnly()">Rebuild HTML Portal from Local Cache</button>
        <a class="btn btn-success" id="btnOpenPortalStep3" style="display:none" href="/portal/index.html">Open Documentation Portal &rarr;</a>
      </div>

      <div id="portalExportHint" style="margin-top:12px;padding-top:10px;border-top:1px dashed var(--border);font-size:12.5px;color:var(--fg-muted);display:none">
        <b>PDF, Standalone HTML, SharePoint Online &amp; Data Dictionary:</b> open the Documentation Portal and click <b>Export / Publish</b> in the top bar (available for the <b>entire catalog</b> or any <b>individual semantic model</b>).
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
          <a class="btn btn-success" id="btnOpenPortalLocal" style="display:none" href="/portal/index.html">Open Documentation Portal &rarr;</a>
        </div>
      </div>

      <div id="localBanner" class="inline-banner info" style="display:none;margin-bottom:12px"></div>

      <details class="subtle">
        <summary>Advanced: select a standalone .SemanticModel folder or paste a path</summary>
        <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
          <input type="text" id="localPathInput" style="flex:1;min-width:260px" placeholder="e.g. C:\Reports\Sales.pbip or C:\Projects\Sales.SemanticModel" oninput="document.getElementById('btnImportLocal').disabled=!this.value.trim()">
          <button type="button" class="btn btn-primary" id="btnImportLocal" onclick="importLocalPath()" disabled>Generate from Path</button>
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
  <span><a href="https://github.com/djrien-ai/pbi-doc-generator" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;font-weight:600">PBI Doc Generator v1.1</a> &bull; 100% Local &amp; Read-Only (MIT Open Source)</span>
  <span>Created by <a href="https://github.com/djrien-ai" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;font-weight:600">Rien Scheerlinck</a> &bull; <a href="mailto:dj.rien@gmail.com?subject=Power%20BI%20Enterprise%20%26%20Architecture%20Inquiry" style="color:var(--accent);text-decoration:none;font-weight:600">Contact</a> &bull; <a href="https://ko-fi.com/rienscheerlinck" target="_blank" rel="noopener" style="color:var(--accent);text-decoration:none;font-weight:600">Support on Ko-fi</a></span>
</footer>

<script>
var uiConnecting = false;
var wsLoadedOnce = false;
var wasBusy = false;
var latestAuthenticated = false;
var latestBusy = false;

function toggleStudioTheme() {
  var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", cur);
  localStorage.setItem("pbidoc-v1-theme", cur);
}

document.querySelectorAll(".mode-tab").forEach(function(btn) {
  btn.addEventListener("click", function() {
    if (latestBusy) return;
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

function appendLog(msg, boxId) {
  var box = document.getElementById(boxId || "logBox");
  box.textContent += "\n" + msg;
  box.scrollTop = box.scrollHeight;
}

async function apiPost(path, payload) {
  var res = await fetch(path, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload || {}) });
  return await res.json();
}

function updateWsSelectionUi() {
  var allChks = Array.from(document.querySelectorAll("#wsList .ws-chk"));
  var checkedChks = allChks.filter(function(c) { return c.checked; });
  var total = allChks.length;
  var sel = checkedChks.length;

  var wsPill = document.getElementById("wsSelectedPill");
  if (wsPill) {
    if (latestAuthenticated && total > 0) {
      wsPill.style.display = "inline-flex";
      wsPill.textContent = sel + " of " + total + " selected";
      wsPill.className = sel > 0 ? "status-pill connected" : "status-pill";
    } else {
      wsPill.style.display = "none";
    }
  }

  var hasItems = latestAuthenticated && total > 0 && !latestBusy;
  ["btnWsAll", "btnWsClear", "wsFilter"].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.disabled = !hasItems;
  });
  var refBtn = document.getElementById("btnRefreshWs");
  if (refBtn) refBtn.disabled = !latestAuthenticated || latestBusy;

  var scanBtn = document.getElementById("btnScanBuild");
  if (scanBtn) {
    if (latestBusy) {
      scanBtn.disabled = true;
      scanBtn.textContent = "Scanning workspaces...";
    } else if (!latestAuthenticated) {
      scanBtn.disabled = true;
      scanBtn.textContent = "Sign in & select workspaces above to scan";
    } else if (sel === 0) {
      scanBtn.disabled = true;
      scanBtn.textContent = total > 0 ? "Select at least 1 workspace in Step 2" : "No workspaces available to scan";
    } else {
      scanBtn.disabled = false;
      scanBtn.textContent = "Scan " + sel + " Selected Workspace" + (sel === 1 ? "" : "s") + " & Build Portal";
    }
  }
}

async function signOutAuth() {
  await apiPost("/api/sign-out", {});
  wsLoadedOnce = false;
  latestAuthenticated = false;
  var wsFilter = document.getElementById("wsFilter");
  if (wsFilter) wsFilter.value = "";
  var list = document.getElementById("wsList");
  if (list) {
    list.innerHTML = "<div style='color:var(--fg-muted);padding:8px;font-size:12.5px'>Complete Step 1 above to load your visible Power BI workspaces.</div>";
  }
  setBanner("authBanner", "", "");
  await refreshStatus();
}

async function cancelAuth() {
  uiConnecting = false;
  setAuthButtonsDisabled(false);
  await apiPost("/api/cancel-auth", {});
  await refreshStatus();
  setBanner("authBanner", "err",
    "<span>Sign-in cancelled. If standard Microsoft OAuth is restricted by your IT policy, use <b>Power BI Web Window</b>.</span>" +
    "<button type='button' class='btn btn-secondary' style='padding:6px 12px;font-size:12px' onclick=\"connectAuth('browser')\">Use Power BI Web Window &rarr;</button>"
  );
}

async function refreshStatus() {
  try {
    var st = await (await fetch("/api/status")).json();
    var pill = document.getElementById("authStatusPill");
    var stepNum1 = document.getElementById("stepNum1");
    var disWrap = document.getElementById("authDisconnectedWrap");
    var conWrap = document.getElementById("authConnectedWrap");
    var prinLbl = document.getElementById("authPrincipalLabel");
    var step2 = document.getElementById("stepCard2");
    var step3 = document.getElementById("stepCard3");

    var isConnecting = !!(uiConnecting || (st.auth && st.auth.auth_in_progress));
    var isAuth = !!(st.auth && st.auth.authenticated);
    latestAuthenticated = isAuth;
    latestBusy = !!st.busy;

    if (isConnecting) {
      pill.className = "status-pill connecting";
      pill.innerHTML = "<span class='spin'></span> Connecting...";
      if (disWrap) disWrap.style.display = "";
      if (conWrap) conWrap.style.display = "none";
      if (stepNum1) { stepNum1.className = "step-num"; stepNum1.textContent = "1"; }
      if (st.auth && st.auth.pending_auth_url) {
        setBanner("authBanner", "info",
          "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span>" +
          "<span><b>Waiting for Microsoft sign-in in your browser...</b> Complete login in the opened tab, or <a href='" + escHtml(st.auth.pending_auth_url) + "' target='_blank' style='color:inherit;font-weight:700'>click here if no tab appeared</a>.</span></span>" +
          "<button type='button' class='btn btn-secondary' style='padding:5px 12px;font-size:12px' onclick='cancelAuth()'>Cancel</button>"
        );
      }
    } else if (isAuth) {
      pill.className = "status-pill connected";
      pill.textContent = "Connected (" + st.auth.minutes_remaining + "m remaining)";
      if (disWrap) disWrap.style.display = "none";
      if (conWrap) conWrap.style.display = "flex";
      if (prinLbl) prinLbl.textContent = st.auth.principal || "Microsoft account";
      if (stepNum1) { stepNum1.className = "step-num done"; stepNum1.innerHTML = "&#10003;"; }
      if (!wsLoadedOnce) {
        wsLoadedOnce = true;
        loadWorkspaces(false);
      }
    } else if (st.auth && st.auth.last_error) {
      pill.className = "status-pill failed";
      pill.textContent = "Sign-in failed";
      if (disWrap) disWrap.style.display = "";
      if (conWrap) conWrap.style.display = "none";
      if (stepNum1) { stepNum1.className = "step-num"; stepNum1.textContent = "1"; }
    } else {
      pill.className = "status-pill";
      pill.textContent = "Not connected";
      if (disWrap) disWrap.style.display = "";
      if (conWrap) conWrap.style.display = "none";
      if (stepNum1) { stepNum1.className = "step-num"; stepNum1.textContent = "1"; }
    }

    var hasModels = typeof st.models_count === "number" && st.models_count > 0;
    var portalReady = !!st.portal_ready;

    if (step2) step2.classList.toggle("is-locked", !isAuth || !!st.busy);
    if (step3) step3.classList.toggle("is-locked", (!isAuth && !hasModels && !portalReady));
    document.querySelectorAll(".mode-tab").forEach(function(b) { b.disabled = !!st.busy; });

    var existingModeWrap = document.getElementById("existingCatalogModeWrap");
    if (existingModeWrap) existingModeWrap.style.display = hasModels ? "" : "none";

    if (st.logs && st.logs.length) {
      document.getElementById("logBox").textContent = st.logs.join("\n");
      document.getElementById("logBox").scrollTop = document.getElementById("logBox").scrollHeight;
    }

    var topPortalBtn = document.getElementById("topOpenPortalBtn");
    if (topPortalBtn) {
      if (portalReady) {
        topPortalBtn.innerHTML = "2. Documentation Portal (" + st.models_count + ") &rarr;";
        topPortalBtn.style.pointerEvents = "auto";
        topPortalBtn.style.color = "#fff";
        topPortalBtn.style.cursor = "pointer";
        topPortalBtn.title = "Open generated Documentation Portal";
      } else {
        topPortalBtn.innerHTML = st.busy ? "2. Documentation Portal (scanning...)" : "2. Documentation Portal (scan first)";
        topPortalBtn.style.pointerEvents = "none";
        topPortalBtn.style.color = "rgba(255,255,255,0.5)";
        topPortalBtn.style.cursor = "default";
        topPortalBtn.title = "Scan at least one workspace or import a local file first";
      }
    }
    var catPill = document.getElementById("activeCatalogPill");
    if (catPill && typeof st.models_count === "number") {
      catPill.textContent = hasModels
        ? ("Catalog: " + st.models_count + " model" + (st.models_count === 1 ? "" : "s") + " ready")
        : "Catalog: Empty";
      catPill.className = hasModels ? "status-pill connected" : "status-pill";
    }
    var rebuildBtn = document.getElementById("btnRebuildOnly");
    if (rebuildBtn) {
      rebuildBtn.style.display = hasModels ? "" : "none";
      rebuildBtn.disabled = !!st.busy;
    }
    var openStep3 = document.getElementById("btnOpenPortalStep3");
    if (openStep3) openStep3.style.display = portalReady ? "" : "none";
    var openLocal = document.getElementById("btnOpenPortalLocal");
    if (openLocal) openLocal.style.display = portalReady ? "" : "none";
    var exportHint = document.getElementById("portalExportHint");
    if (exportHint) exportHint.style.display = portalReady ? "" : "none";
    var resetCatBtn = document.getElementById("btnResetCatalog");
    if (resetCatBtn) {
      resetCatBtn.style.display = (hasModels || portalReady) ? "" : "none";
      resetCatBtn.disabled = !!st.busy;
    }

    var azBtn = document.getElementById("btnAuthAz");
    if (azBtn && st.auth && st.auth.az_available === false) {
      azBtn.disabled = true;
      azBtn.title = "Optional: requires Microsoft Azure CLI ('az') to be installed on this PC.";
      azBtn.textContent = "Azure CLI (not installed on this PC)";
    }

    updateWsSelectionUi();

    if (st.busy) {
      wasBusy = true;
      var lastLine = (st.logs && st.logs.length) ? st.logs[st.logs.length - 1] : "Scanning workspaces...";
      setBanner("scanBanner", "info",
        "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span><b>Scan in progress:</b> " + escHtml(lastLine) + "</span></span>"
      );
    } else if (wasBusy) {
      wasBusy = false;
      updateWsSelectionUi();
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
    ((mode === "oauth" || mode === "browser") ? "<button type='button' class='btn btn-secondary' style='padding:5px 12px;font-size:12px' onclick='cancelAuth()'>Cancel</button>" : "")
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
          "<span><b>Connected!</b> " + count + " workspace(s) loaded in Step 2 below.</span>"
        );
      }
    } else {
      var errTxt = data.error || "Unknown sign-in error";
      if (errTxt.toLowerCase().indexOf("cancelled") !== -1) {
        return;
      }
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
    await refreshStatus();
    setBanner("authBanner", "err", "<span><b>Connection error:</b> " + escHtml(err) + "</span>");
  } finally {
    uiConnecting = false;
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
        setBanner("authBanner", "err", "<span><b>Could not refresh workspaces:</b> " + escHtml(data.error) + "</span>");
      }
      updateWsSelectionUi();
      return null;
    }
    if (!data.workspaces.length) {
      list.innerHTML = "<div style='padding:8px;color:var(--fg-muted)'>No workspaces returned for this account.</div>";
      updateWsSelectionUi();
      return 0;
    }
    // Auto-select all only on small estates (<= 5 workspaces); on larger tenants let user pick deliberately
    var autoCheck = data.workspaces.length <= 5 ? " checked" : "";
    list.innerHTML = data.workspaces.map(function(w) {
      return '<label class="ws-item" data-wsname="' + escHtml(w.name.toLowerCase()) + '">' +
        '<span style="display:flex;align-items:center;gap:8px"><input type="checkbox" class="ws-chk" value="' + escHtml(w.id) + '"' + autoCheck + ' onchange="updateWsSelectionUi()"> <b>' + escHtml(w.name) + '</b></span>' +
        '<span class="sku-tag">' + escHtml(w.sku) + '</span></label>';
    }).join("");
    updateWsSelectionUi();
    if (showBanner) {
      setBanner("authBanner", "ok", "<span>Refreshed workspace list: <b>" + data.workspaces.length + " workspace(s)</b> available.</span>");
    }
    return data.workspaces.length;
  } finally {
    if (btn) btn.disabled = !latestAuthenticated || latestBusy;
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
  updateWsSelectionUi();
}

async function runScanAndBuild() {
  var ids = Array.from(document.querySelectorAll(".ws-chk:checked")).map(function(c) { return c.value; });
  if (!ids.length) {
    setBanner("scanBanner", "err", "<span>Please select at least one workspace in Step 2 before scanning.</span>");
    return;
  }
  var cleanRadio = document.getElementById("radScanClean");
  var modeWrap = document.getElementById("existingCatalogModeWrap");
  var hasExisting = !!(modeWrap && modeWrap.style.display !== "none");
  var cleanSlate = !!(hasExisting && cleanRadio && cleanRadio.checked);
  setBanner("scanBanner", "info",
    "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>Starting " + (cleanSlate ? "clean " : "") + "background scan for <b>" + ids.length + " workspace(s)</b>...</span></span>"
  );
  appendLog("Launching background scan for " + ids.length + " workspace(s)...");
  var res = await apiPost("/api/scan", {
    workspace_ids: ids,
    clean_catalog: cleanSlate,
    refresh: cleanSlate,
    include_reports: document.getElementById("chkReports") ? document.getElementById("chkReports").checked : true,
    include_dataflows: document.getElementById("chkDataflows") ? document.getElementById("chkDataflows").checked : true,
    follow_outside: document.getElementById("chkFollowOutside") ? document.getElementById("chkFollowOutside").checked : false,
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

async function resetCatalogFresh() {
  if (!window.confirm("Reset local catalog? All previously scanned models, reports, and generated HTML portal pages will be cleared.")) {
    return;
  }
  var btn = document.getElementById("btnResetCatalog");
  if (btn) btn.disabled = true;
  try {
    var res = await apiPost("/api/reset-catalog", {});
    if (res.ok) {
      appendLog("Catalog reset: all previously scanned models, reports, and portal files cleared.");
      await refreshStatus();
      setBanner("scanBanner", "ok", "<span><b>Clean slate ready!</b> Local catalog cache cleared (0 models).</span>");
    } else {
      setBanner("scanBanner", "err", "<span><b>Could not reset catalog:</b> " + escHtml(res.error) + "</span>");
    }
  } finally {
    if (btn) btn.disabled = false;
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
      await refreshStatus();
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

function triggerSiteExport(fmt) {
  var anon = (document.getElementById("chkAnon") && document.getElementById("chkAnon").checked) ? "1" : "0";
  appendLog("Preparing " + (fmt === "zip" ? "Offline Portal Bundle (.zip)" : "SharePoint Single-File (.html)") + " export...");
  window.location.href = "/api/export-site?format=" + encodeURIComponent(fmt) + "&anonymous=" + anon;
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
      setBanner("localBanner", "info", "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>Importing <b>" + escHtml(f.name) + "</b> (" + (i + 1) + "/" + files.length + ") and building v1.1 Portal...</span></span>");
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
      "<span><b>Imported " + escHtml(imported.join(", ")) + "!</b> Added to your v1.1 Documentation &amp; Live Lineage Portal.</span>" +
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
        "<span><b>Imported '" + escHtml(res.model_name) + "'!</b> Added to your v1.1 Documentation &amp; Live Lineage Portal.</span>" +
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
  setBanner("localBanner", "info", "<span style='display:flex;align-items:center;gap:10px'><span class='spin'></span><span>Extracting metadata and building v1.1 Portal for <b>" + escHtml(p) + "</b>...</span></span>");
  appendLog("Importing " + p + " into v1.1 Portal ...", "localLogBox");
  try {
    var res = await apiPost("/api/import-local", { path: p });
    if (res.ok) {
      appendLog("Done! Imported '" + (res.model_name || "") + "' into Portal (" + res.output + ").", "localLogBox");
      setBanner("localBanner", "ok",
        "<span><b>Imported '" + escHtml(res.model_name || p) + "'!</b> Added to your v1.1 Documentation &amp; Live Lineage Portal.</span>" +
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


class _ExclusiveServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = sys.platform != "win32"


def _render_portal_state_html(busy: bool, logs: list[str], models_count: int, requested_path: str) -> bytes:
    """Render a clean, themed HTML waiting/empty-state page instead of a naked plain-text 404."""
    import html as _html

    last_log = _html.escape(logs[-1] if logs else "Ready.")
    req_esc = _html.escape(requested_path or "/portal/index.html")
    if busy:
        title = "Generating Documentation Portal..."
        badge = '<span class="pill busy"><span class="spin"></span> Scan in progress</span>'
        body = (
            "<p>Your Power BI workspace scan and interactive HTML portal build are currently running in the background. "
            "This page will open your documentation automatically the moment generation finishes.</p>"
            f'<div class="log-tail" id="liveTail">{last_log}</div>'
            '<div class="actions">'
            '<a class="btn sec" href="/">&larr; View Full Progress in 1. Scanner &amp; Setup</a>'
            "</div>"
        )
    elif models_count > 0:
        title = "Model Page Moved or Replaced"
        badge = f'<span class="pill ok">{models_count} model(s) ready</span>'
        body = (
            f"<p>The requested page (<code>{req_esc}</code>) is not in the current catalog snapshot, "
            f"but your Documentation Portal has <b>{models_count} documented model(s)</b> ready to explore.</p>"
            '<div class="actions">'
            '<a class="btn pri" href="/portal/index.html">Open Documentation Portal Home &rarr;</a>'
            '<a class="btn sec" href="/">&larr; 1. Scanner &amp; Setup</a>'
            "</div>"
        )
    else:
        title = "No Documentation Portal Generated Yet"
        badge = '<span class="pill">Empty catalog (0 models)</span>'
        body = (
            "<p>Your local catalog is currently empty (clean slate). Sign in and scan one or more Power BI workspaces, "
            "or drop a local <code>.pbix</code> / <code>.pbip</code> / <code>.xlsx</code> file to generate your interactive portal.</p>"
            '<div class="actions">'
            '<a class="btn pri" href="/">&larr; Go to 1. Scanner &amp; Setup</a>'
            "</div>"
        )

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} - PBI Doc Generator v1.1</title>
  <style>
    :root {{
      --bg:#f4f7fb; --surface:#ffffff; --fg:#0f172a; --muted:#526077;
      --border:#dce3ee; --accent:#0b63ce; --accent-soft:#e8f1fd;
    }}
    [data-theme="dark"] {{
      --bg:#0b1120; --surface:#111827; --fg:#e5e7eb; --muted:#9ca3af;
      --border:#1f2937; --accent:#60a5fa; --accent-soft:rgba(59,130,246,0.16);
    }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"Segoe UI",-apple-system,sans-serif; background:var(--bg); color:var(--fg); min-height:100vh; display:flex; flex-direction:column; }}
    header {{ background:linear-gradient(125deg,#072854 0%,#0b63ce 100%); color:#fff; padding:18px 28px; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px; }}
    header h1 {{ margin:0; font-size:19px; font-weight:750; }}
    .switcher {{ display:inline-flex; background:rgba(255,255,255,0.14); padding:4px; border-radius:10px; border:1px solid rgba(255,255,255,0.24); gap:4px; }}
    .switcher a, .switcher span {{ padding:6px 12px; border-radius:7px; font-size:12.5px; font-weight:650; text-decoration:none; color:#fff; }}
    .switcher .act {{ background:#fff; color:#072854; font-weight:700; }}
    main {{ flex:1; display:flex; align-items:center; justify-content:center; padding:32px 20px; }}
    .card {{ max-width:600px; width:100%; background:var(--surface); border:1px solid var(--border); border-radius:16px; padding:28px 30px; box-shadow:0 8px 30px rgba(15,23,42,0.07); }}
    .card h2 {{ margin:12px 0 8px 0; font-size:21px; }}
    .card p {{ margin:0 0 18px 0; color:var(--muted); font-size:14px; line-height:1.55; }}
    .pill {{ display:inline-flex; align-items:center; gap:7px; padding:4px 11px; border-radius:999px; font-size:12px; font-weight:700; background:var(--accent-soft); color:var(--accent); }}
    .pill.ok {{ background:#dcfce7; color:#15803d; }}
    .spin {{ width:12px; height:12px; border:2px solid currentColor; border-right-color:transparent; border-radius:50%; display:inline-block; animation:sp .75s linear infinite; }}
    @keyframes sp {{ to {{ transform:rotate(360deg); }} }}
    .log-tail {{ font-family:Consolas,monospace; font-size:12px; padding:10px 12px; border-radius:8px; background:#0f172a; color:#e2e8f0; margin-bottom:18px; overflow-wrap:anywhere; }}
    .actions {{ display:flex; gap:10px; flex-wrap:wrap; }}
    .btn {{ display:inline-flex; align-items:center; gap:6px; padding:10px 16px; border-radius:9px; font-size:13.5px; font-weight:650; text-decoration:none; }}
    .btn.pri {{ background:var(--accent); color:#fff; }}
    .btn.sec {{ background:var(--accent-soft); color:var(--accent); }}
  </style>
  <script>
    (function() {{
      try {{ var t = localStorage.getItem("pbidoc-v1-theme"); if (t) document.documentElement.setAttribute("data-theme", t); }} catch(e) {{}}
      var isBusy = {"true" if busy else "false"};
      if (isBusy) {{
        setInterval(async function() {{
          try {{
            var st = await (await fetch("/api/status")).json();
            var tail = document.getElementById("liveTail");
            if (tail && st.logs && st.logs.length) tail.textContent = st.logs[st.logs.length - 1];
            if (!st.busy && st.models_count > 0) {{
              window.location.href = "/portal/index.html";
            }} else if (!st.busy) {{
              window.location.reload();
            }}
          }} catch (e) {{}}
        }}, 1500);
      }}
    }})();
  </script>
</head>
<body>
  <header>
    <h1>Power BI Documentation &amp; Live Lineage Portal</h1>
    <div class="switcher">
      <a href="/">&larr; 1. Scanner &amp; Setup</a>
      <span class="act">2. Documentation Portal</span>
    </div>
  </header>
  <main>
    <div class="card">
      {badge}
      <h2>{title}</h2>
      {body}
    </div>
  </main>
</body>
</html>"""
    return page.encode("utf-8")


class StudioState:
    def __init__(self, catalog_dir: str | Path):
        self.store = CatalogStore(catalog_dir)
        self.logs: list[str] = [f"Studio initialized. Catalog directory: {self.store.root}"]
        self.auth = TokenProvider(mode="oauth", log_fn=self.log)
        self.busy = False
        self.last_scan_error = ""
        self._op_lock = threading.Lock()
        self._models_mtime: float = -1.0
        self._models_count_cache: int = 0

    def invalidate_cache(self) -> None:
        self._models_mtime = -1.0
        self._models_count_cache = 0

    def get_models_count(self) -> int:
        try:
            sf = self.store.state_file
            if not sf.exists():
                self._models_count_cache = 0
                self._models_mtime = -1.0
                return 0
            mt = sf.stat().st_mtime
            if mt != self._models_mtime:
                self._models_count_cache = len(self.store.load_scoped().get("models", {}))
                self._models_mtime = mt
            return self._models_count_cache
        except Exception:
            return self._models_count_cache

    def log(self, msg: str) -> None:
        stamp = time.strftime("%H:%M:%S")
        self.logs.append(f"[{stamp}] {msg}")
        if len(self.logs) > 200:
            self.logs = self.logs[-200:]


def create_studio_server(catalog_dir: str | Path, host: str = "127.0.0.1", port: int = 8765) -> tuple[http.server.ThreadingHTTPServer, StudioState]:
    state = StudioState(catalog_dir)
    # Ensure initial portal exists ONLY if store already has non-zero models
    if state.store.state_file.exists() and state.get_models_count() > 0:
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
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            except (ConnectionAbortedError, BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/favicon.ico":
                svg_ico = (
                    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                    b'<rect width="32" height="32" rx="7" fill="#0b63ce"/>'
                    b'<rect x="7" y="16" width="4" height="10" rx="1.5" fill="#fff"/>'
                    b'<rect x="14" y="11" width="4" height="15" rx="1.5" fill="#93c5fd"/>'
                    b'<rect x="21" y="6" width="4" height="20" rx="1.5" fill="#fff"/>'
                    b'</svg>'
                )
                self.send_response(200)
                self.send_header("Content-Type", "image/svg+xml")
                self.send_header("Content-Length", str(len(svg_ico)))
                self.end_headers()
                self.wfile.write(svg_ico)
                return

            if parsed.path in ("/", "/index.html"):
                html = STUDIO_HTML.replace("{{CATALOG_DIR}}", str(state.store.root)).replace("{{MCP_JSON}}", mcp_cfg)
                raw = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
                return

            if parsed.path == "/api/status":
                m_cnt = state.get_models_count()
                portal_ready = bool(m_cnt > 0 and (state.store.portal_dir / "index.html").is_file())
                self._json(
                    {
                        "auth": state.auth.status(),
                        "busy": state.busy,
                        "last_scan_error": state.last_scan_error,
                        "models_count": m_cnt,
                        "portal_ready": portal_ready,
                        "logs": state.logs[-80:],
                    }
                )
                return

            if parsed.path == "/api/export-site":
                qs = urllib.parse.parse_qs(parsed.query)
                fmt = (qs.get("format", ["single"])[0] or "single").strip().lower()
                model_slug = (qs.get("model", [""])[0] or "").strip()
                anon = (qs.get("anonymous", ["0"])[0] or "0").strip() in ("1", "true", "yes")
                inc_aspx = (qs.get("aspx", ["0"])[0] or "0").strip() in ("1", "true", "yes")
                exports_dir = (state.store.root / "_exports").resolve()
                exports_dir.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M")
                is_single = fmt != "zip"
                ext = ".aspx" if (is_single and inc_aspx) else (".html" if is_single else ".zip")
                if model_slug:
                    safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in model_slug)[:80]
                    fname = f"PBI_Model_{safe_slug}_{stamp}{ext}"
                else:
                    fname = (
                        f"PBI_Documentation_Portal_SharePoint_{stamp}{ext}"
                        if is_single
                        else f"PBI_Documentation_Portal_Bundle_{stamp}.zip"
                    )
                out_file = exports_dir / fname
                try:
                    if model_slug:
                        built = build_single_model_export(
                            state.store,
                            model_slug,
                            out_file,
                            anonymous=anon,
                            as_aspx=inc_aspx,
                            log_fn=state.log,
                        )
                    else:
                        built = build_site_export(
                            state.store,
                            out_file,
                            anonymous=anon,
                            include_aspx=inc_aspx,
                            log_fn=state.log,
                            single_file_only=is_single,
                        )
                    payload_bytes = built.read_bytes()
                    ctype = "text/html; charset=utf-8" if is_single else "application/zip"
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Content-Disposition", f'attachment; filename="{built.name}"')
                    self.send_header("Content-Length", str(len(payload_bytes)))
                    self.end_headers()
                    self.wfile.write(payload_bytes)
                except Exception as exc:
                    state.log(f"Export error: {exc}")
                    self._json({"ok": False, "error": str(exc)}, code=500)
                finally:
                    try:
                        out_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                return

            if parsed.path == "/portal" or parsed.path.startswith("/portal/"):
                rel = parsed.path[len("/portal"):].lstrip("/") or "index.html"
                portal_root = (state.store.root / "portal").resolve()
                target = (portal_root / rel).resolve()
                if target.is_relative_to(portal_root) and target.is_file():
                    ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                    data = target.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", ctype)
                    self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if rel.endswith(".html") or "." not in Path(rel).name:
                    raw_state = _render_portal_state_html(
                        busy=state.busy,
                        logs=state.logs,
                        models_count=state.get_models_count(),
                        requested_path=parsed.path,
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(raw_state)))
                    self.end_headers()
                    self.wfile.write(raw_state)
                    return
                self.send_response(404)
                self.end_headers()
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
                        state.invalidate_cache()
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
                    state.invalidate_cache()
                    idx = generate_portal(state.store)
                    state.log(f"Imported '{meta.get('name', safe_name)}' into v1.1 Portal: {idx}")
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
                        if not dest.is_relative_to(staging_root):
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

                    state.invalidate_cache()
                    idx = generate_portal(state.store)
                    joined = ", ".join(imported_names)
                    state.log(f"Imported '{joined}' into v1.1 Portal: {idx}")
                    self._json({"ok": True, "model_name": joined, "output": str(idx)})
                except Exception as exc:
                    state.log(f"Folder upload import error: {exc}")
                    self._json({"ok": False, "error": str(exc)})
                finally:
                    shutil.rmtree(staging_root, ignore_errors=True)
                return

            if parsed.path == "/api/reset-catalog":
                with state._op_lock:
                    if state.busy:
                        self._json({"ok": False, "error": "Cannot reset catalog while a scan is running."})
                        return
                    state.store.clear()
                    state.invalidate_cache()
                    state.last_scan_error = ""
                    state.log("Catalog cleared (clean slate: 0 models).")
                self._json({"ok": True, "models_count": 0})
                return

            if parsed.path == "/api/publish-sharepoint":
                target_url = str(body.get("target_url") or "").strip()
                scope = str(body.get("scope") or "catalog").strip().lower()
                model_slug = str(body.get("model_slug") or "").strip()
                anon = bool(body.get("anonymous"))
                use_aspx = bool(body.get("aspx"))
                if not target_url:
                    self._json({"ok": False, "error": "Please provide a SharePoint Document Library URL."})
                    return
                exports_dir = (state.store.root / "_exports").resolve()
                exports_dir.mkdir(parents=True, exist_ok=True)
                ext = ".aspx" if use_aspx else ".html"
                if scope == "model" and model_slug:
                    safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in model_slug)[:80]
                    out_file = exports_dir / f"{safe_slug}_Documentation{ext}"
                else:
                    out_file = exports_dir / f"PBI_Documentation_Portal{ext}"
                try:
                    if scope == "model" and model_slug:
                        built = build_single_model_export(
                            state.store,
                            model_slug,
                            out_file,
                            anonymous=anon,
                            as_aspx=use_aspx,
                            log_fn=state.log,
                        )
                    else:
                        built = build_site_export(
                            state.store,
                            out_file,
                            anonymous=anon,
                            include_aspx=use_aspx,
                            log_fn=state.log,
                            single_file_only=True,
                        )
                        if use_aspx:
                            aspx_cand = built.with_suffix(".aspx")
                            if aspx_cand.exists():
                                built = aspx_cand
                    res = publish_file_to_sharepoint(built, target_url, log_fn=state.log)
                    self._json(res)
                except Exception as exc:
                    state.log(f"SharePoint publish failed: {exc}")
                    self._json({"ok": False, "error": str(exc)})
                finally:
                    try:
                        out_file.unlink(missing_ok=True)
                        out_file.with_suffix(".aspx").unlink(missing_ok=True)
                    except Exception:
                        pass
                return

            if parsed.path == "/api/sign-out":
                state.auth.sign_out()
                state.log("Signed out from Power BI session.")
                self._json({"ok": True})
                return

            if parsed.path == "/api/cancel-auth":
                state.auth.cancel_pending()
                state.log("Sign-in cancelled by user.")
                self._json({"ok": True})
                return

            if parsed.path == "/api/connect":
                try:
                    req_mode = str(body.get("mode", "oauth") or "oauth").lower()
                    state.auth.get_token(force_refresh=True, mode_override=req_mode)
                    state.log(f"Connected successfully ({state.auth.status().get('principal') or state.auth.mode}).")
                    self._json({"ok": True, "status": state.auth.status()})
                except Exception as exc:
                    state.log(f"Sign-in failed: {exc}")
                    self._json({"ok": False, "error": str(exc)})
                return

            if parsed.path == "/api/workspaces":
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
                            "name": (g.get("name") or ""),
                            "sku": caps.get(g.get("capacityId", ""), "Dedicated" if g.get("isOnDedicatedCapacity") else "Pro"),
                        }
                        for g in sorted(groups, key=lambda x: (x.get("name") or "").lower())
                    ]
                    state.log(f"Loaded {len(ws)} visible workspace(s).")
                    self._json({"ok": True, "workspaces": ws})
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)})
                return

            if parsed.path == "/api/scan":
                with state._op_lock:
                    if state.busy:
                        self._json({"ok": False, "error": "A scan is already running."})
                        return
                    state.busy = True
                    state.last_scan_error = ""

                def _worker() -> None:
                    try:
                        if body.get("clean_catalog"):
                            state.store.clear()
                            state.invalidate_cache()
                            state.log("Cleared previous catalog cache (clean slate enabled).")
                        client = PowerBiReadOnlyClient(state.auth)
                        scanner = WorkspaceScanner(client, state.store, log_fn=state.log)
                        ws_ids = body.get("workspace_ids") or None
                        refresh_flag = bool(body.get("refresh"))
                        follow_outside = bool(body.get("follow_outside", False))
                        scanner.scan_inventory(workspace_ids=ws_ids)
                        scanner.scan_model_definitions(
                            workspace_ids=ws_ids,
                            refresh=refresh_flag,
                            include_access=bool(body.get("include_access")),
                        )
                        if body.get("include_reports", True):
                            scanner.scan_report_definitions(
                                workspace_ids=ws_ids,
                                refresh=refresh_flag,
                                follow_shared_models=follow_outside,
                            )
                        if body.get("include_dataflows", True):
                            scanner.scan_dataflow_definitions(
                                workspace_ids=ws_ids,
                                refresh=refresh_flag,
                                follow_outside=follow_outside,
                            )
                        state.invalidate_cache()
                        idx = generate_portal(state.store, anonymous=bool(body.get("anonymous")))
                        state.log(f"Portal ready! Click 'Open Documentation Portal' ({idx})")
                    except Exception as exc:
                        state.last_scan_error = str(exc)
                        state.log(f"Scan error: {exc}")
                    finally:
                        state.invalidate_cache()
                        state.busy = False

                threading.Thread(target=_worker, daemon=True).start()
                self._json({"ok": True})
                return

            if parsed.path == "/api/portal":
                try:
                    idx = generate_portal(state.store, anonymous=bool(body.get("anonymous")))
                    self._json({"ok": True, "index": str(idx)})
                except Exception as exc:
                    self._json({"ok": False, "error": str(exc)})
                return

            if parsed.path == "/api/import-local":
                p = Path(body.get("path", "")).expanduser()
                try:
                    meta = WorkspaceScanner.register_local_any(state.store, str(p))
                    state.invalidate_cache()
                    idx = generate_portal(state.store)
                    state.log(f"Imported '{meta.get('name', p.name)}' into v1.1 Portal: {idx}")
                    self._json({"ok": True, "model_name": meta.get("name", p.stem), "output": str(idx)})
                except Exception as exc:
                    state.log(f"Local import error: {exc}")
                    self._json({"ok": False, "error": str(exc)})
                return

            self._json({"ok": False, "error": f"Unknown API endpoint: {parsed.path}"}, code=404)

    httpd: http.server.ThreadingHTTPServer | None = None
    last_err: Exception | None = None
    candidates = [0] if port == 0 else [port + i for i in range(16)]
    for cand in candidates:
        try:
            httpd = _ExclusiveServer((host, cand), Handler)
            break
        except OSError as exc:
            last_err = exc
    if httpd is None:
        raise last_err or OSError(f"Could not bind Studio server near {host}:{port}")
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
