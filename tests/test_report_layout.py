"""
Report Explorer: report layouts (pages, visuals, fields, filters, slicer selections) parsed from both report
definition formats, resolved to end-to-end lineage nodes, published as portal assets and served over MCP.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pbi_catalog.mcp_server import CatalogMcpEngine  # noqa: E402
from pbi_catalog.portal import generate_portal  # noqa: E402
from pbi_catalog.reports import LAYOUT_VERSION, parse_report_layout  # noqa: E402
from tests.test_dataflow_lineage import DS, WS, _seed_store  # noqa: E402

RPT = "abababab-0000-0000-0000-000000000001"


def _col(entity, prop, source=None):
    ref = {"Source": source} if source else {"Entity": entity}
    return {"Column": {"Expression": {"SourceRef": ref}, "Property": prop}}


def _meas(entity, prop, source=None):
    ref = {"Source": source} if source else {"Entity": entity}
    return {"Measure": {"Expression": {"SourceRef": ref}, "Property": prop}}


def _in_filter(entity, prop, values):
    return {"Version": 2, "From": [{"Name": "p", "Entity": entity, "Type": 0}],
            "Where": [{"Condition": {"In": {"Expressions": [_col(entity, prop, "p")], "Values": [[{"Literal": {"Value": v}}] for v in values]}}}]}


def legacy_parts() -> dict[str, str]:
    chart_cfg = {
        "name": "v_chart",
        "singleVisual": {
            "visualType": "clusteredColumnChart",
            "projections": {"Category": [{"queryRef": "Product.Cost"}], "Y": [{"queryRef": "Sales.Total Sales"}, {"queryRef": "Sum(Sales.Qty)"}]},
            "prototypeQuery": {
                "From": [{"Name": "s", "Entity": "Sales"}, {"Name": "p", "Entity": "Product"}],
                "Select": [
                    dict(_col("", "Cost", "p"), Name="Product.Cost"),
                    dict(_meas("", "Total Sales", "s"), Name="Sales.Total Sales"),
                    {"Aggregation": {"Expression": _col("", "Qty", "s"), "Function": 0}, "Name": "Sum(Sales.Qty)"},
                ],
            },
            "vcObjects": {"title": [{"properties": {"text": {"expr": {"Literal": {"Value": "'Sales by cost'"}}}}}]},
        },
    }
    slicer_cfg = {
        "name": "v_slicer",
        "singleVisual": {
            "visualType": "slicer",
            "projections": {"Values": [{"queryRef": "Product.Cost"}]},
            "prototypeQuery": {"From": [{"Name": "p", "Entity": "Product"}], "Select": [dict(_col("", "Cost", "p"), Name="Product.Cost")]},
            "objects": {"general": [{"properties": {"filter": {"filter": _in_filter("Product", "Cost", ["10L", "'High'"])}}}]},
        },
    }
    text_cfg = {"name": "v_text", "singleVisual": {"visualType": "textbox", "objects": {"general": [{"properties": {"paragraphs": [{"textRuns": [{"value": "Quarterly review"}]}]}}]}}}
    report = {
        "filters": json.dumps([{"name": "rf", "expression": _col("Product", "Cost"), "type": "Categorical", "filter": _in_filter("Product", "Cost", ["'A'"])}]),
        "sections": [
            {"name": "s1", "displayName": "Overview", "ordinal": 0, "width": 1280, "height": 720,
             "filters": json.dumps([{"name": "pf", "expression": _col("Sales", "Amount"), "type": "Advanced",
                                     "filter": {"Version": 2, "From": [{"Name": "s", "Entity": "Sales", "Type": 0}],
                                                "Where": [{"Condition": {"Comparison": {"ComparisonKind": 1, "Left": _col("", "Amount", "s"), "Right": {"Literal": {"Value": "100D"}}}}}]}}]),
             "visualContainers": [
                 {"x": 10, "y": 20, "z": 1, "width": 600, "height": 300, "config": json.dumps(chart_cfg),
                  "filters": json.dumps([{"name": "vf", "expression": _col("Product", "Cost"), "type": "Categorical", "howCreated": 1},
                                         {"name": "vf2", "expression": _col("Product", "Cost"), "type": "Categorical", "filter": _in_filter("Product", "Cost", ["5L"])}])},
                 {"x": 620, "y": 20, "z": 2, "width": 200, "height": 300, "config": json.dumps(slicer_cfg)},
                 {"x": 10, "y": 330, "z": 3, "width": 300, "height": 40, "config": json.dumps(text_cfg)},
             ]},
            {"name": "s2", "displayName": "Hidden detail", "ordinal": 1, "width": 1280, "height": 720, "config": json.dumps({"visibility": 1}), "visualContainers": []},
        ],
    }
    return {"report.json": json.dumps(report), "definition.pbir": json.dumps({"datasetReference": {"byConnection": {"connectionString": f"semanticmodelid={DS}"}}})}


def pbir_parts() -> dict[str, str]:
    visual = {
        "name": "card1", "position": {"x": 5, "y": 6, "z": 0, "width": 200, "height": 100},
        "visual": {"visualType": "card", "query": {"queryState": {"Values": {"projections": [{"field": _meas("Sales", "Margin %"), "queryRef": "Sales.Margin %"}]}}}},
    }
    return {
        "definition/pages/pages.json": json.dumps({"pageOrder": ["p1"]}),
        "definition/pages/p1/page.json": json.dumps({"name": "p1", "displayName": "KPIs", "width": 1280, "height": 720,
                                                     "filterConfig": {"filters": [{"name": "f", "field": _col("Product", "Cost"), "type": "Categorical"}]}}),
        "definition/pages/p1/visuals/card1/visual.json": json.dumps(visual),
        "definition/report.json": json.dumps({}),
        "definition.pbir": "{}",
    }


def test_parse_layout_legacy_and_pbir():
    lay = parse_report_layout(legacy_parts())
    assert lay["format"] == "PBIR-Legacy" and lay["version"] == LAYOUT_VERSION and lay["visual_count"] == 3
    p1, p2 = lay["pages"]
    assert p1["display"] == "Overview" and not p1["hidden"] and p2["hidden"]
    chart = next(v for v in p1["visuals"] if v["id"] == "v_chart")
    assert chart["type"] == "clusteredColumnChart" and chart["title"] == "Sales by cost" and (chart["x"], chart["w"]) == (10.0, 600.0)
    assert chart["roles"]["Category"] == [{"kind": "column", "table": "Product", "name": "Cost"}]
    assert {"kind": "measure", "table": "Sales", "name": "Total Sales"} in chart["roles"]["Y"]
    assert {"kind": "column", "table": "Sales", "name": "Qty", "agg": "Sum"} in chart["roles"]["Y"]
    assert len(chart["filters"]) == 1 and chart["filters"][0]["condition"] == "Product[Cost] in (5)"  # empty auto filter dropped
    slicer = next(v for v in p1["visuals"] if v["type"] == "slicer")
    assert slicer["selection"]["values"] == ["10", "High"]
    assert next(v for v in p1["visuals"] if v["type"] == "textbox")["text"] == "Quarterly review"
    assert p1["filters"][0]["condition"] == "Sales[Amount] > 100"
    assert lay["filters"][0]["values"] == ["A"]

    lay2 = parse_report_layout(pbir_parts())
    assert lay2["format"] == "PBIR" and lay2["pages"][0]["display"] == "KPIs"
    card = lay2["pages"][0]["visuals"][0]
    assert card["type"] == "card" and card["roles"]["Values"][0] == {"kind": "measure", "table": "Sales", "name": "Margin %"}
    assert lay2["pages"][0]["filters"][0]["condition"] == ""  # field in the filter pane, nothing selected


def test_report_explorer_assets_lineage_and_mcp():
    tmp = Path(tempfile.mkdtemp())
    try:
        store = _seed_store(tmp)
        st = store.load()
        st["reports"][RPT] = {"id": RPT, "name": "Sales Overview", "workspace_id": WS, "workspace": "Finance BI", "dataset_id": DS,
                              "report_type": "PowerBIReport", "page_count": 2, "visual_count": 3, "layout_version": LAYOUT_VERSION}
        store.save(st)
        lay = parse_report_layout(legacy_parts())
        lay["report_id"], lay["dataset_id"] = RPT, DS
        # A field that no longer exists in the model -> reported as a broken visual reference
        lay["pages"][0]["visuals"][0]["roles"]["Y"].append({"kind": "column", "table": "Gone", "name": "Old"})
        store.write_report_layout(RPT, lay)

        idx = generate_portal(store, output_dir=tmp / "portal")
        assets = idx.parent / "assets"
        index_html = idx.read_text(encoding="utf-8")
        assert 'data-tab="tab-reports"' in index_html and 'id="rxCanvas"' in index_html and "report_explorer.js" in index_html
        assert f"index.html#rpt:r={RPT}" in index_html  # report name in Workspaces & Reports opens the explorer
        assert "no longer exist in Sales Model" in index_html  # governance finding for the broken field
        rjs = (assets / "reports" / f"{RPT}.js").read_text(encoding="utf-8")
        data = json.loads(rjs[rjs.index("= {") + 2:rjs.rstrip().rindex("}") + 1])
        chart = data["pages"][0]["visuals"][0]
        nodes = {f["name"]: f.get("node") for f in chart["roles"]["Y"] + chart["roles"]["Category"]}
        assert nodes["Total Sales"] == f"m:{DS}:Sales[Total Sales]" and nodes["Cost"] == f"t:{DS}:Product" and nodes["Old"] == ""
        usage = (assets / "report_usage.js").read_text(encoding="utf-8")
        assert f"m:{DS}:Sales[Total Sales]" in usage and f"col:{DS}:Product[Cost]" in usage
        assert "report_usage.js" in (idx.parent / "e2e_lineage.html").read_text(encoding="utf-8")

        eng = CatalogMcpEngine(store)
        reports = eng.call_tool("pbi_report_layout", {"workspace": "finance"})
        assert reports and reports[0]["name"] == "Sales Overview" and reports[0]["pages"] == 2
        pages = eng.call_tool("pbi_report_layout", {"report": "sales overview"})
        assert [p["display"] for p in pages["pages"]] == ["Overview", "Hidden detail"]
        page = eng.call_tool("pbi_report_layout", {"report": RPT, "page": "Overview"})
        y = page["visuals"][0]["roles"]["Y"]
        assert y[0]["lineage_object_id"] == f"m:{DS}:Sales[Total Sales]"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
