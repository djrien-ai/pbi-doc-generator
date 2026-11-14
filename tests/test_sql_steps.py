"""Native SQL extraction, SQL formatting and Power Query step interpretation (patterns seen in real Gen1 dataflows)."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pbi_catalog.mparse import extract_native_sql, parse_let_steps
from pbi_catalog.pq_steps import interpret_query
from pbi_catalog.sql_format import format_sql

SNOWFLAKE_Q = '''let
    // 1. Current year as text
    CurrentYear = Date.Year(DateTime.LocalNow()),
    YearString = Text.From(CurrentYear),
    Sqlast = "SELECT * #(lf)FROM DEMO_DB.FX.RATES WHERE YEAR IN (" & YearString & ")",
    Source = Value.NativeQuery(
        Snowflake.Databases("acct.snowflakecomputing.com", "DEMO_WH"){[Name="DEMO_DB"]}[Data],
        Sqlast, null, [EnableFolding=true])
in
    Source'''

HANA_Q = '''let
  PARAM_YEAR = #"PARAM_FISCAL_YEAR"[YEAR]{0},
  Source = SapHana.Database("hana.example.local:30015", [Implementation = "2.0", Query = "select a, b from ""_SYS_BIC"".""demo.pkg/SALES_VIEW"" where FY = '" & Text.From(PARAM_YEAR) & "' and x = 1"]),
  #"Renamed columns" = Table.RenameColumns(Source, {{"a", "Account"}, {"b", "Bookings"}}),
  #"Filtered rows" = Table.SelectRows(#"Renamed columns", each [Bookings] <> 0 and [Account] <> null),
  #"Merged queries" = Table.NestedJoin(#"Filtered rows", {"Account"}, DIM_ACCOUNT, {"KEY"}, "DIM", JoinKind.LeftOuter),
  #"Expanded DIM" = Table.ExpandTableColumn(#"Merged queries", "DIM", {"NAME"}, {"ACCOUNT_NAME"}),
  #"Changed column type" = Table.TransformColumnTypes(#"Expanded DIM", {{"Bookings", type number}}),
  #"Uppercased text" = Table.TransformColumns(#"Changed column type", {{"ACCOUNT_NAME", Text.Upper, type text}})
in
  #"Uppercased text"'''


def test_native_sql_extraction_patterns():
    sf = extract_native_sql(SNOWFLAKE_Q)
    assert len(sf) == 1 and sf[0]["via"] == "Value.NativeQuery"
    assert sf[0]["sql"] == "SELECT * \nFROM DEMO_DB.FX.RATES WHERE YEAR IN ({{YearString}})" and sf[0]["parameters"] == ["YearString"]

    hana = extract_native_sql(HANA_Q)
    assert len(hana) == 1 and hana[0]["via"] == "Query option"
    assert hana[0]["sql"] == """select a, b from "_SYS_BIC"."demo.pkg/SALES_VIEW" where FY = '{{PARAM_YEAR}}' and x = 1"""


def test_let_steps_offsets_and_comments():
    steps, final = parse_let_steps(SNOWFLAKE_Q)
    assert [s["name"] for s in steps] == ["CurrentYear", "YearString", "Sqlast", "Source"] and final == "Source"
    for s in steps:
        assert SNOWFLAKE_Q[s["start"] : s["end"]].startswith(s["name"])


def test_step_interpreter():
    st = interpret_query(HANA_Q, {"DIM_ACCOUNT", "PARAM_FISCAL_YEAR"})
    by = {s["name"]: s for s in st}
    assert by["PARAM_YEAR"]["summary"] == "Read single value: column YEAR, first row of query PARAM_FISCAL_YEAR"
    assert by["Source"]["category"] == "sql" and "SAP HANA hana.example.local:30015" in by["Source"]["summary"]
    assert by["Renamed columns"]["summary"] == "Rename columns: a → Account, b → Bookings"
    assert by["Filtered rows"]["summary"] == "Filter rows where Bookings <> 0 and Account <> null"
    assert by["Merged queries"]["summary"] == "Merge with DIM_ACCOUNT on Account = KEY (left outer join) into column 'DIM'"
    assert by["Merged queries"]["queries"] == ["DIM_ACCOUNT"] and by["Merged queries"]["input"] == "Filtered rows"
    assert by["Expanded DIM"]["category"] == "expand" and "ACCOUNT_NAME" in by["Expanded DIM"]["details"][0]
    assert by["Changed column type"]["summary"] == "Set data types: Bookings as number"
    assert by["Uppercased text"]["summary"] == "Transform values (uppercase) in: ACCOUNT_NAME"
    assert st[-1]["is_output"] and not st[0]["is_output"]


def test_sql_formatter():
    one_line = "select a.id, sum(b.amt) as total from dbo.A a inner join dbo.B b on a.id = b.id where a.x = 1 and a.y between 1 and 5 group by a.id"
    assert format_sql(one_line) == (
        "SELECT\n    a.id,\n    sum(b.amt) AS total\nFROM\n    dbo.A a\n    INNER JOIN dbo.B b\n        ON a.id = b.id\n"
        "WHERE\n    a.x = 1\n    AND a.y BETWEEN 1 AND 5\nGROUP BY\n    a.id"
    )
    hand = "SELECT\n\t    a,\n   -- b,\n      c\n   FROM t\n\n\n\n   WHERE x = 1"
    assert format_sql(hand) == "SELECT\n     a,\n-- b,\n   c\nFROM t\n\nWHERE x = 1"  # layout + comments kept, only tidied


def test_graph_and_doc_carry_sql_and_steps():
    sys.path.insert(0, str(ROOT / "tests"))
    import test_dataflow_lineage as t
    from pbi_catalog.e2e_lineage import build_e2e_graph, render_measure_doc_markdown

    tmp = Path(tempfile.mkdtemp())
    try:
        store = t._seed_store(tmp)
        g = build_e2e_graph(store)
        q = g["nodes"][f"q:{t.DF_STG}:stg_Sales"]
        assert q["sql"] and g["nodes"][q["sql"][0]["source_id"]]["code"].startswith("SELECT")
        assert [s["category"] for s in q["steps"]] == ["sql", "type"]
        fact = g["nodes"][f"q:{t.DF_CUR}:FactSales"]
        merge = fact["steps"][0]
        assert merge["category"] == "merge" and f"q:{t.DF_CUR}:DimDate" in merge["query_ids"]
        assert "code" not in merge  # UI slices node.code instead
        assert fact["code"][merge["start"] : merge["end"]].startswith("Source = Table.NestedJoin")
        xl = next(n for n in g["nodes"].values() if n.get("source_type") == "Excel")
        md = render_measure_doc_markdown(g, f"m:{t.DS}:Sales[Margin %]")
        assert "**Native SQL:**" in md and "- **Native SQL:** see section 1." in md
        assert "**Transformation steps (2):**" in md and "[Merge (join)] - Merge with DimDate" in md
        assert xl["files"][0].startswith("https://")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
