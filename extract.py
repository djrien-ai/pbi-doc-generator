#!/usr/bin/env python3
"""
PBI Metadata Extractor
======================
Generates a standalone HTML data documentation page directly from a
Power BI .pbix file.

Usage:
    python extract.py <path_to.pbix>  [--output <output.html>]

    # Or via GUI:
    python gui.py
"""

import argparse
import os
import sys
import re
import html as html_module
from pathlib import Path

from html_template import generate_html

# ---------------------------------------------------------------------------
# Fix for pbixray 0.1.21: add support for "multithreaded XPrs9" DataModel
# format.  The shipped version only handles single-threaded Xpress9.
# Algorithm ported from pbixray >=0.10 (loader.py).
# ---------------------------------------------------------------------------
import ctypes
import zipfile
from pbixray.pbix_unpacker import PbixUnpacker
from pbixray.abf import parser as _abf_parser
from pbixray.abf.data_model import DataModel


def _detect_compression(dm):
    """Read the first 102 bytes and decide: single / multi / uncompressed."""
    dm.seek(0)
    header = dm.read(102)
    text = header.decode('utf-16-le', errors='replace').rstrip('\x00')
    dm.seek(0)
    if 'multithreaded' in text.lower():
        return 'multi'
    if 'xprs9' in text.lower() or 'xpress9' in text.lower():
        return 'single'
    return 'uncompressed'


def _decompress_chunk(lib, compressed_data, compressed_size, uncompressed_size):
    """Decompress a single chunk using libxpress9."""
    compressed_buffer = (ctypes.c_ubyte * compressed_size)(*compressed_data)
    decompressed_buffer = (ctypes.c_ubyte * uncompressed_size)()
    result = lib.Decompress(compressed_buffer, compressed_size,
                            decompressed_buffer, uncompressed_size)
    if result != uncompressed_size:
        raise RuntimeError(
            f"Expected {uncompressed_size} bytes after decompression, "
            f"but got {result} bytes")
    return bytes(decompressed_buffer)


def _process_single_threaded(lib, dm):
    """Original single-threaded Xpress9 decompression."""
    all_data = bytearray()
    total_size = dm.seek(0, 2)
    dm.seek(102)
    while dm.tell() < total_size:
        raw = dm.read(8)
        if len(raw) < 8:
            break
        uncompressed_size = int.from_bytes(raw[:4], 'little')
        compressed_size = int.from_bytes(raw[4:], 'little')
        compressed_data = dm.read(compressed_size)
        all_data.extend(
            _decompress_chunk(lib, compressed_data, compressed_size,
                              uncompressed_size))
    return all_data


def _process_multi_threaded(lib, dm):
    """Multi-threaded XPrs9 decompression (ported from pbixray >=0.10)."""
    dm.seek(102)
    main_chunks_per_thread = int.from_bytes(dm.read(8), 'little')
    prefix_chunks_per_thread = int.from_bytes(dm.read(8), 'little')
    prefix_thread_count = int.from_bytes(dm.read(8), 'little')
    main_thread_count = int.from_bytes(dm.read(8), 'little')
    _chunk_uncompressed_size = int.from_bytes(dm.read(8), 'little')

    all_data = bytearray()

    # --- prefix chunks ---
    total_prefix = prefix_thread_count * prefix_chunks_per_thread
    if total_prefix > 0:
        chunks = []
        for _ in range(total_prefix):
            uncomp = int.from_bytes(dm.read(4), 'little')
            comp = int.from_bytes(dm.read(4), 'little')
            cdata = dm.read(comp)
            chunks.append((uncomp, cdata, comp))
        # Process per thread-group, in order
        for t in range(prefix_thread_count):
            lib.Initialize()
            start = t * prefix_chunks_per_thread
            end = start + prefix_chunks_per_thread
            for uncomp, cdata, comp in chunks[start:end]:
                all_data.extend(
                    _decompress_chunk(lib, cdata, comp, uncomp))
            lib.Terminate()

    # --- main chunks ---
    total_main = main_thread_count * main_chunks_per_thread
    if total_main > 0:
        chunks = []
        for _ in range(total_main):
            uncomp = int.from_bytes(dm.read(4), 'little')
            comp = int.from_bytes(dm.read(4), 'little')
            cdata = dm.read(comp)
            chunks.append((uncomp, cdata, comp))
        for t in range(main_thread_count):
            lib.Initialize()
            start = t * main_chunks_per_thread
            end = start + main_chunks_per_thread
            for uncomp, cdata, comp in chunks[start:end]:
                all_data.extend(
                    _decompress_chunk(lib, cdata, comp, uncomp))
            lib.Terminate()

    return all_data


def _patched_unpack(self):
    with zipfile.ZipFile(self.file_path, 'r') as zip_ref:
        with zip_ref.open('DataModel') as dm:
            mode = _detect_compression(dm)

            if mode == 'uncompressed':
                dm.seek(0)
                self._data_model.decompressed_data = bytearray(dm.read())
            elif mode == 'multi':
                self._data_model.decompressed_data = \
                    _process_multi_threaded(self.lib, dm)
            else:  # single
                self.lib.Initialize()
                self._data_model.decompressed_data = \
                    _process_single_threaded(self.lib, dm)
                self.lib.Terminate()

    _abf_parser.AbfParser(self._data_model)

PbixUnpacker._PbixUnpacker__unpack = _patched_unpack


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _esc(text):
    """HTML-escape a string."""
    if text is None:
        return ""
    return html_module.escape(str(text))

def _code(text):
    """Wrap text in <code> tags."""
    return f"<code>{_esc(text)}</code>"

def _safe_id(name):
    """Create a safe HTML id from a table/column name."""
    return "".join(c if c.isalnum() else "_" for c in str(name))


# ---------------------------------------------------------------------------
# M-query step parser
# ---------------------------------------------------------------------------

def _parse_m_steps(m_code):
    """Parse Power Query M code into named steps."""
    steps = []
    if not m_code or "let" not in m_code.lower():
        return []
    pattern = re.compile(
        r'(?:^|\n)\s*(#"[^"]+"|[A-Za-z_]\w*)\s*=\s*(.+?)(?=\n\s*(?:#"[^"]+"|[A-Za-z_]\w*)\s*=|\n\s*in\b|$)',
        re.DOTALL
    )
    for name, expr in pattern.findall(m_code):
        name = name.strip().strip('"').lstrip('#').strip('"')
        expr = expr.strip().rstrip(',')
        steps.append((name, expr))
    return steps


def _extract_hana_info(m_code):
    """Extract HANA package, view name, connection from M code."""
    if not m_code:
        return ("--", "--", "--")

    package = "--"
    view = "--"
    connection = "via parameter"

    if 'SapHana.Database("' in m_code or "SapHana.Database('" in m_code:
        connection = "hardcoded"
    elif "SapHana.Database(HanaServer" in m_code:
        connection = "via HanaServer param"

    names = re.findall(r'\{?\[Name="([^"]+)"\]\}?\[Data\]', m_code)
    if names:
        names = [n for n in names if n != "Contents"]
        if len(names) >= 2:
            package = names[-2]
            view = names[-1]
        elif len(names) == 1:
            package = names[0]

    if "&HanaPackage&" in m_code or '""&HanaPackage&""' in m_code:
        package = "(via HanaPackage param)"
    if "&HanaView&" in m_code or '""&HanaView&""' in m_code:
        view = "(via HanaView param)"

    return (package, view, connection)


# ---------------------------------------------------------------------------
# Section builders — each returns (section_html, sidebar_html)
# ---------------------------------------------------------------------------

def build_data_sources(pq_df, dax_tables_df, m_params_df):
    """Section 1: Data Sources."""
    h = ""
    sidebar_items = []

    # Classify tables
    hana_tables = []
    manual_tables = []
    computed_tables = []
    param_tables = []

    pq_dict = dict(zip(pq_df['TableName'], pq_df['Expression']))

    dax_table_names = set()
    if dax_tables_df is not None and len(dax_tables_df) > 0:
        dax_table_names = set(dax_tables_df['TableName'].tolist())

    # Separate params/functions from real tables in m_parameters
    real_params = []
    helper_funcs = []
    if m_params_df is not None and len(m_params_df) > 0:
        for _, row in m_params_df.iterrows():
            name = row['ParameterName']
            expr = str(row.get('Expression', ''))
            if 'meta [IsParameterQuery=true' in expr or expr.startswith('"'):
                real_params.append(row)
            elif '(' in name or 'let' in expr.lower() or '=>' in expr:
                helper_funcs.append(row)
            elif expr.strip().startswith('"') and 'meta' in expr:
                real_params.append(row)
            else:
                helper_funcs.append(row)

    for tbl_name, m_code in pq_dict.items():
        if tbl_name in dax_table_names:
            continue  # DAX table, skip here

        if "SapHana.Database" in m_code:
            hana_tables.append((tbl_name, m_code))
        elif "Binary.Decompress" in m_code or "Table.FromRows(Json" in m_code:
            manual_tables.append((tbl_name, m_code))
        elif "FnCreateDateTable" in m_code:
            computed_tables.append((tbl_name, m_code))
        elif "#table(type table" in m_code and "DateTime.LocalNow" in m_code:
            manual_tables.append((tbl_name, m_code))
        elif len(m_code.strip()) < 100 and ("Table.FromRows" in m_code or "Table.RemoveColumns" in m_code):
            manual_tables.append((tbl_name, m_code))
        else:
            computed_tables.append((tbl_name, m_code))

    # Add DAX computed tables
    if dax_tables_df is not None:
        for _, row in dax_tables_df.iterrows():
            computed_tables.append((row['TableName'], row.get('Expression', '')))

    # --- 1.1 HANA Views ---
    sec_id = "sec1-1"
    sidebar_items.append(f'<li><a href="#{sec_id}">1.1 SAP HANA Views</a></li>')
    h += f'<h3 id="{sec_id}">1.1 SAP HANA Views (Primary Source) <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'

    if hana_tables:
        h += "<table>\n<thead><tr><th>#</th><th>Table Name</th><th>HANA Package</th><th>HANA View</th><th>Connection</th></tr></thead>\n<tbody>\n"
        for i, (tbl_name, m_code) in enumerate(hana_tables, 1):
            pkg, view, conn = _extract_hana_info(m_code)
            h += f'<tr><td>{i}</td><td><strong><a href="#sec2-tbl-{_safe_id(tbl_name)}">{_esc(tbl_name)}</a></strong></td>'
            h += f'<td>{_code(pkg)}</td><td>{_code(view)}</td><td>{_esc(conn)}</td></tr>\n'
        h += "</tbody></table>\n"
    else:
        h += "<p><em>No HANA views detected.</em></p>\n"

    # --- 1.2 Manual Tables ---
    if manual_tables:
        sec_id = "sec1-2"
        sidebar_items.append(f'<li><a href="#{sec_id}">1.2 Manual Tables</a></li>')
        h += f'<hr>\n<h3 id="{sec_id}">1.2 Manual / Hardcoded Tables <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += "<table>\n<thead><tr><th>#</th><th>Table</th><th>Type</th></tr></thead>\n<tbody>\n"
        for i, (tbl_name, m_code) in enumerate(manual_tables, 1):
            ttype = "Base64 encoded" if "Binary.Decompress" in m_code else "Inline M"
            h += f'<tr><td>{i}</td><td><strong>{_esc(tbl_name)}</strong></td><td>{_esc(ttype)}</td></tr>\n'
        h += "</tbody></table>\n"

    # --- 1.3 Computed Tables ---
    if computed_tables:
        sec_id = "sec1-3"
        sidebar_items.append(f'<li><a href="#{sec_id}">1.3 Computed Tables</a></li>')
        h += f'<hr>\n<h3 id="{sec_id}">1.3 Computed / Derived Tables <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += "<table>\n<thead><tr><th>#</th><th>Table</th><th>Source</th><th>Type</th></tr></thead>\n<tbody>\n"
        for i, (tbl_name, expr) in enumerate(computed_tables, 1):
            is_dax = tbl_name in dax_table_names
            src = expr.strip()[:80] + "..." if len(expr.strip()) > 80 else expr.strip()
            ttype = "DAX Calculated Table" if is_dax else "M (Power Query)"
            h += f'<tr><td>{i}</td><td><strong><a href="#sec2-tbl-{_safe_id(tbl_name)}">{_esc(tbl_name)}</a></strong></td>'
            h += f'<td>{_code(src)}</td><td>{_esc(ttype)}</td></tr>\n'
        h += "</tbody></table>\n"

    # --- 1.4 Parameters ---
    if real_params:
        sec_id = "sec1-4"
        sidebar_items.append(f'<li><a href="#{sec_id}">1.4 Parameters</a></li>')
        h += f'<hr>\n<h3 id="{sec_id}">1.4 Parameters <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += "<table>\n<thead><tr><th>Parameter</th><th>Expression</th></tr></thead>\n<tbody>\n"
        for row in real_params:
            h += f'<tr><td>{_code(row["ParameterName"])}</td><td>{_code(str(row.get("Expression",""))[:150])}</td></tr>\n'
        h += "</tbody></table>\n"

    # --- 1.5 Helper Functions ---
    if helper_funcs:
        sec_id = "sec1-5"
        sidebar_items.append(f'<li><a href="#{sec_id}">1.5 Helper Functions</a></li>')
        h += f'<hr>\n<h3 id="{sec_id}">1.5 Helper Functions <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += "<table>\n<thead><tr><th>Function</th><th>Description</th></tr></thead>\n<tbody>\n"
        for row in helper_funcs:
            desc = str(row.get("Description", "")) or "Custom M function"
            h += f'<tr><td>{_code(row["ParameterName"])}</td><td>{_esc(desc)}</td></tr>\n'
        h += "</tbody></table>\n"

    sidebar = f'<li><a href="#sec1">1. Data Sources</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="sec1">1. Data Sources <a href="#sec1" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_transformations(pq_df, dax_tables_df):
    """Section 2: Power Query step-by-step per table."""
    h = ""
    sidebar_items = []

    dax_table_names = set()
    if dax_tables_df is not None and len(dax_tables_df) > 0:
        dax_table_names = set(dax_tables_df['TableName'].tolist())
    dax_dict = {}
    if dax_tables_df is not None and len(dax_tables_df) > 0:
        dax_dict = dict(zip(dax_tables_df['TableName'], dax_tables_df['Expression']))

    idx = 1
    # M query tables first
    for _, row in pq_df.iterrows():
        tbl = row['TableName']
        m_code = row['Expression']
        if tbl in dax_table_names:
            continue

        sec_id = f"sec2-tbl-{_safe_id(tbl)}"
        sidebar_items.append(f'<li><a href="#{sec_id}">2.{idx} {_esc(tbl)}</a></li>')
        h += f'<h3 id="{sec_id}">2.{idx} {_esc(tbl)} <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'

        steps = _parse_m_steps(m_code)
        if steps:
            h += "<ol>\n"
            for step_name, step_expr in steps:
                display = step_expr[:250]
                if len(step_expr) > 250:
                    display += "..."
                h += f"  <li><strong>{_esc(step_name)}</strong>: {_code(display)}</li>\n"
            h += "</ol>\n"
        else:
            h += f"<pre><code>{_esc(m_code.strip()[:500])}</code></pre>\n"

        # Warn about hardcoded connections
        if 'SapHana.Database("' in m_code or "SapHana.Database('" in m_code:
            h += '<div class="alert alert-warning"><div class="alert-title">Warning</div>'
            h += 'This table has a <strong>hardcoded</strong> HANA connection instead of using a parameter.</div>\n'

        h += "<hr>\n"
        idx += 1

    # DAX calculated tables
    for tbl_name, dax_expr in dax_dict.items():
        sec_id = f"sec2-tbl-{_safe_id(tbl_name)}"
        sidebar_items.append(f'<li><a href="#{sec_id}">2.{idx} {_esc(tbl_name)}</a></li>')
        h += f'<h3 id="{sec_id}">2.{idx} {_esc(tbl_name)} (DAX Calculated Table) <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += f"<pre><code>{_esc(dax_expr.strip())}</code></pre>\n<hr>\n"
        idx += 1

    sidebar = f'<li><a href="#sec2">2. Power Query Transformations</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="sec2">2. Power Query Transformations (Modeling) <a href="#sec2" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_relationships(rel_df):
    """Section 3: Relationships + Mermaid diagram."""
    h = ""

    if rel_df is None or len(rel_df) == 0:
        h += "<p><em>No relationships found.</em></p>\n"
        sidebar = '<li><a href="#sec3">3. Relationships</a></li>'
        section = f'<h2 id="sec3">3. Relationships <a href="#sec3" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar

    # Filter out rows with NaN values
    rel_df = rel_df.dropna(subset=['FromTableName', 'ToTableName', 'FromColumnName', 'ToColumnName'])

    h += "<table>\n<thead><tr><th>#</th><th>From Table</th><th>From Column</th><th>--</th><th>To Table</th><th>To Column</th><th>Cross-Filter</th></tr></thead>\n<tbody>\n"
    for i, (_, row) in enumerate(rel_df.iterrows(), 1):
        cf_raw = str(row.get('CrossFilteringBehavior', '1'))
        cf = "<strong>Both</strong>" if cf_raw == '2' or 'both' in cf_raw.lower() else "Single"
        h += f'<tr><td>{i}</td><td>{_esc(str(row["FromTableName"]))}</td><td>{_code(str(row["FromColumnName"]))}</td><td>--</td>'
        h += f'<td>{_esc(str(row["ToTableName"]))}</td><td>{_code(str(row["ToColumnName"]))}</td><td>{cf}</td></tr>\n'
    h += "</tbody></table>\n"

    # Mermaid diagram
    h += "<h4>Data Model Diagram</h4>\n"
    h += '<pre class="mermaid">\ngraph LR\n'
    all_tables = set()
    for _, row in rel_df.iterrows():
        all_tables.add(str(row['FromTableName']))
        all_tables.add(str(row['ToTableName']))
    for tbl in sorted(all_tables):
        h += f'    {_safe_id(tbl)}["{_esc(tbl)}"]\n'
    for _, row in rel_df.iterrows():
        h += f'    {_safe_id(str(row["FromTableName"]))} -->|"{_esc(str(row["FromColumnName"]))}"| {_safe_id(str(row["ToTableName"]))}\n'
    h += "</pre>\n"

    sidebar = '<li><a href="#sec3">3. Relationships</a></li>'
    section = f'<h2 id="sec3">3. Relationships <a href="#sec3" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_measures(measures_df):
    """Section 4: DAX Measures grouped by table."""
    h = ""
    sidebar_items = []

    if measures_df is None or len(measures_df) == 0:
        h += "<p><em>No measures found.</em></p>\n"
        sidebar = '<li><a href="#sec4">4. DAX Measures</a></li>'
        section = f'<h2 id="sec4">4. DAX Measures <a href="#sec4" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar

    grouped = measures_df.groupby('TableName')
    group_idx = 1
    for tbl_name, group in grouped:
        sec_id = f"sec4-{group_idx}"
        sidebar_items.append(f'<li><a href="#{sec_id}">4.{group_idx} {_esc(tbl_name)}</a></li>')
        h += f'<h3 id="{sec_id}">4.{group_idx} Measures on {_esc(tbl_name)} <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'

        h += "<table>\n<thead><tr><th>Measure</th><th>DAX Expression</th></tr></thead>\n<tbody>\n"
        for _, row in group.iterrows():
            expr = str(row.get('Expression', '')).strip()
            display = expr[:300]
            if len(expr) > 300:
                display += "..."
            h += f'<tr><td><strong>{_esc(row["Name"])}</strong></td><td>{_code(display)}</td></tr>\n'
        h += "</tbody></table>\n"
        group_idx += 1

    sidebar = f'<li><a href="#sec4">4. DAX Measures</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="sec4">4. DAX Measures <a href="#sec4" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_calculated_columns(dax_cols_df):
    """Section 5: DAX Calculated Columns grouped by table."""
    h = ""
    sidebar_items = []

    if dax_cols_df is None or len(dax_cols_df) == 0:
        h += "<p><em>No calculated columns found.</em></p>\n"
        sidebar = '<li><a href="#sec5">5. DAX Calculated Columns</a></li>'
        section = f'<h2 id="sec5">5. DAX Calculated Columns <a href="#sec5" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar

    grouped = dax_cols_df.groupby('TableName')
    group_idx = 1
    for tbl_name, group in grouped:
        sec_id = f"sec5-{group_idx}"
        sidebar_items.append(f'<li><a href="#{sec_id}">5.{group_idx} {_esc(tbl_name)}</a></li>')
        h += f'<h3 id="{sec_id}">5.{group_idx} {_esc(tbl_name)} <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'

        h += "<table>\n<thead><tr><th>Column</th><th>Expression</th></tr></thead>\n<tbody>\n"
        for _, row in group.iterrows():
            expr = str(row.get('Expression', '')).strip()
            h += f'<tr><td><strong>{_esc(row["ColumnName"])}</strong></td><td>{_code(expr)}</td></tr>\n'
        h += "</tbody></table>\n"
        group_idx += 1

    sidebar = f'<li><a href="#sec5">5. DAX Calculated Columns</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="sec5">5. DAX Calculated Columns <a href="#sec5" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_observations(pq_df, rel_df, measures_df, dax_cols_df):
    """Section 6: Auto-detected observations."""
    h = ""
    observations = []

    # Hardcoded connections
    if pq_df is not None:
        hardcoded = []
        for _, row in pq_df.iterrows():
            m = str(row.get('Expression', ''))
            if 'SapHana.Database("' in m or "SapHana.Database('" in m:
                hardcoded.append(row['TableName'])
        if hardcoded:
            tlist = ", ".join(f"<strong>{_esc(t)}</strong>" for t in hardcoded)
            observations.append(('warning', 'Hardcoded Connections',
                f'Tables with hardcoded HANA server: {tlist}. Consider using a parameter for environment switching.'))

    # Bidirectional relationships
    if rel_df is not None and len(rel_df) > 0:
        bidir = rel_df[rel_df['CrossFilteringBehavior'].astype(str).isin(['2', 'BothDirections', 'bothDirections'])]
        if len(bidir) > 3:
            observations.append(('important', 'Bidirectional Relationships',
                f'There are <strong>{len(bidir)}</strong> bidirectional cross-filter relationships. Consider restricting where possible.'))

    # Measure count
    if measures_df is not None and len(measures_df) > 30:
        observations.append(('note', 'Measure Count',
            f'This model contains <strong>{len(measures_df)}</strong> DAX measures. Consider Calculation Groups to reduce duplication.'))

    # Calculated columns count
    if dax_cols_df is not None and len(dax_cols_df) > 10:
        observations.append(('tip', 'Calculated Columns',
            f'There are <strong>{len(dax_cols_df)}</strong> DAX calculated columns. Consider moving transformations to Power Query for better performance.'))

    if observations:
        for atype, title, text in observations:
            h += f'<div class="alert alert-{atype}"><div class="alert-title">{title}</div>{text}</div>\n'
    else:
        h += "<p>No significant observations detected.</p>\n"

    sidebar = '<li><a href="#sec6">6. Observations</a></li>'
    section = f'<h2 id="sec6">6. Observations for Redevelopment <a href="#sec6" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


# ---------------------------------------------------------------------------
# Main extraction function (called by GUI and CLI)
# ---------------------------------------------------------------------------

def extract_from_pbix(pbix_path, output_path=None):
    """
    Extract metadata from a .pbix file and generate HTML documentation.

    Parameters
    ----------
    pbix_path : str
        Path to the .pbix file.
    output_path : str, optional
        Where to save the HTML. Default: same folder as the PBIX.

    Returns
    -------
    str
        The path to the generated HTML file.
    """
    from pbixray import PBIXRay

    print(f"Loading PBIX: {pbix_path}")
    model = PBIXRay(pbix_path)

    report_name = Path(pbix_path).stem

    print(f"  Tables:        {len(model.tables)}")
    print(f"  Measures:      {len(model.dax_measures)}")
    print(f"  Power Queries: {len(model.power_query)}")
    print(f"  Relationships: {len(model.relationships)}")

    # Build all sections
    sections = []
    sidebar_entries = []

    s, sb = build_data_sources(model.power_query, model.dax_tables, model.m_parameters)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_transformations(model.power_query, model.dax_tables)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_relationships(model.relationships)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_measures(model.dax_measures)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_calculated_columns(model.dax_columns)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_observations(model.power_query, model.relationships, model.dax_measures, model.dax_columns)
    sections.append(s); sidebar_entries.append(sb)

    # Assemble HTML
    full_content = "\n\n".join(sections)
    full_sidebar = "\n".join(sidebar_entries)
    output_html = generate_html(report_name, full_content, full_sidebar)

    # Output path
    if not output_path:
        output_path = os.path.join(os.path.dirname(pbix_path), f"{report_name}_Data_Documentation.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_html)

    print(f"\n[OK] Documentation generated: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate HTML data documentation from a Power BI .pbix file.",
    )
    parser.add_argument("pbix", help="Path to the .pbix file.")
    parser.add_argument("--output", "-o", help="Output HTML file path.")
    args = parser.parse_args()

    extract_from_pbix(args.pbix, args.output)


if __name__ == "__main__":
    main()
