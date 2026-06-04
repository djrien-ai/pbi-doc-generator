"""
TMDL Parser – extracts metadata from a Power BI PBIP SemanticModel folder.

Parses the following TMDL artefacts:
  • Tables   (tables/*.tmdl)   – columns, measures, partitions, hierarchies
  • Relationships              – from/to tables and columns, cardinality, cross-filter
  • Expressions                – M parameters and helper functions

Usage
-----
    from tmdl_parser import TmdlModel

    model = TmdlModel(r"path/to/MyReport.SemanticModel")
    # – or –
    model = TmdlModel.from_pbip_folder(r"path/to/MyReport")

    for table in model.tables:
        print(table.name, [c.name for c in table.columns])
"""

from __future__ import annotations

import os
import re
import glob
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional


# ────────────────────────────────────────────────────────────────────
# Data classes
# ────────────────────────────────────────────────────────────────────

@dataclass
class ColumnInfo:
    """A column (regular or calculated) inside a table."""
    name: str
    data_type: str = ""
    source_column: Optional[str] = None
    dax_expression: Optional[str] = None
    is_calculated: bool = False
    sort_by_column: Optional[str] = None
    format_string: Optional[str] = None
    is_key: bool = False
    summarize_by: Optional[str] = None


@dataclass
class MeasureInfo:
    """A DAX measure inside a table."""
    name: str
    expression: str = ""
    format_string: Optional[str] = None
    table_name: str = ""


@dataclass
class MQueryInfo:
    """A partition (M query or DAX calculated table) inside a table."""
    partition_name: str
    mode: str = "import"
    source_code: str = ""
    is_calculated: bool = False
    dax_expression: Optional[str] = None


@dataclass
class TableInfo:
    """A table with its columns, measures, partitions and hierarchies."""
    name: str
    columns: List[ColumnInfo] = field(default_factory=list)
    measures: List[MeasureInfo] = field(default_factory=list)
    partitions: List[MQueryInfo] = field(default_factory=list)
    hierarchies: list = field(default_factory=list)
    calculation_group: object = None


@dataclass
class RelationshipInfo:
    """A relationship between two tables."""
    from_table: str = ""
    from_column: str = ""
    to_table: str = ""
    to_column: str = ""
    cross_filter: str = "Single"
    to_cardinality: str = "one"


@dataclass
class ParameterInfo:
    """An M parameter (expression with IsParameterQuery=true)."""
    name: str
    default_value: str = ""
    type: str = ""
    allowed_values: List[str] = field(default_factory=list)
    is_required: bool = False


@dataclass
class FunctionInfo:
    """A helper M function (expression without IsParameterQuery)."""
    name: str
    code: str = ""


@dataclass
class CalculationItem:
    """A single calculation item inside a calculation group."""
    name: str
    expression: str = ""
    ordinal: int = 0


@dataclass
class CalculationGroupInfo:
    """A calculation group attached to a table."""
    table_name: str
    column_name: str = ""
    items: List[CalculationItem] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

def _unquote(name: str) -> str:
    """Remove surrounding single quotes from a TMDL identifier.

    >>> _unquote("'My Table'")
    'My Table'
    >>> _unquote("SimpleTable")
    'SimpleTable'
    """
    name = name.strip()
    if name.startswith("'") and name.endswith("'"):
        return name[1:-1]
    return name


def _read_file(path: str) -> List[str]:
    """Read a file and return its lines (newlines stripped)."""
    with open(path, encoding="utf-8") as fh:
        return [line.rstrip("\n\r") for line in fh.readlines()]


def _split_table_column(ref: str):
    """Split a ``Table.Column`` or ``Table.'Column Name'`` reference.

    Splits on the *first* dot only, so quoted column names containing
    dots are handled correctly.

    Returns (table_name, column_name) with quotes removed.
    """
    ref = ref.strip()
    dot_idx = ref.index(".")
    table_part = ref[:dot_idx]
    col_part = ref[dot_idx + 1:]
    return _unquote(table_part), _unquote(col_part)


def _indent_level(line: str) -> int:
    """Return the number of leading tab characters."""
    count = 0
    for ch in line:
        if ch == "\t":
            count += 1
        else:
            break
    return count


def _parse_name_from_header(line: str, keyword: str):
    """Extract the identifier after a keyword on a header line.

    Handles both quoted (``'My Name'``) and unquoted identifiers.
    Returns ``(name, remainder)`` where *remainder* is everything after
    the name (e.g. ``= <expression>``).
    """
    text = line.strip()
    # Remove the keyword prefix (e.g. "column ", "measure ")
    if text.lower().startswith(keyword.lower()):
        text = text[len(keyword):].strip()
    else:
        return text, ""

    if text.startswith("'"):
        # Quoted name – find the closing quote
        end = text.index("'", 1)
        name = text[1:end]
        remainder = text[end + 1:].strip()
    else:
        # Unquoted name – ends at first whitespace or '='
        m = re.match(r"(\S+)(.*)", text)
        if m:
            name = m.group(1)
            remainder = m.group(2).strip()
        else:
            name = text
            remainder = ""
    return name, remainder


# ────────────────────────────────────────────────────────────────────
# Collect a multi-line block that may use ``` delimiters
# ────────────────────────────────────────────────────────────────────

def _collect_expression(lines: List[str], start_idx: int, base_indent: int):
    """Collect a (possibly multi-line) expression starting at *start_idx*.

    TMDL uses two conventions for multi-line expressions:
      1. Triple-backtick blocks (```)
      2. Continued indented lines (indent > base_indent)

    Returns ``(expression_text, next_index)`` where *next_index* is the
    first line that no longer belongs to the expression.
    """
    idx = start_idx
    total = len(lines)

    # Check if the first relevant content starts with ```
    # The ``` might be on the same line or the next line.
    first_line = lines[idx] if idx < total else ""
    stripped = first_line.strip()

    if stripped == "```":
        # Multi-line triple-backtick block
        idx += 1
        expr_lines: list[str] = []
        while idx < total:
            if lines[idx].strip() == "```":
                idx += 1
                break
            expr_lines.append(lines[idx])
            idx += 1
        # Dedent: find minimum indentation and strip it
        expression = _dedent_block(expr_lines)
        return expression, idx

    # Otherwise: inline expression possibly continued on next lines
    # The first line already contains the beginning of the expression
    expr_lines = [stripped]
    idx += 1
    while idx < total:
        l = lines[idx]
        if l.strip() == "```":
            # Start of a triple-backtick continuation
            idx += 1
            while idx < total:
                if lines[idx].strip() == "```":
                    idx += 1
                    break
                expr_lines.append(lines[idx])
                idx += 1
            break
        if l.strip() == "" or _indent_level(l) <= base_indent:
            break
        expr_lines.append(l)
        idx += 1

    expression = _dedent_block(expr_lines)
    return expression, idx


def _dedent_block(lines: List[str]) -> str:
    """Remove common leading tabs from a list of lines and join them."""
    if not lines:
        return ""
    # Find minimum indent (ignoring blank lines)
    min_indent = None
    for l in lines:
        if l.strip() == "":
            continue
        ind = _indent_level(l)
        if min_indent is None or ind < min_indent:
            min_indent = ind
    if min_indent is None:
        min_indent = 0
    dedented = [l[min_indent:] if len(l) >= min_indent else l for l in lines]
    return "\n".join(dedented).strip()


# ────────────────────────────────────────────────────────────────────
# Table parser
# ────────────────────────────────────────────────────────────────────

def _parse_table_file(path: str) -> TableInfo:
    """Parse a single ``tables/<TableName>.tmdl`` file.

    Extracts columns (including calculated columns), measures, partitions
    (M query and DAX calculated tables) and hierarchies.
    """
    lines = _read_file(path)
    if not lines:
        return TableInfo(name=os.path.splitext(os.path.basename(path))[0])

    # ── Table name ──────────────────────────────────────────────────
    table_name, _ = _parse_name_from_header(lines[0], "table")

    table = TableInfo(name=table_name)
    idx = 1
    total = len(lines)

    while idx < total:
        line = lines[idx]
        stripped = line.strip()
        indent = _indent_level(line)

        # ── Column ─────────────────────────────────────────────────
        if indent == 1 and stripped.startswith("column "):
            col, idx = _parse_column(lines, idx, table_name)
            table.columns.append(col)
            continue

        # ── Measure ────────────────────────────────────────────────
        if indent == 1 and stripped.startswith("measure "):
            meas, idx = _parse_measure(lines, idx, table_name)
            table.measures.append(meas)
            continue

        # ── Partition ──────────────────────────────────────────────
        if indent == 1 and stripped.startswith("partition "):
            part, idx = _parse_partition(lines, idx)
            table.partitions.append(part)
            continue

        # ── Hierarchy ──────────────────────────────────────────────
        if indent == 1 and stripped.startswith("hierarchy "):
            hier, idx = _parse_hierarchy(lines, idx)
            table.hierarchies.append(hier)
            continue

        # ── Calculation Group ─────────────────────────────────────
        if indent == 1 and stripped == "calculationGroup":
            cg, idx = _parse_calculation_group(lines, idx, table_name)
            table.calculation_group = cg
            continue

        idx += 1

    return table


# ── Column parser ──────────────────────────────────────────────────

def _parse_column(lines: List[str], start: int, table_name: str):
    """Parse a column block starting at *start*.

    Returns ``(ColumnInfo, next_index)``.
    """
    header = lines[start].strip()
    # Remove "column " prefix
    after_keyword = header[len("column "):].strip()

    name = ""
    dax_expr = None
    is_calculated = False

    if after_keyword.startswith("'"):
        # Quoted column name
        end_quote = after_keyword.index("'", 1)
        name = after_keyword[1:end_quote]
        remainder = after_keyword[end_quote + 1:].strip()
    else:
        # Unquoted – name ends at whitespace or '='
        m = re.match(r"(\S+)(.*)", after_keyword)
        name = m.group(1) if m else after_keyword
        remainder = (m.group(2) if m else "").strip()

    # Check for calculated column (= expression)
    if remainder.startswith("="):
        is_calculated = True
        dax_expr_start = remainder[1:].strip()
        # The expression may continue on subsequent lines
        idx = start + 1
        expr_lines = [dax_expr_start] if dax_expr_start else []
        # Check for triple-backtick block or continued indented lines
        if idx < len(lines) and lines[idx].strip() == "```":
            idx += 1
            while idx < len(lines):
                if lines[idx].strip() == "```":
                    idx += 1
                    break
                expr_lines.append(lines[idx])
                idx += 1
            dax_expr = _dedent_block(expr_lines)
        else:
            # Collect continuation lines (indent > 2, i.e. \t\t\t)
            while idx < len(lines) and _indent_level(lines[idx]) >= 3:
                expr_lines.append(lines[idx])
                idx += 1
            dax_expr = _dedent_block(expr_lines)
    else:
        idx = start + 1

    col = ColumnInfo(
        name=name,
        is_calculated=is_calculated,
        dax_expression=dax_expr,
    )

    # ── Read properties (indent == 2) ──────────────────────────────
    total = len(lines)
    while idx < total:
        pline = lines[idx]
        pindent = _indent_level(pline)
        if pindent < 2:
            break
        ps = pline.strip()

        if ps.startswith("dataType:"):
            col.data_type = ps.split(":", 1)[1].strip()
        elif ps.startswith("sourceColumn:"):
            col.source_column = _unquote(ps.split(":", 1)[1].strip())
        elif ps.startswith("sortByColumn:"):
            col.sort_by_column = _unquote(ps.split(":", 1)[1].strip())
        elif ps.startswith("formatString:"):
            col.format_string = _extract_property_value(ps, "formatString:")
        elif ps.startswith("isKey:"):
            col.is_key = ps.split(":", 1)[1].strip().lower() == "true"
        elif ps.startswith("summarizeBy:"):
            col.summarize_by = ps.split(":", 1)[1].strip()

        idx += 1

    return col, idx


def _extract_property_value(line: str, prop: str) -> str:
    """Extract the value after a property key, handling quoted strings."""
    val = line.split(prop, 1)[1].strip()
    # TMDL sometimes quotes format strings: formatString: "0.00"
    if val.startswith('"') and val.endswith('"'):
        val = val[1:-1]
    return val


# ── Measure parser ─────────────────────────────────────────────────

def _parse_measure(lines: List[str], start: int, table_name: str):
    """Parse a measure block starting at *start*.

    Returns ``(MeasureInfo, next_index)``.
    """
    header = lines[start].strip()
    after_keyword = header[len("measure "):].strip()

    # Extract name (before the '=')
    if after_keyword.startswith("'"):
        end_quote = after_keyword.index("'", 1)
        name = after_keyword[1:end_quote]
        remainder = after_keyword[end_quote + 1:].strip()
    else:
        eq_pos = after_keyword.find("=")
        if eq_pos >= 0:
            name = after_keyword[:eq_pos].strip()
            remainder = after_keyword[eq_pos:].strip()
        else:
            # No '=' on this line — name is everything, no inline expression
            name = after_keyword.strip()
            remainder = ""

    # Remove leading '='
    if remainder.startswith("="):
        remainder = remainder[1:].strip()

    # Collect expression
    idx = start + 1
    total = len(lines)
    expr_lines = [remainder] if remainder else []

    # Check for triple-backtick block on the next line
    if idx < total and lines[idx].strip() == "```":
        idx += 1
        while idx < total:
            if lines[idx].strip() == "```":
                idx += 1
                break
            expr_lines.append(lines[idx])
            idx += 1
    else:
        # Collect continuation lines at indent >= 3
        while idx < total and _indent_level(lines[idx]) >= 3:
            expr_lines.append(lines[idx])
            idx += 1

    expression = _dedent_block(expr_lines)

    meas = MeasureInfo(
        name=name,
        expression=expression,
        table_name=table_name,
    )

    # ── Read remaining properties (indent == 2) ───────────────────
    while idx < total:
        pline = lines[idx]
        if _indent_level(pline) < 2:
            break
        ps = pline.strip()
        if ps.startswith("formatString:"):
            meas.format_string = _extract_property_value(ps, "formatString:")
        idx += 1

    return meas, idx


# ── Partition parser ───────────────────────────────────────────────

def _parse_partition(lines: List[str], start: int):
    """Parse a partition block starting at *start*.

    Returns ``(MQueryInfo, next_index)``.
    """
    header = lines[start].strip()
    after_keyword = header[len("partition "):].strip()

    # Name is everything before '='
    eq_idx = after_keyword.index("=")
    name = _unquote(after_keyword[:eq_idx].strip())
    part_type = after_keyword[eq_idx + 1:].strip().lower()  # 'm', 'calculated', 'entity', ...

    is_calculated = part_type.startswith("calculated")

    part = MQueryInfo(
        partition_name=name,
        is_calculated=is_calculated,
    )

    idx = start + 1
    total = len(lines)

    while idx < total:
        pline = lines[idx]
        pindent = _indent_level(pline)
        if pindent < 2:
            break
        ps = pline.strip()

        if ps.startswith("mode:"):
            part.mode = ps.split(":", 1)[1].strip()
        elif ps.startswith("source"):
            # Could be "source =" or "source="
            src_match = re.match(r"source\s*=", ps)
            if src_match:
                inline = ps[src_match.end():].strip()
                idx += 1
                # Collect the source expression
                expr_lines = [inline] if inline else []

                # Check for triple-backtick block
                if idx < total and lines[idx].strip() == "```":
                    idx += 1
                    while idx < total:
                        if lines[idx].strip() == "```":
                            idx += 1
                            break
                        expr_lines.append(lines[idx])
                        idx += 1
                else:
                    # Collect indented continuation lines
                    while idx < total and _indent_level(lines[idx]) >= 3:
                        expr_lines.append(lines[idx])
                        idx += 1

                source_text = _dedent_block(expr_lines)
                if is_calculated:
                    part.dax_expression = source_text
                else:
                    part.source_code = source_text
                continue
            idx += 1
            continue

        idx += 1

    return part, idx


# ── Calculation Group parser ───────────────────────────────────────

def _parse_calculation_group(lines: List[str], start: int, table_name: str):
    """Parse a calculationGroup block starting at *start*.

    Returns ``(CalculationGroupInfo, next_index)``.
    """
    cg = CalculationGroupInfo(table_name=table_name)

    idx = start + 1
    total = len(lines)

    while idx < total:
        pline = lines[idx]
        pindent = _indent_level(pline)
        if pindent < 2:
            break
        ps = pline.strip()

        # ── calculationItem header at indent 2 ────────────────────
        if pindent == 2 and ps.startswith("calculationItem "):
            item_name, _ = _parse_name_from_header(ps, "calculationItem")
            item = CalculationItem(name=item_name)
            idx += 1

            # Read item properties at indent >= 3
            while idx < total:
                iline = lines[idx]
                iindent = _indent_level(iline)
                if iindent < 3:
                    break
                ips = iline.strip()

                if ips.startswith("expression") and "=" in ips:
                    # expression = <inline or multi-line DAX>
                    eq_pos = ips.index("=")
                    inline = ips[eq_pos + 1:].strip()
                    idx += 1
                    expr_lines = [inline] if inline else []

                    # Check for triple-backtick block
                    if idx < total and lines[idx].strip() == "```":
                        idx += 1
                        while idx < total:
                            if lines[idx].strip() == "```":
                                idx += 1
                                break
                            expr_lines.append(lines[idx])
                            idx += 1
                    else:
                        # Collect indented continuation lines
                        while idx < total and _indent_level(lines[idx]) >= 4:
                            expr_lines.append(lines[idx])
                            idx += 1

                    item.expression = _dedent_block(expr_lines)
                    continue

                elif ips.startswith("ordinal") and "=" in ips:
                    eq_pos = ips.index("=")
                    val = ips[eq_pos + 1:].strip()
                    try:
                        item.ordinal = int(val)
                    except ValueError:
                        pass

                idx += 1

            cg.items.append(item)
            continue

        # ── column property on the calculationGroup itself ────────
        if ps.startswith("column:"):
            cg.column_name = _unquote(ps.split(":", 1)[1].strip())

        idx += 1

    # Sort items by ordinal
    cg.items.sort(key=lambda i: i.ordinal)

    return cg, idx


# ── Hierarchy parser ───────────────────────────────────────────────

def _parse_hierarchy(lines: List[str], start: int):
    """Parse a hierarchy block starting at *start*.

    Returns ``(dict, next_index)`` where the dict has ``name`` and
    ``levels`` keys.
    """
    header = lines[start].strip()
    name, _ = _parse_name_from_header(header, "hierarchy")

    hier = {"name": name, "levels": []}

    idx = start + 1
    total = len(lines)

    while idx < total:
        pline = lines[idx]
        pindent = _indent_level(pline)
        if pindent < 2:
            break
        ps = pline.strip()

        if ps.startswith("level "):
            level_name, _ = _parse_name_from_header(ps, "level")
            level = {"name": level_name, "column": None}
            idx += 1
            # Read level properties
            while idx < total and _indent_level(lines[idx]) >= 3:
                lps = lines[idx].strip()
                if lps.startswith("column:"):
                    level["column"] = _unquote(lps.split(":", 1)[1].strip())
                idx += 1
            hier["levels"].append(level)
            continue

        idx += 1

    return hier, idx


# ────────────────────────────────────────────────────────────────────
# Relationships parser
# ────────────────────────────────────────────────────────────────────

def _parse_relationships_file(path: str) -> List[RelationshipInfo]:
    """Parse ``definition/relationships.tmdl`` and return a list of
    :class:`RelationshipInfo` objects."""
    if not os.path.isfile(path):
        return []

    lines = _read_file(path)
    relationships: List[RelationshipInfo] = []
    idx = 0
    total = len(lines)

    while idx < total:
        line = lines[idx]
        stripped = line.strip()

        if stripped.startswith("relationship "):
            rel = RelationshipInfo()
            idx += 1
            while idx < total:
                pline = lines[idx]
                pindent = _indent_level(pline)
                if pindent < 1:
                    break
                ps = pline.strip()

                if ps.startswith("fromColumn:"):
                    ref = ps.split(":", 1)[1].strip()
                    rel.from_table, rel.from_column = _split_table_column(ref)
                elif ps.startswith("toColumn:"):
                    ref = ps.split(":", 1)[1].strip()
                    rel.to_table, rel.to_column = _split_table_column(ref)
                elif ps.startswith("crossFilteringBehavior:"):
                    val = ps.split(":", 1)[1].strip().lower()
                    rel.cross_filter = "Both" if "both" in val else "Single"
                elif ps.startswith("toCardinality:"):
                    rel.to_cardinality = ps.split(":", 1)[1].strip().lower()

                idx += 1

            relationships.append(rel)
            continue

        idx += 1

    return relationships


# ────────────────────────────────────────────────────────────────────
# Expressions parser  (parameters & helper functions)
# ────────────────────────────────────────────────────────────────────

def _parse_expressions_file(path: str):
    """Parse ``definition/expressions.tmdl``.

    Returns ``(parameters, functions)`` – two lists of
    :class:`ParameterInfo` and :class:`FunctionInfo` respectively.
    """
    if not os.path.isfile(path):
        return [], []

    lines = _read_file(path)
    parameters: List[ParameterInfo] = []
    functions: List[FunctionInfo] = []

    idx = 0
    total = len(lines)

    while idx < total:
        line = lines[idx]
        stripped = line.strip()

        if stripped.startswith("expression "):
            name, remainder = _parse_name_from_header(stripped, "expression")

            # Collect the full expression body (value + meta)
            idx += 1
            body_lines = [remainder] if remainder else []

            # Check for triple-backtick block
            if idx < total and lines[idx].strip() == "```":
                idx += 1
                while idx < total:
                    if lines[idx].strip() == "```":
                        idx += 1
                        break
                    body_lines.append(lines[idx])
                    idx += 1
            else:
                # Collect indented continuation lines (indent >= 2)
                while idx < total and _indent_level(lines[idx]) >= 2:
                    body_lines.append(lines[idx])
                    idx += 1

            full_body = _dedent_block(body_lines)

            # ── Collect any remaining properties at indent 1 ──────
            # (e.g. lineageTag, queryGroup, …)
            meta_lines: List[str] = []
            while idx < total and _indent_level(lines[idx]) >= 1 and not lines[idx].strip().startswith("expression "):
                meta_lines.append(lines[idx])
                idx += 1

            meta_text = " ".join(l.strip() for l in meta_lines)
            combined = full_body + " " + meta_text

            # ── Decide: parameter or function ─────────────────────
            if "IsParameterQuery=true" in combined or "IsParameterQuery = true" in combined:
                param = _build_parameter(name, full_body, combined)
                parameters.append(param)
            else:
                # Strip "= " prefix if present
                code = full_body
                if code.startswith("="):
                    code = code[1:].strip()
                functions.append(FunctionInfo(name=name, code=code))
            continue

        idx += 1

    return parameters, functions


def _build_parameter(name: str, body: str, combined: str) -> ParameterInfo:
    """Build a :class:`ParameterInfo` from the raw expression body."""
    param = ParameterInfo(name=name)

    # Default value: text between first '=' and 'meta' (or end)
    val_match = re.search(r"=\s*(.*?)(?:\s+meta\s+|$)", body, re.DOTALL)
    if val_match:
        raw_val = val_match.group(1).strip().strip('"').strip("'")
        param.default_value = raw_val

    # Type from meta
    type_match = re.search(r'Type\s*=\s*"([^"]*)"', combined)
    if type_match:
        param.type = type_match.group(1)
    else:
        type_match2 = re.search(r"Type\s*=\s*type\s+(\w+)", combined)
        if type_match2:
            param.type = type_match2.group(1)

    # IsParameterQueryRequired
    if "IsParameterQueryRequired=true" in combined or "IsParameterQueryRequired = true" in combined:
        param.is_required = True

    # Allowed values from List
    list_match = re.search(r"List\s*=\s*\{([^}]*)\}", combined)
    if list_match:
        raw_list = list_match.group(1)
        param.allowed_values = [
            v.strip().strip('"').strip("'")
            for v in raw_list.split(",")
            if v.strip()
        ]

    return param


# ────────────────────────────────────────────────────────────────────
# Main model class
# ────────────────────────────────────────────────────────────────────

class TmdlModel:
    """Top-level entry point: parse a full SemanticModel folder.

    Parameters
    ----------
    semantic_model_path : str
        Path to the ``*.SemanticModel`` folder (must contain a
        ``definition/`` subfolder).

    Attributes
    ----------
    name : str
        The model name (derived from the folder name, minus the
        ``.SemanticModel`` suffix).
    tables : list[TableInfo]
    relationships : list[RelationshipInfo]
    parameters : list[ParameterInfo]
    helper_functions : list[FunctionInfo]
    """

    def __init__(self, semantic_model_path: str):
        self.path = os.path.normpath(semantic_model_path)
        folder_name = os.path.basename(self.path)
        self.name = re.sub(r"\.SemanticModel$", "", folder_name, flags=re.IGNORECASE)

        self.tables: List[TableInfo] = []
        self.relationships: List[RelationshipInfo] = []
        self.parameters: List[ParameterInfo] = []
        self.helper_functions: List[FunctionInfo] = []

        self._parse()

    # ── Factory method ─────────────────────────────────────────────

    @classmethod
    def from_pbip_folder(cls, pbip_input: str) -> "TmdlModel":
        """Resolve the ``*.SemanticModel`` folder from a .pbip file or a folder,
        and parse it.

        Raises ValueError/FileNotFoundError if no SemanticModel folder is found
        or if it uses the older TMSL format.
        """
        pbip_input = os.path.abspath(os.path.normpath(pbip_input))
        
        # 1. Determine the search base
        if os.path.isfile(pbip_input) and pbip_input.lower().endswith(".pbip"):
            search_base = os.path.dirname(pbip_input)
            target_stem = Path(pbip_input).stem.lower()
        else:
            search_base = pbip_input
            target_stem = None
            
        # If the given input is already a SemanticModel or Dataset folder, use it directly
        if os.path.isdir(pbip_input) and (pbip_input.lower().endswith(".semanticmodel") or pbip_input.lower().endswith(".dataset")):
            model_folder = pbip_input
        else:
            # 2. Search for matching folders (*.SemanticModel or *.Dataset)
            candidates = []
            try:
                for entry in os.scandir(search_base):
                    if entry.is_dir():
                        name_lower = entry.name.lower()
                        if name_lower.endswith(".semanticmodel") or name_lower.endswith(".dataset"):
                            candidates.append(entry.path)
            except OSError as e:
                raise FileNotFoundError(f"Could not read directory {search_base}: {e}")
            
            if not candidates:
                raise FileNotFoundError(
                    f"No *.SemanticModel or *.Dataset folder found in directory: '{search_base}'.\n"
                    "Please ensure the project contains a SemanticModel directory."
                )
            
            if len(candidates) == 1:
                model_folder = candidates[0]
            else:
                if target_stem:
                    # Try to find one matching the pbip stem
                    matches = [c for c in candidates if Path(c).stem.lower() == target_stem]
                    if len(matches) == 1:
                        model_folder = matches[0]
                    else:
                        raise ValueError(f"Multiple SemanticModel folders found in '{search_base}'. Could not resolve unambiguously.")
                else:
                    raise ValueError(f"Multiple SemanticModel folders found in '{search_base}'. Please specify the folder directly.")

        # 3. Check layout inside model_folder
        defn_dir = os.path.join(model_folder, "definition")
        bim_file = os.path.join(model_folder, "model.bim")
        
        if os.path.isdir(defn_dir):
            return cls(model_folder)
        elif os.path.isfile(bim_file):
            raise ValueError(
                f"The project at '{model_folder}' uses the older TMSL (model.bim) format.\n\n"
                "To fix this: Open the .pbip in Power BI Desktop, go to File > Options > Preview features, "
                "enable 'Store semantic model using TMDL format', and save the project again."
            )
        else:
            raise FileNotFoundError(f"Invalid SemanticModel directory: '{model_folder}'. Missing 'definition' folder.")

    # ── Internal parsing orchestration ─────────────────────────────

    def _parse(self):
        """Orchestrate parsing of all TMDL files."""
        defn = os.path.join(self.path, "definition")
        if not os.path.isdir(defn):
            return

        # 1. Tables
        tables_dir = os.path.join(defn, "tables")
        if os.path.isdir(tables_dir):
            for tmdl_file in sorted(glob.glob(os.path.join(tables_dir, "*.tmdl"))):
                table = _parse_table_file(tmdl_file)
                self.tables.append(table)

        # 2. Relationships
        rel_path = os.path.join(defn, "relationships.tmdl")
        self.relationships = _parse_relationships_file(rel_path)

        # 3. Expressions (parameters + functions)
        expr_path = os.path.join(defn, "expressions.tmdl")
        self.parameters, self.helper_functions = _parse_expressions_file(expr_path)

    # ── Convenience helpers ────────────────────────────────────────

    def get_table(self, name: str) -> Optional[TableInfo]:
        """Return the table with the given name, or ``None``."""
        for t in self.tables:
            if t.name == name:
                return t
        return None

    def calculation_groups(self) -> List[CalculationGroupInfo]:
        """Return a list of all calculation groups across all tables."""
        return [t.calculation_group for t in self.tables if t.calculation_group is not None]

    def all_measures(self) -> List[MeasureInfo]:
        """Return a flat list of all measures across all tables."""
        return [m for t in self.tables for m in t.measures]

    def all_columns(self) -> List[ColumnInfo]:
        """Return a flat list of all columns across all tables."""
        return [c for t in self.tables for c in t.columns]

    def calculated_columns(self) -> List[ColumnInfo]:
        """Return all calculated columns across all tables."""
        return [c for c in self.all_columns() if c.is_calculated]

    def summary(self) -> str:
        """Return a human-readable summary of the model."""
        parts = [
            f"Model: {self.name}",
            f"  Tables:          {len(self.tables)}",
            f"  Columns:         {len(self.all_columns())}",
            f"  Calc. columns:   {len(self.calculated_columns())}",
            f"  Measures:        {len(self.all_measures())}",
            f"  Relationships:   {len(self.relationships)}",
            f"  Parameters:      {len(self.parameters)}",
            f"  Helper functions: {len(self.helper_functions)}",
        ]
        return "\n".join(parts)

    def __repr__(self):
        return (
            f"TmdlModel(name={self.name!r}, tables={len(self.tables)}, "
            f"relationships={len(self.relationships)}, "
            f"parameters={len(self.parameters)}, "
            f"functions={len(self.helper_functions)})"
        )


# ────────────────────────────────────────────────────────────────────
# CLI quick test
# ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python tmdl_parser.py <path-to-SemanticModel-folder>")
        sys.exit(1)

    model = TmdlModel(sys.argv[1])
    print(model.summary())
    print()
    for t in model.tables:
        print(f"  Table: {t.name}")
        for c in t.columns:
            calc = " [CALC]" if c.is_calculated else ""
            print(f"    Column: {c.name} ({c.data_type}){calc}")
        for m in t.measures:
            print(f"    Measure: {m.name}")
        for p in t.partitions:
            tag = "DAX" if p.is_calculated else "M"
            print(f"    Partition: {p.partition_name} ({tag}, {p.mode})")
    print()
    for r in model.relationships:
        print(f"  Rel: {r.from_table}.{r.from_column} -> {r.to_table}.{r.to_column} ({r.cross_filter}, to={r.to_cardinality})")
    for p in model.parameters:
        print(f"  Param: {p.name} = {p.default_value!r} (type={p.type})")
    for f in model.helper_functions:
        print(f"  Func: {f.name}")
