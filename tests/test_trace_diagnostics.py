"""Diagnostics trace: HTTP recording (token never written), browser event endpoint, metadata-only verification."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pbi_catalog.api import HttpResponse, PowerBiReadOnlyClient
from pbi_catalog.diagnose import build_report
from pbi_catalog.store import CatalogStore
from pbi_catalog.web_ui import create_studio_server

SECRET = "eyJTOKEN-SHOULD-NEVER-BE-LOGGED-1234567890"


class _Tok:
    def get_token(self, force_refresh: bool = False) -> str:
        return SECRET


def test_trace_and_diagnose():
    tmp = Path(tempfile.mkdtemp())
    old = os.environ.get("PBI_TRACE_DIR")
    os.environ["PBI_TRACE_DIR"] = str(tmp / "trace")
    try:
        client = PowerBiReadOnlyClient(_Tok())
        responses = {
            "groups": HttpResponse(200, {"content-type": "application/json"}, json.dumps({"value": [{"id": "x", "name": "WS"}]})),
            "dataflows": HttpResponse(403, {}, '{"error":{"code":"Forbidden"}}'),
        }
        client._request_urllib = lambda m, u, t: responses["dataflows" if "dataflows" in u else "groups"]
        assert client.pbi_get_list("groups?$top=5000")[0]["name"] == "WS"
        try:
            client.get_dataflow_definition("11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222")
        except RuntimeError:
            pass

        tdir = tmp / "trace"
        lines = (tdir / "http_trace.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2 and json.loads(lines[1])["status"] == 403
        all_text = "".join(p.read_text(encoding="utf-8") for p in tdir.rglob("*") if p.is_file())
        assert SECRET not in all_text

        store = CatalogStore(tmp / "catalog")
        rep = build_report(store, tdir)
        assert "PASS - every call hit a known structure/schema endpoint" in rep and "403" in rep

        # A data endpoint must be flagged
        client._request_urllib = lambda m, u, t: HttpResponse(200, {}, '{"value":[]}')
        client.pbi_get_list("groups/11111111-1111-1111-1111-111111111111/datasets/22222222-2222-2222-2222-222222222222/tables/Sales/rows")
        rep = build_report(store, tdir)
        assert "FAIL - Calls that look like data access" in rep

        # Browser events endpoint
        httpd, _state = create_studio_server(tmp / "catalog", port=0)
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            body = json.dumps({"events": [{"type": "js-error", "message": "boom", "source": "e2e_explorer.js", "line": 3}]}).encode()
            req = urllib.request.Request(f"{base}/api/client-log", data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as r:
                assert json.loads(r.read())["recorded"] == 1
            with urllib.request.urlopen(base + "/") as r:
                assert "pbidocLog" in r.read().decode("utf-8")
        finally:
            httpd.shutdown()
            httpd.server_close()
        rep = build_report(store, tdir)
        assert "js-error" in rep and "boom" in rep
    finally:
        if old is None:
            os.environ.pop("PBI_TRACE_DIR", None)
        else:
            os.environ["PBI_TRACE_DIR"] = old
        shutil.rmtree(tmp, ignore_errors=True)


def test_state_save_survives_concurrent_reads():
    """Regression: WinError 5 when the scan saves catalog_state.json while the Studio status poll reads it."""
    from pbi_catalog.store import CatalogStore

    tmp = Path(tempfile.mkdtemp())
    try:
        store = CatalogStore(tmp / "cat")
        state = store.load()
        state["models"] = {f"m{i}": {"id": f"m{i}", "blob": "x" * 2000} for i in range(150)}
        stop = threading.Event()
        errors: list[Exception] = []

        def reader() -> None:
            while not stop.is_set():
                try:
                    store.load()
                except FileNotFoundError:
                    pass
                except Exception as exc:  # pragma: no cover - failure path
                    errors.append(exc)

        readers = [threading.Thread(target=reader) for _ in range(3)]
        for r in readers:
            r.start()
        try:
            for _ in range(150):
                store.save(state)
        finally:
            stop.set()
            for r in readers:
                r.join()
        assert not errors, errors[:3]
        assert len(store.load()["models"]) == 150
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
