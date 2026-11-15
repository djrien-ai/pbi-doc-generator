"""
Automated Verification Suite for PBI Doc Generator v1.1.
Verifies:
1. Issue #12 fix: leading /// TMDL table doc-comments do not overwrite Table Name.
2. Security redaction: passwords, bearer tokens, SAS tokens, and account keys are masked.
3. Read-only API guard: blocks non-GET mutations and allows only Fabric getDefinition POST.
4. DAX Auto-Formatter & Power Query M Step Extractor.
5. Multi-workspace Portal + Live Lineage HTML generation + zero em-dashes check.
6. MCP JSON-RPC 2.0 server (`initialize`, `tools/list`, `tools/call` across all tools).
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import types
import urllib.request
from pathlib import Path

try:
    import pandas as pd  # type: ignore
except ImportError:
    class _MiniDF:
        def __init__(self, rows=None, columns=None):
            self._rows = list(rows or [])
            self.columns = list(columns or (list(self._rows[0].keys()) if self._rows else []))
            self.empty = len(self._rows) == 0

        def iterrows(self):
            return enumerate(self._rows)

    class _MiniPd:
        DataFrame = _MiniDF

    pd = _MiniPd()  # type: ignore

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pbi_catalog.analyzer import analyze_model
from pbi_catalog.api import PowerBiReadOnlyClient
from pbi_catalog.auth import TokenProvider
from pbi_catalog.cli import main as cli_main
from pbi_catalog.dataflows import parse_dataflow_definition, strip_data_locations
from pbi_catalog.e2e_lineage import build_e2e_graph, render_measure_doc_markdown, resolve_field_node_id
from pbi_catalog.export_bundle import (
    build_single_file,
    build_single_model_export,
    build_site_export,
    pack_single_model_from_portal,
)
from pbi_catalog.mcp_server import CatalogMcpEngine, handle_jsonrpc_message
from pbi_catalog.portal import extract_m_steps, format_dax_pretty, generate_portal
from pbi_catalog.pq_steps import interpret_query
from pbi_catalog.report_parser import (
    parse_dataflow_model_json,
    parse_report_definition_files,
    redact_report_layout_literals,
)
from pbi_catalog.scanner import WorkspaceScanner
from pbi_catalog.security import mask_secrets
from pbi_catalog.sharepoint_publisher import parse_sharepoint_target
from pbi_catalog.sql_format import format_sql
from pbi_catalog.store import CatalogStore
from pbi_catalog.web_ui import create_studio_server
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
        assert list_resp and len(list_resp["result"]["tools"]) == 10

        impact_resp = handle_jsonrpc_message(
            engine,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "pbi_source_impact", "arguments": {"source": "CV_SHIPMENT_OTIF"}}},
        )
        assert impact_resp and not impact_resp["result"]["isError"]
        assert "Global OTIF Scorecard" in impact_resp["result"]["content"][0]["text"]

        trace_resp = handle_jsonrpc_message(
            engine,
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "pbi_trace_measure_end_to_end", "arguments": {"measure": "OTIF %", "format": "markdown"}}},
        )
        assert trace_resp and not trace_resp["result"]["isError"]
        assert "CV_SHIPMENT_OTIF" in trace_resp["result"]["content"][0]["text"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_local_pbix_and_pbip_import_and_cli_file() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_local_import_"))
    try:
        # 1. Create a local .pbip + .SemanticModel + .Report structure
        proj_dir = tmp / "SalesDemo"
        def_dir = proj_dir / "SalesDemo.SemanticModel" / "definition" / "tables"
        rep_dir = proj_dir / "SalesDemo.Report"
        def_dir.mkdir(parents=True)
        rep_dir.mkdir(parents=True)
        pbip_file = proj_dir / "SalesDemo.pbip"
        pbip_file.write_text('{"version": "1.0"}', encoding="utf-8")
        (def_dir.parent / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
        (def_dir / "FactOrders.tmdl").write_text(
            "/// Order line fact table.\n"
            "table 'Fact Orders'\n"
            "\tmeasure 'Net Revenue' = SUM('Fact Orders'[Amount])\n"
            "\t\tformatString: $#,##0\n"
            "\tcolumn Amount\n"
            "\t\tdataType: decimal\n"
            "\t\tsourceColumn: Amount\n"
            "\tpartition 'Fact Orders' = m\n"
            "\t\tmode: import\n"
            "\t\tsource =\n"
            "\t\t\tlet\n"
            "\t\t\t\tSource = PostgreSQL.Database(\"pg-analytics.contoso.net\", \"sales_dw\")\n"
            "\t\t\tin\n"
            "\t\t\t\tSource\n",
            encoding="utf-8",
        )

        # Verify legacy single-file CLI (`pbi-doc-generator file <pbip>`) works cleanly
        standalone_out = tmp / "SalesDemo_Standalone.html"
        rc = cli_main(["file", str(pbip_file), "-o", str(standalone_out)])
        assert rc == 0 and standalone_out.is_file(), "CLI `file` subcommand failed on .pbip"

        # 2. Verify PBIX -> v1.0 TMDL bridge (`register_local_pbix_or_xlsx`) with mocked PBIXRay
        dummy_pbix = tmp / "Executive_Margin.pbix"
        dummy_pbix.write_bytes(b"PK\x03\x04dummy")

        class FakePBIXRay:
            def __init__(self, file_path: str):
                self.tables = ["Fact Margin", "Dim Product"]
                self.schema = pd.DataFrame(
                    [
                        {"TableName": "Fact Margin", "ColumnName": "ProductKey", "PandasDataType": "int64"},
                        {"TableName": "Fact Margin", "ColumnName": "GrossMargin", "PandasDataType": "float64"},
                        {"TableName": "Dim Product", "ColumnName": "ProductKey", "PandasDataType": "int64"},
                        {"TableName": "Dim Product", "ColumnName": "Category", "PandasDataType": "string"},
                    ]
                )
                self.power_query = pd.DataFrame(
                    [
                        {
                            "TableName": "Fact Margin",
                            "Expression": 'let\n    Source = Sql.Database("sql-dw.contoso.net", "FIN_MART"),\n    Tbl = Source{[Schema="dbo",Item="FACT_MARGIN"]}[Data]\nin\n    Tbl',
                        },
                        {
                            "TableName": "Dim Product",
                            "Expression": 'let\n    Source = Sql.Database("sql-dw.contoso.net", "FIN_MART"),\n    Tbl = Source{[Schema="dbo",Item="DIM_PRODUCT"]}[Data]\nin\n    Tbl',
                        },
                    ]
                )
                self.dax_measures = pd.DataFrame(
                    [
                        {
                            "TableName": "Fact Margin",
                            "Name": "Total Margin",
                            "Expression": "SUM('Fact Margin'[GrossMargin])",
                            "DisplayFolder": "01. Financials",
                            "Description": "Total gross margin in reporting currency.",
                        },
                        {
                            "TableName": "Fact Margin",
                            "Name": "Margin per Product",
                            "Expression": "DIVIDE([Total Margin], DISTINCTCOUNT('Dim Product'[ProductKey]), 0)",
                            "DisplayFolder": "02. Ratios",
                            "Description": "Average gross margin per distinct product.",
                        },
                    ]
                )
                self.dax_columns = pd.DataFrame(
                    [
                        {
                            "TableName": "Dim Product",
                            "ColumnName": "Category Upper",
                            "Expression": "UPPER('Dim Product'[Category])",
                        }
                    ]
                )
                self.dax_tables = pd.DataFrame(columns=["TableName", "Expression"])
                self.m_parameters = pd.DataFrame(
                    [
                        {
                            "ParameterName": "Environment",
                            "Description": "Target DW environment",
                            "Expression": '"PROD" meta [IsParameterQuery=true, Type="Text"]',
                        }
                    ]
                )
                self.relationships = pd.DataFrame(
                    [
                        {
                            "FromTableName": "Fact Margin",
                            "FromColumnName": "ProductKey",
                            "ToTableName": "Dim Product",
                            "ToColumnName": "ProductKey",
                            "IsActive": 1,
                            "Cardinality": "M:1",
                            "CrossFilteringBehavior": "Single",
                        }
                    ]
                )

        real_pbixray_mod = sys.modules.get("pbixray")
        fake_mod = types.ModuleType("pbixray")
        fake_mod.PBIXRay = FakePBIXRay  # type: ignore[attr-defined]
        sys.modules["pbixray"] = fake_mod
        try:
            cat_dir = tmp / "cat"
            store = CatalogStore(cat_dir)
            WorkspaceScanner.register_local_any(store, str(dummy_pbix))
            idx = generate_portal(store)
            assert idx.is_file()
            html_pages = list((cat_dir / "portal" / "models").glob("*.html"))
            assert len(html_pages) == 1
            page_txt = html_pages[0].read_text(encoding="utf-8")
            assert "Total Margin" in page_txt
            assert "Margin per Product" in page_txt
            assert "sql-dw.contoso.net" in page_txt
            assert "Executive_Margin (Embedded Report)" in page_txt
        finally:
            if real_pbixray_mod is not None:
                sys.modules["pbixray"] = real_pbixray_mod
            else:
                sys.modules.pop("pbixray", None)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_web_studio_http_endpoints() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_studio_http_"))
    try:
        proj_dir = tmp / "HttpModel.SemanticModel" / "definition" / "tables"
        proj_dir.mkdir(parents=True)
        (proj_dir.parent / "model.tmdl").write_text("model Model\n\tculture: en-US\n", encoding="utf-8")
        (proj_dir / "KPIs.tmdl").write_text(
            "table KPIs\n\tmeasure 'Order Count' = COUNTROWS(KPIs)\n\tcolumn Id\n\t\tdataType: int64\n\t\tsourceColumn: Id\n",
            encoding="utf-8",
        )

        cat_dir = tmp / "studio_cat"
        httpd, _ = create_studio_server(cat_dir, host="127.0.0.1", port=0)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/") as r:
                studio_html = r.read().decode("utf-8")
                assert r.status == 200 and "Sign in with Microsoft" in studio_html

            with urllib.request.urlopen(f"{base}/api/status") as r:
                st = json.loads(r.read().decode("utf-8"))
                assert "auth" in st and "logs" in st

            req = urllib.request.Request(
                f"{base}/api/import-local",
                data=json.dumps({"path": str(proj_dir.parent.parent)}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as r:
                imp = json.loads(r.read().decode("utf-8"))
                assert imp["ok"] is True and imp["model_name"] == "HttpModel"

            with urllib.request.urlopen(f"{base}/portal/index.html") as r:
                portal_html = r.read().decode("utf-8")
                assert r.status == 200 and "HttpModel" in portal_html

            with urllib.request.urlopen(f"{base}/api/export-site?format=single") as r:
                sp_html = r.read().decode("utf-8")
                assert r.status == 200 and "pbidoc-vfs" in sp_html and "DecompressionStream" in sp_html

            with urllib.request.urlopen(f"{base}/api/export-site?format=zip&aspx=1") as r:
                zip_bytes = r.read()
                assert r.status == 200 and zip_bytes[:2] == b"PK"
        finally:
            httpd.shutdown()
            httpd.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v11_report_xray_star_schema_dataflow_and_dax() -> None:
    # 1. Verify short multi-argument DAX expressions (< 68 chars) format across indented lines
    short_div = "DIVIDE([OTIF Lines], [Delivery Lines], 0)"
    pretty_div = format_dax_pretty(short_div)
    assert "\n    [OTIF Lines]," in pretty_div and "\n    [Delivery Lines]," in pretty_div, f"Expected multi-line DIVIDE, got:\n{pretty_div}"

    short_calc = "calculate([Total Sales], 'Dim Region'[Country] = \"BE\")"
    pretty_calc = format_dax_pretty(short_calc)
    assert pretty_calc.startswith("CALCULATE(\n    [Total Sales],"), f"Expected uppercase multi-line CALCULATE, got:\n{pretty_calc}"

    # 2. Verify Fabric getDefinition guard allows Reports, Dataflows & Workspace Items read-only calls
    client = PowerBiReadOnlyClient(TokenProvider(mode="token", manual_token="dummy"))
    client._assert_readonly("POST", "https://api.fabric.microsoft.com/v1/workspaces/w1/reports/r1/getDefinition")
    client._assert_readonly("POST", "https://api.fabric.microsoft.com/v1/workspaces/w1/dataflows/d1/getDefinition")
    client._assert_readonly("GET", "https://api.fabric.microsoft.com/v1/workspaces/w1/items")

    # 3. Verify PBIR report definition + reportExtensions.json + Dataflow model.json parsers
    pbir_files = {
        "definition/pages/pages.json": json.dumps({"pageOrder": ["PageExec"]}),
        "definition/pages/PageExec/page.json": json.dumps(
            {"name": "PageExec", "displayName": "Executive Summary", "width": 1280, "height": 720}
        ),
        "definition/pages/PageExec/visuals/v1/visual.json": json.dumps(
            {
                "name": "v1",
                "position": {"x": 20, "y": 30, "width": 300, "height": 120},
                "visual": {
                    "visualType": "card",
                    "query": {
                        "queryState": {
                            "Values": {
                                "projections": [
                                    {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": "Fact Sales"}}, "Property": "Margin %"}}},
                                    {"field": {"Column": {"Expression": {"SourceRef": {"Entity": "Fact Sales"}}, "Property": "MissingCol"}}},
                                ]
                            }
                        }
                    },
                },
            }
        ),
        "definition/reportExtensions.json": json.dumps(
            {
                "entities": [
                    {
                        "name": "Fact Sales",
                        "measures": [
                            {"name": "Local Target KPI", "expression": "DIVIDE([Net Sales], 100, 0)", "formatString": "0.0%"}
                        ],
                    }
                ]
            }
        ),
    }
    parsed_rep = parse_report_definition_files(pbir_files)
    assert parsed_rep["format"] == "PBIR"
    assert len(parsed_rep["pages"]) == 1
    assert len(parsed_rep["report_measures"]) == 1
    assert parsed_rep["report_measures"][0]["name"] == "Local Target KPI"

    df_parsed = parse_dataflow_model_json(
        {
            "name": "Harmonized MDM",
            "description": "Shared vendor & material dataflow",
            "entities": [{"name": "HarmonizedMaterials", "attributes": [{"name": "MatKey"}, {"name": "MatDesc"}]}],
            "pbi:mashup": {
                "document": 'section Section1;\nshared HarmonizedMaterials = let\n    Source = Sql.Database("dw-prod", "MDM"),\n    Tbl = Source{[Schema="dbo",Item="MAT"]}[Data]\nin\n    Tbl;\n'
            },
        }
    )
    assert len(df_parsed["entities"]) == 1
    assert df_parsed["entities"][0]["columns_count"] == 2
    assert df_parsed["entities"][0]["pq_steps"] == 2

    # 4. Verify Direct Lake + Dataflow Lineage + Broken Ref + Transitive Measure Usage + v1.1 Portal Widgets
    from scripts.build_demo_portal import build_demo

    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_v11_demo_"))
    try:
        idx = build_demo(tmp)
        idx_txt = idx.read_text(encoding="utf-8")
        assert "xrayRegistryData" in idx_txt
        assert "Dataflows &amp; Upstream Fabric Items" in idx_txt
        assert "Inspect Dataflow" in idx_txt

        otif_html = (tmp / "portal" / "models" / "enterprise-core-semantic-models-global-supply-chain-otif-core.html").read_text(encoding="utf-8")
        assert 'class="doc-topbar"' in otif_html
        assert 'class="model-switcher-select"' in otif_html
        assert 'class="star-shell"' in otif_html
        assert "Fact Inventory Snapshots" in otif_html
        assert "Direct Lake OneLake Binding" in otif_html
        assert "Upstream Power BI Dataflows Feeding This Model" in otif_html
        assert 'class="dax-folder-details" open' in otif_html
        assert 'data-dax-usage="unused"' in otif_html
        assert "principals-details" in otif_html

        legacy_html = (tmp / "portal" / "models" / "supply-chain-procurement-analytics-regional-vendor-spend-tracker.html").read_text(encoding="utf-8")
        assert "broken visual field reference" in legacy_html

        for html_file in (tmp / "portal").rglob("*.html"):
            content = html_file.read_text(encoding="utf-8")
            assert "\u2014" not in content and "\u2013" not in content, f"Forbidden dash in {html_file}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v11_unified_backend_e2e_sharepoint_and_privacy() -> None:
    import re
    import zipfile
    from scripts.build_demo_portal import build_demo

    # 1. SQL pretty-formatter + comment preservation + placeholder safety
    sql_one_liner = "SELECT MANDT, MATNR AS MaterialKey FROM sapsr3.MARA WHERE MANDT = '{{SapClient}}' AND LVORM IS NULL ORDER BY MATNR"
    formatted_sql = format_sql(sql_one_liner)
    assert "SELECT" in formatted_sql and "\nFROM" in formatted_sql and "{{SapClient}}" in formatted_sql
    hand_indented = "-- Keep author layout\nSELECT\n    a,\n    b\nFROM dbo.T"
    assert format_sql(hand_indented) == hand_indented

    # 2. PQ Step-by-step interpreter UTF-16 code-unit span accuracy (including surrogate pairs)
    m_with_emoji = 'let\n    Tag = "\U0001f680 Launch",\n    Cleaned = Table.SelectRows(Src, each [Tag] <> Tag)\nin\n    Cleaned'
    pq_steps = interpret_query(m_with_emoji)
    utf16_units = m_with_emoji.encode("utf-16-le")
    assert len(pq_steps) == 2
    st2 = pq_steps[1]
    sliced = utf16_units[st2["start"] * 2 : st2["end"] * 2].decode("utf-16-le")
    assert "Cleaned" in sliced and "Table.SelectRows" in sliced, f"UTF-16 slice mismatch: {sliced!r}"

    # 3. Dataflow Gen1 strip_data_locations + Gen2 Lakehouse destination parsing
    raw_df_model = {
        "name": "Secure DF",
        "pbi:dataLocations": [{"path": "https://adls.dfs.core.windows.net/secret?sig=SUPERSECRET"}],
        "entities": [
            {
                "name": "Orders",
                "partitions": [{"name": "Part1", "location": "https://blob.core.windows.net/p1?sv=2024&sig=SECRET2"}],
                "attributes": [{"name": "OrderId", "dataType": "int64"}],
            }
        ],
        "pbi:mashup": {"document": 'section Section1;\nshared Orders = let Source = Sql.Database("srv", "db") in Source;\n'},
    }
    stripped = strip_data_locations(raw_df_model)
    dumped_stripped = json.dumps(stripped)
    assert "SUPERSECRET" not in dumped_stripped and "SECRET2" not in dumped_stripped
    assert "pbi:mashup" in stripped

    gen2_parsed = parse_dataflow_definition(
        {"id": "df-g2", "name": "Gen2 Sales"},
        {
            "format": "FabricDataflowGen2",
            "mashup_pq": 'section Section1;\nshared fact_sales = let Source = Sql.Database("sql-prod", "ERP") in Source;\n',
            "query_metadata": {
                "queriesMetadata": {
                    "fact_sales": {
                        "loadEnabled": True,
                        "destinationSettings": {
                            "kind": "Lakehouse",
                            "itemName": "lh_gold",
                            "schemaName": "dbo",
                            "tableName": "fact_sales",
                        },
                    }
                }
            },
        },
    )
    assert gen2_parsed["generation"] == "Gen2"
    assert gen2_parsed["queries"][0]["destination"]["table"] == "fact_sales"
    assert gen2_parsed["queries"][0]["destination"]["item_name"] == "lh_gold"

    # 4. Full Demo Catalog: 4-tab UI invariant, L2->L1 Dataflows, E2E Measure Doc, CLI, SharePoint Export & Anonymous Scrubbing
    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_v11_unified_"))
    try:
        idx = build_demo(tmp)
        idx_html = idx.read_text(encoding="utf-8")

        # Strict 4-Tab Calm UI invariant & zero iframes on index.html
        tab_ids = re.findall(r'class="top-tab[^"]*"\s+data-tab="([^"]+)"', idx_html)
        assert tab_ids == ["tab-portfolio", "tab-workspaces", "tab-lineage", "tab-health"], f"Unexpected tabs: {tab_ids}"
        assert "<iframe" not in idx_html.lower(), "Forbidden <iframe> found in portal index.html"
        assert "Fabric Dataflow Gen2" in idx_html

        # Multi-hop L1 + L2 Dataflow lineage on OTIF model page
        otif_html = (tmp / "portal" / "models" / "enterprise-core-semantic-models-global-supply-chain-otif-core.html").read_text(encoding="utf-8")
        assert "Layer L1 Direct" in otif_html
        assert "Layer L2 Upstream" in otif_html
        assert "Measure Doc (.md)" in otif_html
        assert "Trace to SQL" in otif_html

        # Broken visual column must NOT falsely resolve to table node in E2E graph
        store = CatalogStore(tmp)
        mcp_engine = CatalogMcpEngine(store)
        analyses = mcp_engine._load_analyses()
        graph = build_e2e_graph(store, analyses)
        assert resolve_field_node_id(graph, "ds-legacy", "Fact Spend", "DeletedRebateColumn", "column") is None
        assert resolve_field_node_id(graph, "ds-otif", "Dim Material", "MaterialKey", "column") is not None

        # CLI `measure-doc` & `export-site`
        md_path = tmp / "DimMaterial_MeasureDoc.md"
        rc_md = cli_main(["measure-doc", "OTIF %", "--catalog", str(tmp), "-o", str(md_path)])
        assert rc_md == 0 and md_path.is_file()
        md_txt = md_path.read_text(encoding="utf-8")
        assert "OTIF %" in md_txt and "CV_SD_DELIVERY_OTIF" in md_txt
        assert "\u2014" not in md_txt and "\u2013" not in md_txt

        sp_single = tmp / "SharePoint_Single.html"
        rc_sp = cli_main(["export-site", "--catalog", str(tmp), "--format", "single", "-o", str(sp_single)])
        assert rc_sp == 0 and sp_single.is_file()
        sp_txt = sp_single.read_text(encoding="utf-8")
        assert "PBIDOC_SHELL" in sp_txt and "e2e_graph.js" in sp_txt

        zip_out = tmp / "Portal_Bundle.zip"
        build_site_export(store, zip_out, anonymous=True, include_aspx=True, single_file_only=False)
        with zipfile.ZipFile(zip_out, "r") as zf:
            names = zf.namelist()
            assert any(n.endswith("/index.html") for n in names)
            assert any(n.endswith("/index.aspx") for n in names)
            assert any(n.endswith("/PBI_Documentation_Portal_SharePoint.html") for n in names)

        # Anonymous report literal scrubbing check
        dirty_layout = {
            "format": "PBIR",
            "report_filters": ["Customer[Name] = 'TopSecretClient'"],
            "filter_items": [{"target": "Customer[Name]", "type": "Categorical", "condition": "= 'TopSecretClient'"}],
            "pages": [
                {
                    "id": "p1",
                    "name": "Secret Page",
                    "filters": ["Region[Code] = 'CONFIDENTIAL_REGION'"],
                    "filter_items": [{"target": "Region[Code]", "type": "Categorical", "condition": "= 'CONFIDENTIAL_REGION'"}],
                    "visuals": [
                        {
                            "id": "v1",
                            "type": "slicer",
                            "title": "Client Filter",
                            "selection": ["TopSecretClient"],
                            "text": "Private board commentary",
                            "filters": ["Customer[Tier] = 'VIPOnly'"],
                            "filter_items": [{"target": "Customer[Tier]", "type": "Categorical", "condition": "= 'VIPOnly'"}],
                            "fields": [],
                        }
                    ],
                }
            ],
        }
        clean_layout = redact_report_layout_literals(dirty_layout)
        clean_blob = json.dumps(clean_layout)
        assert "TopSecretClient" not in clean_blob
        assert "CONFIDENTIAL_REGION" not in clean_blob
        assert "Private board commentary" not in clean_blob
        assert "VIPOnly" not in clean_blob

        # Deleted upstream dataflow governance warning check
        del_analysis = analyze_model(
            {"id": "ds-del", "name": "Broken DF Model", "workspace": "WS", "workspace_id": "ws-1"},
            {
                "definition/model.tmdl": "model Model\n",
                "definition/tables/T1.tmdl": (
                    "table T1\n\tcolumn Id\n\t\tdataType: int64\n\t\tsourceColumn: Id\n"
                    "\tpartition T1 = m\n\t\tmode: import\n\t\tsource =\n"
                    "\t\t\tlet\n"
                    "\t\t\t\tSource = PowerPlatform.Dataflows(null),\n"
                    "\t\t\t\tWs = Source{[workspaceId=\"ws-1\"]}[Data],\n"
                    "\t\t\t\tDf = Ws{[dataflowId=\"df-missing-ghost\"]}[Data],\n"
                    "\t\t\t\tEnt = Df{[entity=\"GhostEntity\"]}[Data]\n"
                    "\t\t\tin\n"
                    "\t\t\t\tEnt\n"
                ),
            },
            dataflows={
                "df-missing-ghost": {
                    "id": "df-missing-ghost",
                    "name": "df-missing-ghost",
                    "workspace": "WS",
                    "definition_status": "missing: HTTP 404 deleted in service",
                }
            },
        )
        assert any("df-missing-ghost" in f["detail"] for f in del_analysis["findings"]), f"Expected missing DF warning, got: {del_analysis['findings']}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v11_clean_slate_single_model_export_and_sharepoint_publisher() -> None:
    from scripts.build_demo_portal import build_demo

    # 1. Verify SharePoint Document Library URL parser (direct folder, AllItems.aspx?id=..., .aspx file, non-SP rejection)
    sp1_site, sp1_folder, sp1_file = parse_sharepoint_target(
        "https://contoso.sharepoint.com/sites/BI_Hub/Shared%20Documents/Architecture"
    )
    assert sp1_site == "https://contoso.sharepoint.com/sites/BI_Hub"
    assert sp1_folder == "/sites/BI_Hub/Shared Documents/Architecture"
    assert sp1_file is None

    sp2_site, sp2_folder, sp2_file = parse_sharepoint_target(
        "https://contoso.sharepoint.com/sites/100200/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2F100200%2FShared%20Documents%2FDocs&viewid=abc"
    )
    assert sp2_site == "https://contoso.sharepoint.com/sites/100200"
    assert sp2_folder == "/sites/100200/Shared Documents/Docs"
    assert sp2_file is None

    sp3_site, sp3_folder, sp3_file = parse_sharepoint_target(
        "https://contoso.sharepoint.com/teams/DataOps/Shared%20Documents/MyPortal.html"
    )
    assert sp3_site == "https://contoso.sharepoint.com/teams/DataOps"
    assert sp3_folder == "/teams/DataOps/Shared Documents"
    assert sp3_file == "MyPortal.html"

    rejected = False
    try:
        parse_sharepoint_target("https://example.com/not-sharepoint/folder")
    except ValueError:
        rejected = True
    assert rejected, "Expected non-SharePoint URL to raise ValueError"

    # 2. Verify Single-Model Standalone Export (zero external assets + zero sibling model leakage) & CatalogStore.clear()
    tmp = Path(tempfile.mkdtemp(prefix="pbidoc_v11_single_model_"))
    try:
        idx = build_demo(tmp)
        assert idx.is_file()
        store = CatalogStore(tmp)

        slug = "enterprise-core-semantic-models-global-supply-chain-otif-core"
        out_single = tmp / "OTIF_Standalone.html"
        build_single_model_export(store, slug, out_single, anonymous=True)
        assert out_single.is_file()
        txt = out_single.read_text(encoding="utf-8")
        assert 'data-standalone-model="1"' in txt
        assert "../assets/portal.css" not in txt
        assert "../assets/e2e_graph.js" not in txt
        assert "Global Supply Chain &amp; OTIF Core" in txt or "Global Supply Chain & OTIF Core" in txt
        # Sibling models must NOT leak into scoped PBI_E2E_GRAPH
        assert "Group Working Capital & Margin" not in txt
        assert "clara.vance@northwind-global.example" not in txt, "Anonymous single-model export leaked owner email!"
        # Verify isolated PDF / Print engine safeguards (screen responsive breakpoint must never fire on A4 print)
        assert "@media screen and (max-width: 1100px)" in txt
        assert "@media (max-width: 1100px)" not in txt
        assert "print-only-star-stack" in txt and "buildSvgStarBlock" in txt
        assert "print-only-doc-banner" in txt
        assert "print-only-doc-banner" in idx.read_text(encoding="utf-8")

        # Verify Store.clear() resets everything cleanly
        store.clear()
        cleared = store.load()
        assert len(cleared.get("models", {})) == 0
        assert len(cleared.get("reports", {})) == 0
        assert not (tmp / "portal" / "index.html").exists()

        # 3. Verify Studio HTTP Empty State (themed HTML, never plain text), Single-Model HTTP Export & Reset API
        httpd, _ = create_studio_server(tmp, host="127.0.0.1", port=0)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with urllib.request.urlopen(f"{base}/portal/index.html") as r:
                empty_html = r.read().decode("utf-8")
                ctype = r.headers.get("Content-Type", "")
                assert r.status == 200 and "text/html" in ctype
                assert "No Documentation Portal Generated Yet" in empty_html
                assert "<!DOCTYPE html>" in empty_html

            # Re-populate demo into tmp and test single-model HTTP export + reset-catalog endpoint
            build_demo(tmp)
            with urllib.request.urlopen(f"{base}/api/export-site?format=single&model={slug}") as r:
                http_single = r.read().decode("utf-8")
                assert r.status == 200 and 'data-standalone-model="1"' in http_single

            req_reset = urllib.request.Request(
                f"{base}/api/reset-catalog",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_reset) as r:
                res_reset = json.loads(r.read().decode("utf-8"))
                assert res_reset["ok"] is True

            with urllib.request.urlopen(f"{base}/api/status") as r:
                st_after = json.loads(r.read().decode("utf-8"))
                assert st_after["models_count"] == 0
        finally:
            httpd.shutdown()
            httpd.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v11_studio_oauth_signin_cancel_and_error_resilience() -> None:
    """Verify Studio OAuth PKCE sign-in, non-blocking /api/status, instant Cancel, and clean Entra HTTP 400 error surfacing."""
    import base64
    import io
    import tempfile
    import threading
    import time
    import urllib.error
    import urllib.parse
    import urllib.request
    from unittest.mock import patch

    import pbi_catalog.auth as auth_mod
    from pbi_catalog.web_ui import create_studio_server

    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').decode("ascii").rstrip("=")
    payload = base64.urlsafe_b64encode(
        json.dumps({"upn": "architect@contoso.com", "exp": int(time.time()) + 3600}).encode("utf-8")
    ).decode("ascii").rstrip("=")
    fake_jwt = f"{header}.{payload}.sig"

    tmp = Path(tempfile.mkdtemp(prefix="pbi_v11_auth_"))
    try:
        httpd, _ = create_studio_server(tmp, host="127.0.0.1", port=0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            opened_urls: list[str] = []

            # 1. Start OAuth via /api/connect on a worker thread, verify /api/status never blocks, then Cancel
            connect_res: dict = {}

            def _call_connect() -> None:
                req = urllib.request.Request(
                    f"{base}/api/connect",
                    data=b'{"mode":"oauth"}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    connect_res.update(json.loads(r.read().decode("utf-8")))

            with patch.object(auth_mod.webbrowser, "open", side_effect=lambda u: (opened_urls.append(u), True)[1]):
                t_conn = threading.Thread(target=_call_connect, daemon=True)
                t_conn.start()
                deadline = time.time() + 5.0
                st = {}
                while time.time() < deadline:
                    with urllib.request.urlopen(f"{base}/api/status", timeout=2) as r:
                        st = json.loads(r.read().decode("utf-8"))
                    if st.get("auth", {}).get("pending_auth_url"):
                        break
                    time.sleep(0.05)

                assert st["auth"]["auth_in_progress"] is True
                assert "login.microsoftonline.com" in st["auth"]["pending_auth_url"]
                assert len(opened_urls) == 1

                # Click Cancel -> /api/connect must terminate cleanly within < 1s and clear auth_in_progress
                req_cancel = urllib.request.Request(
                    f"{base}/api/cancel-auth",
                    data=b"{}",
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req_cancel, timeout=2) as r:
                    assert json.loads(r.read().decode("utf-8"))["ok"] is True

                t_conn.join(timeout=3.0)
                assert not t_conn.is_alive()
                assert connect_res.get("ok") is False

                with urllib.request.urlopen(f"{base}/api/status", timeout=2) as r:
                    st_cancelled = json.loads(r.read().decode("utf-8"))
                assert st_cancelled["auth"]["auth_in_progress"] is False
                assert st_cancelled["auth"]["authenticated"] is False

            # 2. Complete full loopback OAuth redirect -> verify token exchange & principal
            opened_urls.clear()
            connect_res.clear()
            with (
                patch.object(auth_mod.webbrowser, "open", side_effect=lambda u: (opened_urls.append(u), True)[1]),
                patch.object(auth_mod, "_post_token_endpoint", return_value={"access_token": fake_jwt, "refresh_token": "ref123"}),
            ):
                t_conn2 = threading.Thread(target=_call_connect, daemon=True)
                t_conn2.start()
                deadline = time.time() + 5.0
                pending_url = ""
                while time.time() < deadline:
                    with urllib.request.urlopen(f"{base}/api/status", timeout=2) as r:
                        pending_url = json.loads(r.read().decode("utf-8")).get("auth", {}).get("pending_auth_url", "")
                    if pending_url:
                        break
                    time.sleep(0.05)

                assert pending_url
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(pending_url).query)
                redir = qs["redirect_uri"][0]
                state_nonce = qs["state"][0]
                cb_port = urllib.parse.urlparse(redir).port

                # Open 2 raw idle keep-alive/preconnect TCP sockets on cb_port (reproduces Chromium 60s keep-alive deadlock)
                import socket
                hung_socks = [socket.create_connection(("127.0.0.1", cb_port), timeout=5) for _ in range(2)]
                try:
                    t_cb0 = time.perf_counter()
                    with urllib.request.urlopen(f"{redir}/?code=mock_auth_code&state={urllib.parse.quote(state_nonce)}", timeout=5) as cb:
                        assert cb.status == 200
                        assert cb.headers.get("Connection", "").lower() == "close"
                        assert "Signed in with Microsoft" in cb.read().decode("utf-8")

                    t_conn2.join(timeout=2.0)
                    assert not t_conn2.is_alive(), "OAuth PKCE hung on browser keep-alive TCP socket!"
                    assert (time.perf_counter() - t_cb0) < 2.0
                finally:
                    for hs in hung_socks:
                        hs.close()

                assert connect_res.get("ok") is True
                assert connect_res["status"]["authenticated"] is True
                assert connect_res["status"]["principal"] == "architect@contoso.com"

            # 2b. Switch Account with open_browser=False (client popup mode) -> switches cleanly to second user
            payload2 = base64.urlsafe_b64encode(
                json.dumps({"upn": "lead@contoso.com", "exp": int(time.time()) + 3600}).encode("utf-8")
            ).decode("ascii").rstrip("=")
            fake_jwt2 = f"{header}.{payload2}.sig"
            opened_urls.clear()
            connect_res.clear()

            def _call_switch_popup() -> None:
                req = urllib.request.Request(
                    f"{base}/api/connect",
                    data=b'{"mode":"oauth","open_browser":false}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    connect_res.update(json.loads(r.read().decode("utf-8")))

            with (
                patch.object(auth_mod.webbrowser, "open", side_effect=lambda u, *a, **kw: (opened_urls.append(u), True)[1]),
                patch.object(auth_mod, "_post_token_endpoint", return_value={"access_token": fake_jwt2, "refresh_token": "ref456"}),
            ):
                t_sw = threading.Thread(target=_call_switch_popup, daemon=True)
                t_sw.start()
                deadline = time.time() + 5.0
                sw_url = ""
                while time.time() < deadline:
                    with urllib.request.urlopen(f"{base}/api/status", timeout=2) as r:
                        st_sw = json.loads(r.read().decode("utf-8"))["auth"]
                        if st_sw.get("pending_auth_url") and st_sw.get("attempt_seq", 0) >= 3:
                            sw_url = st_sw["pending_auth_url"]
                            break
                    time.sleep(0.03)
                assert sw_url
                assert len(opened_urls) == 0, "Backend webbrowser.open should not fire when client opened popup!"
                qs2 = urllib.parse.parse_qs(urllib.parse.urlparse(sw_url).query)
                with urllib.request.urlopen(f"{qs2['redirect_uri'][0]}/?code=mock_code_2&state={urllib.parse.quote(qs2['state'][0])}", timeout=5) as cb2:
                    assert cb2.status == 200
                t_sw.join(timeout=2.0)
                assert connect_res.get("ok") is True
                assert connect_res["status"]["principal"] == "lead@contoso.com"

            # 2c. Mid-scan HTTP 401 Unauthorized -> automatic silent token refresh & retry
            from pbi_catalog.api import HttpResponse
            tp_401 = auth_mod.TokenProvider(mode="oauth")
            tp_401._cached_token = fake_jwt
            tp_401._expires_at = time.time() + 3600
            tp_401._refresh_token = "ref123"
            ro_client = PowerBiReadOnlyClient(tp_401)
            seen_tokens: list[str] = []

            def _mock_req(method: str, url: str, token: str) -> HttpResponse:
                seen_tokens.append(token)
                if len(seen_tokens) == 1:
                    return HttpResponse(status=401, headers={}, body='{"error":"TokenExpired"}')
                return HttpResponse(status=200, headers={}, body='{"value":[{"id":"w1","name":"WS"}]}')

            with (
                patch.object(auth_mod, "_post_token_endpoint", return_value={"access_token": fake_jwt2, "refresh_token": "ref789"}),
                patch.object(ro_client, "_request_urllib", side_effect=_mock_req),
            ):
                ws_res = ro_client.pbi_get_list("groups?$top=10")
                assert len(ws_res) == 1 and ws_res[0]["id"] == "w1"
                assert seen_tokens == [fake_jwt, fake_jwt2]

            # 3. Verify _post_token_endpoint surfaces human-readable Entra JSON error_description on HTTP 400
            err_payload = json.dumps({"error": "invalid_grant", "error_description": "AADSTS500200: User account is a personal Microsoft account.\r\nTrace ID: 123"}).encode("utf-8")
            http_400 = urllib.error.HTTPError("https://login.microsoftonline.com/organizations/oauth2/v2.0/token", 400, "Bad Request", {}, io.BytesIO(err_payload))
            with patch.object(auth_mod.urllib.request, "urlopen", side_effect=http_400):
                try:
                    auth_mod._post_token_endpoint("https://login.microsoftonline.com/organizations/oauth2/v2.0/token", b"grant_type=authorization_code")
                    raise AssertionError("Expected RuntimeError on HTTP 400")
                except RuntimeError as exc:
                    assert "AADSTS500200" in str(exc)
                    assert "HTTP Error 400: Bad Request" not in str(exc)
        finally:
            httpd.shutdown()
            httpd.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v11_crash_resilience_and_fault_isolation() -> None:
    """Verify Studio HTTP, CatalogStore, Portal builder, MCP server, and CLI never crash on corrupt input or runtime errors."""
    import contextlib
    import io
    import tempfile
    import threading
    import urllib.error
    import urllib.request
    from unittest.mock import patch

    import pbi_catalog.portal as portal_mod
    from pbi_catalog.cli import main as cli_main
    from pbi_catalog.mcp_server import CatalogMcpEngine, handle_jsonrpc_message
    from pbi_catalog.store import CatalogStore
    from pbi_catalog.web_ui import create_studio_server
    from scripts.build_demo_portal import build_demo

    tmp = Path(tempfile.mkdtemp(prefix="pbi_v11_resilience_"))
    try:
        # 1. Corrupted catalog_state.json recovery
        store = CatalogStore(tmp)
        store.ensure_dirs()
        store.state_file.write_text("{TRUNCATED_CORRUPT_JSON!!!", encoding="utf-8")
        recovered = store.load()
        assert isinstance(recovered, dict) and recovered.get("models") == {}
        assert store.state_file.with_suffix(".corrupt.json").is_file()

        # 2. Studio HTTP server resilience against malformed JSON, bad binary payloads, and unexpected exceptions
        httpd, state_obj = create_studio_server(tmp, host="127.0.0.1", port=0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            # 2a. Broken JSON payload -> HTTP 400 with error_code ERR_BAD_JSON, server stays alive
            bad_req = urllib.request.Request(
                f"{base}/api/connect",
                data=b"{broken_json_payload",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(bad_req, timeout=5)
                raise AssertionError("Expected HTTP 400 on malformed JSON")
            except urllib.error.HTTPError as he:
                assert he.code == 400
                err_obj = json.loads(he.read().decode("utf-8"))
                assert err_obj["ok"] is False and err_obj["error_code"] == "ERR_BAD_JSON"

            # 2b. Invalid UTF-8 bytes -> HTTP 400 with error_code ERR_BAD_JSON
            bad_utf8 = urllib.request.Request(
                f"{base}/api/connect",
                data=b"\xff\xfe\xfd\x00",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                urllib.request.urlopen(bad_utf8, timeout=5)
                raise AssertionError("Expected HTTP 400 on invalid UTF-8")
            except urllib.error.HTTPError as he:
                assert he.code == 400
                err_obj = json.loads(he.read().decode("utf-8"))
                assert err_obj["ok"] is False and err_obj["error_code"] == "ERR_BAD_JSON"

            # 2c. Unexpected exception inside handler -> HTTP 500 with error_code + secret redaction, server stays alive!
            with patch.object(state_obj, "get_models_count", side_effect=RuntimeError("boom password=SuperSecretPassword123!")):
                try:
                    urllib.request.urlopen(f"{base}/api/status", timeout=5)
                    raise AssertionError("Expected HTTP 500 when handler raises RuntimeError")
                except urllib.error.HTTPError as he:
                    assert he.code == 500
                    err_obj = json.loads(he.read().decode("utf-8"))
                    assert err_obj["ok"] is False
                    assert err_obj["error_code"] == "ERR_RUNTIMEERROR"
                    assert "SuperSecretPassword123" not in err_obj["error"]

            # Immediately verify server is STILL healthy right after the 500 error!
            with urllib.request.urlopen(f"{base}/api/status", timeout=5) as r:
                assert r.status == 200
                st_ok = json.loads(r.read().decode("utf-8"))
                assert "models_count" in st_ok
        finally:
            httpd.shutdown()
            httpd.server_close()

        # 3. Per-model fault isolation in generate_portal(): 1 exploding model must NOT crash the rest of the catalog
        demo_dir = tmp / "fault_isolated_demo"
        build_demo(demo_dir)
        demo_store = CatalogStore(demo_dir)
        orig_analyze = portal_mod.analyze_model

        def _flaky_analyze(m_meta, bundle, **kwargs):
            if m_meta.get("id") == "ds-legacy":
                raise ValueError("Simulated corrupt TMDL partition in ds-legacy")
            return orig_analyze(m_meta, bundle, **kwargs)

        with patch.object(portal_mod, "analyze_model", side_effect=_flaky_analyze):
            idx_html = portal_mod.generate_portal(demo_store)
            assert idx_html.is_file()
            idx_txt = idx_html.read_text(encoding="utf-8")
            # Healthy sibling models still rendered cleanly!
            assert "Global Supply Chain" in idx_txt
            assert "Group Working Capital" in idx_txt
            assert "ERR_MODEL_ANALYZE" in idx_txt

        # 4. MCP JSON-RPC resilience against non-dict payloads & unknown tools
        mcp_eng = CatalogMcpEngine(demo_store)
        non_dict_resp = handle_jsonrpc_message(mcp_eng, [1, 2, 3])  # type: ignore[arg-type]
        assert non_dict_resp is not None and non_dict_resp["error"]["code"] == -32600
        bad_tool_resp = handle_jsonrpc_message(
            mcp_eng,
            {"jsonrpc": "2.0", "id": 99, "method": "tools/call", "params": {"name": "nonexistent_tool", "arguments": {}}},
        )
        assert bad_tool_resp is not None and bad_tool_resp["result"]["isError"] is True

        # 5. CLI top-level exception shield returns exit code 1 + clean stderr message (never raw traceback)
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf):
            rc = cli_main(["import-local", str(tmp / "nonexistent_missing_model_999.pbix"), "--catalog", str(tmp)])
        assert rc == 1
        err_out = err_buf.getvalue()
        assert "Error [" in err_out and "Traceback" not in err_out
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v11_legacy_v10_cache_detection_and_clean_upgrade() -> None:
    """Verify v1.0 catalog_state.json is detected, surfaces a clear upgrade notice, blocks stale v1.0 portal rendering, and archives cleanly to catalog_state.v1_0.bak.json."""
    tmp = Path(tempfile.mkdtemp(prefix="pbi_v10_upgrade_"))
    try:
        store = CatalogStore(tmp)
        store.ensure_dirs()
        # Simulate a real v1.0.0 catalog_state.json + stale v1.0 portal/index.html on disk
        v10_state = {
            "schema_version": "1.0",
            "updated_at": "2026-11-10T10:00:00Z",
            "workspaces": {
                "ws-1": {"id": "ws-1", "name": "Scanned WS"},
                "ws-ghost-99": {"id": "ws-ghost-99", "name": "Unscanned Tenant WS From v1.0"},
            },
            "models": {
                "ds-old": {"id": "ds-old", "name": "Legacy v1.0 Model", "workspace_id": "ws-1", "workspace": "Scanned WS", "definition_status": "ok"}
            },
            "reports": {"rep-old": {"id": "rep-old", "name": "Old Report", "dataset_id": "ds-old", "workspace_id": "ws-1"}},
            "dataflows": {},
            "errors": [],
        }
        store.state_file.write_text(json.dumps(v10_state), encoding="utf-8")
        (store.portal_dir / "index.html").write_text("<html>STALE_V10_PORTAL</html>", encoding="utf-8")

        leg = store.legacy_schema_info()
        assert leg["is_legacy"] is True and leg["schema_version"] == "1.0"
        assert leg["models_count"] == 1 and leg["workspaces_count"] == 2

        httpd, _ = create_studio_server(tmp, host="127.0.0.1", port=0)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        try:
            # 1. /api/status flags legacy_catalog.is_legacy == True and portal_ready == False
            with urllib.request.urlopen(f"{base}/api/status", timeout=5) as r:
                st_before = json.loads(r.read().decode("utf-8"))
                assert st_before["legacy_catalog"]["is_legacy"] is True
                assert st_before["portal_ready"] is False
                assert any("Upgrade Notice" in ln for ln in st_before["logs"])

            # 2. Visiting /portal/index.html does NOT serve STALE_V10_PORTAL; serves clean Upgrade Notice page
            with urllib.request.urlopen(f"{base}/portal/index.html", timeout=5) as r:
                p_html = r.read().decode("utf-8")
                assert "STALE_V10_PORTAL" not in p_html
                assert "Clean v1.1 Scan Required" in p_html

            # 2b. Bad path / unsupported extension upload must NOT prematurely wipe legacy v1.0 state
            bad_imp = urllib.request.Request(
                f"{base}/api/import-local",
                data=json.dumps({"path": str(tmp / "missing_file_xyz.pbip")}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(bad_imp, timeout=5) as r:
                assert json.loads(r.read().decode("utf-8"))["ok"] is False
            assert store.legacy_schema_info()["is_legacy"] is True

            # 3. Clicking 'Start Clean for v1.1' (/api/reset-catalog) EVEN WHILE another reader holds catalog_state.json open on Windows!
            open_reader = open(store.state_file, "r", encoding="utf-8")
            try:
                req = urllib.request.Request(
                    f"{base}/api/reset-catalog",
                    data=b'{"from_legacy":true}',
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=5) as r:
                    res = json.loads(r.read().decode("utf-8"))
                    assert res["ok"] is True

                bak = tmp / "catalog_state.v1_0.bak.json"
                assert bak.is_file(), "Expected v1.0 state backup file catalog_state.v1_0.bak.json"
                assert "Legacy v1.0 Model" in bak.read_text(encoding="utf-8")
                assert store.legacy_schema_info()["is_legacy"] is False
            finally:
                open_reader.close()

            with urllib.request.urlopen(f"{base}/api/status", timeout=5) as r:
                st_after = json.loads(r.read().decode("utf-8"))
                assert st_after["legacy_catalog"]["is_legacy"] is False
                assert st_after["models_count"] == 0
        finally:
            httpd.shutdown()
            httpd.server_close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_v11_parallel_scanner_lro_and_progress_telemetry() -> None:
    """Verify persistent HTTP/1.1 connection reuse, progressive LRO polling, parallel scanner, and Studio 5-stage progress bar."""
    import base64
    import http.server
    import time
    from unittest.mock import patch
    from pbi_catalog.web_ui import StudioState

    # 1. Persistent HTTP/1.1 socket reuse + Retry-After: 20 progressive LRO polling (< 3.5s instead of 20s)
    client_ports: set[int] = set()
    tmdl_b64 = base64.b64encode(b"model Model\n\tculture: en-US\n").decode("ascii")

    class _LroSrv(http.server.ThreadingHTTPServer):
        daemon_threads = True

    class _LroHandler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            return

        def _reply(self, code: int, body_obj: dict, hdrs: dict | None = None) -> None:
            raw = json.dumps(body_obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "keep-alive")
            for k, v in (hdrs or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self) -> None:
            client_ports.add(self.client_address[1])
            n = int(self.headers.get("Content-Length") or "0")
            if n:
                self.rfile.read(n)
            p = self.server.server_address[1]
            self._reply(202, {}, {"Location": f"http://127.0.0.1:{p}/v1/operations/op1", "Retry-After": "20"})

        def do_GET(self) -> None:
            client_ports.add(self.client_address[1])
            if self.path.endswith("/result"):
                self._reply(200, {"definition": {"parts": [{"path": "definition/model.tmdl", "payload": tmdl_b64}]}})
            else:
                self._reply(200, {"status": "Succeeded"})

    srv = _LroSrv(("127.0.0.1", 0), _LroHandler)
    srv_port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        hdr_b = base64.urlsafe_b64encode(b'{"alg":"none"}').decode().rstrip("=")
        pay_b = base64.urlsafe_b64encode(json.dumps({"upn": "u@contoso.com", "exp": int(time.time()) + 3600}).encode()).decode().rstrip("=")
        tp = TokenProvider(mode="token", manual_token=f"{hdr_b}.{pay_b}.sig")
        tp.set_manual_token(f"{hdr_b}.{pay_b}.sig")
        ro = PowerBiReadOnlyClient(tp)
        ro._proxies = {}
        t0 = time.perf_counter()
        with patch("pbi_catalog.api.FABRIC_BASE", f"http://127.0.0.1:{srv_port}/v1/"):
            res_files = ro.get_model_tmdl_files("ws-1", "ds-1")
        assert "definition/model.tmdl" in res_files
        assert (time.perf_counter() - t0) < 4.0, "Progressive LRO should not sleep 20s!"
        assert len(client_ports) == 1, f"Expected single persistent TCP client port across POST + LRO GETs, got {client_ports}"
    finally:
        srv.shutdown()
        srv.server_close()

    # 2. Parallel WorkspaceScanner + StudioState monotonic 5-stage progress telemetry
    tmp = Path(tempfile.mkdtemp(prefix="pbi_v11_prog_"))
    try:
        st_state = StudioState(tmp)
        st_state.start_scan_progress(workspaces_count=1, include_reports=True, include_dataflows=True)
        pct_history: list[float] = []

        def _track(evt: dict) -> None:
            st_state.update_scan_progress(evt)
            snap = st_state.get_scan_progress_snapshot()
            pct_history.append(float(snap["percent"]))

        tp2 = TokenProvider(mode="token", manual_token="dummy")
        ro2 = PowerBiReadOnlyClient(tp2)
        scanner = WorkspaceScanner(ro2, st_state.store, log_fn=st_state.log, progress_fn=_track)

        with (
            patch.object(
                ro2,
                "pbi_get_list",
                side_effect=lambda p: (
                    [{"id": "ws-1", "name": "Portfolio WS", "isOnDedicatedCapacity": True}]
                    if p.startswith("groups?")
                    else [{"id": f"ds-{i}", "name": f"Model {i}"} for i in range(1, 16)]
                    if p.endswith("/datasets")
                    else [{"id": f"rep-{i}", "name": f"Report {i}", "datasetId": "ds-1"} for i in range(1, 21)]
                    if p.endswith("/reports")
                    else [{"objectId": "df-1", "name": "DF 1", "generation": 1}]
                    if p.endswith("/dataflows")
                    else []
                ),
            ),
            patch.object(ro2, "get_fabric_workspace_items", return_value=[]),
            patch.object(ro2, "get_model_tmdl_files", return_value={"definition/model.tmdl": "model Model\n", "definition/tables/T.tmdl": "table T\n\tcolumn C\n\t\tdataType: string\n"}),
            patch.object(ro2, "get_report_definition_files", return_value={"definition/pages/P1/page.json": '{"name":"P1","displayName":"Overview"}'}),
            patch.object(ro2, "get_dataflow_definition", return_value={"name": "DF 1", "entities": [{"name": "E1"}]}),
        ):
            scanner.scan_inventory(workspace_ids=["ws-1"])
            scanner.scan_model_definitions(workspace_ids=["ws-1"], refresh=True, include_access=False)
            scanner.scan_report_definitions(workspace_ids=["ws-1"], refresh=True)
            scanner.scan_dataflow_definitions(workspace_ids=["ws-1"], refresh=True)
            generate_portal(
                st_state.store,
                progress_fn=lambda dn, tot, itm: _track({"phase": "portal", "done": dn, "total": tot, "item": itm}),
            )
            st_state.finish_scan_progress(ok=True)
            final_snap = st_state.get_scan_progress_snapshot()
            pct_history.append(float(final_snap["percent"]))

        assert pct_history == sorted(pct_history), f"Progress % was not monotonic: {pct_history}"
        assert final_snap["percent"] == 100.0
        assert final_snap["counts"] == {"workspaces": 1, "models": 15, "reports": 20, "dataflows": 1}
        assert all(sg["status"] == "done" for sg in final_snap["stages"])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_issue_12_tmdl_table_doc_comment()
    test_secret_masking_and_readonly_guard()
    test_dax_formatter_and_m_steps()
    test_end_to_end_portal_and_mcp()
    test_local_pbix_and_pbip_import_and_cli_file()
    test_web_studio_http_endpoints()
    test_v11_report_xray_star_schema_dataflow_and_dax()
    test_v11_unified_backend_e2e_sharepoint_and_privacy()
    test_v11_clean_slate_single_model_export_and_sharepoint_publisher()
    test_v11_studio_oauth_signin_cancel_and_error_resilience()
    test_v11_crash_resilience_and_fault_isolation()
    test_v11_legacy_v10_cache_detection_and_clean_upgrade()
    test_v11_parallel_scanner_lro_and_progress_telemetry()
    print("ALL 13 V1.1 TEST SUITES PASSED SUCCESSFULLY!")
