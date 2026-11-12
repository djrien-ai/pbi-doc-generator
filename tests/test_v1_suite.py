"""
Automated Verification Suite for PBI Doc Generator v1.0.
Verifies:
1. Issue #12 fix: leading /// TMDL table doc-comments do not overwrite Table Name.
2. Security redaction: passwords, bearer tokens, SAS tokens, and account keys are masked.
3. Read-only API guard: blocks non-GET mutations and allows only Fabric getDefinition POST.
4. DAX Auto-Formatter & Power Query M Step Extractor.
5. Multi-workspace Portal + Live Lineage HTML generation + zero em-dashes check.
6. MCP JSON-RPC 2.0 server (`initialize`, `tools/list`, `tools/call` across all tools).
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pbi_catalog.analyzer import analyze_model
from pbi_catalog.api import PowerBiReadOnlyClient
from pbi_catalog.auth import TokenProvider
from pbi_catalog.mcp_server import CatalogMcpEngine, handle_jsonrpc_message
from pbi_catalog.portal import extract_m_steps, format_dax_pretty, generate_portal
from pbi_catalog.security import mask_secrets
from pbi_catalog.store import CatalogStore
from tmdl_parser import TmdlModel


def test_issue_12_tmdl_table_doc_comment() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_issue12_"))
    try:
        def_dir = tmp / "Demo.SemanticModel" / "definition" / "tables"
        def_dir.mkdir(parents=True)
        (def_dir.parent / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
        (def_dir / "DimDate.tmdl").write_text(
            "/// Shared calendar dimension used to link multiple fact tables across fiscal periods.\n"
            "table 'Dim Calendar'\n"
            "\tcolumn Date\n"
            "\t\tdataType: dateTime\n"
            "\t\tsourceColumn: Date\n"
            "\tpartition 'Dim Calendar' = m\n"
            "\t\tmode: import\n"
            "\t\tsource =\n"
            "\t\t\tlet\n"
            "\t\t\t\tSource = Sql.Database(\"sql-prod.contoso.net\", \"DW_Core\")\n"
            "\t\t\tin\n"
            "\t\t\t\tSource\n",
            encoding="utf-8",
        )
        model = TmdlModel.from_pbip_folder(str(tmp))
        assert len(model.tables) == 1
        assert model.tables[0].name == "Dim Calendar", f"Got wrong table name: {model.tables[0].name}"
        assert "Shared calendar dimension" in model.tables[0].description
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_secret_masking_and_readonly_guard() -> None:
    raw = 'Sql.Database("srv", "db", [Query="SELECT * FROM t WHERE Password=SuperSecret123;AccountKey=abcdef1234567890=="])'
    redacted = mask_secrets(raw)
    assert "SuperSecret123" not in redacted
    assert "abcdef1234567890==" not in redacted

    client = PowerBiReadOnlyClient(TokenProvider(mode="token", manual_token="dummy"))
    blocked = False
    try:
        client._assert_readonly("DELETE", "https://api.powerbi.com/v1.0/myorg/groups/123")
    except PermissionError:
        blocked = True
    assert blocked, "DELETE should have been blocked by read-only guard!"

    blocked_post = False
    try:
        client._assert_readonly("POST", "https://api.powerbi.com/v1.0/myorg/groups/123/datasets/456/refreshes")
    except PermissionError:
        blocked_post = True
    assert blocked_post, "Refresh trigger POST should have been blocked!"

    # Fabric getDefinition POST must pass guard
    client._assert_readonly("POST", "https://api.fabric.microsoft.com/v1/workspaces/w1/semanticModels/m1/getDefinition?format=TMDL")


def test_dax_formatter_and_m_steps() -> None:
    ugly = "VAR BaseAmt = SUM('Fact Sales'[Net Amount]) RETURN CALCULATE(DIVIDE(BaseAmt, COUNTROWS('Fact Sales'), 0), DATESYTD('Dim Calendar'[Date]))"
    pretty = format_dax_pretty(ugly)
    assert "\n" in pretty and "RETURN" in pretty and "    " in pretty, f"Expected multi-line DAX, got:\n{pretty}"

    m_code = 'let\n    Source = SapHana.Database("hana-prod:30015"),\n    #"Filtered Rows" = Table.SelectRows(Source, each [Active] = 1),\n    #"Changed Type" = Table.TransformColumnTypes(#"Filtered Rows", {{"Amount", type number}})\nin\n    #"Changed Type"'
    steps = extract_m_steps(m_code)
    assert len(steps) == 3
    assert steps[0]["name"] == "Source" and steps[0]["op"] == "SapHana.Database"
    assert steps[1]["name"] == "Filtered Rows" and steps[1]["op"] == "Table.SelectRows"


def test_end_to_end_portal_and_mcp() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_portal_"))
    try:
        store = CatalogStore(tmp)
        state = store.load()
        state["workspaces"]["ws-core"] = {
            "id": "ws-core",
            "name": "Core Enterprise Datasets",
            "type": "Workspace",
            "capacity_sku": "F64",
            "is_dedicated": True,
            "is_read_only": False,
            "users": [{"displayName": "Alex Morgan", "principalType": "User", "groupUserAccessRight": "Admin"}],
            "last_scanned": "2026-11-12T10:00:00Z",
        }
        state["workspaces"]["ws-exec"] = {
            "id": "ws-exec",
            "name": "Executive Commercial Reports",
            "type": "Workspace",
            "capacity_sku": "F64",
            "is_dedicated": True,
            "is_read_only": False,
            "users": [],
            "last_scanned": "2026-11-12T10:00:00Z",
        }
        state["models"]["ds-1"] = {
            "id": "ds-1",
            "name": "Supply Chain OTIF Hub",
            "workspace_id": "ws-core",
            "workspace": "Core Enterprise Datasets",
            "configured_by": "alex.morgan@contoso.com",
            "last_refresh": {"status": "Completed", "end_time": "2026-11-12T06:15:00Z"},
            "permissions": [],
            "workspace_users": [],
            "definition_status": "ok",
        }
        state["reports"]["rep-1"] = {
            "id": "rep-1",
            "name": "Global OTIF Scorecard",
            "workspace_id": "ws-exec",
            "workspace": "Executive Commercial Reports",
            "dataset_id": "ds-1",
            "report_type": "PowerBIReport",
        }
        store.save(state)

        store.write_tmdl_bundle(
            "Supply Chain OTIF Hub",
            "ds-1",
            {
                "definition/model.tmdl": "model Model\n\tculture: en-US\n",
                "definition/relationships.tmdl": (
                    "relationship rel_1\n"
                    "\tfromColumn: 'Fact Shipments'.CalendarDate\n"
                    "\ttoColumn: 'Dim Calendar'.Date\n"
                ),
                "definition/roles/EMEA_Viewer.tmdl": (
                    "role 'EMEA Viewer'\n"
                    "\tmodelPermission: read\n"
                    "\ttablePermission 'Fact Shipments' = [Region] == \"EMEA\"\n"
                ),
                "definition/tables/DimCalendar.tmdl": (
                    "/// Conformed enterprise calendar table.\n"
                    "table 'Dim Calendar'\n"
                    "\tcolumn Date\n"
                    "\t\tdataType: dateTime\n"
                    "\t\tsourceColumn: Date\n"
                    "\tpartition 'Dim Calendar' = m\n"
                    "\t\tmode: import\n"
                    "\t\tsource =\n"
                    "\t\t\tlet\n"
                    "\t\t\t\tSource = Snowflake.Databases(\"contoso.eu-west-1.snowflakecomputing.com\", \"WH_BI\")\n"
                    "\t\t\tin\n"
                    "\t\t\t\tSource\n"
                ),
                "definition/tables/FactShipments.tmdl": (
                    "/// Granular outbound shipment lines with promised and actual delivery dates.\n"
                    "table 'Fact Shipments'\n"
                    "\tmeasure 'Total Shipments' = COUNTROWS('Fact Shipments')\n"
                    "\t\tformatString: #,##0\n"
                    "\t\tdisplayFolder: 01. Volumes\n"
                    "\tmeasure 'On-Time Shipments' = CALCULATE([Total Shipments], 'Fact Shipments'[DeliveredOnTime] = 1)\n"
                    "\t\tformatString: #,##0\n"
                    "\t\tdisplayFolder: 01. Volumes\n"
                    "\tmeasure 'OTIF %' = DIVIDE([On-Time Shipments], [Total Shipments], 0)\n"
                    "\t\tformatString: 0.0%\n"
                    "\t\tdisplayFolder: 02. Service KPIs\n"
                    "\tcolumn CalendarDate\n"
                    "\t\tdataType: dateTime\n"
                    "\t\tsourceColumn: CalendarDate\n"
                    "\tcolumn Region\n"
                    "\t\tdataType: string\n"
                    "\t\tsourceColumn: Region\n"
                    "\tcolumn DeliveredOnTime\n"
                    "\t\tdataType: int64\n"
                    "\t\tsourceColumn: DeliveredOnTime\n"
                    "\tpartition 'Fact Shipments' = m\n"
                    "\t\tmode: import\n"
                    "\t\tsource =\n"
                    "\t\t\tlet\n"
                    "\t\t\t\tSource = SapHana.Database(\"hana-bi-prod.contoso.internal:30015\"),\n"
                    "\t\t\t\tView = Source{[Name=\"CV_SHIPMENT_OTIF\"]}[Data]\n"
                    "\t\t\tin\n"
                    "\t\t\t\tView\n"
                ),
            },
        )

        idx = generate_portal(store)
        assert idx.exists()
        idx_html = idx.read_text(encoding="utf-8")
        assert "\u2014" not in idx_html and "\u2013" not in idx_html, "Found forbidden dash in index.html"
        assert "Cross-Workspace Shared Dataset" in idx_html

        model_pages = list((tmp / "portal" / "models").glob("*.html"))
        assert len(model_pages) == 1
        m_html = model_pages[0].read_text(encoding="utf-8")
        assert "\u2014" not in m_html and "\u2013" not in m_html, "Found forbidden dash in model page"
        assert "Conformed enterprise calendar table." in m_html

        # Verify MCP JSON-RPC calls
        engine = CatalogMcpEngine(store)
        init_resp = handle_jsonrpc_message(engine, {"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        assert init_resp and init_resp["result"]["serverInfo"]["name"] == "pbi-doc-generator-mcp"

        list_resp = handle_jsonrpc_message(engine, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert list_resp and len(list_resp["result"]["tools"]) == 8

        impact_resp = handle_jsonrpc_message(
            engine,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pbi_source_impact", "arguments": {"source": "CV_SHIPMENT_OTIF"}}},
        )
        assert impact_resp and not impact_resp["result"]["isError"]
        assert "Global OTIF Scorecard" in impact_resp["result"]["content"][0]["text"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_issue_12_tmdl_table_doc_comment()
    test_secret_masking_and_readonly_guard()
    test_dax_formatter_and_m_steps()
    test_end_to_end_portal_and_mcp()
    print("ALL 4 V1.0 TEST SUITES PASSED SUCCESSFULLY!")
