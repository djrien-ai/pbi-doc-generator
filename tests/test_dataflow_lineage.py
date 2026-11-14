"""
Dataflow Gen1 + End-to-End measure lineage tests.

Fixture: a two-layer dataflow chain feeding a semantic model.

  SQL Server (native SQL) --> [DF Staging] stg_Sales ----linked----> [DF Curated] FactSales --> model table Sales
  Excel workbook ----------> [DF Staging] stg_Targets                     ^ computed (merge) <-- DimDate (helper)
  SQL Server (table) ---------------------------------------------------------------------> model table Product
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pbi_catalog.dataflows import find_dataflow_refs, parse_dataflow_definition, split_m_section
from pbi_catalog.e2e_lineage import build_e2e_graph, render_measure_doc_markdown, trace_upstream
from pbi_catalog.mcp_server import CatalogMcpEngine
from pbi_catalog.portal import generate_portal
from pbi_catalog.scanner import WorkspaceScanner
from pbi_catalog.store import CatalogStore

WS = "11111111-1111-1111-1111-111111111111"
DF_STG = "22222222-2222-2222-2222-222222222222"
DF_CUR = "33333333-3333-3333-3333-333333333333"
DS = "44444444-4444-4444-4444-444444444444"

STAGING_DOC = (
    "section Section1;\r\n"
    'shared ServerName = "sql-prod-01.corp.local" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true];\r\n'
    "shared stg_Sales = let\r\n"
    '    Source = Sql.Database(ServerName, "SalesDW", [Query="SELECT s.OrderId, s.OrderDate, s.Amount, s.Qty; -- semicolon inside string#(lf)FROM dbo.FactSales s WHERE s.IsDeleted = 0"]),\r\n'
    '    #"Changed Type" = Table.TransformColumnTypes(Source, {{"Amount", type number}})\r\n'
    'in\r\n    #"Changed Type";\r\n'
    "// Targets maintained by finance\r\n"
    "shared stg_Targets = let\r\n"
    '    Source = Excel.Workbook(Web.Contents("https://corp.sharepoint.com/sites/fin/Shared Documents/Targets.xlsx"), null, true),\r\n'
    '    Targets_Sheet = Source{[Item="Targets",Kind="Sheet"]}[Data],\r\n'
    '    #"Promoted Headers" = Table.PromoteHeaders(Targets_Sheet)\r\n'
    'in\r\n    #"Promoted Headers";\r\n'
)

CURATED_DOC = (
    "section Section1;\r\n"
    "shared stg_Sales = let\r\n"
    "    Source = PowerPlatform.Dataflows(null),\r\n"
    '    Workspaces = Source{[Id="Workspaces"]}[Data],\r\n'
    f'    Workspace = Workspaces{{[workspaceId="{WS}"]}}[Data],\r\n'
    f'    Dataflow = Workspace{{[dataflowId="{DF_STG}"]}}[Data],\r\n'
    '    Sales_ = Dataflow{[entity="stg_Sales", version=""]}[Data]\r\n'
    "in\r\n    Sales_;\r\n"
    "shared DimDate = let\r\n"
    '    Source = List.Dates(#date(2020,1,1), 3650, #duration(1,0,0,0))\r\n'
    "in\r\n    Source;\r\n"
    '[Description = "Curated sales fact"]\r\n'
    "shared FactSales = let\r\n"
    '    Source = Table.NestedJoin(stg_Sales, {"OrderDate"}, DimDate, {"Date"}, "D", JoinKind.LeftOuter),\r\n'
    '    #"Filtered" = Table.SelectRows(Source, each [Amount] > 0)\r\n'
    "in\r\n    #\"Filtered\";\r\n"
)


def _df_def(name: str, doc: str, loaded: dict[str, bool]) -> dict:
    return {
        "name": name,
        "version": "1.0",
        "pbi:mashup": {
            "queriesMetadata": {k: {"queryId": f"id-{k}", "queryName": k, "loadEnabled": v} for k, v in loaded.items()},
            "document": doc,
        },
        "entities": [
            {"$type": "LocalEntity", "name": k, "attributes": [{"name": "Amount", "dataType": "double"}]} for k, v in loaded.items() if v
        ],
    }


TMDL = f"""// ===== definition/model.tmdl
model Model
\tculture: en-US

// ===== definition/tables/Sales.tmdl
table Sales
\tmeasure 'Total Sales' = SUM(Sales[Amount])
\t\tformatString: #,0
\tmeasure 'Total Cost' = SUMX(Sales, Sales[Qty] * RELATED(Product[Cost]))
\tmeasure 'Margin %' = DIVIDE([Total Sales] - [Total Cost], [Total Sales])
\t\tdisplayFolder: KPIs
\tmeasure 'Order Count' = COUNTROWS(Sales) // Sales[Ignored] in comment
\tcolumn Amount
\t\tdataType: double
\t\tsourceColumn: Amount
\tcolumn Qty
\t\tdataType: int64
\t\tsourceColumn: Qty
\tcolumn 'Line Margin' = Sales[Amount] - Sales[Qty] * RELATED(Product[Cost])
\t\tdataType: double
\tpartition Sales = m
\t\tmode: import
\t\tsource =
\t\t\t\tlet
\t\t\t\t    Source = PowerPlatform.Dataflows(null),
\t\t\t\t    Workspaces = Source{{[Id="Workspaces"]}}[Data],
\t\t\t\t    Workspace = Workspaces{{[workspaceId="{WS}"]}}[Data],
\t\t\t\t    Dataflow = Workspace{{[dataflowId="{DF_CUR}"]}}[Data],
\t\t\t\t    FactSales_ = Dataflow{{[entity="FactSales", version=""]}}[Data]
\t\t\t\tin
\t\t\t\t    FactSales_

// ===== definition/tables/Product.tmdl
table Product
\tmeasure 'Avg Line Margin' = AVERAGE(Sales[Line Margin])
\tcolumn Cost
\t\tdataType: double
\t\tsourceColumn: Cost
\tpartition Product = m
\t\tmode: import
\t\tsource =
\t\t\t\tlet
\t\t\t\t    Source = Sql.Database("sql-prod-01.corp.local", "SalesDW"),
\t\t\t\t    dbo_DimProduct = Source{{[Schema="dbo",Item="DimProduct"]}}[Data]
\t\t\t\tin
\t\t\t\t    dbo_DimProduct
"""


def _seed_store(tmp: Path) -> CatalogStore:
    store = CatalogStore(tmp / "catalog")
    state = store.load()
    state["workspaces"][WS] = {"id": WS, "name": "Finance BI", "type": "Workspace", "users": []}
    state["models"][DS] = {"id": DS, "name": "Sales Model", "workspace_id": WS, "workspace": "Finance BI", "definition_status": "ok"}
    for df_id, name in ((DF_STG, "DF Staging"), (DF_CUR, "DF Curated")):
        state["dataflows"][df_id] = {"id": df_id, "name": name, "workspace_id": WS, "workspace": "Finance BI", "definition_status": "ok"}
    store.save(state)
    store.write_tmdl_bundle("Sales Model", DS, {"x": ""})  # ensure dirs
    store.tmdl_path("Sales Model", DS).write_text(TMDL, encoding="utf-8")
    store.write_dataflow_definition(DF_STG, _df_def("DF Staging", STAGING_DOC, {"ServerName": False, "stg_Sales": True, "stg_Targets": True}))
    store.write_dataflow_definition(DF_CUR, _df_def("DF Curated", CURATED_DOC, {"stg_Sales": False, "DimDate": False, "FactSales": True}))
    return store


def test_split_section_and_classification():
    members = split_m_section(STAGING_DOC)
    assert [m["name"] for m in members] == ["ServerName", "stg_Sales", "stg_Targets"]
    assert "semicolon inside string" in members[1]["code"]  # ';' inside a string must not split
    assert members[2]["description"] == "Targets maintained by finance"

    cur = parse_dataflow_definition({"id": DF_CUR, "name": "DF Curated"}, _df_def("DF Curated", CURATED_DOC, {"stg_Sales": False, "DimDate": False, "FactSales": True}))
    roles = {q["name"]: q["role"] for q in cur["queries"]}
    assert roles == {"stg_Sales": "Linked query (staging)", "DimDate": "Staging / helper query", "FactSales": "Entity"}
    fact = next(q for q in cur["queries"] if q["name"] == "FactSales")
    assert sorted(fact["depends_on"]) == ["DimDate", "stg_Sales"] and fact["description"] == "Curated sales fact"

    stg = parse_dataflow_definition({"id": DF_STG}, _df_def("DF Staging", STAGING_DOC, {"ServerName": False, "stg_Sales": True, "stg_Targets": True}))
    sales = next(q for q in stg["queries"] if q["name"] == "stg_Sales")
    ep = sales["endpoints"][0]
    assert (ep["connector"], ep["label"], ep["server"], ep["database"]) == ("Sql.Database", "SQL Server / Azure SQL", "sql-prod-01.corp.local", "SalesDW")
    assert "FROM dbo.FactSales" in sales["native_queries"][0]
    assert sales["parameters"] == ["ServerName"]

    refs = find_dataflow_refs(CURATED_DOC)
    assert refs == [{"workspace_id": WS, "dataflow_id": DF_STG, "entity": "stg_Sales"}]
    # Parameterised dataflow id resolves through the params dict
    assert find_dataflow_refs('PowerBI.Dataflows(null){[dataflowId=DfParam]}[Data]{[entity="X"]}[Data]', {"DfParam": DF_CUR})[0]["dataflow_id"] == DF_CUR


def test_end_to_end_graph_doc_and_portal():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        graph = build_e2e_graph(store)
        nodes = graph["nodes"]
        root = f"m:{DS}:Sales[Margin %]"
        tr = trace_upstream(graph, root)
        ids = set(tr["order"])

        # DAX chain
        assert {f"m:{DS}:Sales[Total Sales]", f"m:{DS}:Sales[Total Cost]"} <= ids
        # Tables (incl. RELATED -> Product) and the dataflow layers behind Sales
        assert {f"t:{DS}:Sales", f"t:{DS}:Product"} <= ids
        fact = f"q:{DF_CUR}:FactSales"
        stg_link = f"q:{DF_CUR}:stg_Sales"
        stg_src = f"q:{DF_STG}:stg_Sales"
        assert {fact, stg_link, stg_src, f"q:{DF_CUR}:DimDate"} <= ids
        assert tr["dataflow_layer"] == {DF_CUR: 1, DF_STG: 2}
        # Physical sources: native SQL in staging dataflow + DimProduct table for Product
        srcs = [nodes[i] for i in ids if nodes[i]["kind"] == "source"]
        sql_src = next(s for s in srcs if "FROM dbo.FactSales" in s.get("code", ""))
        assert sql_src["database"] == "SalesDW" and sql_src["name"] == "SQL: dbo.FactSales"
        assert "s.Qty; -- semicolon inside string\nFROM" in sql_src["code"]  # #(lf) decoded
        assert any(s.get("object") == "dbo/DimProduct" for s in srcs)
        # Excel target sheet is NOT part of this measure's lineage
        assert not any("Targets" in (s.get("name") or "") for s in srcs)
        # Comment reference ignored; COUNTROWS(Sales) is a whole-table reference
        oc = trace_upstream(graph, f"m:{DS}:Sales[Order Count]")
        assert f"t:{DS}:Sales" in oc["order"] and not any("Ignored" in "".join(e["labels"]) for e in oc["edges"])
        # Calculated column chain
        alm = trace_upstream(graph, f"m:{DS}:Product[Avg Line Margin]")
        assert f"c:{DS}:Sales[Line Margin]" in alm["order"] and f"t:{DS}:Product" in alm["order"]
        # Excel source reachable from the staging entity
        tgt = trace_upstream(graph, f"q:{DF_STG}:stg_Targets")
        xl = [nodes[i] for i in tgt["order"] if nodes[i]["kind"] == "source"]
        assert xl and xl[0]["source_type"] == "Excel" and xl[0]["object"] == "Targets" and "Targets.xlsx" in xl[0]["files"][0]

        md = render_measure_doc_markdown(graph, root)
        pos = [md.index(h) for h in ("## 1. Source Systems", "## 2. Dataflow Transformations", "## 3. Semantic Model Power Query", "## 5. DAX Calculation Chain")]
        assert pos == sorted(pos)
        assert "Dataflow (layer 2): DF Staging" in md and "Dataflow (layer 1): DF Curated" in md
        assert md.index("Dataflow (layer 2)") < md.index("Dataflow (layer 1)")
        assert md.index("[Total Sales]\n") < md.index("[Margin %] (documented measure)")
        assert "```sql" in md and "```mermaid" in md and "DIVIDE([Total Sales]" in md

        idx = generate_portal(store)
        e2e = idx.parent / "e2e_lineage.html"
        assert e2e.exists() and (idx.parent / "assets" / "e2e_graph.js").exists()
        assert "e2e_lineage.html" in idx.read_text(encoding="utf-8")
        model_pages = list((idx.parent / "models").glob("*.html"))
        # The explorer is tab 6 of the portal home page; model pages deep-link into it
        assert any("../index.html#e2e:node=" in p.read_text(encoding="utf-8") for p in model_pages)
        index_html = idx.read_text(encoding="utf-8")
        assert 'data-tab="tab-e2e"' in index_html and 'id="e2eFrame"' in index_html and 'href="e2e_lineage.html"' in index_html
        assert 'id="pdExportDocBtn"' in index_html and 'id="pdExportSiteBtn"' in index_html
        assert all('id="pdExportDocBtn"' in p.read_text(encoding="utf-8") for p in model_pages)
        meta = (idx.parent / "assets" / "portal_meta.js").read_text(encoding="utf-8")
        assert meta.startswith("window.PORTAL_META = ") and '"relationships"' in meta and (idx.parent / "assets" / "portal_export.js").exists()
        assert "</script" not in (idx.parent / "assets" / "e2e_graph.js").read_text(encoding="utf-8").lower()

        res = CatalogMcpEngine(store).call_tool("pbi_trace_measure_end_to_end", {"measure": "Margin %"})
        assert res["object_id"] == root and "DF Staging" in res["documentation_markdown"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unscanned_dataflow_becomes_placeholder():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        store.dataflow_path(DF_STG).unlink()
        graph = build_e2e_graph(store)
        node = graph["nodes"][f"q:{DF_STG}:stg_Sales"]
        assert node.get("external") is True and node["group"] == "DF Staging"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


class _FakeClient:
    """Mimics PowerBiReadOnlyClient for the dataflow scan step (cross-workspace upstream discovery)."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_dataflow_definition(self, ws, df):
        self.calls.append(df)
        if df == DF_CUR:
            return _df_def("DF Curated", CURATED_DOC, {"stg_Sales": False, "DimDate": False, "FactSales": True})
        if df == DF_STG:
            return _df_def("DF Staging", STAGING_DOC, {"ServerName": False, "stg_Sales": True, "stg_Targets": True})
        raise RuntimeError("HTTP 404")

    def get_dataflow_upstream(self, ws, df):
        return [{"targetDataflowId": DF_STG, "groupId": WS}] if df == DF_CUR else []

    def get_dataflow_datasources(self, ws, df):
        return []


def test_scanner_follows_upstream_dataflows():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        state = store.load()
        state["dataflows"].pop(DF_STG)  # staging dataflow lives in an unselected workspace
        for d in state["dataflows"].values():
            d["definition_status"] = "pending"
        store.save(state)
        store.dataflow_path(DF_STG).unlink()

        client = _FakeClient()
        WorkspaceScanner(client, store, log_fn=lambda _m: None).scan_dataflow_definitions()
        st = store.load()
        assert DF_STG in st["dataflows"] and st["dataflows"][DF_STG]["definition_status"] == "ok"
        assert st["dataflows"][DF_STG]["name"] == "DF Staging"
        assert sorted(client.calls) == sorted([DF_CUR, DF_STG])
        assert store.read_dataflow_definition(DF_STG)["name"] == "DF Staging"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_dataflow_scan_respects_workspace_selection():
    from pbi_catalog.store import set_scan_scope

    sel_ws = "88888888-8888-8888-8888-888888888888"
    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        state = store.load()
        state["dataflows"].pop(DF_STG)  # staging dataflow lives in WS, which is NOT selected
        state["dataflows"][DF_CUR].update({"workspace_id": sel_ws, "workspace": "Selected", "definition_status": "pending"})
        state["workspaces"][sel_ws] = {"id": sel_ws, "name": "Selected"}
        set_scan_scope(state, [sel_ws])
        store.save(state)
        store.dataflow_path(DF_STG).unlink()

        client = _FakeClient()
        WorkspaceScanner(client, store, log_fn=lambda _m: None).scan_dataflow_definitions(workspace_ids=[sel_ws])
        st = store.load()
        assert client.calls == [DF_CUR]  # nothing exported outside the selection
        assert st["dataflows"][DF_STG]["definition_status"] == "outside selected workspaces"
        graph = build_e2e_graph(store)
        assert all(d["workspace"] == "Selected" for d in graph["dataflows"])
        ph = graph["nodes"][f"q:{DF_STG}:stg_Sales"]
        assert ph["external"] and "outside selected workspaces" in ph["role"]
        assert not any(n.get("model_id") == DS for n in graph["nodes"].values())  # model in WS is out of scope

        # Opt-in: follow the reference; only that dataflow (not its workspace) joins the scope
        sc = WorkspaceScanner(client, store, log_fn=lambda _m: None)
        sc.follow_outside = True
        sc.scan_dataflow_definitions(workspace_ids=[sel_ws])
        st = store.load()
        assert DF_STG in client.calls and st["dataflows"][DF_STG]["definition_status"] == "ok"
        assert DF_STG in st["scope"]["extra_ids"]
        assert not build_e2e_graph(store)["nodes"][f"q:{DF_STG}:stg_Sales"].get("external")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_deleted_dataflow_reference_is_reported_not_exported():
    from pbi_catalog.store import set_scan_scope

    gone = "99999999-9999-9999-9999-999999999999"
    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        state = store.load()
        # The model still links to a dataflow that is no longer in its (selected) workspace's dataflow list
        state["dataset_dataflow_links"] = {DS: [{"dataflow_id": gone, "workspace_id": WS}]}
        set_scan_scope(state, [WS])
        store.save(state)
        client = _FakeClient()
        WorkspaceScanner(client, store, log_fn=lambda _m: None).scan_dataflow_definitions(workspace_ids=[WS])
        st = store.load()
        assert gone not in client.calls  # no export attempt -> no HTTP 400 "Unexpected dataflow error"
        status = st["dataflows"][gone]["definition_status"]
        assert status.startswith("missing:") and "Sales Model" in status
        index = generate_portal(store, output_dir=tmp / "portal").read_text(encoding="utf-8")
        assert "Broken reference: dataflow no longer exists" not in index or "Sales Model" in index
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_split_section_and_classification()
    test_end_to_end_graph_doc_and_portal()
    test_unscanned_dataflow_becomes_placeholder()
    test_scanner_follows_upstream_dataflows()
    print("ALL DATAFLOW LINEAGE TESTS PASSED")


def test_reference_entities_from_real_export_shape():
    """Real Gen1 exports list linked entities only as ReferenceEntity (no M); modelId = '<ws>/<dataflow>'."""
    from pbi_catalog.dataflows import definition_dataflow_refs, strip_data_locations

    etl = {
        "name": "ETL Sales",
        "pbi:mashup": {
            "queriesMetadata": {"FACT_Sales": {"queryId": "q1", "queryName": "FACT_Sales", "loadEnabled": True}},
            "document": "section Section1;\r\nshared FACT_Sales = let\r\n    Source = Table.Combine({SRC_SALES_CY, SRC_SALES_PY})\r\nin\r\n    Source;\r\n",
        },
        "entities": [
            {"$type": "LocalEntity", "name": "FACT_Sales", "attributes": [], "partitions": [{"name": "p", "location": "https://x.blob.core.windows.net/data.csv?sig=abc"}]},
            {"$type": "ReferenceEntity", "name": "SRC_SALES_CY", "source": "stg_Sales", "modelId": f"{WS}/{DF_STG}"},
            {"$type": "ReferenceEntity", "name": "SRC_SALES_PY", "source": "stg_Targets", "modelId": f"{WS}/{DF_STG}"},
        ],
        "referenceModels": [{"id": f"{WS}/{DF_STG}", "location": "https://x.blob.core.windows.net/model.json?snapshot=1"}],
    }
    pdf = parse_dataflow_definition({"id": "55555555-5555-5555-5555-555555555555", "name": "ETL Sales"}, etl)
    q = {x["name"]: x for x in pdf["queries"]}
    assert q["SRC_SALES_CY"]["role"] == "Linked entity"
    assert q["SRC_SALES_CY"]["dataflow_refs"] == [{"workspace_id": WS, "dataflow_id": DF_STG, "entity": "stg_Sales"}]
    assert sorted(q["FACT_Sales"]["depends_on"]) == ["SRC_SALES_CY", "SRC_SALES_PY"]
    assert q["FACT_Sales"]["role"] == "Computed entity"
    assert definition_dataflow_refs(etl) == [(WS, DF_STG)]
    stripped = strip_data_locations(json.loads(json.dumps(etl)))
    assert "blob.core" not in json.dumps(stripped)

    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        etl_id = "55555555-5555-5555-5555-555555555555"
        st = store.load()
        st["dataflows"][etl_id] = {"id": etl_id, "name": "ETL Sales", "workspace_id": WS, "workspace": "Finance BI", "definition_status": "ok"}
        store.save(st)
        store.write_dataflow_definition(etl_id, etl)
        graph = build_e2e_graph(store)
        tr = trace_upstream(graph, f"q:{etl_id}:FACT_Sales")
        assert f"q:{DF_STG}:stg_Sales" in tr["order"] and f"q:{DF_STG}:stg_Targets" in tr["order"]
        assert tr["dataflow_layer"][DF_STG] == tr["dataflow_layer"][etl_id] + 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_site_export_for_sharepoint():
    """'Export all data': static portal zip with .aspx twins, no Studio trace hook, README."""
    import zipfile

    from pbi_catalog.site_export import _to_aspx_links, build_site_export

    assert _to_aspx_links('<a href="models/a.html#m-x">x</a><a href="https://x.com/a.html">y</a>"href": "models/b.html"') == (
        '<a href="models/a.aspx#m-x">x</a><a href="https://x.com/a.html">y</a>"href": "models/b.aspx"'
    )
    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        z = build_site_export(store, tmp / "out" / "site.zip", anonymous=True, include_aspx=True)
        names = zipfile.ZipFile(z).namelist()
        root = names[0].split("/")[0]
        # Single-file version for the SharePoint Online viewer (sandboxed srcdoc): everything packed inside
        single = zipfile.ZipFile(z).read(f"{root}/PBI_Documentation_Portal_SharePoint.html").decode("utf-8")
        assert 'id="pbidoc-vfs"' in single and "DecompressionStream" in single and '"index.html":' in single
        assert '"assets/e2e_graph.js":' in single and '"models/' in single
        one = build_site_export(store, tmp / "out" / "portal.html", single_file_only=True)
        assert one.suffix == ".html" and one.read_text(encoding="utf-8").startswith("<!DOCTYPE html>")
        for page in ("index", "e2e_lineage", "README"):
            assert f"{root}/{page}.html" in names and f"{root}/{page}.aspx" in names
        assert any(n.startswith(f"{root}/models/") and n.endswith(".aspx") for n in names)
        zf = zipfile.ZipFile(z)
        assert "pbidocLog" not in zf.read(f"{root}/assets/portal_common.js").decode("utf-8")
        e2e_aspx = zf.read(f"{root}/e2e_lineage.aspx").decode("utf-8")
        assert 'href="index.aspx"' in e2e_aspx and "e2eExportSiteBtn" in e2e_aspx and "studio-only-link" in e2e_aspx
        assert not any(n.endswith(".part") for n in names)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


THIN_RPT = "66666666-6666-6666-6666-666666666666"
OTHER_WS = "77777777-7777-7777-7777-777777777777"


def _pbir_parts() -> dict:
    ext = {"name": "extension", "entities": [{"name": "Sales", "measures": [
        {"name": "Margin % LY Gap", "dataType": "Double", "expression": "[Margin %] - [Report Base]", "formatString": "0.0%"},
        {"name": "Report Base", "dataType": "Double", "expression": "CALCULATE([Total Sales], Product[Cost] > 0)"},
    ]}]}
    return {"definition/reportExtensions.json": json.dumps(ext),
            "definition.pbir": '{"datasetReference":{"byConnection":{"connectionString":"Data Source=x;semanticmodelid=' + DS + '"}}}'}


def test_report_measure_parsing_both_formats():
    from pbi_catalog.reports import parse_report_measures

    p = parse_report_measures(_pbir_parts())
    assert p["format"] == "PBIR" and p["dataset_ref"] == DS
    assert [m["name"] for m in p["measures"]] == ["Margin % LY Gap", "Report Base"] and p["measures"][0]["format"] == "0.0%"
    cfg = {"modelExtensions": [{"name": "extension", "entities": [{"name": "Sales", "extends": "Sales", "measures": [
        {"name": "Legacy M", "expression": "SUM(Sales[Amount]) * 2", "formatInformation": {"formatString": "#,0"}}]}]}]}
    lp = parse_report_measures({"report.json": json.dumps({"config": json.dumps(cfg), "sections": [{"visualContainers": []}]})})
    assert lp["format"] == "PBIR-Legacy" and lp["measures"][0]["name"] == "Legacy M" and lp["measures"][0]["format"] == "#,0"
    assert parse_report_measures({"report.json": json.dumps({"config": "{}"})})["measures"] == []


class _ReportClient(_FakeClient):
    def get_report_definition_parts(self, ws, rid):
        return _pbir_parts()

    def pbi_get_json(self, path):
        assert path == f"groups/{OTHER_WS}/datasets/{DS}"
        return {"id": DS, "name": "Sales Model"}

    def get_model_tmdl_files(self, ws, ds):
        assert ws == OTHER_WS
        files = {}
        for blk in TMDL.split("// ===== ")[1:]:
            path, _, body = blk.partition("\n")
            files[path.strip()] = body
        return files

    def pbi_get_list(self, path):
        return []


def test_thin_report_measures_trace_through_shared_model_and_dataflows():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        st = store.load()
        # Shared model lives in another workspace that was NOT scanned
        st["models"].pop(DS)
        st["reports"][THIN_RPT] = {"id": THIN_RPT, "name": "Exec KPIs", "workspace_id": WS, "workspace": "Finance BI",
                                   "dataset_id": DS, "dataset_workspace_id": OTHER_WS, "report_type": "PowerBIReport"}
        from pbi_catalog.store import set_scan_scope

        set_scan_scope(st, [WS])
        store.save(st)
        # Default: the workspace selection is respected - the shared model in OTHER_WS is not read
        WorkspaceScanner(_ReportClient(), store, log_fn=lambda _m: None).scan_report_definitions(workspace_ids=[WS])
        st = store.load()
        assert DS not in st["models"] and st["reports"][THIN_RPT]["report_measure_count"] == 2
        g0 = build_e2e_graph(store)
        assert "outside the selection" in g0["nodes"][f"m:{DS}:rpt:{THIN_RPT}:Sales[Margin % LY Gap]"]["note"]
        # Opt-in: follow the reference into the other workspace (only that model is added to the scope)
        sc = WorkspaceScanner(_ReportClient(), store, log_fn=lambda _m: None)
        sc.follow_outside = True
        sc.scan_report_definitions(workspace_ids=[WS])
        st = store.load()
        assert DS in st["scope"]["extra_ids"]
        assert st["reports"][THIN_RPT]["measures_status"] == "ok" and st["reports"][THIN_RPT]["report_measure_count"] == 2
        assert st["models"][DS]["discovered_via"] == "thin report" and st["models"][DS]["definition_status"] == "ok"

        graph = build_e2e_graph(store)
        rid = f"m:{DS}:rpt:{THIN_RPT}:Sales[Margin % LY Gap]"
        node = graph["nodes"][rid]
        assert node["report"] == "Exec KPIs" and node["group"] == "Exec KPIs" and "another workspace" in node["role"]
        tr = trace_upstream(graph, rid)
        ids = set(tr["order"])
        # report measure -> report measure -> model measures -> tables -> dataflow layers -> SQL
        assert f"m:{DS}:rpt:{THIN_RPT}:Sales[Report Base]" in ids
        assert {f"m:{DS}:Sales[Margin %]", f"m:{DS}:Sales[Total Sales]", f"t:{DS}:Product", f"q:{DF_STG}:stg_Sales"} <= ids
        assert any(graph["nodes"][i]["kind"] == "source" and "FactSales" in graph["nodes"][i].get("code", "") for i in ids)
        assert graph["reports"][0]["name"] == "Exec KPIs" and graph["reports"][0]["model_scanned"]
        md = render_measure_doc_markdown(graph, rid)
        assert "| Report (report-level measure) | Exec KPIs |" in md and "## 2. Dataflow Transformations" in md

        # The same info is browsable on the other portal pages
        from pbi_catalog.portal_xref import build_portal_xref

        xref = build_portal_xref(graph, store.load())
        assert xref["reports"][THIN_RPT]["measures"] and xref["models"][DS]["report_measures"]
        tbl = xref["models"][DS]["tables"]["Sales"]
        assert any(graph["nodes"][q]["group_id"] == DF_STG.lower() for q in tbl["dataflow_queries"]) and tbl["sources"]
        assert node["model_workspace"] == st["models"][DS]["workspace"]
        out = generate_portal(store, output_dir=tmp / "portal")
        index = out.read_text(encoding="utf-8")
        assert 'id="tab-dataflows"' in index and "data-df-row" in index and "Exec KPIs" in index
        assert f"grp=rpt%3A{THIN_RPT}" in index  # report-level measure count links into the explorer
        page = next((tmp / "portal" / "models").glob("*.html")).read_text(encoding="utf-8")
        assert "Report-level Measures in Thin Reports (2)" in page and "Margin % LY Gap" in page
        assert "Dataflows Feeding This Model" in page and "Upstream lineage" in page
        assert f"grp=model%3A{DS}" in page
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
