"""
Local diagnostics trace (opt-in, for testing).

Enabled by setting the `PBI_TRACE_DIR` environment variable (or `pbi-doc-generator studio --trace DIR`).
Writes, inside that folder:

- `http_trace.jsonl`   one line per Power BI / Fabric HTTP call: method, URL, status, duration, size,
                       retry attempt, transport, error, and the file holding the response body.
- `bodies/`            raw response bodies (JSON) exactly as received, so parsing issues can be reproduced.
- `studio.log`         every Studio log line (scan progress, warnings, errors).
- `browser.jsonl`      browser-side events sent by the portal / explorer / Studio pages
                       (JS errors, failed fetches, console errors, page loads, explorer selections, exports).

The Authorization header / access token is never written. Everything stays on the local disk.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

_LOCK = threading.Lock()
_SEQ = [0]


def trace_dir() -> Path | None:
    raw = os.environ.get("PBI_TRACE_DIR", "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser().resolve()
    (p / "bodies").mkdir(parents=True, exist_ok=True)
    return p


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S") + f".{int(time.time() * 1000) % 1000:03d}"


def _append(name: str, record: dict) -> None:
    d = trace_dir()
    if not d:
        return
    line = json.dumps(record, ensure_ascii=False)
    with _LOCK:
        with open(d / name, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def _endpoint_slug(url: str) -> str:
    path = re.sub(r"^https?://[^/]+/", "", url.split("?", 1)[0])
    path = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "{id}", path)
    return re.sub(r"[^A-Za-z0-9{}]+", "_", path).strip("_")[:90]


def endpoint_pattern(url: str) -> str:
    """URL with GUIDs replaced by {id} and query string dropped - used to group calls in reports."""
    path = re.sub(r"^https?://([^/]+)/", r"\1/", url.split("?", 1)[0])
    return re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "{id}", path)


def record_http(method: str, url: str, status: int | None, elapsed_ms: float, attempt: int, transport: str,
                body: str = "", headers: dict | None = None, error: str = "") -> None:
    d = trace_dir()
    if not d:
        return
    with _LOCK:
        _SEQ[0] += 1
        seq = _SEQ[0]
    body_file = ""
    if body:
        body_file = f"bodies/{time.strftime('%H%M%S')}_{seq:05d}_{_endpoint_slug(url)}.json"
        try:
            (d / body_file).write_text(body, encoding="utf-8")
        except OSError:
            body_file = ""
    safe_headers = {k: v for k, v in (headers or {}).items() if k.lower() in ("location", "retry-after", "content-type", "requestid", "x-ms-request-id", "x-ms-routing-hint")}
    _append(
        "http_trace.jsonl",
        {
            "ts": _now(),
            "seq": seq,
            "method": method.upper(),
            "url": url,
            "endpoint": endpoint_pattern(url),
            "status": status,
            "ms": round(elapsed_ms, 1),
            "attempt": attempt,
            "transport": transport,
            "bytes": len(body.encode("utf-8")) if body else 0,
            "body_file": body_file,
            "headers": safe_headers,
            "error": error,
        },
    )


def record_studio_log(line: str) -> None:
    d = trace_dir()
    if not d:
        return
    with _LOCK:
        with open(d / "studio.log", "a", encoding="utf-8") as fh:
            fh.write(line + "\n")


def record_browser_events(events: list[dict], user_agent: str = "") -> int:
    if not trace_dir():
        return 0
    n = 0
    for ev in events[:200]:
        if not isinstance(ev, dict):
            continue
        rec = {"ts": _now(), "ua": user_agent[:120]}
        for k, v in ev.items():
            rec[str(k)[:40]] = v if isinstance(v, (int, float, bool)) or v is None else str(v)[:4000]
        _append("browser.jsonl", rec)
        n += 1
    return n


# Browser-side capture. Injected into portal pages (portal_common.js) and the Studio page.
# Only active when the page is served by the local Studio (http://127.0.0.1 / localhost).
BROWSER_TRACE_JS = r"""
(function () {
  if (window.pbidocLog) return;
  var isStudio = (location.protocol === "http:" || location.protocol === "https:") &&
    (location.hostname === "127.0.0.1" || location.hostname === "localhost");
  var queue = [], timer = null;
  function flush() {
    timer = null;
    if (!queue.length) return;
    var batch = queue.splice(0, queue.length);
    try {
      var body = JSON.stringify({ events: batch });
      if (navigator.sendBeacon) navigator.sendBeacon("/api/client-log", new Blob([body], { type: "application/json" }));
      else fetch("/api/client-log", { method: "POST", headers: { "Content-Type": "application/json" }, body: body, keepalive: true });
    } catch (e) { /* never break the page */ }
  }
  window.pbidocLog = function (ev) {
    if (!isStudio) return;
    ev = ev || {};
    ev.page = location.pathname + location.hash;
    ev.t = Date.now();
    queue.push(ev);
    if (!timer) timer = setTimeout(flush, 400);
  };
  window.addEventListener("error", function (e) {
    if (e.target && e.target !== window && (e.target.src || e.target.href)) {
      window.pbidocLog({ type: "resource-error", src: e.target.src || e.target.href });
      return;
    }
    window.pbidocLog({ type: "js-error", message: e.message, source: e.filename, line: e.lineno, col: e.colno,
      stack: e.error && e.error.stack ? e.error.stack : "" });
  }, true);
  window.addEventListener("unhandledrejection", function (e) {
    var r = e.reason || {};
    window.pbidocLog({ type: "promise-rejection", message: r.message || String(r), stack: r.stack || "" });
  });
  ["error", "warn"].forEach(function (lvl) {
    var orig = console[lvl];
    console[lvl] = function () {
      try {
        window.pbidocLog({ type: "console-" + lvl, message: Array.prototype.map.call(arguments, function (a) {
          try { return typeof a === "string" ? a : (a && a.stack) || JSON.stringify(a); } catch (x) { return String(a); }
        }).join(" ") });
      } catch (x) { /* ignore */ }
      return orig.apply(console, arguments);
    };
  });
  if (window.fetch) {
    var of = window.fetch;
    window.fetch = function (input, init) {
      var url = typeof input === "string" ? input : (input && input.url) || "";
      return of.apply(this, arguments).then(function (resp) {
        if (!resp.ok && url.indexOf("/api/client-log") < 0) window.pbidocLog({ type: "fetch-failed", url: url, status: resp.status });
        return resp;
      }, function (err) {
        if (url.indexOf("/api/client-log") < 0) window.pbidocLog({ type: "fetch-error", url: url, message: String(err) });
        throw err;
      });
    };
  }
  window.addEventListener("DOMContentLoaded", function () {
    window.pbidocLog({ type: "page-load", title: document.title, width: window.innerWidth });
  });
  window.addEventListener("pagehide", flush);
})();
"""
