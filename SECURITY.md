# Security & Privacy Policy

`pbi-doc-generator` is designed from the ground up for enterprise BI environments where metadata confidentiality and read-only guarantees are non-negotiable.

## Core Security Guarantees

1. **100% Local Execution:** All metadata extraction, TMDL parsing, HTML portal generation, and MCP queries run strictly on your local machine (`127.0.0.1`). Zero telemetry, analytics, or external CDN calls are made.
2. **Hardcoded Read-Only API Guard:** `PowerBiReadOnlyClient` (`pbi_catalog/api.py`) enforces a strict HTTP allowlist at the transport layer. Only `GET` metadata requests and the read-only Fabric `getDefinition` endpoints (semantic models, reports) are permitted; `DELETE`, `PATCH`, `PUT`, and mutating `POST` endpoints are blocked in code.
3. **Structure Only, Never Data:** No DAX query, SQL query or dataflow refresh is ever executed. The catalog contains definitions only - DAX, Power Query M, native SQL text, relationships, dataflow `model.json` exports (data partition locations are stripped) and report layouts (pages, visuals, bound fields, filter / slicer selections, text). Report images and other static resources are discarded on download. `pbi-doc-generator diagnose --trace <dir>` checks a recorded session against the metadata-endpoint allowlist.
4. **Workspace Scope:** Only the workspaces selected for a scan are read and shown. Dataflows or shared models referenced from other workspaces are only read when *Follow references outside the selected workspaces* (`scan --follow-outside`) is enabled.
5. **Diagnostics Trace is Sensitive:** The optional trace (`--trace` / `PBI_TRACE_DIR`) records request URLs and full response bodies (model, report and dataflow definitions) for troubleshooting. Access tokens are never recorded, but treat the trace folder like the catalog itself and do not share or commit it.
6. **In-Memory Authentication Only:** Access tokens live strictly in Python process RAM for the active session and are never written to disk, logs, or catalog files.
7. **Automatic Secret Redaction:** Connection passwords, SAS signatures, API keys, client secrets, and bearer tokens are automatically masked in both generated HTML documentation and MCP tool responses (`pbi_catalog/security.py`).

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 1.0.x   | Yes       |
| < 1.0   | No        |

## Reporting a Vulnerability

If you discover a security or secret-masking issue, please report it responsibly via GitHub's [Private Vulnerability Reporting](https://github.com/djrien-ai/pbi-doc-generator/security/advisories/new) or open an issue without including sensitive credentials or proprietary tenant data.
