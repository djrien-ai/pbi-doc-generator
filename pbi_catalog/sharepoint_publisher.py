"""
Generic, vendor-neutral SharePoint Online Document Library Publisher.

Allows users running Localhost Studio on Windows / macOS to paste any SharePoint Online
Document Library folder URL (e.g. `https://<tenant>.sharepoint.com/sites/<Site>/Shared%20Documents/Folder`
or `.../Forms/AllItems.aspx?id=/sites/...`) and upload a standalone `.html` or `.aspx` documentation file
via the standard SharePoint REST API (`/_api/contextinfo` + `GetFolderByServerRelativePath/Files/add`).

Security & Privacy Guarantees:
- Zero hardcoded tenant or organization URLs.
- Strict HTTPS + `*.sharepoint.com` host allowlist (prevents SSRF or credential leakage).
- Session cookies (`FedAuth`, `rtFa`) are held strictly in memory for the single upload call and never written to disk.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def parse_sharepoint_target(raw_url: str) -> tuple[str, str, str | None]:
    """
    Parse any SharePoint Online folder, view, or file URL into:
    `(site_url, server_relative_folder_path, explicit_filename_or_None)`.

    Supported input shapes:
    - `https://contoso.sharepoint.com/sites/BI/Shared%20Documents/Docs`
    - `https://contoso.sharepoint.com/sites/BI/Shared Documents/Forms/AllItems.aspx?id=%2Fsites%2FBI%2FShared%20Documents%2FDocs`
    - `https://contoso.sharepoint.com/teams/DataPlatform/Shared%20Documents`
    - `https://contoso.sharepoint.com/sites/BI` (defaults to `<site>/Shared Documents`)
    """
    cleaned = (raw_url or "").strip()
    if not cleaned:
        raise ValueError("Please enter a SharePoint Online Document Library URL.")

    parsed = urllib.parse.urlparse(cleaned)
    host = (parsed.hostname or "").lower()
    if parsed.scheme.lower() != "https" or not host.endswith(".sharepoint.com"):
        raise ValueError("URL must be an HTTPS SharePoint Online address (`https://<tenant>.sharepoint.com/...`).")

    origin = f"https://{host}"
    qs = urllib.parse.parse_qs(parsed.query)

    # If user pasted an AllItems.aspx?id=/sites/... URL, use the `id` query parameter
    if "id" in qs and qs["id"] and qs["id"][0].startswith("/"):
        decoded_path = urllib.parse.unquote(qs["id"][0])
    else:
        decoded_path = urllib.parse.unquote(parsed.path or "/")

    parts = [p for p in decoded_path.split("/") if p]
    if not parts:
        raise ValueError("SharePoint URL must include a site or document library path (e.g. `/sites/TeamName/Shared Documents`).")

    # Identify site prefix: `/sites/<name>`, `/teams/<name>`, `/personal/<name>`, or root site `/`
    if parts[0].lower() in ("sites", "teams", "personal") and len(parts) >= 2:
        site_parts = parts[:2]
        rest = parts[2:]
    else:
        site_parts = []
        rest = parts[:]

    site_prefix = ("/" + "/".join(site_parts)) if site_parts else ""
    site_url = f"{origin}{site_prefix}"

    # Strip SharePoint system view suffixes (`/Forms/AllItems.aspx`, `/_layouts/...`)
    lower_rest = [r.lower() for r in rest]
    if "forms" in lower_rest:
        f_idx = lower_rest.index("forms")
        rest = rest[:f_idx]
    elif "_layouts" in lower_rest:
        l_idx = lower_rest.index("_layouts")
        rest = rest[:l_idx]

    explicit_file: str | None = None
    if rest and rest[-1].lower().endswith((".html", ".htm", ".aspx")):
        explicit_file = rest[-1]
        rest = rest[:-1]

    # If user pasted just the site root (`https://contoso.sharepoint.com/sites/BI`) or SitePages, default cleanly
    if not rest:
        rest = ["Shared Documents"]

    folder_rel = f"{site_prefix}/" + "/".join(rest)
    folder_rel = "/" + folder_rel.lstrip("/")
    return site_url, folder_rel, explicit_file


def _cleanup_sp_profile_locks(profile_dir: Path) -> None:
    if sys.platform == "win32":
        try:
            ps_cmd = (
                "$p = [regex]::Escape('" + str(profile_dir) + "'); "
                "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe' OR Name='chrome.exe'\" -ErrorAction SilentlyContinue | "
                "Where-Object { $_.CommandLine -match $p } | "
                "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            )
            subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, timeout=5, check=False)
        except Exception:
            pass
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        try:
            (profile_dir / lock_name).unlink(missing_ok=True)
        except OSError:
            pass


def _acquire_sharepoint_cookies_in_memory(site_url: str, log_fn=None) -> str:
    """
    Acquire SharePoint authentication cookies (`FedAuth` / `rtFa`) strictly in RAM
    using an isolated Playwright Edge/Chrome profile with Windows SSO.
    """
    log = log_fn or (lambda _m: None)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Direct SharePoint publishing requires `playwright` (`py -m pip install --user playwright`). "
            "Alternatively, click 'Download SharePoint File (.html)' and drag it into your SharePoint library."
        ) from exc

    profile_dir = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PbiDocGenerator" / "sp_browser_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_sp_profile_locks(profile_dir)

    host = (urllib.parse.urlparse(site_url).hostname or "").lower()

    def _try_session(headless: bool, wait_seconds: int) -> dict[str, str]:
        with sync_playwright() as p:
            ctx = None
            for ch in ("msedge", "chrome", None):
                try:
                    kwargs = {"user_data_dir": str(profile_dir), "headless": headless}
                    if ch:
                        kwargs["channel"] = ch
                    ctx = p.chromium.launch_persistent_context(**kwargs)
                    break
                except Exception:
                    continue
            if ctx is None:
                raise RuntimeError("Could not launch Microsoft Edge or Chrome for SharePoint authentication.")

            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                try:
                    page.goto(site_url, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass

                deadline = time.time() + wait_seconds
                while time.time() < deadline:
                    cur_url = (page.url or "").lower()
                    on_sp = host in cur_url and "login.microsoftonline.com" not in cur_url
                    cookies = ctx.cookies(site_url)
                    cmap = {c["name"]: c["value"] for c in cookies if c.get("name") and c.get("value")}
                    if on_sp and ("FedAuth" in cmap or "SPOIDCRL" in cmap or "rtFa" in cmap):
                        return cmap
                    time.sleep(0.8)
                return {}
            finally:
                try:
                    ctx.close()
                except Exception:
                    pass

    log(f"Checking existing Windows / Edge session for {site_url}...")
    cmap = _try_session(headless=True, wait_seconds=10)
    if not cmap:
        log("Opening Microsoft Edge sign-in window for SharePoint Online (up to 120s)...")
        _cleanup_sp_profile_locks(profile_dir)
        cmap = _try_session(headless=False, wait_seconds=120)

    if not cmap:
        raise RuntimeError(
            f"Could not obtain an authenticated SharePoint session for {site_url}. "
            "Verify you have Contribute access to the target SharePoint site, or download the `.html` file manually."
        )

    return "; ".join(f"{k}={v}" for k, v in cmap.items())


def _sp_post_json(url: str, cookie_header: str, extra_headers: dict[str, str] | None = None, body: bytes = b"") -> dict:
    headers = {
        "Accept": "application/json;odata=nometadata",
        "Cookie": cookie_header,
        "User-Agent": "PbiDocGenerator/1.1",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:320]
        except Exception:
            pass
        raise RuntimeError(f"SharePoint HTTP {exc.code} ({exc.reason}): {detail}") from exc


def publish_file_to_sharepoint(
    file_path: str | Path,
    target_url: str,
    filename: str | None = None,
    log_fn=None,
) -> dict[str, str]:
    """
    Upload `file_path` directly into the SharePoint Online Document Library folder specified by `target_url`.
    """
    log = log_fn or (lambda _m: None)
    src = Path(file_path)
    if not src.is_file():
        raise FileNotFoundError(f"Export file not found: {src}")

    site_url, folder_rel, url_filename = parse_sharepoint_target(target_url)
    final_name = filename or url_filename or src.name
    cookie_header = _acquire_sharepoint_cookies_in_memory(site_url, log_fn=log)

    # 1. Request FormDigestValue from `/_api/contextinfo`
    ctx_info = _sp_post_json(f"{site_url}/_api/contextinfo", cookie_header, {"Content-Length": "0"}, b"")
    digest = (
        ctx_info.get("FormDigestValue")
        or (ctx_info.get("d", {}).get("GetContextWebInformation", {}).get("FormDigestValue"))
        or ""
    )
    if not digest:
        raise RuntimeError("SharePoint `/_api/contextinfo` did not return a valid `FormDigestValue`.")

    # 2. Upload file via `GetFolderByServerRelativePath(decodedurl='...')/Files/add(url='...',overwrite=true)`
    safe_folder_q = urllib.parse.quote(folder_rel.replace("'", "''"), safe="/:")
    safe_file_q = urllib.parse.quote(final_name.replace("'", "''"), safe="._-")
    upload_ep = (
        f"{site_url}/_api/web/GetFolderByServerRelativePath(decodedurl='{safe_folder_q}')"
        f"/Files/add(url='{safe_file_q}',overwrite=true)"
    )

    payload = src.read_bytes()
    log(f"Uploading '{final_name}' ({len(payload) / 1024:.1f} KB) to SharePoint folder '{folder_rel}'...")
    res = _sp_post_json(
        upload_ep,
        cookie_header,
        {
            "X-RequestDigest": digest,
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(payload)),
        },
        payload,
    )

    srv_rel = res.get("ServerRelativeUrl") or f"{folder_rel.rstrip('/')}/{final_name}"
    parsed_site = urllib.parse.urlparse(site_url)
    web_url = f"https://{parsed_site.hostname}{urllib.parse.quote(srv_rel, safe='/:._-')}"
    log(f"Published successfully to SharePoint: {web_url}")
    return {
        "site_url": site_url,
        "folder": folder_rel,
        "filename": final_name,
        "web_url": web_url,
    }
