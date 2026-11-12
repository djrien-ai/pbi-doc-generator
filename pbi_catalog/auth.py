"""
Zero-Admin In-Memory Power BI & Fabric Authentication Provider.

Supports 5 authentication modes without ever writing tokens to disk:
1. 'oauth'     : Standard "Sign in with Microsoft" (OAuth 2.0 PKCE in default browser, zero extra packages).
2. 'browser'   : Power BI Web Sign-In via isolated Edge/Chrome window on app.powerbi.com (for locked-down tenants).
3. 'az'        : Azure CLI (`az account get-access-token --resource https://analysis.windows.net/powerbi/api`).
4. 'spn'       : Service Principal OAuth2 client_credentials (`PBI_TENANT_ID`, `PBI_CLIENT_ID`, `PBI_CLIENT_SECRET`).
5. 'token'     : Direct Bearer token from $PBI_TOKEN, clipboard, or advanced paste input.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# Standard Microsoft Public Client ID supporting http://localhost OAuth 2.0 PKCE without tenant admin registration
DEFAULT_PUBLIC_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
PBI_SCOPE = "https://analysis.windows.net/powerbi/api/.default offline_access"


def decode_jwt_exp(token: str) -> tuple[float, dict]:
    """Extract expiration epoch timestamp and claims from a JWT payload without external libraries."""
    clean = (token or "").strip()
    if clean.lower().startswith("bearer "):
        clean = clean[7:].strip()
    parts = clean.split(".")
    if len(parts) < 2:
        raise ValueError("Invalid JWT token format (expected header.payload.signature).")
    payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")).decode("utf-8", errors="replace"))
    exp = float(claims.get("exp") or (time.time() + 3300))
    return exp, claims


def clean_token(raw: str) -> str:
    tok = (raw or "").strip().strip('"').strip("'")
    if tok.lower().startswith("bearer "):
        tok = tok[7:].strip()
    return tok


def read_windows_clipboard() -> str:
    """Read plain text from clipboard on Windows/macOS without external packages."""
    if sys.platform == "win32":
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        return (res.stdout or "").strip()
    if sys.platform == "darwin":
        res = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=5)
        return (res.stdout or "").strip()
    return ""


def fetch_token_via_oauth_pkce(
    tenant: str = "organizations",
    client_id: str = DEFAULT_PUBLIC_CLIENT_ID,
    timeout_sec: int = 120,
    log_fn: Callable[[str], None] | None = None,
    cancel_event: threading.Event | None = None,
    on_auth_url: Callable[[str], None] | None = None,
    open_browser: bool = True,
) -> tuple[str, str]:
    """
    Standard "Sign in with Microsoft" OAuth 2.0 Authorization Code + PKCE flow.
    Opens the user's normal default browser to login.microsoftonline.com and receives the redirect on localhost.
    """
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    state_nonce = secrets.token_urlsafe(24)
    result_box: dict[str, str] = {}
    done_event = threading.Event()

    class _CallbackHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("state", [""])[0] != state_nonce:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Invalid OAuth state.")
                return
            if "error" in params:
                result_box["error"] = params.get("error_description", params["error"])[0]
                html = (
                    "<html><body style='font-family:Segoe UI,sans-serif;padding:48px;text-align:center;background:#fef2f2;color:#7f1d1d'>"
                    "<div style='max-width:480px;margin:0 auto;background:#fff;padding:32px;border-radius:14px;border:1px solid #fecaca'>"
                    "<h2 style='color:#b91c1c;margin-top:0'>Microsoft sign-in did not complete</h2>"
                    "<p style='color:#475569'>Return to PBI Doc Generator Studio for details or use 'Sign in via Power BI Web Window'.</p>"
                    "</div></body></html>"
                )
            else:
                result_box["code"] = params.get("code", [""])[0]
                html = (
                    "<html><body style='font-family:Segoe UI,sans-serif;padding:48px;text-align:center;background:#f8fafc;color:#0f172a'>"
                    "<div style='max-width:440px;margin:0 auto;background:#fff;padding:32px;border-radius:14px;border:1px solid #e2e8f0;box-shadow:0 4px 16px rgba(0,0,0,0.06)'>"
                    "<h2 style='color:#15803d;margin-top:0'>Signed in with Microsoft</h2>"
                    "<p style='color:#475569'>Your Power BI session is ready. You can close this browser tab and return to PBI Doc Generator Studio.</p>"
                    "</div><script>setTimeout(function(){window.close();},1200);</script></body></html>"
                )
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            done_event.set()

    httpd = http.server.HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = httpd.server_port
    redirect_uri = f"http://localhost:{port}"

    # Also bind IPv6 loopback [::1] on the same port so Windows browsers resolving localhost -> ::1 connect immediately
    httpd6 = None
    try:
        class _IPv6Server(http.server.HTTPServer):
            address_family = socket.AF_INET6

        httpd6 = _IPv6Server(("::1", port), _CallbackHandler)
        threading.Thread(target=httpd6.serve_forever, daemon=True).start()
    except Exception:
        httpd6 = None

    srv_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    srv_thread.start()

    auth_params = urllib.parse.urlencode(
        {
            "client_id": client_id or DEFAULT_PUBLIC_CLIENT_ID,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "response_mode": "query",
            "scope": PBI_SCOPE,
            "state": state_nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "select_account",
        }
    )
    auth_url = f"https://login.microsoftonline.com/{tenant or 'organizations'}/oauth2/v2.0/authorize?{auth_params}"
    if on_auth_url:
        on_auth_url(auth_url)
    if log_fn:
        log_fn("Opening Microsoft sign-in page in your default browser...")
    if open_browser:
        webbrowser.open(auth_url)

    deadline = time.time() + timeout_sec
    try:
        while time.time() < deadline:
            if done_event.wait(timeout=0.25):
                break
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Sign-in cancelled.")
        if not done_event.is_set():
            raise RuntimeError(
                "Microsoft sign-in timed out in the browser. If your corporate IT blocks standard OAuth apps, use 'Sign in via Power BI Web Window' right below."
            )
    finally:
        httpd.shutdown()
        httpd.server_close()
        if httpd6 is not None:
            try:
                httpd6.shutdown()
                httpd6.server_close()
            except Exception:
                pass

    if "error" in result_box:
        raise RuntimeError(f"Microsoft OAuth sign-in declined or restricted by tenant: {result_box['error']}")
    code = result_box.get("code") or ""
    if not code:
        raise RuntimeError("No authorization code received from Microsoft sign-in.")

    token_url = f"https://login.microsoftonline.com/{tenant or 'organizations'}/oauth2/v2.0/token"
    body = urllib.parse.urlencode(
        {
            "client_id": client_id or DEFAULT_PUBLIC_CLIENT_ID,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": verifier,
            "scope": PBI_SCOPE,
        }
    ).encode("utf-8")
    req = urllib.request.Request(token_url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    access_tok = clean_token(data.get("access_token") or "")
    refresh_tok = data.get("refresh_token") or ""
    if not access_tok:
        raise RuntimeError("Microsoft token endpoint did not return an access_token.")
    return access_tok, refresh_tok


def refresh_oauth_token(refresh_token: str, tenant: str = "organizations", client_id: str = DEFAULT_PUBLIC_CLIENT_ID) -> tuple[str, str]:
    token_url = f"https://login.microsoftonline.com/{tenant or 'organizations'}/oauth2/v2.0/token"
    body = urllib.parse.urlencode(
        {
            "client_id": client_id or DEFAULT_PUBLIC_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": PBI_SCOPE,
        }
    ).encode("utf-8")
    req = urllib.request.Request(token_url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return clean_token(data.get("access_token") or ""), (data.get("refresh_token") or refresh_token)


def fetch_token_via_browser(browser_channel: str = "msedge", headless_first: bool = True, log_fn: Callable[[str], None] | None = None) -> str:
    """
    Locked-Down Corporate Tenant Bridge: reads first-party session from app.powerbi.com
    using an isolated browser profile when standard OAuth public clients are blocked by IT policy.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Power BI Web Sign-In requires Playwright (`pip install playwright`). "
            "Try 'Sign in with Microsoft' first (works without Playwright)."
        ) from exc

    base_dir = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "PbiDocGenerator" / "browser_profile"
    base_dir.mkdir(parents=True, exist_ok=True)
    js_expr = "() => (typeof powerBIAccessToken === 'string' && powerBIAccessToken.startsWith('eyJ')) ? powerBIAccessToken : null"

    def _attempt(pw, headless: bool, timeout_sec: int) -> str | None:
        kwargs = {"headless": headless}
        if browser_channel in ("msedge", "chrome"):
            kwargs["channel"] = browser_channel
        if headless:
            kwargs["viewport"] = {"width": 1400, "height": 900}
        else:
            kwargs["no_viewport"] = True

        ctx = pw.chromium.launch_persistent_context(str(base_dir), **kwargs)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://app.powerbi.com/home", timeout=60000)
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                try:
                    tok = page.evaluate(js_expr)
                    if tok:
                        return tok
                except Exception:
                    pass
                time.sleep(1.0)
            return None
        finally:
            ctx.close()

    with sync_playwright() as pw:
        tok = None
        if headless_first:
            if log_fn:
                log_fn("Checking existing Power BI Web session...")
            try:
                tok = _attempt(pw, headless=True, timeout_sec=30)
            except Exception:
                tok = None
        if not tok:
            if log_fn:
                log_fn("Opening Power BI Web window for sign-in (closes automatically once Power BI Home loads)...")
            tok = _attempt(pw, headless=False, timeout_sec=300)

    if not tok:
        raise RuntimeError("Could not complete Power BI Web sign-in within timeout.")
    return clean_token(tok)


def find_az_cli_executable() -> str | None:
    """Locate the Azure CLI executable if installed on this machine."""
    found = shutil.which("az") or shutil.which("az.cmd")
    if found:
        return found
    if sys.platform == "win32":
        for candidate in (
            r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
            r"C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
        ):
            if os.path.isfile(candidate):
                return candidate
    return None


def fetch_token_via_az_cli() -> str:
    """Obtain Power BI token via Azure CLI (`az account get-access-token`)."""
    az_exe = find_az_cli_executable()
    if not az_exe:
        raise RuntimeError(
            "Azure CLI ('az') is not installed on this PC. "
            "Use 'Sign in via Power BI Web Window (Edge/Chrome)' instead - no extra software needed."
        )
    cmd = [az_exe, "account", "get-access-token", "--resource", "https://analysis.windows.net/powerbi/api", "--query", "accessToken", "-o", "tsv"]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
    if res.returncode != 0 or not (res.stdout or "").strip():
        raise RuntimeError(f"Azure CLI sign-in failed: {(res.stderr or res.stdout or '').strip()}")
    return clean_token(res.stdout)


def fetch_token_via_spn(tenant_id: str, client_id: str, client_secret: str) -> str:
    """Obtain Power BI / Fabric token via Service Principal OAuth2 client_credentials."""
    url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "https://analysis.windows.net/powerbi/api/.default",
        }
    ).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    tok = data.get("access_token")
    if not tok:
        raise RuntimeError("Service Principal response did not include an access_token.")
    return clean_token(tok)


@dataclass
class TokenProvider:
    """Manages an in-memory OAuth2 Bearer token and refreshes it automatically before expiry."""

    mode: str = "oauth"  # oauth | browser | token | clipboard | az | spn | auto
    manual_token: str = ""
    browser_channel: str = "msedge"
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""
    log_fn: Callable[[str], None] | None = None

    _cached_token: str = ""
    _refresh_token: str = ""
    _expires_at: float = 0.0
    _claims: dict | None = None
    _pending_cancel: threading.Event | None = None
    _pending_auth_url: str = ""
    auth_in_progress: bool = False
    last_error: str = ""

    def cancel_pending(self) -> None:
        if self._pending_cancel is not None:
            self._pending_cancel.set()
        self._pending_auth_url = ""
        self.auth_in_progress = False

    def set_manual_token(self, raw_token: str) -> dict:
        tok = clean_token(raw_token)
        exp, claims = decode_jwt_exp(tok)
        if exp <= time.time() + 15:
            raise ValueError("The supplied Power BI token has already expired.")
        self._cached_token = tok
        self._expires_at = exp
        self._claims = claims
        self.mode = "token"
        return self.status()

    def sign_out(self) -> None:
        self._cached_token = ""
        self._refresh_token = ""
        self._expires_at = 0.0
        self._claims = None

    def get_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._cached_token and time.time() < (self._expires_at - 120):
            return self._cached_token

        if self._refresh_token and not force_refresh:
            try:
                tok, new_ref = refresh_oauth_token(
                    self._refresh_token,
                    tenant=self.tenant_id or "organizations",
                    client_id=self.client_id or DEFAULT_PUBLIC_CLIENT_ID,
                )
                exp, claims = decode_jwt_exp(tok)
                self._cached_token = tok
                self._refresh_token = new_ref
                self._expires_at = exp
                self._claims = claims
                return self._cached_token
            except Exception:
                self._refresh_token = ""

        mode = (self.mode or "oauth").lower()
        tok = ""

        # Cancel any previous hanging browser listener before starting a new attempt
        if self._pending_cancel is not None:
            self._pending_cancel.set()
        cancel_ev = threading.Event()
        self._pending_cancel = cancel_ev
        self._pending_auth_url = ""
        self.auth_in_progress = True
        self.last_error = ""

        try:
            if mode == "token" or (mode == "auto" and (self.manual_token or os.environ.get("PBI_TOKEN"))):
                tok = clean_token(self.manual_token or os.environ.get("PBI_TOKEN", ""))
                if not tok:
                    raise RuntimeError("No manual token or PBI_TOKEN environment variable set.")
            elif mode == "clipboard":
                tok = clean_token(read_windows_clipboard())
                if not tok.startswith("eyJ"):
                    raise RuntimeError("Clipboard does not contain a valid session token.")
            elif mode == "spn" or (
                mode == "auto"
                and (self.client_secret or os.environ.get("PBI_CLIENT_SECRET"))
                and (self.client_id or os.environ.get("PBI_CLIENT_ID"))
            ):
                tok = fetch_token_via_spn(
                    self.tenant_id or os.environ["PBI_TENANT_ID"],
                    self.client_id or os.environ["PBI_CLIENT_ID"],
                    self.client_secret or os.environ["PBI_CLIENT_SECRET"],
                )
            elif mode == "az":
                tok = fetch_token_via_az_cli()
            elif mode == "oauth":
                def _set_url(u: str) -> None:
                    self._pending_auth_url = u

                tok, ref = fetch_token_via_oauth_pkce(
                    tenant=self.tenant_id or "organizations",
                    client_id=self.client_id or DEFAULT_PUBLIC_CLIENT_ID,
                    log_fn=self.log_fn,
                    cancel_event=cancel_ev,
                    on_auth_url=_set_url,
                )
                self._refresh_token = ref
            elif mode in ("browser", "auto"):
                tok = fetch_token_via_browser(browser_channel=self.browser_channel, log_fn=self.log_fn)
            else:
                raise ValueError(f"Unknown authentication mode: {self.mode}")

            exp, claims = decode_jwt_exp(tok)
            self._cached_token = tok
            self._expires_at = exp
            self._claims = claims
            return self._cached_token
        except Exception as exc:
            self.last_error = str(exc)
            raise
        finally:
            self.auth_in_progress = False
            self._pending_auth_url = ""

    def status(self) -> dict:
        remaining = max(0, int(self._expires_at - time.time())) if self._cached_token else 0
        claims = self._claims or {}
        user = claims.get("upn") or claims.get("unique_name") or claims.get("name") or claims.get("appid") or ""
        return {
            "authenticated": bool(self._cached_token and remaining > 0),
            "mode": self.mode,
            "seconds_remaining": remaining,
            "minutes_remaining": round(remaining / 60, 1),
            "principal": user,
            "auth_in_progress": self.auth_in_progress,
            "pending_auth_url": self._pending_auth_url,
            "last_error": self.last_error,
            "az_available": bool(find_az_cli_executable()),
        }
