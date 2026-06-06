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
# Report Pages Extraction
# ---------------------------------------------------------------------------
import json
import zipfile
from pathlib import Path

def _parse_expr(expr):
    """Recursively parse PBI expression to extract table/column/measure names."""
    if not isinstance(expr, dict):
        return str(expr)
    
    if 'Measure' in expr:
        table = _parse_expr(expr['Measure'].get('Expression', {}))
        return f"{table}[{expr['Measure'].get('Property', '')}]"
    elif 'Column' in expr:
        table = _parse_expr(expr['Column'].get('Expression', {}))
        return f"{table}[{expr['Column'].get('Property', '')}]"
    elif 'SourceRef' in expr:
        return expr['SourceRef'].get('Entity', '')
    elif 'Aggregation' in expr:
        agg_type = expr['Aggregation'].get('Function', 0)
        col = _parse_expr(expr['Aggregation'].get('Expression', {}))
        return f"Agg({col})"
    elif 'HierarchyLevel' in expr:
        level = expr['HierarchyLevel'].get('Level', '')
        return f"HierarchyLevel({level})"
    
    return str(expr)

def _parse_layout_data(data):
    """Extract pages and visuals from parsed layout JSON."""
    pages = []
    for section in data.get('sections', []):
        page_name = section.get('displayName', 'Unknown Page')
        visuals = []
        for vc in section.get('visualContainers', []):
            if 'config' not in vc:
                continue
            config = json.loads(vc['config'])
            
            v_type = 'Unknown'
            if 'singleVisual' in config:
                v_type = config['singleVisual'].get('visualType', 'Unknown')
                
            title = ""
            try:
                if 'singleVisual' in config and 'vcObjects' in config['singleVisual']:
                    title_obj = config['singleVisual']['vcObjects'].get('title', [])
                    if title_obj and 'properties' in title_obj[0]:
                        title = title_obj[0]['properties'].get('text', {}).get('expr', {}).get('Literal', {}).get('Value', '').strip("'")
            except:
                pass
                
            fields = []
            if 'dataTransforms' in vc:
                try:
                    dt = json.loads(vc['dataTransforms'])
                    if 'selects' in dt:
                        for sel in dt['selects']:
                            name = sel.get('displayName', '')
                            expr_parsed = _parse_expr(sel.get('expr', {}))
                            # Get the role/well from the select
                            roles = sel.get('roles', {})
                            role = list(roles.keys())[0] if roles else 'Values'
                            fields.append(f"{role}: {name} -> {expr_parsed}")
                except:
                    pass
            
            # Fallback: try prototypeQuery in singleVisual config
            if not fields and 'singleVisual' in config:
                pq = config['singleVisual'].get('prototypeQuery', {})
                for sel in pq.get('Select', []):
                    name = sel.get('Name', sel.get('NativeReferenceName', ''))
                    expr_parsed = _parse_expr(sel)
                    fields.append(f"Values: {name} -> {expr_parsed}")
                    
            filters = []
            if 'filters' in vc:
                try:
                    vc_filters = json.loads(vc['filters'])
                    for f in vc_filters:
                        expr = f.get('expression', {})
                        filters.append(_parse_expr(expr))
                except:
                    pass
                    
            visuals.append({
                'type': v_type,
                'title': title,
                'fields': fields,
                'filters': filters
            })
            
        pages.append({
            'name': page_name,
            'hidden': section.get('config', '') and '"visibility":1' in json.dumps(section.get('config', '')),
            'visuals': visuals
        })
    return pages

def extract_report_pages_pbir_folder(report_dir):
    import json
    from pathlib import Path
    pages_dict = {}
    
    pages_dir = report_dir / 'definition' / 'pages'
    if not pages_dir.exists():
        return []
        
    for page_folder in pages_dir.iterdir():
        if not page_folder.is_dir():
            continue
            
        page_json = page_folder / 'page.json'
        if page_json.exists():
            try:
                with open(page_json, 'r', encoding='utf-8-sig', errors='ignore') as f:
                    page_data = json.loads(f.read())
                    page_name = page_data.get('displayName', 'Unknown Page')
                    page_hidden = page_data.get('visibility', 0) == 1
                    pages_dict[page_folder.name] = {'name': page_name, 'hidden': page_hidden, 'visuals': []}
            except:
                pass
                
        visuals_dir = page_folder / 'visuals'
        if visuals_dir.exists() and page_folder.name in pages_dict:
            for vis_folder in visuals_dir.iterdir():
                vis_json = vis_folder / 'visual.json'
                if vis_json.exists():
                    try:
                        with open(vis_json, 'r', encoding='utf-8-sig', errors='ignore') as f:
                            vis_data = json.loads(f.read())
                            
                        v_type = vis_data.get('visual', {}).get('visualType', 'Unknown')
                        
                        title = ""
                        try:
                            title_text = vis_data.get('visual', {}).get('visualContainerObjects', {}).get('title', [])[0].get('properties', {}).get('text', {}).get('expr', {}).get('Literal', {}).get('Value', '')
                            title = title_text.strip("'")
                        except:
                            pass
                            
                        fields = []
                        for key in ['Values', 'Rows', 'Columns', 'Category', 'Y', 'X', 'Size', 'Tooltips']:
                            projs = vis_data.get('visual', {}).get('query', {}).get('queryState', {}).get(key, {}).get('projections', [])
                            if not projs and isinstance(vis_data.get('visual', {}).get('query', {}).get('queryState', {}).get(key, {}), list):
                                projs = vis_data.get('visual', {}).get('query', {}).get('queryState', {}).get(key, [])
                            if isinstance(projs, list):
                                for p in projs:
                                    name = p.get('queryRef', '')
                                    expr_parsed = _parse_expr(p.get('field', {}))
                                    fields.append(f"{key}: {name} -> {expr_parsed}")
                                    
                        if not fields:
                            projs = vis_data.get('visual', {}).get('query', {}).get('queryState', {}).get('projections', [])
                            for p in projs:
                                name = p.get('queryRef', '')
                                expr_parsed = _parse_expr(p.get('field', {}))
                                fields.append(f"{name} -> {expr_parsed}")
                                
                        pages_dict[page_folder.name]['visuals'].append({
                            'type': v_type,
                            'title': title,
                            'fields': fields,
                            'filters': []
                        })
                    except:
                        pass
                        
    return list(pages_dict.values())

def extract_report_pages_pbir(z):
    import json
    pages_dict = {}
    
    page_files = [p for p in z.namelist() if p.startswith('Report/definition/pages/') and p.endswith('/page.json')]
    for pf in page_files:
        try:
            page_id = pf.split('/')[3]
            page_data = json.loads(z.read(pf).decode('utf-8-sig', errors='ignore'))
            page_name = page_data.get('displayName', 'Unknown Page')
            page_hidden = page_data.get('visibility', 0) == 1
            pages_dict[page_id] = {'name': page_name, 'hidden': page_hidden, 'visuals': []}
        except:
            pass

    visual_files = [p for p in z.namelist() if p.startswith('Report/definition/pages/') and p.endswith('/visual.json')]
    for vf in visual_files:
        try:
            parts = vf.split('/')
            page_id = parts[3]
            if page_id not in pages_dict:
                continue
                
            vis_data = json.loads(z.read(vf).decode('utf-8-sig', errors='ignore'))
            v_type = vis_data.get('visual', {}).get('visualType', 'Unknown')
            
            title = ""
            try:
                title_text = vis_data.get('visual', {}).get('visualContainerObjects', {}).get('title', [])[0].get('properties', {}).get('text', {}).get('expr', {}).get('Literal', {}).get('Value', '')
                title = title_text.strip("'")
            except:
                pass
                
            fields = []
            for key in ['Values', 'Rows', 'Columns', 'Category', 'Y', 'X', 'Size', 'Tooltips']:
                projs = vis_data.get('visual', {}).get('query', {}).get('queryState', {}).get(key, {}).get('projections', [])
                if not projs and isinstance(vis_data.get('visual', {}).get('query', {}).get('queryState', {}).get(key, {}), list):
                    projs = vis_data.get('visual', {}).get('query', {}).get('queryState', {}).get(key, [])
                if isinstance(projs, list):
                    for p in projs:
                        name = p.get('queryRef', '')
                        expr_parsed = _parse_expr(p.get('field', {}))
                        fields.append(f"{name} -> {expr_parsed}")
                        
            if not fields:
                projs = vis_data.get('visual', {}).get('query', {}).get('queryState', {}).get('projections', [])
                for p in projs:
                    name = p.get('queryRef', '')
                    expr_parsed = _parse_expr(p.get('field', {}))
                    fields.append(f"{name} -> {expr_parsed}")
                    
            pages_dict[page_id]['visuals'].append({
                'type': v_type,
                'title': title,
                'fields': fields,
                'filters': []
            })
        except:
            pass
            
    return list(pages_dict.values())

def extract_report_pages_pbix(pbix_path):
    """Extract report pages from PBIX."""
    try:
        with zipfile.ZipFile(pbix_path) as z:
            if 'Report/Layout' not in z.namelist():
                return []
            layout_bytes = z.read('Report/Layout')
            layout_str = layout_bytes.decode('utf-16-le', errors='ignore').lstrip('\ufeff')
            if layout_str and layout_str[0] != '{':
                layout_str = layout_bytes.decode('utf-8', errors='ignore').lstrip('\ufeff')
            data = json.loads(layout_str)
            return _parse_layout_data(data)
    except Exception as e:
        print(f"Warning: Could not extract report pages from PBIX: {e}")
        import traceback
        return traceback.format_exc()

def extract_report_pages_pbip(pbip_path):
    """Extract report pages from PBIP (looks for matching .Report folder)."""
    try:
        pbip_file = Path(pbip_path)
        pbip_dir = pbip_file.parent if pbip_file.is_file() else pbip_file
        
        # Match the .Report folder that belongs to THIS .pbip file
        # e.g. "ServiceLevelOTIF_DS.pbip" -> "ServiceLevelOTIF_DS.Report"
        report_dir = None
        if pbip_file.is_file():
            expected_name = pbip_file.stem + ".Report"
            candidate = pbip_dir / expected_name
            if candidate.exists() and candidate.is_dir():
                report_dir = candidate
        
        # Fallback: first *.Report in directory (only if single file)
        if report_dir is None:
            report_dirs = list(pbip_dir.glob("*.Report"))
            if not report_dirs:
                return []
            report_dir = report_dirs[0]
        
        report_json_path = report_dir / "report.json"
        if report_json_path.exists():
            with open(report_json_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
                content = f.read()
                data = json.loads(content)
                return _parse_layout_data(data)
        else:
            # Try PBIR format
            return extract_report_pages_pbir_folder(report_dir)
        return []
    except Exception as e:
        print(f"Warning: Could not extract report pages from PBIP: {e}")
        import traceback
        return traceback.format_exc()


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
# Noise filter: technical/non-functional objects
# ---------------------------------------------------------------------------
TECHNICAL_DENYLIST = {
    'ServerString', 'NoRecords', 'NrRecords', 'Total Deliveries shells',
    'Last Refreshed (Local)', 'Transparent', 'BeginPeriod', 'EndPeriod',
}
TECHNICAL_PREFIXES = ('!',)
TECHNICAL_PATTERNS = (re.compile(r'^Tooltip', re.IGNORECASE),)

def _is_technical(name):
    """Return True for technical/non-functional objects (denylist)."""
    n = str(name)
    if n in TECHNICAL_DENYLIST:
        return True
    if any(n.startswith(p) for p in TECHNICAL_PREFIXES):
        return True
    if any(pat.match(n) for pat in TECHNICAL_PATTERNS):
        return True
    return False

def _is_binary_payload(m_code):
    """Return True for inline binary/JSON table payloads."""
    if not m_code:
        return False
    return bool(re.search(r'Binary\.Decompress\(.*?Binary\.FromText\(', m_code, re.DOTALL) or
                re.search(r'Table\.FromRows\(\s*Json\.Document\(\s*Binary\.Decompress\(', m_code, re.DOTALL))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SYSTEM_TABLE_PREFIXES = (
    'LocalDateTable_',
    'DateTableTemplate_',
    'RowNumber-',
)

def _is_system_table(name):
    """Return True for auto-generated Power BI system tables."""
    return any(str(name).startswith(p) for p in _SYSTEM_TABLE_PREFIXES)

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
# Role labels for semantic visual rendering (ENGLISH)
# ---------------------------------------------------------------------------
_WELL_LABELS = {
    'Category': 'X-axis', 'X': 'X-axis', 'Axis': 'X-axis',
    'Y': 'Y-axis', 'Y2': 'Y-axis (secondary)',
    'Series': 'Legend', 'Legend': 'Legend',
    'Values': 'Value', 'Rows': 'Rows', 'Columns': 'Columns',
    'Tooltips': 'Tooltips', 'Details': 'Detail', 'Size': 'Size',
}

_VISUAL_LABELS = {
    'barChart': 'Bar chart', 'columnChart': 'Column chart',
    'lineChart': 'Line chart', 'areaChart': 'Area chart',
    'clusteredBarChart': 'Clustered bar chart',
    'clusteredColumnChart': 'Clustered column chart',
    'stackedBarChart': 'Stacked bar chart',
    'stackedColumnChart': 'Stacked column chart',
    'hundredPercentStackedBarChart': '100% stacked bar chart',
    'hundredPercentStackedColumnChart': '100% stacked column chart',
    'lineClusteredColumnComboChart': 'Line + clustered column',
    'lineStackedColumnComboChart': 'Line + stacked column',
    'ribbonChart': 'Ribbon chart', 'waterfallChart': 'Waterfall chart',
    'funnelChart': 'Funnel chart', 'scatterChart': 'Scatter chart',
    'pieChart': 'Pie chart', 'donutChart': 'Donut chart',
    'treemap': 'Treemap', 'map': 'Map', 'filledMap': 'Filled map',
    'shapeMap': 'Shape map', 'gauge': 'Gauge', 'kpi': 'KPI',
    'card': 'Card', 'multiRowCard': 'Multi-row card',
    'tableEx': 'Table', 'pivotTable': 'Matrix', 'matrix': 'Matrix',
    'slicer': 'Slicer', 'textbox': 'Text box', 'image': 'Image',
    'actionButton': 'Button', 'basicShape': 'Shape',
    'decompositionTreeVisual': 'Decomposition tree',
    'keyDriversVisual': 'Key influencers',
}

def _clean_field_name(raw):
    """Strip Entity[Field], -> syntax, aggregation wrappers, trailing parens."""
    s = str(raw)
    # Remove well prefix like "Values: " first
    for prefix in _WELL_LABELS:
        if s.startswith(prefix + ': '):
            s = s[len(prefix) + 2:]
            break
    # Use the resolved name (right side of ->) if available
    if ' -> ' in s:
        resolved = s.split(' -> ')[-1]
        # Extract from Entity[Field] pattern
        bracket_match = re.search(r'\[([^\]]+)\]', resolved)
        if bracket_match:
            s = bracket_match.group(1)
        else:
            s = resolved
    # Remove "Entity." prefix (e.g. "TableName.FieldName")
    if '.' in s:
        s = s.split('.')[-1]
    # Strip aggregation wrapper: "Sum(Tbl[Field])" or "Agg(Entity[Field])" -> "Field"
    agg_match = re.match(r'^(?:Sum|Count|Min|Max|Average|Agg)\((.+)\)$', s, re.IGNORECASE)
    if agg_match:
        inner = agg_match.group(1)
        bracket_match2 = re.search(r'\[([^\]]+)\]', inner)
        s = bracket_match2.group(1) if bracket_match2 else inner
    # Strip trailing unbalanced closing parens
    while s.endswith(')') and s.count(')') > s.count('('):
        s = s[:-1]
    # Strip numeric alias suffixes ("...months1" -> "...months")
    s = re.sub(r'(\D)(\d{1,2})$', r'\1', s)
    return s.strip()

def _get_well(raw):
    """Extract the well/role prefix from a raw field string."""
    s = str(raw)
    for prefix in _WELL_LABELS:
        if s.startswith(prefix + ': '):
            return prefix
    return 'Values'

def _is_measure_field(raw):
    """Heuristic: field is a measure if it has Agg() wrapper or Measure ref."""
    s = str(raw)
    return 'Agg(' in s or 'Measure' in s or '[Measure]' in s

def _readable_type(vtype):
    """Return English-readable visual type label."""
    return _VISUAL_LABELS.get(vtype, vtype)

def _card_is_technical(v):
    """Return True if a card visual shows a technical/helper measure."""
    for f in v.get('fields', []):
        name = _clean_field_name(f)
        if _is_technical(name):
            return True
    title = v.get('title', '')
    if title and _is_technical(title):
        return True
    return False

def build_report_pages(pages, sec_num):
    """Section N: Report Pages & Visuals. sec_num is the section number."""
    h = ""
    sidebar_items = []
    sec_id = "sec-pages"
    
    if isinstance(pages, str):
        h += f"<p><em>Error extracting report pages:</em></p>\n<pre><code>{_esc(pages)}</code></pre>\n"
        sidebar = f'<li><a href="#{sec_id}">{sec_num}. Report Pages</a></li>'
        section = f'<h2 id="{sec_id}">{sec_num}. Report Pages &amp; Visuals <a href="#{sec_id}" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar

    if not pages:
        h += "<p><em>No report pages found (or could not extract).</em></p>\n"
        sidebar = f'<li><a href="#{sec_id}">{sec_num}. Report Pages</a></li>'
        section = f'<h2 id="{sec_id}">{sec_num}. Report Pages &amp; Visuals <a href="#{sec_id}" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar
        
    for p_idx, page in enumerate(pages, 1):
        page_sec_id = f"sec-page-{p_idx}"
        page_name = page.get('name', 'Unknown')
        hidden = page.get('hidden', False)
        visuals = page.get('visuals', [])
        
        hidden_tag = ' <span style="color:var(--fg-muted);">[Hidden]</span>' if hidden else ''
        sidebar_items.append(f'<li><a href="#{page_sec_id}">{sec_num}.{p_idx} {_esc(page_name)}</a></li>')
        h += f'<h3 id="{page_sec_id}">{sec_num}.{p_idx} {_esc(page_name)}{hidden_tag} <a href="#{page_sec_id}" class="section-anchor">#</a></h3>\n'
        
        # Classify visuals
        func_visuals = []
        tech_visuals = []
        tech_cards = []
        slicers = []
        for v in visuals:
            vtype = v.get('type', '')
            vtitle = v.get('title', '')
            # Decorative / structural elements -> always technical
            if vtype in ('basicShape', 'image', 'textbox', 'actionButton'):
                tech_visuals.append(v)
            # Explicit denylist on title or type
            elif _is_technical(vtitle) or _is_technical(vtype):
                tech_visuals.append(v)
            elif vtype == 'slicer':
                slicers.append(v)
            # Cards showing technical measures -> technical
            elif vtype in ('card', 'multiRowCard') and _card_is_technical(v):
                tech_cards.append(v)
            else:
                func_visuals.append(v)
        
        data_visuals = [v for v in func_visuals if v.get('fields')]
        
        # Summary line
        h += f"<p>{len(data_visuals)} functional visuals"
        if slicers:
            h += f", {len(slicers)} slicers"
        h += ".</p>\n"
        
        # Slicer chip-line
        if slicers:
            slicer_fields = []
            for sl in slicers:
                for f in sl.get('fields', []):
                    slicer_fields.append(_clean_field_name(f))
            if slicer_fields:
                chips = ", ".join(f"<code>{_esc(sf)}</code>" for sf in slicer_fields)
                h += f"<p>Filters: {chips}</p>\n"
        
        # Data visuals as <ul> hierarchy
        if data_visuals:
            h += "<ul>\n"
            for v in data_visuals:
                vtype = v.get('type', 'Unknown')
                vtitle = v.get('title', '')
                label = _readable_type(vtype)
                
                # Visual heading
                if vtitle:
                    h += f"<li><strong>{_esc(label)}</strong> — {_esc(vtitle)}\n"
                else:
                    h += f"<li><strong>{_esc(label)}</strong>\n"
                
                # Group fields by well
                wells = {}
                for f in v.get('fields', []):
                    well = _get_well(f)
                    name = _clean_field_name(f)
                    is_measure = _is_measure_field(f)
                    display = f"{name} (measure)" if is_measure else name
                    wells.setdefault(well, []).append(display)
                
                # Tables: "Columns (N):" label
                if vtype in ('tableEx', 'pivotTable', 'matrix'):
                    all_fields = [_clean_field_name(f) for f in v.get('fields', [])]
                    n = len(all_fields)
                    if n <= 8:
                        field_str = ", ".join(_esc(f) for f in all_fields)
                        h += f"<br><span style=\"color:var(--fg-muted);\">Columns ({n}): {field_str}</span>\n"
                    else:
                        sample = ", ".join(_esc(f) for f in all_fields[:5])
                        h += f"<br><span style=\"color:var(--fg-muted);\">Columns ({n}): {sample}, …</span>\n"
                elif wells:
                    # Compact well line for charts
                    parts = []
                    for well_key, field_list in wells.items():
                        well_label = _WELL_LABELS.get(well_key, well_key)
                        # For cards, use "Value:" not "X-axis:"
                        if vtype in ('card', 'multiRowCard') and well_label in ('X-axis', 'Value'):
                            well_label = 'Value'
                        fields_str = ", ".join(_esc(f) for f in field_list)
                        parts.append(f"{well_label}: {fields_str}")
                    h += f"<br><span style=\"color:var(--fg-muted);\">{' &middot; '.join(parts)}</span>\n"
                
                h += "</li>\n"
            h += "</ul>\n"
            
        # Technical footnote
        total_tech = len(tech_visuals) + len(tech_cards)
        if total_tech > 0:
            parts = []
            if tech_cards:
                parts.append(f"{len(tech_cards)} helper cards")
            shapes_etc = len(tech_visuals)
            if shapes_etc:
                parts.append(f"{shapes_etc} shapes/buttons")
            h += f'<details><summary>+ {total_tech} technical objects ({", ".join(parts)})</summary>\n'
            h += "<ul>\n"
            for v in tech_cards + tech_visuals:
                title = _esc(v.get('title', '')) or v.get('type', '')
                h += f'<li>{_esc(v.get("type", ""))}: {title}</li>\n'
            h += "</ul></details>\n"
            
    sidebar = f'<li><a href="#{sec_id}">{sec_num}. Report Pages</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="{sec_id}">{sec_num}. Report Pages &amp; Visuals <a href="#{sec_id}" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_data_sources(pq_df, dax_tables_df, m_params_df, include_system_tables=False):
    """Section 1: Data Sources."""
    h = ""
    sidebar_items = []

    # Dictionaries to group tables by category
    categories = {
        "File": [],
        "Database": [],
        "Power Platform": [],
        "Azure": [],
        "Online Services": [],
        "Other": []
    }
    
    # Internal categories
    computed_tables = []
    real_params = []
    helper_funcs = []

    # Keyword mappings
    mappings = {
        "File": [("Excel.Workbook", "Excel"), ("Csv.Document", "CSV"), ("Xml.Tables", "XML"), ("Json.Document", "JSON"), ("Pdf.Tables", "PDF"), ("Folder.Files", "Folder"), ("SharePoint.Files", "SharePoint Folder"), ("File.Contents", "File")],
        "Database": [("Sql.Database", "SQL Server"), ("SapHana.Database", "SAP HANA"), ("SapBusinessWarehouse.Cubes", "SAP BW"), ("AnalysisServices.Database", "Analysis Services"), ("Oracle.Database", "Oracle"), ("PostgreSQL.Database", "PostgreSQL"), ("MySQL.Database", "MySQL"), ("Teradata.Database", "Teradata"), ("GoogleBigQuery.Database", "BigQuery"), ("Snowflake.Databases", "Snowflake"), ("AdoDotNet.DataSource", "ADO.NET"), ("Odbc.DataSource", "ODBC"), ("OleDb.DataSource", "OLE DB")],
        "Power Platform": [("PowerBI.Dataflows", "Dataflows"), ("CommonDataService.Database", "Dataverse"), ("PowerPlatform.Dataflows", "Power Platform Dataflows")],
        "Azure": [("AzureStorage.Blobs", "Azure Blobs"), ("AzureStorage.DataLake", "Azure Data Lake"), ("AzureDataExplorer.Contents", "Azure Data Explorer"), ("AzureSql.Database", "Azure SQL")],
        "Online Services": [("Salesforce.Data", "Salesforce"), ("SharePoint.Contents", "SharePoint"), ("Exchange.Contents", "Exchange"), ("GoogleAnalytics.Accounts", "Google Analytics"), ("Dynamics365", "Dynamics 365")],
        "Other": [("Web.Contents", "Web"), ("Web.BrowserContents", "Web"), ("OData.Feed", "OData"), ("ActiveDirectory.Domains", "Active Directory")]
    }

    if pq_df.empty or 'TableName' not in pq_df.columns:
        pq_dict = {}
    else:
        pq_dict = dict(zip(pq_df['TableName'], pq_df['Expression']))

    dax_table_names = set()
    if dax_tables_df is not None and len(dax_tables_df) > 0:
        dax_table_names = set(dax_tables_df['TableName'].tolist())

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
            continue
        if not include_system_tables and _is_system_table(tbl_name):
            continue

        matched = False
        for cat_name, kw_list in mappings.items():
            for kw, conn_type in kw_list:
                if kw in m_code:
                    categories[cat_name].append((tbl_name, conn_type, m_code))
                    matched = True
                    break
            if matched:
                break
                
        if not matched:
            # Check for hardcoded manual tables or just compute
            if "Binary.Decompress" in m_code or "Table.FromRows(Json" in m_code or ("#table(type table" in m_code and "DateTime.LocalNow" in m_code) or (len(m_code.strip()) < 100 and ("Table.FromRows" in m_code or "Table.RemoveColumns" in m_code)):
                categories["Other"].append((tbl_name, "Manual/Inline Table", m_code))
            else:
                computed_tables.append((tbl_name, m_code))

    if dax_tables_df is not None:
        for _, row in dax_tables_df.iterrows():
            if not include_system_tables and _is_system_table(row['TableName']):
                continue
            computed_tables.append((row['TableName'], row.get('Expression', '')))

    # Build HTML for categories
    sec_idx = 1
    
    for cat_name, cat_list in categories.items():
        if not cat_list:
            continue
            
        sec_id = f"sec1-{sec_idx}"
        sidebar_items.append(f'<li><a href="#{sec_id}">1.{sec_idx} {cat_name}</a></li>')
        if sec_idx > 1:
            h += f'<hr>\n'
        h += f'<h3 id="{sec_id}">1.{sec_idx} {cat_name} <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += "<table>\n<thead><tr><th>#</th><th>Table Name</th><th>Connection Type</th><th>Source Excerpt</th></tr></thead>\n<tbody>\n"
        
        for i, (tbl_name, conn_type, m_code) in enumerate(cat_list, 1):
            # Try to extract HANA specifics if it's HANA
            if _is_binary_payload(m_code):
                excerpt = "[binary payload - inline table]"
            elif len(m_code) > 120:
                excerpt = m_code.split("\\n")[0].strip()[:100] + "…"
            else:
                excerpt = m_code.strip()
            if conn_type == "SAP HANA":
                pkg, view, _ = _extract_hana_info(m_code)
                excerpt = f"Package: {pkg} / View: {view}"
                
            h += f'<tr><td>{i}</td><td><strong><a href="#sec2-tbl-{_safe_id(tbl_name)}">{_esc(tbl_name)}</a></strong></td>'
            h += f'<td>{_esc(conn_type)}</td><td>{_code(excerpt)}</td></tr>\n'
        h += "</tbody></table>\n"
        sec_idx += 1

    # Computed Tables
    if computed_tables:
        sec_id = f"sec1-{sec_idx}"
        sidebar_items.append(f'<li><a href="#{sec_id}">1.{sec_idx} Computed Tables</a></li>')
        if sec_idx > 1:
            h += f'<hr>\n'
        h += f'<h3 id="{sec_id}">1.{sec_idx} Computed / Derived Tables <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += "<table>\n<thead><tr><th>#</th><th>Table</th><th>Source</th><th>Type</th></tr></thead>\n<tbody>\n"
        for i, (tbl_name, expr) in enumerate(computed_tables, 1):
            is_dax = tbl_name in dax_table_names
            if _is_binary_payload(expr):
                src = "[binary payload - inline table]"
            elif len(expr.strip()) > 120:
                src = expr.strip()[:100] + "…"
            else:
                src = expr.strip()
            ttype = "DAX Calculated Table" if is_dax else "M (Power Query)"
            h += f'<tr><td>{i}</td><td><strong><a href="#sec2-tbl-{_safe_id(tbl_name)}">{_esc(tbl_name)}</a></strong></td>'
            h += f'<td>{_code(src)}</td><td>{_esc(ttype)}</td></tr>\n'
        h += "</tbody></table>\n"
        sec_idx += 1

    # Parameters
    if real_params:
        sec_id = f"sec1-{sec_idx}"
        sidebar_items.append(f'<li><a href="#{sec_id}">1.{sec_idx} Parameters</a></li>')
        if sec_idx > 1:
            h += f'<hr>\n'
        h += f'<h3 id="{sec_id}">1.{sec_idx} Parameters <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += "<table>\n<thead><tr><th>Parameter</th><th>Expression</th></tr></thead>\n<tbody>\n"
        for row in real_params:
            h += f'<tr><td>{_code(row["ParameterName"])}</td><td>{_code(str(row.get("Expression",""))[:150])}</td></tr>\n'
        h += "</tbody></table>\n"
        sec_idx += 1

    # Helper Functions
    if helper_funcs:
        sec_id = f"sec1-{sec_idx}"
        sidebar_items.append(f'<li><a href="#{sec_id}">1.{sec_idx} Helper Functions</a></li>')
        if sec_idx > 1:
            h += f'<hr>\n'
        h += f'<h3 id="{sec_id}">1.{sec_idx} Helper Functions <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += "<table>\n<thead><tr><th>Function</th><th>Description</th></tr></thead>\n<tbody>\n"
        for row in helper_funcs:
            desc = str(row.get("Description", "")) or "Custom M function"
            h += f'<tr><td>{_code(row["ParameterName"])}</td><td>{_esc(desc)}</td></tr>\n'
        h += "</tbody></table>\n"

    if sec_idx == 1:
        h += "<p><em>No data sources detected.</em></p>\n"

    sidebar = f'<li><a href="#sec1">1. Data Sources</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="sec1">1. Data Sources <a href="#sec1" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_transformations(pq_df, dax_tables_df, include_system_tables=False):
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
        if not include_system_tables and _is_system_table(tbl):
            continue

        sec_id = f"sec2-tbl-{_safe_id(tbl)}"
        sidebar_items.append(f'<li><a href="#{sec_id}">2.{idx} {_esc(tbl)}</a></li>')
        h += f'<h3 id="{sec_id}">2.{idx} {_esc(tbl)} <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'

        steps = _parse_m_steps(m_code)
        if steps:
            h += "<ol>\n"
            for step_name, step_expr in steps:
                if _is_binary_payload(step_expr):
                    display = "[binary payload omitted]"
                else:
                    display = step_expr
                h += f"  <li><strong>{_esc(step_name)}</strong>:\n<pre><code>{_esc(display)}</code></pre></li>\n"
            h += "</ol>\n"
        else:
            h += f"<pre><code>{_esc(m_code.strip())}</code></pre>\n"

        # Warn about hardcoded connections
        if 'SapHana.Database("' in m_code or "SapHana.Database('" in m_code:
            h += '<div class="alert alert-warning"><div class="alert-title">Warning</div>'
            h += 'This table has a <strong>hardcoded</strong> HANA connection instead of using a parameter.</div>\n'

        h += "<hr>\n"
        idx += 1

    # DAX calculated tables
    for tbl_name, dax_expr in dax_dict.items():
        if not include_system_tables and _is_system_table(tbl_name):
            continue
        sec_id = f"sec2-tbl-{_safe_id(tbl_name)}"
        sidebar_items.append(f'<li><a href="#{sec_id}">2.{idx} {_esc(tbl_name)}</a></li>')
        h += f'<h3 id="{sec_id}">2.{idx} {_esc(tbl_name)} (DAX Calculated Table) <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += f"<pre><code>{_esc(dax_expr.strip())}</code></pre>\n<hr>\n"
        idx += 1

    sidebar = f'<li><a href="#sec2">2. Power Query Transformations</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="sec2">2. Power Query Transformations (Modeling) <a href="#sec2" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_relationships(rel_df, include_system_tables=False):
    """Section 3: Relationships + Mermaid diagram."""
    h = ""

    if rel_df is None or len(rel_df) == 0:
        h += "<p><em>No relationships found.</em></p>\n"
        sidebar = '<li><a href="#sec3">3. Relationships</a></li>'
        section = f'<h2 id="sec3">3. Relationships <a href="#sec3" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar

    # Filter out rows with NaN values
    rel_df = rel_df.dropna(subset=['FromTableName', 'ToTableName', 'FromColumnName', 'ToColumnName'])
    if not include_system_tables:
        rel_df = rel_df[~rel_df['FromTableName'].apply(_is_system_table) & ~rel_df['ToTableName'].apply(_is_system_table)]

    h += "<table>\n<thead><tr><th>#</th><th>From Table</th><th>From Column</th><th>→</th><th>To Table</th><th>To Column</th><th>Cross-Filter</th></tr></thead>\n<tbody>\n"
    for i, (_, row) in enumerate(rel_df.iterrows(), 1):
        cf_raw = str(row.get('CrossFilteringBehavior', '1'))
        cf = "<strong>Both</strong>" if cf_raw == '2' or 'both' in cf_raw.lower() else "Single"
        h += f'<tr><td>{i}</td><td>{_esc(str(row["FromTableName"]))}</td><td><code>{_esc(str(row["FromColumnName"]))}</code></td><td>→</td>'
        h += f'<td>{_esc(str(row["ToTableName"]))}</td><td><code>{_esc(str(row["ToColumnName"]))}</code></td><td>{cf}</td></tr>\n'
    h += "</tbody></table>\n"

    # Rendered Mermaid diagram (mermaid.js is bundled in the exe)
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
    h += '</pre>\n'

    sidebar = '<li><a href="#sec3">3. Relationships</a></li>'
    section = f'<h2 id="sec3">3. Relationships <a href="#sec3" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_measures(measures_df, include_system_tables=False):
    """Section 4: DAX Measures grouped by table."""
    h = ""
    sidebar_items = []

    if measures_df is None or len(measures_df) == 0:
        h += "<p><em>No measures found.</em></p>\n"
        sidebar = '<li><a href="#sec4">4. DAX Measures</a></li>'
        section = f'<h2 id="sec4">4. DAX Measures <a href="#sec4" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar

    if not include_system_tables:
        measures_df = measures_df[~measures_df['TableName'].apply(_is_system_table)]
    if len(measures_df) == 0:
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

        for _, row in group.sort_values('Name').iterrows():
            expr = str(row.get('Expression', '')).strip()
            h += f"<h4>{_esc(row['Name'])}</h4>\n"
            h += f"<pre><code>{_esc(expr)}</code></pre>\n"

        group_idx += 1

    sidebar = f'<li><a href="#sec4">4. DAX Measures</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="sec4">4. DAX Measures <a href="#sec4" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar


def build_calculated_columns(dax_cols_df, include_system_tables=False):
    """Section 5: DAX Calculated Columns grouped by table."""
    h = ""
    sidebar_items = []

    if dax_cols_df is None or len(dax_cols_df) == 0:
        h += "<p><em>No calculated columns found.</em></p>\n"
        sidebar = '<li><a href="#sec5">5. DAX Calculated Columns</a></li>'
        section = f'<h2 id="sec5">5. DAX Calculated Columns <a href="#sec5" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar

    if not include_system_tables:
        dax_cols_df = dax_cols_df[~dax_cols_df['TableName'].apply(_is_system_table)]
    if len(dax_cols_df) == 0:
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


def build_observations(pq_df, rel_df, measures_df, dax_cols_df, pages=None):
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

    # Duplicate DAX expressions
    if measures_df is not None and len(measures_df) > 1:
        expr_map = {}
        for _, row in measures_df.iterrows():
            expr = str(row.get('Expression', '')).strip()
            if expr and len(expr) > 10:
                expr_map.setdefault(expr, []).append(row['Name'])
        dupes = {expr: names for expr, names in expr_map.items() if len(names) > 1}
        if dupes:
            dupe_lines = []
            for expr, names in dupes.items():
                dupe_lines.append(", ".join(f"<strong>{_esc(n)}</strong>" for n in names))
            observations.append(('tip', 'Duplicate DAX Logic',
                f'These measures share identical DAX: {"; ".join(dupe_lines)}.'))

    # Unused measures (defined but not on any report page)
    if pages and measures_df is not None and len(measures_df) > 0:
        bound_fields = set()
        page_list = pages if isinstance(pages, list) else []
        for page in page_list:
            for vis in page.get('visuals', []):
                for f in vis.get('fields', []):
                    bound_fields.add(str(f).lower())
        all_measure_names = set(measures_df['Name'].dropna().astype(str).tolist())
        unused = []
        for m in sorted(all_measure_names):
            if not any(m.lower() in bf for bf in bound_fields):
                unused.append(m)
        if unused and len(unused) < len(all_measure_names):  # Only flag if some ARE used
            if len(unused) <= 10:
                ulist = ", ".join(f"<strong>{_esc(u)}</strong>" for u in unused)
            else:
                ulist = ", ".join(f"<strong>{_esc(u)}</strong>" for u in unused[:10]) + f" … and {len(unused)-10} more"
            observations.append(('note', 'Unused Measures',
                f'{len(unused)} measures defined but not bound to any report visual: {ulist}.'))

    if observations:
        for atype, title, text in observations:
            h += f'<div class="alert alert-{atype}"><div class="alert-title">{title}</div>{text}</div>\n'
    else:
        h += "<p>No significant observations detected.</p>\n"

    sidebar = '<li><a href="#sec6">Observations</a></li>'
    section = f'<h2 id="sec6">Observations for Redevelopment <a href="#sec6" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar

def build_calculation_groups(calc_groups, include_system_tables=False):
    """Section: Calculation Groups (TMDL only)."""
    h = ""
    sidebar_items = []
    
    if not calc_groups:
        return "", ""
        
    for idx, cg in enumerate(calc_groups, 1):
        if not include_system_tables and _is_system_table(cg.table_name):
            continue
            
        sec_id = f"sec-cg-{idx}"
        sidebar_items.append(f'<li><a href="#{sec_id}">CG {idx}: {_esc(cg.table_name)}</a></li>')
        h += f'<h3 id="{sec_id}">Calculation Group: {_esc(cg.table_name)} <a href="#{sec_id}" class="section-anchor">#</a></h3>\n'
        h += f"<p>Column: {_code(cg.column_name)}</p>\n"
        
        h += "<table>\n<thead><tr><th>Item</th><th>DAX Expression</th><th>Ordinal</th></tr></thead>\n<tbody>\n"
        # Sort items by ordinal if possible
        items = sorted(cg.items, key=lambda x: getattr(x, 'ordinal', 0))
        for item in items:
            expr = getattr(item, 'expression', '').strip()
            h += f'<tr><td><strong>{_esc(getattr(item, "name", ""))}</strong></td><td><pre><code>{_esc(expr)}</code></pre></td><td>{getattr(item, "ordinal", "")}</td></tr>\n'
        h += "</tbody></table>\n"

    if not h:
        return "", ""

    sidebar = f'<li><a href="#sec-cg">Calculation Groups</a><ul>{"".join(sidebar_items)}</ul></li>'
    section = f'<h2 id="sec-cg">Calculation Groups <a href="#sec-cg" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar

def _parse_dax_dependencies(expression, measure_names_lower, column_names_lower):
    """Parse DAX dependencies for measure lineage."""
    deps = {"measures": set(), "columns": set()}
    if not expression:
        return deps
        
    expr = re.sub(r'/\*.*?\*/', '', expression, flags=re.DOTALL)
    expr = re.sub(r'--.*', '', expr)
    expr = re.sub(r'//.*', '', expr)
    expr = re.sub(r'"[^"]*"', '""', expr)
    
    vars_declared = set(re.findall(r'(?i)\bVAR\s+([a-zA-Z0-9_]+)\b', expr))
    vars_declared_lower = {v.lower() for v in vars_declared}
    
    pattern = r"(?:('[^']+'|[a-zA-Z0-9_]+)\s*)?\[([^\]]+)\]"
    for table_match, name_match in re.findall(pattern, expr):
        name_lower = name_match.lower()
        if name_lower in vars_declared_lower:
            continue
            
        if table_match:
            deps["columns"].add(name_match)
        else:
            if name_lower in measure_names_lower:
                deps["measures"].add(name_match)
            elif name_lower in column_names_lower:
                deps["columns"].add(name_match)
                
    return deps

def build_measure_lineage(measures_df, all_columns, include_system_tables=False):
    """Section 7: Measure Lineage Diagram."""
    h = ""
    sidebar_items = []
    
    if measures_df is None or len(measures_df) == 0:
        h += "<p><em>No measures found.</em></p>\n"
        sidebar = '<li><a href="#sec7">Measure Lineage</a></li>'
        section = f'<h2 id="sec7">Measure Lineage <a href="#sec7" class="section-anchor">#</a></h2>\n{h}'
        return section, sidebar
        
    if not include_system_tables:
        measures_df = measures_df[~measures_df['TableName'].apply(_is_system_table)]

    measure_names_lower = {str(x).lower() for x in measures_df['Name'].dropna()}
    column_names_lower = {str(x).lower() for x in all_columns}
    
    lineage = {}
    for _, row in measures_df.iterrows():
        m_name = row['Name']
        expr = str(row.get('Expression', ''))
        lineage[m_name] = _parse_dax_dependencies(expr, measure_names_lower, column_names_lower)
        
    has_any_deps = any(d['measures'] or d['columns'] for d in lineage.values())
    
    if not has_any_deps:
        h += "<p><em>No measure dependencies found.</em></p>\n"
    else:
        # Rendered Mermaid dependency diagram (mermaid.js is bundled)
        h += "<h4>Dependency Diagram</h4>\n"
        h += '<pre class="mermaid">\ngraph LR\n'
        h += '    classDef measure fill:#0969da,stroke:#0550ae,color:#fff,rx:10,ry:10;\n'
        h += '    classDef column fill:#f6f8fa,stroke:#d1d9e0,color:#1f2328;\n'
        
        used_measures = set()
        used_columns = set()
        for m, deps in lineage.items():
            if deps['measures'] or deps['columns']:
                used_measures.add(m)
                used_measures.update(deps['measures'])
                used_columns.update(deps['columns'])
                
        for m in sorted(used_measures):
            h += f'    {_safe_id(m)}("{_esc(m)}"):::measure\n'
        for c in sorted(used_columns):
            h += f'    {_safe_id(c)}["{_esc(c)}"]:::column\n'
            
        for m, deps in lineage.items():
            for dep_m in deps['measures']:
                h += f'    {_safe_id(dep_m)} --> {_safe_id(m)}\n'
            for dep_c in deps['columns']:
                h += f'    {_safe_id(dep_c)} -.-> {_safe_id(m)}\n'
        h += '</pre>\n'
        
        h += "<h4>Dependency Details</h4>\n"
        h += "<table>\n<thead><tr><th>Measure</th><th>Depends on Measures</th><th>Depends on Columns</th></tr></thead>\n<tbody>\n"
        for m, deps in sorted(lineage.items()):
            if not deps['measures'] and not deps['columns']:
                continue
            m_links = ", ".join(_code(x) for x in sorted(deps['measures'])) if deps['measures'] else "--"
            c_links = ", ".join(_code(x) for x in sorted(deps['columns'])) if deps['columns'] else "--"
            h += f'<tr><td><strong>{_esc(m)}</strong></td><td>{m_links}</td><td>{c_links}</td></tr>\n'
        h += "</tbody></table>\n"

    sidebar = '<li><a href="#sec7">Measure Lineage</a></li>'
    section = f'<h2 id="sec7">Measure Lineage <a href="#sec7" class="section-anchor">#</a></h2>\n{h}'
    return section, sidebar

# ---------------------------------------------------------------------------
# Main extraction function (called by GUI and CLI)
# ---------------------------------------------------------------------------

def extract_documentation(input_path, output_path=None, include_system_tables=False):
    """
    Extract metadata from a .pbix or .pbip file and generate HTML documentation.

    Parameters
    ----------
    input_path : str
        Path to the .pbix or .pbip file.
    output_path : str, optional
        Where to save the HTML. Default: same folder as the input.
    include_system_tables : bool
        Whether to include auto-generated system tables.

    Returns
    -------
    str
        The path to the generated HTML file.
    """
    input_path_obj = Path(input_path)
    report_name = input_path_obj.stem
    
    if input_path.lower().endswith('.pbix'):
        from pbixray import PBIXRay
        print(f"Loading PBIX: {input_path}")
        try:
            model = PBIXRay(input_path)
        except Exception as e:
            raise ValueError(f"Could not open the PBIX file: '{input_path}'.\nIt may be corrupted, missing, or locked. Details: {e}")
    elif input_path.lower().endswith('.pbip') or os.path.isdir(input_path):
        from pbip_adapter import PbipAdapter
        print(f"Loading PBIP/Folder: {input_path}")
        # The TmdlModel handles the internal resolution and throws clear FileNotFoundError/ValueError
        model = PbipAdapter(input_path)
    else:
        raise ValueError(f"Unsupported input: '{input_path}'. Expected a .pbix file, a .pbip file, or a SemanticModel folder.")

    print(f"  Tables:        {len(model.tables)}")
    print(f"  Measures:      {len(model.dax_measures)}")
    print(f"  Power Queries: {len(model.power_query)}")
    print(f"  Relationships: {len(model.relationships)}")

    # Extract Report Pages early (needed for unused-measures observation)
    if input_path.lower().endswith('.pbix'):
        pages = extract_report_pages_pbix(input_path)
    else:
        pages = extract_report_pages_pbip(input_path)
    print(f"  Report Pages:  {len(pages) if not isinstance(pages, str) else 'Error'}")

    # Build all sections
    sections = []
    sidebar_entries = []

    s, sb = build_data_sources(model.power_query, model.dax_tables, model.m_parameters, include_system_tables=include_system_tables)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_transformations(model.power_query, model.dax_tables, include_system_tables=include_system_tables)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_relationships(model.relationships, include_system_tables=include_system_tables)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_measures(model.dax_measures, include_system_tables=include_system_tables)
    sections.append(s); sidebar_entries.append(sb)

    s, sb = build_calculated_columns(model.dax_columns, include_system_tables=include_system_tables)
    sections.append(s); sidebar_entries.append(sb)

    # Add Calculation Groups if available (PBIP only)
    if hasattr(model, 'calculation_groups'):
        cg = model.calculation_groups
        if cg:
            s, sb = build_calculation_groups(cg, include_system_tables=include_system_tables)
            if s:
                sections.append(s); sidebar_entries.append(sb)

    s, sb = build_observations(model.power_query, model.relationships, model.dax_measures, model.dax_columns, pages=pages)
    sections.append(s); sidebar_entries.append(sb)

    all_columns = set()
    if getattr(model, 'schema', None) is not None and 'ColumnName' in model.schema.columns:
        all_columns.update(model.schema['ColumnName'].dropna().astype(str).tolist())
    if getattr(model, 'dax_columns', None) is not None and 'ColumnName' in model.dax_columns.columns:
        all_columns.update(model.dax_columns['ColumnName'].dropna().astype(str).tolist())
        
    s, sb = build_measure_lineage(model.dax_measures, all_columns, include_system_tables=include_system_tables)
    sections.append(s); sidebar_entries.append(sb)

    # Report Pages as last section (dynamic number)
    next_sec = len(sections) + 1
    s, sb = build_report_pages(pages, sec_num=next_sec)
    if s:
        sections.append(s); sidebar_entries.append(sb)

    # Assemble HTML
    full_content = "\n\n".join(sections)
    full_sidebar = "\n".join(sidebar_entries)
    output_html = generate_html(report_name, full_content, full_sidebar)

    # Output path
    if not output_path:
        output_path = os.path.join(input_path_obj.parent, f"{report_name}_Data_Documentation.html")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output_html)

    print(f"\n[OK] Documentation generated: {output_path}")
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate HTML data documentation from a Power BI .pbix or .pbip file.",
    )
    parser.add_argument("file", help="Path to the .pbix or .pbip file.")
    parser.add_argument("--output", "-o", help="Output HTML file path.")
    parser.add_argument("--sys-tables", action="store_true", help="Include auto-generated system tables.")
    args = parser.parse_args()

    extract_documentation(args.file, args.output, include_system_tables=args.sys_tables)


if __name__ == "__main__":
    main()
