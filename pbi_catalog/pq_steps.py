"""
Power Query step interpreter.

Turns each `let` step of an M query into a plain-language description of what it does to the data
("Filter rows where STATUS <> 'Closed'", "Merge with DIM_PRODUCT on PRODUCT_KEY = KEY (left outer join)",
"Rename columns: A -> B"), with a category used for colour coding, the step it builds on, the other
queries it pulls in, and character offsets (UTF-16, matching JavaScript) so the UI can highlight the
step inside the full M code.
"""

from __future__ import annotations

import re

from .mparse import call_args, parse_let_steps, split_top_level, string_literals, unquote_ident

CATEGORY_LABEL = {
    "source": "Source",
    "navigate": "Navigate",
    "filter": "Filter rows",
    "columns": "Choose / remove columns",
    "rename": "Rename",
    "type": "Change type",
    "add": "Add column",
    "transform": "Transform values",
    "merge": "Merge (join)",
    "expand": "Expand",
    "append": "Append",
    "group": "Group / aggregate",
    "pivot": "Pivot / unpivot",
    "sort": "Sort",
    "dedupe": "Remove duplicates",
    "rows": "Keep / remove rows",
    "headers": "Headers",
    "replace": "Replace values",
    "split": "Split / combine",
    "reference": "Reference query",
    "sql": "Native SQL",
    "buffer": "Performance",
    "other": "Custom step",
}


_TRANSFORM_FNS = {
    "Text.Upper": "uppercase", "Text.Lower": "lowercase", "Text.Proper": "capitalize each word", "Text.Trim": "trim spaces",
    "Text.Clean": "remove non-printable characters", "Text.Start": "keep first characters", "Text.End": "keep last characters",
    "Text.Middle": "extract text", "Text.Replace": "replace text", "Text.PadStart": "pad", "Text.BeforeDelimiter": "text before delimiter",
    "Text.AfterDelimiter": "text after delimiter", "Text.From": "convert to text", "Number.Round": "round", "Number.Abs": "absolute value",
    "Number.From": "convert to number", "Date.From": "convert to date", "DateTime.Date": "date part", "Date.Year": "year",
    "Date.Month": "month", "Date.StartOfMonth": "start of month", "Date.EndOfMonth": "end of month", "Text.Length": "text length",
    "Number.IntegerDivide": "integer divide", "Value.Multiply": "multiply", "Value.Divide": "divide",
}


def _short(text: str, n: int = 140) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    return t if len(t) <= n else t[: n - 1] + "…"


def _cols(arg: str, limit: int = 12) -> str:
    names = string_literals(arg)
    if not names:
        return _short(arg, 60)
    more = f" (+{len(names) - limit} more)" if len(names) > limit else ""
    return ", ".join(names[:limit]) + more


def _pairs(arg: str) -> list[tuple[str, str]]:
    out = []
    for m in re.finditer(r'\{\s*"((?:[^"]|"")*)"\s*,\s*([^{}]+?)\s*\}', arg or ""):
        out.append((m.group(1).replace('""', '"'), m.group(2).strip()))
    return out


def _cond(expr: str) -> str:
    """`each [Status] <> "Closed" and [Amount] > 0` -> `Status <> "Closed" and Amount > 0`."""
    e = re.sub(r"^\s*each\s+", "", expr or "")
    e = re.sub(r"^\s*\(\s*\w+\s*\)\s*=>\s*", "", e)
    e = re.sub(r"\[([^\[\]]+)\]", r"\1", e)
    return _short(e, 160)


def _type_name(t: str) -> str:
    t = t.strip()
    t = re.sub(r"^type\s+", "", t)
    t = re.sub(r"^(Int64|Number|Text|Date|DateTime|Logical|Currency|Percentage|Decimal)\.Type$", r"\1", t)
    return t


def _join_kind(arg: str) -> str:
    m = re.search(r"JoinKind\.(\w+)", arg or "")
    labels = {"LeftOuter": "left outer", "RightOuter": "right outer", "FullOuter": "full outer", "Inner": "inner",
              "LeftAnti": "left anti (rows with no match)", "RightAnti": "right anti"}
    return labels.get(m.group(1), m.group(1)) if m else "left outer"


def _ref_name(arg: str) -> str:
    return unquote_ident((arg or "").strip())


def describe_step(expr: str, prev_names: set[str], query_names: set[str]) -> dict:
    """Return {fn, category, summary, details, input, queries} for one step expression."""
    e = (expr or "").strip()
    ca = call_args(e)
    fn = ca[0] if ca else ""
    args = ca[1] if ca else []
    a0 = _ref_name(args[0]) if args else ""
    input_step = a0 if a0 in prev_names else ""
    details: list[str] = []
    cat, summary = "other", ""

    def arg(i: int) -> str:
        return args[i] if len(args) > i else ""

    if fn in ("Table.SelectRows",):
        cat, summary = "filter", f"Filter rows where {_cond(arg(1))}"
    elif fn in ("Table.RemoveColumns",):
        cat, summary = "columns", f"Remove columns: {_cols(arg(1))}"
    elif fn in ("Table.SelectColumns",):
        cat, summary = "columns", f"Keep only columns: {_cols(arg(1))}"
    elif fn == "Table.ReorderColumns":
        cat, summary = "columns", f"Reorder columns: {_cols(arg(1))}"
    elif fn == "Table.RenameColumns":
        pr = _pairs(arg(1))
        cat = "rename"
        summary = "Rename columns: " + ", ".join(f"{a} → {string_literals(b)[0] if string_literals(b) else b}" for a, b in pr[:8]) + (f" (+{len(pr) - 8} more)" if len(pr) > 8 else "")
        details = [f"{a} → {string_literals(b)[0] if string_literals(b) else b}" for a, b in pr]
    elif fn == "Table.TransformColumnTypes":
        pr = _pairs(arg(1))
        cat = "type"
        summary = "Set data types: " + ", ".join(f"{a} as {_type_name(b)}" for a, b in pr[:6]) + (f" (+{len(pr) - 6} more)" if len(pr) > 6 else "")
        details = [f"{a}: {_type_name(b)}" for a, b in pr]
    elif fn == "Table.AddColumn":
        name = (string_literals(arg(1)) or [arg(1)])[0]
        cat, summary = "add", f"Add column '{name}' = {_cond(arg(2))}"
        if arg(3):
            details.append(f"Type: {_type_name(arg(3))}")
    elif fn in ("Table.AddIndexColumn",):
        cat, summary = "add", f"Add index column '{(string_literals(arg(1)) or ['Index'])[0]}'"
    elif fn == "Table.DuplicateColumn":
        lits = string_literals(" ".join(args[1:3]))
        cat, summary = "add", f"Duplicate column {lits[0] if lits else ''} as {lits[1] if len(lits) > 1 else ''}"
    elif fn in ("Table.AddConditionalColumn",):
        cat, summary = "add", f"Add conditional column '{(string_literals(arg(1)) or [''])[0]}'"
    elif fn in ("Table.TransformColumns",):
        cols = [m.group(1) for m in re.finditer(r'\{\s*"((?:[^"]|"")*)"\s*,', arg(1))]
        ops = sorted({_TRANSFORM_FNS[f] for f in re.findall(r"\b(\w+\.\w+)\b", arg(1)) if f in _TRANSFORM_FNS})
        cat = "transform"
        summary = f"Transform values{' (' + ', '.join(ops) + ')' if ops else ''} in: {', '.join(cols[:8]) or _short(arg(1), 80)}"
        details = [_short(x, 160) for x in re.findall(r'\{\s*"[^"]*"\s*,[^{}]*\}', arg(1))]
    elif fn in ("Table.NestedJoin", "Table.Join", "Table.FuzzyNestedJoin"):
        other = _ref_name(arg(2))
        lk, rk = _cols(arg(1)), _cols(arg(3))
        new_col = (string_literals(arg(4)) or [""])[0] if fn != "Table.Join" else ""
        kind = _join_kind(" ".join(args))
        cat = "merge"
        summary = f"Merge with {other} on {lk} = {rk} ({kind} join)" + (f" into column '{new_col}'" if new_col else "")
    elif fn in ("Table.ExpandTableColumn", "Table.ExpandRecordColumn", "Table.ExpandListColumn"):
        col = (string_literals(arg(1)) or [arg(1)])[0]
        cat, summary = "expand", f"Expand '{col}'" + (f" to columns: {_cols(arg(2))}" if arg(2) else "")
        if arg(3):
            details.append(f"New names: {_cols(arg(3))}")
    elif fn == "Table.Combine":
        tables = [_ref_name(x) for x in split_top_level(arg(0).strip()[1:-1])] if arg(0).strip().startswith("{") else [arg(0)]
        input_step = ""
        cat, summary = "append", f"Append (stack) {len(tables)} tables: {', '.join(tables[:8])}" + (" …" if len(tables) > 8 else "")
        details = tables
    elif fn == "Table.Group":
        aggs = [m.group(1) for m in re.finditer(r'\{\s*"((?:[^"]|"")*)"\s*,\s*each', arg(2))]
        fns = sorted(set(re.findall(r"(List\.\w+|Table\.RowCount)", arg(2))))
        cat = "group"
        summary = f"Group by {_cols(arg(1))}" + (f"; aggregate {', '.join(aggs[:6])}" if aggs else "")
        if fns:
            details.append("Aggregations: " + ", ".join(f.replace("List.", "").replace("Table.RowCount", "Count rows") for f in fns))
    elif fn in ("Table.Pivot",):
        cat, summary = "pivot", f"Pivot column {(string_literals(arg(2)) or [arg(2)])[0]} into columns (values from {(string_literals(arg(3)) or [arg(3)])[0]})"
    elif fn in ("Table.Unpivot", "Table.UnpivotOtherColumns"):
        other = "all columns except " if fn == "Table.UnpivotOtherColumns" else ""
        lits = string_literals(" ".join(args[2:4]))
        cat, summary = "pivot", f"Unpivot {other}{_cols(arg(1))} into attribute/value columns" + (f" ({', '.join(lits)})" if lits else "")
    elif fn == "Table.Sort":
        cat, summary = "sort", f"Sort by {_cols(arg(1))}" + (" (descending)" if "Order.Descending" in arg(1) else "")
    elif fn == "Table.Distinct":
        cat, summary = "dedupe", "Remove duplicate rows" + (f" based on {_cols(arg(1))}" if arg(1) else "")
    elif fn in ("Table.FirstN", "Table.LastN", "Table.Skip", "Table.RemoveFirstN", "Table.RemoveLastN", "Table.Range",
                "Table.RemoveRowsWithErrors", "Table.SelectRowsWithErrors", "Table.RemoveMatchingRows", "Table.AlternateRows"):
        verb = {"Table.FirstN": "Keep first", "Table.LastN": "Keep last", "Table.Skip": "Skip first", "Table.RemoveFirstN": "Remove first",
                "Table.RemoveLastN": "Remove last", "Table.Range": "Keep a range of", "Table.RemoveRowsWithErrors": "Remove rows with errors",
                "Table.SelectRowsWithErrors": "Keep only rows with errors", "Table.RemoveMatchingRows": "Remove matching rows",
                "Table.AlternateRows": "Keep alternate rows"}[fn]
        cat, summary = "rows", f"{verb} {_short(arg(1), 60)}".strip() + (" rows" if fn in ("Table.FirstN", "Table.LastN", "Table.Skip", "Table.RemoveFirstN", "Table.RemoveLastN") else "")
    elif fn in ("Table.PromoteHeaders",):
        cat, summary = "headers", "Use first row as column headers"
    elif fn in ("Table.DemoteHeaders",):
        cat, summary = "headers", "Move column headers into the first row"
    elif fn in ("Table.ReplaceValue",):
        cat, summary = "replace", f"Replace {_short(arg(1), 40)} with {_short(arg(2), 40)} in {_cols(arg(4))}"
    elif fn in ("Table.ReplaceErrorValues",):
        cat, summary = "replace", f"Replace errors in {_cols(arg(1))}"
    elif fn in ("Table.FillDown", "Table.FillUp"):
        cat, summary = "replace", f"Fill {'down' if fn.endswith('Down') else 'up'} empty values in {_cols(arg(1))}"
    elif fn in ("Table.SplitColumn",):
        cat, summary = "split", f"Split column '{(string_literals(arg(1)) or [''])[0]}'" + (f" into {_cols(arg(3))}" if arg(3) else "")
    elif fn in ("Table.CombineColumns",):
        cat, summary = "split", f"Combine columns {_cols(arg(1))} into '{(string_literals(arg(3)) or [''])[0]}'"
    elif fn in ("Table.Buffer", "List.Buffer", "Binary.Buffer"):
        cat, summary = "buffer", "Buffer the table in memory (performance)"
    elif fn in ("Table.TransformRows", "Table.FromRecords", "Table.FromList", "Table.FromRows", "#table"):
        cat, summary = "transform", f"Build table via {fn}"
    elif fn == "Value.NativeQuery":
        cat, summary = "sql", "Run native SQL against the source (see Native SQL)"
        input_step = ""
    elif fn and re.match(r"(Sql|AzureSql|Snowflake|SapHana|SapBusinessWarehouse|Oracle|PostgreSQL|MySQL|Teradata|Databricks|GoogleBigQuery|AmazonRedshift|Odbc|OleDb|AnalysisServices|Lakehouse|Fabric|PowerPlatform|PowerBI|CommonDataService|Dataverse|OData|Salesforce|SharePoint|Excel|Csv|Json|Xml|Parquet|Folder|File|Web|AzureStorage|AzureDataExplorer)\.", fn):
        lits = string_literals(" ".join(args[:2]))
        cat = "source"
        has_query = re.search(r"\bQuery\s*=", e) is not None
        summary = f"Connect to {fn}" + (f" ({', '.join(_short(x, 70) for x in lits[:2])})" if lits and not has_query else "")
        if fn == "SapHana.Database" and lits:
            summary = f"Connect to SAP HANA {lits[0]}"
        if has_query:
            summary += " and run a native SQL query (see Native SQL)"
            cat = "sql"
        input_step = ""
    elif re.match(r'^(#"(?:[^"]|"")*"|[A-Za-z_][\w.]*)\s*\{\s*\[', e):
        base = _ref_name(re.match(r'^(#"(?:[^"]|"")*"|[A-Za-z_][\w.]*)', e).group(1))
        kv = dict(re.findall(r'(\w+)\s*=\s*"((?:[^"]|"")*)"', e.split("]}", 1)[0]))
        target = kv.get("Item") or kv.get("Name") or kv.get("entity") or kv.get("Schema") or ", ".join(f"{k}={v}" for k, v in kv.items())
        if "Schema" in kv and ("Item" in kv or "Name" in kv):
            target = f"{kv['Schema']}.{kv.get('Item') or kv.get('Name')}"
        kind = kv.get("Kind", "")
        input_step = base if base in prev_names else ""
        cat, summary = "navigate", f"Navigate to {kind.lower() + ' ' if kind else ''}{target}"
        if base in query_names:
            details.append(f"From query {base}")
    elif re.fullmatch(r'(#"(?:[^"]|"")*"|[A-Za-z_][\w.]*)\s*\[([^\[\]]+)\]\s*(\{\s*\d+\s*\})?', e):
        m = re.fullmatch(r'(#"(?:[^"]|"")*"|[A-Za-z_][\w.]*)\s*\[([^\[\]]+)\]\s*(\{\s*(\d+)\s*\})?', e)
        base, col = _ref_name(m.group(1)), m.group(2)
        input_step = base if base in prev_names else ""
        where = f"step '{base}'" if base in prev_names else f"query {base}"
        if m.group(3):
            row = int(m.group(4))
            cat, summary = "navigate", f"Read single value: column {col}, {'first row' if row == 0 else f'row {row + 1}'} of {where}"
        else:
            cat, summary = "navigate", f"Take column {col} of {where} as a list"
    elif fn == "Table.Transpose":
        cat, summary = "pivot", "Transpose the table (rows become columns)"
    elif re.fullmatch(r'#"(?:[^"]|"")*"|[A-Za-z_][\w.]*', e):
        ref = _ref_name(e)
        if ref in prev_names:
            cat, summary, input_step = "reference", f"Continue from step '{ref}'", ref
        else:
            cat, summary = "reference", f"Start from query {ref}"
    elif fn:
        cat, summary = "other", f"Apply {fn}"
    else:
        cat, summary = "other", f"Custom expression: {_short(e, 100)}"

    idents = {m.group(1).replace('""', '"') if m.group(1) is not None else m.group(2)
              for m in re.finditer(r'#"((?:[^"]|"")*)"|(?<![\w."])([A-Za-z_][\w.]*)(?![\w"])', e)}
    queries = sorted(q for q in idents if q in query_names and q not in prev_names)
    return {"fn": fn, "category": cat, "category_label": CATEGORY_LABEL.get(cat, cat), "summary": summary,
            "details": details[:40], "input": input_step, "queries": queries}


def _utf16(code: str, idx: int) -> int:
    return len(code[:idx].encode("utf-16-le")) // 2


def interpret_query(code: str, query_names: list[str] | set[str] | None = None) -> list[dict]:
    """Interpret every step of an M query. Empty list when the query is not a `let` expression."""
    steps, final = parse_let_steps(code or "")
    if not steps:
        return []
    qn = set(query_names or [])
    out: list[dict] = []
    seen: set[str] = set()
    for idx, st in enumerate(steps, 1):
        info = describe_step(st["expr"], seen, qn)
        if not info["input"] and idx > 1 and info["category"] not in ("source", "sql", "append", "reference"):
            # Most UI-generated steps take the previous step as first argument
            prev = steps[idx - 2]["name"]
            if re.search(r'(?<![\w"])(?:#"' + re.escape(prev) + r'"|' + re.escape(prev) + r')(?![\w"])', st["expr"]):
                info["input"] = prev
        out.append(
            {
                "index": idx,
                "name": st["name"],
                **info,
                "code": st["expr"],
                "start": _utf16(code, st["start"]),
                "end": _utf16(code, st["end"]),
            }
        )
        seen.add(st["name"])
    final_ref = unquote_ident(final)
    for s in out:
        s["is_output"] = s["name"] == final_ref
    return out
