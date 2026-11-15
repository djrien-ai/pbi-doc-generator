# Security & Privacy Policy

`pbi-doc-generator` is designed from the ground up for enterprise BI environments where metadata confidentiality and read-only Power BI guarantees are non-negotiable.

## Core Security Guarantees

1. **100% Local Execution by Default:** All metadata extraction, TMDL/Dataflow/PBIR parsing, HTML portal generation, and MCP queries run strictly on your local machine (`127.0.0.1`). Zero telemetry, analytics, or external CDN calls are made. *(Optional 1-click SharePoint Online upload only runs when you explicitly trigger it and enter your own SharePoint Document Library URL.)*
2. **Hardcoded Read-Only Power BI API Guard:** `PowerBiReadOnlyClient` (`pbi_catalog/api.py`) enforces a strict HTTP allowlist at the transport layer. Only `GET` metadata requests and the read-only Fabric `getDefinition` endpoint are permitted; `DELETE`, `PATCH`, `PUT`, and mutating `POST` endpoints against Power BI / Fabric are blocked in code.
3. **In-Memory Authentication Only:** OAuth access tokens live strictly in Python process RAM for the active session and are never written to disk, logs, or catalog files.
4. **Automatic Secret & Storage Redaction:** Connection passwords, SAS signatures, API keys, client secrets, bearer tokens, and internal Dataflow Gen1 storage URLs (`strip_data_locations`) are automatically masked or stripped in generated HTML documentation and MCP tool responses (`pbi_catalog/security.py`).

## Supported Versions

| Version | Supported |
| ------- | --------- |
| 1.1.x (Preview) | Yes |
| 1.0.x (Stable)  | Yes |
| < 1.0           | No  |

## Reporting a Vulnerability

If you discover a security or secret-masking issue, please report it responsibly via GitHub's [Private Vulnerability Reporting](https://github.com/djrien-ai/pbi-doc-generator/security/advisories/new) or open an issue without including sensitive credentials or proprietary tenant data.
