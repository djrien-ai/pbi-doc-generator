"""
Read-only Power BI & Microsoft Fabric REST API Client.

Features:
- Strict read-only guard: only GET calls and `POST .../getDefinition` metadata reads are allowed.
- Dual HTTP transport: Python stdlib `urllib` first, with automatic fallback to `curl` passing
  `Authorization: Bearer <token>` on stdin (`-H @-`) so corporate proxies work seamlessly and
  tokens never appear in OS process command-line arguments.
- Automatic 429 Retry-After handling and Fabric 202 Long-Running Operation (LRO) polling.
"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .auth import TokenProvider

PBI_BASE = "https://api.powerbi.com/v1.0/myorg/"
FABRIC_BASE = "https://api.fabric.microsoft.com/v1/"


@dataclass
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: str

    def json(self) -> dict:
        return json.loads(self.body) if self.body.strip() else {}


class PowerBiReadOnlyClient:
    """Strictly read-only client for Power BI REST API and Fabric Semantic Model / Report definitions."""

    def __init__(self, token_provider: TokenProvider, prefer_curl: bool = False, log_fn: Callable[[str], None] | None = None):
        self.token_provider = token_provider
        self.prefer_curl = prefer_curl
        self.log_fn = log_fn
        self._curl_bin = shutil.which("curl.exe") or shutil.which("curl")

    def _assert_readonly(self, method: str, url: str) -> None:
        m = method.upper()
        if m == "GET":
            return
        if m == "POST" and "/getdefinition" in url.lower():
            return
        raise PermissionError(f"Blocked non-read-only HTTP call: {method} {url}")

    def _request_urllib(self, method: str, url: str, token: str) -> HttpResponse:
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        data = None
        if method.upper() == "POST":
            headers["Content-Type"] = "application/json"
            data = b""
        req = urllib.request.Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                hdrs = {k.lower(): v for k, v in resp.headers.items()}
                body = resp.read().decode("utf-8", errors="replace")
                return HttpResponse(status=resp.status, headers=hdrs, body=body)
        except urllib.error.HTTPError as err:
            hdrs = {k.lower(): v for k, v in (err.headers.items() if err.headers else [])}
            body = err.read().decode("utf-8", errors="replace") if err.fp else ""
            return HttpResponse(status=err.code, headers=hdrs, body=body)

    def _request_curl(self, method: str, url: str, token: str) -> HttpResponse:
        if not self._curl_bin:
            raise RuntimeError("curl is not available for proxy fallback.")
        with tempfile.NamedTemporaryFile(delete=False, mode="w+", encoding="utf-8") as hdr_tmp:
            hdr_path = Path(hdr_tmp.name)
        try:
            args = [
                self._curl_bin,
                "-s",
                "-S",
                "--max-time",
                "120",
                "-H",
                "@-",
                "-D",
                str(hdr_path),
                "-w",
                "\n%{http_code}",
            ]
            if method.upper() == "POST":
                args += ["-X", "POST", "-H", "Content-Type: application/json", "--data", ""]
            args.append(url)
            res = subprocess.run(
                args,
                input=f"Authorization: Bearer {token}\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=135,
            )
            if res.returncode != 0:
                raise RuntimeError(f"curl transport error ({res.returncode}): {(res.stderr or res.stdout or '').strip()}")
            lines = (res.stdout or "").splitlines()
            status = int(lines[-1].strip()) if lines else 0
            body = "\n".join(lines[:-1])
            headers: dict[str, str] = {}
            if hdr_path.exists():
                for line in hdr_path.read_text(encoding="utf-8", errors="replace").splitlines():
                    if ":" in line:
                        k, _, v = line.partition(":")
                        headers[k.strip().lower()] = v.strip()
            return HttpResponse(status=status, headers=headers, body=body)
        finally:
            hdr_path.unlink(missing_ok=True)

    def request(self, method: str, url: str, max_retries: int = 4) -> HttpResponse:
        self._assert_readonly(method, url)
        for attempt in range(1, max_retries + 1):
            token = self.token_provider.get_token()
            try:
                if self.prefer_curl:
                    resp = self._request_curl(method, url, token)
                else:
                    try:
                        resp = self._request_urllib(method, url, token)
                    except urllib.error.URLError:
                        if not self._curl_bin:
                            raise
                        self.prefer_curl = True
                        if self.log_fn:
                            self.log_fn("Switched HTTP transport to system curl for corporate proxy compatibility.")
                        resp = self._request_curl(method, url, token)
            except Exception:
                if attempt == max_retries:
                    raise
                time.sleep(2 * attempt)
                continue

            if resp.status == 429 and attempt < max_retries:
                wait_sec = max(5, int(resp.headers.get("retry-after") or 30))
                if self.log_fn:
                    self.log_fn(f"API rate-limited (429), waiting {wait_sec}s...")
                time.sleep(wait_sec)
                continue
            return resp
        raise RuntimeError(f"Exhausted retries for {url}")

    def pbi_get_list(self, relative_path: str) -> list[dict]:
        resp = self.request("GET", PBI_BASE + relative_path.lstrip("/"))
        if resp.status != 200:
            snippet = (resp.body or "").replace("\n", " ")[:240]
            raise RuntimeError(f"HTTP {resp.status} on {relative_path}: {snippet}")
        return list(resp.json().get("value") or [])

    def pbi_get_json(self, relative_path: str) -> dict:
        resp = self.request("GET", PBI_BASE + relative_path.lstrip("/"))
        if resp.status != 200:
            snippet = (resp.body or "").replace("\n", " ")[:240]
            raise RuntimeError(f"HTTP {resp.status} on {relative_path}: {snippet}")
        return resp.json()

    def get_model_tmdl_files(self, workspace_id: str, dataset_id: str) -> dict[str, str]:
        """Fetch full semantic model definition in TMDL format via Fabric REST API (handles 200 & 202 LRO)."""
        url = f"{FABRIC_BASE}workspaces/{workspace_id}/semanticModels/{dataset_id}/getDefinition?format=TMDL"
        resp = self.request("POST", url)
        if resp.status == 200:
            definition = resp.json().get("definition") or {}
        elif resp.status == 202:
            location = resp.headers.get("location") or ""
            if not location:
                raise RuntimeError("HTTP 202 without Location header on getDefinition.")
            wait_sec = max(2, int(resp.headers.get("retry-after") or 2))
            deadline = time.time() + 300
            definition = {}
            while time.time() < deadline:
                time.sleep(wait_sec)
                poll = self.request("GET", location)
                state = poll.json()
                st = state.get("status")
                if st == "Succeeded":
                    res = self.request("GET", location.rstrip("/") + "/result")
                    if res.status != 200:
                        raise RuntimeError(f"HTTP {res.status} fetching LRO result.")
                    definition = res.json().get("definition") or {}
                    break
                if st == "Failed":
                    raise RuntimeError(f"Fabric getDefinition failed: {json.dumps(state.get('error') or {})}")
                if poll.headers.get("retry-after"):
                    wait_sec = max(1, int(poll.headers["retry-after"]))
            else:
                raise TimeoutError("Fabric getDefinition timed out after 5 minutes.")
        else:
            snippet = (resp.body or "").replace("\n", " ")[:260]
            raise RuntimeError(f"HTTP {resp.status} on getDefinition: {snippet}")

        files: dict[str, str] = {}
        for part in sorted(definition.get("parts") or [], key=lambda p: p.get("path", "")):
            path = part.get("path") or ""
            payload = part.get("payload") or ""
            if path and payload:
                files[path] = base64.b64decode(payload).decode("utf-8", errors="replace")
        return files
