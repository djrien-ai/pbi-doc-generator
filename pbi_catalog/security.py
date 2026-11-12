"""
Security, secret redaction, and PII anonymization utilities.
Ensures API keys, tokens, SAS signatures, and passwords never leak into HTML pages or MCP responses.
"""

from __future__ import annotations

import html
import re

SECRET_KV_RE = re.compile(
    r'(?i)\b((?:api[_-]?)?key|token|access_token|refresh_token|apikey|password|passwd|pwd|secret|client_secret|sig|signature|accountkey)'
    r'(\s*[=:]\s*["\']?)([^&"\'\s;,)\]]+)'
)
BEARER_RE = re.compile(r'(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}')
CONN_PWD_RE = re.compile(r'(?i)(Pwd|Password)\s*=\s*([^;"\']+)')


def mask_secrets(value: str | None) -> str:
    """Redact credentials, tokens, and API keys from M code, DAX, URLs, and logs."""
    if not value:
        return ""
    text = str(value)
    text = SECRET_KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", text)
    text = BEARER_RE.sub(lambda m: f"{m.group(1)}***", text)
    text = CONN_PWD_RE.sub(lambda m: f"{m.group(1)}=***", text)
    return text


def esc(value: object) -> str:
    """HTML-escape after redacting any embedded secrets."""
    return html.escape(mask_secrets("" if value is None else str(value)))


def slugify(value: str) -> str:
    """Turn a model, table, or measure name into a clean URL/HTML anchor slug."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")
    return cleaned or "item"


def safe_filename(value: str) -> str:
    """Sanitize a string for cross-platform filesystem filenames."""
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", (value or "").strip())
    return cleaned[:120] or "unnamed"
