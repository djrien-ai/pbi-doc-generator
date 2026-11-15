"""
Unified Power BI Report Layout, PBIR Visual Binding, Filter/Slicer Inspector, and Thin-Report DAX Parser.

Supports:
1. Power BI Service / Fabric `getDefinition` report payloads (both PBIR `definition/pages/*` and legacy `report.json`).
2. Local `.pbix` archives (`Report/Layout` UTF-16LE/UTF-8 JSON and modern PBIR-in-PBIX `Report/definition/pages/*`).
3. Local `.pbip` / `.Report` project folders (`definition/pages/*`, `definition/reportExtensions.json`, or `report.json`).
4. Privacy-first literal redaction (`redact_report_layout_literals`) so `anonymous=True` never leaks business filter values.
"""

from __future__ import annotations

import copy
import json
import re
import zipfile
from pathlib import Path
from typing import Any

from .security import mask_secrets

LAYOUT_VERSION = 2

VISUAL_TYPE_LABELS: dict[str, str] = {
    "barChart": "Bar Chart",
    "columnChart": "Column Chart",
    "lineChart": "Line Chart",
    "areaChart": "Area Chart",
    "clusteredBarChart": "Clustered Bar",
    "clusteredColumnChart": "Clustered Column",
    "stackedBarChart": "Stacked Bar",
    "stackedColumnChart": "Stacked Column",
    "hundredPercentStackedBarChart": "100% Stacked Bar",
    "hundredPercentStackedColumnChart": "100% Stacked Column",
    "lineClusteredColumnComboChart": "Line & Column Combo",
    "lineStackedColumnComboChart": "Line & Stacked Column",
    "ribbonChart": "Ribbon Chart",
    "waterfallChart": "Waterfall",
    "funnelChart": "Funnel",
    "scatterChart": "Scatter",
    "pieChart": "Pie Chart",
    "donutChart": "Donut Chart",
    "treemap": "Treemap",
    "map": "Map",
    "filledMap": "Filled Map",
    "azureMap": "Azure Map",
    "shapeMap": "Shape Map",
    "gauge": "Gauge",
    "kpi": "KPI Card",
    "card": "Card",
    "cardVisual": "New Card",
    "multiRowCard": "Multi-Row Card",
    "tableEx": "Table",
    "pivotTable": "Matrix",
    "matrix": "Matrix",
    "slicer": "Slicer",
    "advancedSlicerVisual": "Button Slicer",
    "textbox": "Text Box",
    "image": "Image",
    "actionButton": "Action Button",
    "basicShape": "Shape",
    "shape": "Shape",
    "group": "Visual Group",
    "pageNavigator": "Page Navigator",
    "bookmarkNavigator": "Bookmark Navigator",
    "decompositionTreeVisual": "Decomposition Tree",
    "keyDriversVisual": "Key Influencers",
}

DECORATIVE_VISUAL_TYPES = {
    "textbox",
    "image",
    "basicShape",
    "shape",
    "group",
    "actionButton",
    "pageNavigator",
    "bookmarkNavigator",
}

_AGG_LABELS = {
    0: "Sum",
    1: "Average",
    2: "Distinct count",
    3: "Min",
    4: "Max",
    5: "Count",
    6: "Median",
    7: "Std dev",
    8: "Variance",
}
_CMP_OPS = {0: "=", 1: ">", 2: ">=", 3: "<", 4: "<="}


def readable_visual_type(vtype: str) -> str:
    if not vtype:
        return "Visual"
    return VISUAL_TYPE_LABELS.get(vtype, vtype)


def _loads(val: Any, default: Any = None) -> Any:
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str) and val.strip():
        try:
            return json.loads(val.lstrip("\ufeff"))
        except ValueError:
            return default
    return default


def _resolve_source_entity(expr_node: Any, alias_map: dict[str, str]) -> str:
    if not isinstance(expr_node, dict):
        return ""
    sref = expr_node.get("SourceRef")
    if isinstance(sref, dict):
        if sref.get("Entity"):
            return str(sref["Entity"])
        src_alias = str(sref.get("Source") or "")
        if src_alias and src_alias in alias_map:
            return alias_map[src_alias]
        return src_alias
    for sub in expr_node.values():
        if isinstance(sub, dict):
            found = _resolve_source_entity(sub, alias_map)
            if found:
                return found
    return ""


def _extract_field_ref(expr: Any, alias_map: dict[str, str] | None = None) -> dict[str, str] | None:
    """Extract `{entity, property, kind, ref, agg?, level?}` from a Power BI query AST expression."""
    amap = alias_map or {}
    if not isinstance(expr, dict):
        return None

    if "Measure" in expr and isinstance(expr["Measure"], dict):
        m = expr["Measure"]
        ent = _resolve_source_entity(m.get("Expression"), amap)
        prop = str(m.get("Property") or "").strip()
        if prop:
            return {
                "entity": ent,
                "property": prop,
                "kind": "measure",
                "ref": f"{ent}[{prop}]" if ent else f"[{prop}]",
            }

    if "Column" in expr and isinstance(expr["Column"], dict):
        c = expr["Column"]
        ent = _resolve_source_entity(c.get("Expression"), amap)
        prop = str(c.get("Property") or "").strip()
        if prop:
            return {
                "entity": ent,
                "property": prop,
                "kind": "column",
                "ref": f"{ent}[{prop}]" if ent else prop,
            }

    if "Aggregation" in expr and isinstance(expr["Aggregation"], dict):
        agg_node = expr["Aggregation"]
        inner = _extract_field_ref(agg_node.get("Expression"), amap)
        if inner:
            out = dict(inner)
            fn_id = agg_node.get("Function")
            if fn_id is not None:
                out["agg"] = _AGG_LABELS.get(fn_id, f"Agg({fn_id})")
            return out

    if "SparklineData" in expr and isinstance(expr["SparklineData"], dict):
        return _extract_field_ref(expr["SparklineData"].get("Measure"), amap)

    if "HierarchyLevel" in expr and isinstance(expr["HierarchyLevel"], dict):
        hl = expr["HierarchyLevel"]
        lvl = str(hl.get("Level") or "").strip()
        h_expr = hl.get("Expression")
        if isinstance(h_expr, dict) and "Hierarchy" in h_expr and isinstance(h_expr["Hierarchy"], dict):
            h_obj = h_expr["Hierarchy"]
            he = h_obj.get("Expression") or {}
            if isinstance(he, dict) and "PropertyVariationSource" in he and isinstance(he["PropertyVariationSource"], dict):
                pv = he["PropertyVariationSource"]
                ent = _resolve_source_entity(pv.get("Expression"), amap)
                prop = str(pv.get("Property") or "").strip()
                if prop:
                    return {
                        "entity": ent,
                        "property": prop,
                        "kind": "column",
                        "level": lvl,
                        "ref": f"{ent}[{prop}]" if ent else prop,
                    }
            ent = _resolve_source_entity(he, amap)
            h_prop = str(h_obj.get("Hierarchy") or "").strip()
            target = lvl or h_prop
            if target:
                return {
                    "entity": ent,
                    "property": target,
                    "kind": "hierarchy",
                    "level": lvl,
                    "ref": f"{ent}[{target}]" if ent else target,
                }
        ent = _resolve_source_entity(h_expr, amap)
        if lvl:
            return {
                "entity": ent,
                "property": lvl,
                "kind": "hierarchy",
                "level": lvl,
                "ref": f"{ent}[{lvl}]" if ent else lvl,
            }

    for k in ("field", "expr", "Expression"):
        if k in expr and isinstance(expr[k], dict):
            res = _extract_field_ref(expr[k], amap)
            if res:
                return res

    return None


def _literal_val(v: Any) -> str:
    s = str(v)
    if s == "null":
        return "(blank)"
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return mask_secrets(s[1:-1].replace("''", "'"))
    if re.fullmatch(r"-?\d+(\.\d+)?[LDM]", s):
        return s[:-1]
    m = re.fullmatch(r"datetime'([^']+)'", s)
    return m.group(1) if m else mask_secrets(s)


def _lit_node(node: Any) -> str:
    if not isinstance(node, dict):
        return ""
    return _literal_val((node.get("Literal") or {}).get("Value", ""))


def _fname(f: dict[str, str] | None) -> str:
    if not f:
        return "?"
    base = f.get("ref") or f"{f.get('entity', '')}[{f.get('property', '')}]"
    if f.get("agg"):
        base = f"{f['agg']}({base})"
    if f.get("level") and f.get("kind") == "column":
        base = f"{base} ({f['level']})"
    return base


def _cond_text(cond: Any, aliases: dict[str, str]) -> tuple[str, list[str]]:
    """Return `(readable_condition, literal_values)` for a Power BI filter AST condition."""
    if not isinstance(cond, dict):
        return "", []
    if "In" in cond and isinstance(cond["In"], dict):
        i = cond["In"]
        flds = [_fname(_extract_field_ref(e, aliases)) for e in (i.get("Expressions") or [])]
        vals = [" / ".join(_lit_node(x) for x in row) for row in (i.get("Values") or []) if isinstance(row, list)]
        if not vals and i.get("Table"):
            return f"{', '.join(flds)} in (table)", []
        return f"{', '.join(flds)} in ({', '.join(vals)})", vals
    if "Not" in cond and isinstance(cond["Not"], dict):
        t, v = _cond_text(cond["Not"].get("Expression"), aliases)
        return (t.replace(" in (", " not in (", 1) if " in (" in t else f"not ({t})"), v
    if "Comparison" in cond and isinstance(cond["Comparison"], dict):
        c = cond["Comparison"]
        right = c.get("Right") or {}
        if isinstance(right, dict) and "Literal" in right:
            val = _lit_node(right)
            return f"{_fname(_extract_field_ref(c.get('Left'), aliases))} {_CMP_OPS.get(c.get('ComparisonKind'), '?')} {val}", [val]
        rhs_f = _fname(_extract_field_ref(right, aliases))
        return f"{_fname(_extract_field_ref(c.get('Left'), aliases))} {_CMP_OPS.get(c.get('ComparisonKind'), '?')} {rhs_f}", []
    for op, word in (("And", "and"), ("Or", "or")):
        if op in cond and isinstance(cond[op], dict):
            a, va = _cond_text(cond[op].get("Left"), aliases)
            b, vb = _cond_text(cond[op].get("Right"), aliases)
            return f"({a} {word} {b})", va + vb
    for op, word in (("Contains", "contains"), ("StartsWith", "starts with"), ("EndsWith", "ends with")):
        if op in cond and isinstance(cond[op], dict):
            c = cond[op]
            val = _lit_node(c.get("Right"))
            return f"{_fname(_extract_field_ref(c.get('Left'), aliases))} {word} {val}", [val]
    if "Between" in cond and isinstance(cond["Between"], dict):
        c = cond["Between"]
        lo, hi = _lit_node(c.get("LowerBound")), _lit_node(c.get("UpperBound"))
        return f"{_fname(_extract_field_ref(c.get('Expression'), aliases))} between {lo} and {hi}", [lo, hi]
    return "", []


def _parse_filter_def(flt: Any) -> tuple[str, list[str]]:
    flt_obj = _loads(flt, {}) or {}
    if not isinstance(flt_obj, dict):
        return "", []
    aliases = {
        str(f.get("Name") or ""): str(f.get("Entity") or "")
        for f in (flt_obj.get("From") or [])
        if isinstance(f, dict)
    }
    texts: list[str] = []
    values: list[str] = []
    for w in flt_obj.get("Where") or []:
        if isinstance(w, dict):
            t, v = _cond_text(w.get("Condition"), aliases)
            if t:
                texts.append(t)
                values.extend(v)
    return " and ".join(texts), values


def _parse_filters_rich(raw_filters: Any, level: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Return `(ref_strings, rich_filter_items)`."""
    arr = _loads(raw_filters, [])
    if not isinstance(arr, list):
        return [], []
    refs: list[str] = []
    seen_refs: set[str] = set()
    items: list[dict[str, Any]] = []
    for f in arr:
        if not isinstance(f, dict):
            continue
        fld = _extract_field_ref(f.get("field") or f.get("expression"))
        cond, values = _parse_filter_def(f.get("filter"))
        if fld and fld["ref"] not in seen_refs:
            seen_refs.add(fld["ref"])
            refs.append(fld["ref"])
        if level == "visual" and not cond:
            continue
        if not fld and not cond:
            continue
        items.append(
            {
                "level": level,
                "name": str(f.get("name") or ""),
                "field": fld,
                "ref": fld["ref"] if fld else "",
                "type": str(f.get("type") or ""),
                "condition": cond,
                "values": values,
                "hidden": bool(f.get("isHiddenInViewMode")),
                "locked": bool(f.get("isLockedInViewMode")),
            }
        )
    return refs, items


def _extract_text_runs(objs: Any) -> str:
    if not isinstance(objs, dict):
        return ""
    out: list[str] = []
    for g in objs.get("general") or []:
        if not isinstance(g, dict):
            continue
        for para in ((g.get("properties") or {}).get("paragraphs") or []):
            if isinstance(para, dict):
                out.append("".join(str(r.get("value") or "") for r in (para.get("textRuns") or []) if isinstance(r, dict)))
    return mask_secrets("\n".join(x for x in out if x)[:1500])


def _extract_slicer_selection(objs: Any) -> dict[str, Any] | None:
    if not isinstance(objs, dict):
        return None
    for g in objs.get("general") or []:
        if isinstance(g, dict):
            flt = ((g.get("properties") or {}).get("filter") or {}).get("filter")
            if flt:
                cond, vals = _parse_filter_def(flt)
                if cond:
                    return {"condition": cond, "values": vals}
    return None


def _extract_model_extensions_measures(ext_list: Any) -> list[dict[str, Any]]:
    """Extract report-level DAX measures from `modelExtensions` or `reportExtensions.json` entities."""
    if not isinstance(ext_list, list):
        return []
    measures: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for ext in ext_list:
        if not isinstance(ext, dict):
            continue
        for ent in ext.get("entities") or []:
            if not isinstance(ent, dict):
                continue
            tname = str(ent.get("name") or ent.get("extends") or "Report Measures").strip()
            for m in ent.get("measures") or []:
                if not isinstance(m, dict):
                    continue
                mname = str(m.get("name") or "").strip()
                raw_expr = m.get("expression") or ""
                expr_txt = raw_expr if isinstance(raw_expr, str) else "\n".join(str(x) for x in raw_expr)
                expr = mask_secrets(expr_txt.strip())
                if not mname or (tname.lower(), mname.lower()) in seen:
                    continue
                seen.add((tname.lower(), mname.lower()))
                fmt = (
                    m.get("formatString")
                    or ((m.get("formatInformation") or {}).get("formatString") if isinstance(m.get("formatInformation"), dict) else "")
                    or ""
                )
                measures.append(
                    {
                        "table": tname,
                        "name": mname,
                        "expr": expr,
                        "format": str(fmt).strip(),
                        "folder": str(m.get("displayFolder") or "").strip(),
                        "description": str(m.get("description") or "").strip(),
                        "data_type": str(m.get("dataType") or ""),
                        "hidden": bool(m.get("hidden")),
                    }
                )
    return measures


def parse_legacy_report_json(data: dict[str, Any], fmt_label: str = "PBIR-Legacy") -> dict[str, Any]:
    """Parse classic `Report/Layout` or `report.json` payload."""
    cfg_obj = _loads(data.get("config"), {}) or {}
    report_measures: list[dict[str, Any]] = []
    if isinstance(cfg_obj, dict) and "modelExtensions" in cfg_obj:
        report_measures.extend(_extract_model_extensions_measures(cfg_obj.get("modelExtensions")))

    report_filters, report_filter_items = _parse_filters_rich(data.get("filters"), "report")
    pages: list[dict[str, Any]] = []

    sections = sorted(data.get("sections") or [], key=lambda s: s.get("ordinal", 0))
    for s_idx, sec in enumerate(sections, 1):
        if not isinstance(sec, dict):
            continue
        p_name = str(sec.get("displayName") or sec.get("name") or f"Page {s_idx}")
        pw = float(sec.get("width") or 1280)
        ph = float(sec.get("height") or 720)
        sec_cfg = _loads(sec.get("config"), {}) or {}
        p_hidden = int((sec_cfg if isinstance(sec_cfg, dict) else {}).get("visibility", 0) or 0) == 1
        p_filters, p_filter_items = _parse_filters_rich(sec.get("filters"), "page")

        visuals: list[dict[str, Any]] = []
        for v_idx, vc in enumerate(sec.get("visualContainers") or [], 1):
            if not isinstance(vc, dict):
                continue
            vc_cfg = _loads(vc.get("config"), {}) or {}
            if not isinstance(vc_cfg, dict):
                vc_cfg = {}
            vid = str(vc_cfg.get("name") or f"v{s_idx}_{v_idx}")
            vx = round(float(vc.get("x") or 0), 1)
            vy = round(float(vc.get("y") or 0), 1)
            vz = float(vc.get("z") or 0)
            vw = round(float(vc.get("width") or 160), 1)
            vh = round(float(vc.get("height") or 100), 1)
            parent_grp = str(vc_cfg.get("parentGroupName") or "")

            if "singleVisualGroup" in vc_cfg and "singleVisual" not in vc_cfg:
                grp = vc_cfg.get("singleVisualGroup") or {}
                visuals.append(
                    {
                        "id": vid,
                        "type": "group",
                        "type_label": "Visual Group",
                        "decorative": True,
                        "title": mask_secrets(str(grp.get("displayName") or "")),
                        "x": vx,
                        "y": vy,
                        "z": vz,
                        "width": vw,
                        "height": vh,
                        "parent": parent_grp,
                        "hidden": bool(grp.get("isHidden")),
                        "fields": [],
                        "filters": [],
                        "filter_items": [],
                    }
                )
                continue

            sv = vc_cfg.get("singleVisual") or {}
            vtype = str(sv.get("visualType") or "visual")
            layouts_arr = vc_cfg.get("layouts") or []
            disp_mode = ((layouts_arr[0].get("display") or {}).get("mode") if layouts_arr and isinstance(layouts_arr[0], dict) else "")
            v_hidden = disp_mode == "hidden" or '"visibility":1' in json.dumps(vc_cfg).replace(" ", "")

            title = ""
            try:
                t_arr = (sv.get("vcObjects") or {}).get("title") or []
                if t_arr and isinstance(t_arr[0], dict):
                    val = (((t_arr[0].get("properties") or {}).get("text") or {}).get("expr") or {}).get("Literal", {}).get("Value", "")
                    title = _literal_val(val) if val else ""
            except Exception:
                title = ""

            alias_map: dict[str, str] = {}
            pq = sv.get("prototypeQuery") or {}
            for fr in pq.get("From") or []:
                if isinstance(fr, dict) and fr.get("Name") and fr.get("Entity"):
                    alias_map[str(fr["Name"])] = str(fr["Entity"])

            fields: list[dict[str, Any]] = []
            seen_refs: set[tuple[str, str]] = set()
            dt = _loads(vc.get("dataTransforms"), {}) or {}
            if isinstance(dt, dict):
                for sel in dt.get("selects") or []:
                    if not isinstance(sel, dict):
                        continue
                    f_info = _extract_field_ref(sel.get("expr"), alias_map)
                    if not f_info:
                        continue
                    roles = sel.get("roles") or {}
                    role = next(iter(roles.keys()), "Values") if isinstance(roles, dict) else "Values"
                    disp = str(sel.get("displayName") or f_info["property"]).strip()
                    rk = (role, f_info["ref"])
                    if rk not in seen_refs:
                        seen_refs.add(rk)
                        fields.append({**f_info, "role": role, "display": disp})

            if not fields:
                proj_role: dict[str, str] = {}
                for r_name, r_items in (sv.get("projections") or {}).items():
                    if isinstance(r_items, list):
                        for it in r_items:
                            if isinstance(it, dict) and it.get("queryRef"):
                                proj_role[str(it["queryRef"])] = str(r_name)
                for sel in pq.get("Select") or []:
                    if not isinstance(sel, dict):
                        continue
                    f_info = _extract_field_ref(sel, alias_map)
                    if not f_info:
                        continue
                    qname = str(sel.get("Name") or "")
                    disp = str(sel.get("NativeReferenceName") or f_info["property"]).strip()
                    role = proj_role.get(qname, "Values")
                    rk = (role, f_info["ref"])
                    if rk not in seen_refs:
                        seen_refs.add(rk)
                        fields.append({**f_info, "role": role, "display": disp})

            v_filters, v_filter_items = _parse_filters_rich(vc.get("filters"), "visual")
            objs = sv.get("objects") or {}
            v_item: dict[str, Any] = {
                "id": vid,
                "type": vtype,
                "type_label": readable_visual_type(vtype),
                "decorative": vtype in DECORATIVE_VISUAL_TYPES and not fields,
                "title": title,
                "x": vx,
                "y": vy,
                "z": vz,
                "width": vw,
                "height": vh,
                "parent": parent_grp,
                "hidden": v_hidden,
                "fields": fields,
                "filters": v_filters,
                "filter_items": v_filter_items,
            }
            if vtype == "textbox":
                txt = _extract_text_runs(objs)
                if txt:
                    v_item["text"] = txt
            if "slicer" in vtype.lower():
                sel_info = _extract_slicer_selection(objs)
                if sel_info:
                    v_item["selection"] = sel_info
            visuals.append(v_item)

        pages.append(
            {
                "id": str(sec.get("name") or f"page_{s_idx}"),
                "name": p_name,
                "hidden": p_hidden,
                "width": pw,
                "height": ph,
                "filters": p_filters,
                "filter_items": p_filter_items,
                "visuals": visuals,
            }
        )

    return {
        "version": LAYOUT_VERSION,
        "format": fmt_label,
        "dataset_ref": "",
        "report_filters": report_filters,
        "report_filter_items": report_filter_items,
        "report_measures": report_measures,
        "pages": pages,
    }


def parse_pbir_files_map(files: dict[str, str]) -> dict[str, Any]:
    """Parse modern PBIR file map (`definition/pages/*/page.json`, `visuals/*/visual.json`, `reportExtensions.json`, `definition.pbir`)."""
    norm: dict[str, str] = {}
    lower_to_norm: dict[str, str] = {}
    for k, v in files.items():
        clean_k = k.replace("\\", "/").lstrip("/")
        if clean_k.startswith("Report/definition/"):
            clean_k = clean_k[len("Report/") :]
        norm[clean_k] = v
        lower_to_norm[clean_k.lower()] = clean_k

    dataset_ref = ""
    pbir_key = lower_to_norm.get("definition.pbir") or lower_to_norm.get("report/definition.pbir")
    if pbir_key:
        m_ds = re.search(r"semanticModelId\s*=\s*([0-9a-fA-F-]{36})", norm[pbir_key], re.I)
        if not m_ds:
            m_ds = re.search(r'"semanticModelId"\s*:\s*"([0-9a-fA-F-]{36})"', norm[pbir_key], re.I)
        if m_ds:
            dataset_ref = m_ds.group(1)

    if "report.json" in lower_to_norm and not any(p.startswith("definition/pages/") for p in lower_to_norm):
        raw_rep = _loads(norm[lower_to_norm["report.json"]], {})
        if isinstance(raw_rep, dict):
            out = parse_legacy_report_json(raw_rep, fmt_label="PBIR-Legacy")
            out["dataset_ref"] = dataset_ref
            return out
        return {
            "version": LAYOUT_VERSION,
            "format": "PBIR-Legacy",
            "dataset_ref": dataset_ref,
            "report_filters": [],
            "report_filter_items": [],
            "report_measures": [],
            "pages": [],
        }

    report_measures: list[dict[str, Any]] = []
    ext_key = lower_to_norm.get("definition/reportextensions.json")
    if ext_key:
        ext_data = _loads(norm[ext_key], {})
        if isinstance(ext_data, dict):
            report_measures.extend(_extract_model_extensions_measures([ext_data]))

    report_filters: list[str] = []
    report_filter_items: list[dict[str, Any]] = []
    rep_key = lower_to_norm.get("definition/report.json")
    if rep_key:
        rep_root = _loads(norm[rep_key], {})
        if isinstance(rep_root, dict):
            report_filters, report_filter_items = _parse_filters_rich(
                (rep_root.get("filterConfig") or {}).get("filters") or rep_root.get("filters"),
                "report",
            )

    page_order: list[str] = []
    pages_meta_key = lower_to_norm.get("definition/pages/pages.json")
    if pages_meta_key:
        pmeta = _loads(norm[pages_meta_key], {})
        if isinstance(pmeta, dict):
            page_order = [str(x) for x in (pmeta.get("pageOrder") or [])]

    pages_by_id: dict[str, dict[str, Any]] = {}
    for path, txt in sorted(norm.items()):
        m = re.match(r"(?i)^definition/pages/([^/]+)/page\.json$", path)
        if not m:
            continue
        pid = m.group(1)
        pdata = _loads(txt, {})
        if not isinstance(pdata, dict):
            continue
        pw = float(pdata.get("width") or (pdata.get("displayOption") or {}).get("width") or 1280)
        ph = float(pdata.get("height") or (pdata.get("displayOption") or {}).get("height") or 720)
        vis_flag = pdata.get("visibility")
        p_hidden = vis_flag in (1, "HiddenInViewMode", True)
        p_filters, p_filter_items = _parse_filters_rich(
            (pdata.get("filterConfig") or {}).get("filters") or pdata.get("filters"),
            "page",
        )
        pages_by_id[pid] = {
            "id": pid,
            "name": str(pdata.get("displayName") or pid),
            "hidden": p_hidden,
            "width": pw,
            "height": ph,
            "filters": p_filters,
            "filter_items": p_filter_items,
            "visuals": [],
        }

    for path, txt in sorted(norm.items()):
        m = re.match(r"(?i)^definition/pages/([^/]+)/visuals/([^/]+)/visual\.json$", path)
        if not m:
            continue
        pid, vid = m.group(1), m.group(2)
        if pid not in pages_by_id:
            continue
        vdata = _loads(txt, {})
        if not isinstance(vdata, dict):
            continue
        pos = vdata.get("position") or {}
        vx = round(float(pos.get("x") or 0), 1)
        vy = round(float(pos.get("y") or 0), 1)
        vz = float(pos.get("z") or 0)
        vw = round(float(pos.get("width") or 160), 1)
        vh = round(float(pos.get("height") or 100), 1)
        parent_grp = str(vdata.get("parentGroupName") or "")
        v_hidden = bool(vdata.get("isHidden") or vdata.get("visibility") in (1, "HiddenInViewMode"))

        if "visualGroup" in vdata and "visual" not in vdata:
            grp = vdata.get("visualGroup") or {}
            pages_by_id[pid]["visuals"].append(
                {
                    "id": str(vdata.get("name") or vid),
                    "type": "group",
                    "type_label": "Visual Group",
                    "decorative": True,
                    "title": mask_secrets(str(grp.get("displayName") or "")),
                    "x": vx,
                    "y": vy,
                    "z": vz,
                    "width": vw,
                    "height": vh,
                    "parent": parent_grp,
                    "hidden": v_hidden,
                    "fields": [],
                    "filters": [],
                    "filter_items": [],
                }
            )
            continue

        vis = vdata.get("visual") or {}
        vtype = str(vis.get("visualType") or "visual")
        title = ""
        try:
            t_arr = (vis.get("visualContainerObjects") or vis.get("vcObjects") or {}).get("title") or []
            if t_arr and isinstance(t_arr[0], dict):
                val = (((t_arr[0].get("properties") or {}).get("text") or {}).get("expr") or {}).get("Literal", {}).get("Value", "")
                title = _literal_val(val) if val else ""
        except Exception:
            title = ""

        fields: list[dict[str, Any]] = []
        seen_refs: set[tuple[str, str]] = set()
        qstate = (vis.get("query") or {}).get("queryState") or {}
        if isinstance(qstate, dict):
            for role, role_obj in qstate.items():
                projs = (
                    role_obj.get("projections")
                    if isinstance(role_obj, dict)
                    else (role_obj if isinstance(role_obj, list) else [])
                )
                if not isinstance(projs, list):
                    continue
                for prj in projs:
                    if not isinstance(prj, dict):
                        continue
                    f_info = _extract_field_ref(prj.get("field") or prj)
                    if not f_info:
                        continue
                    disp = str(prj.get("displayName") or prj.get("nativeQueryRef") or f_info["property"]).strip()
                    rk = (str(role), f_info["ref"])
                    if rk not in seen_refs:
                        seen_refs.add(rk)
                        fields.append({**f_info, "role": str(role), "display": disp})

        v_filters, v_filter_items = _parse_filters_rich(
            (vdata.get("filterConfig") or {}).get("filters") or vdata.get("filters"),
            "visual",
        )
        objs = vis.get("objects") or {}
        v_item: dict[str, Any] = {
            "id": str(vdata.get("name") or vid),
            "type": vtype,
            "type_label": readable_visual_type(vtype),
            "decorative": vtype in DECORATIVE_VISUAL_TYPES and not fields,
            "title": title,
            "x": vx,
            "y": vy,
            "z": vz,
            "width": vw,
            "height": vh,
            "parent": parent_grp,
            "hidden": v_hidden,
            "fields": fields,
            "filters": v_filters,
            "filter_items": v_filter_items,
        }
        if vtype == "textbox":
            txt = _extract_text_runs(objs)
            if txt:
                v_item["text"] = txt
        if "slicer" in vtype.lower():
            sel_info = _extract_slicer_selection(objs)
            if sel_info:
                v_item["selection"] = sel_info
        pages_by_id[pid]["visuals"].append(v_item)

    ordered_ids = [pid for pid in page_order if pid in pages_by_id] + [pid for pid in pages_by_id if pid not in page_order]
    return {
        "version": LAYOUT_VERSION,
        "format": "PBIR",
        "dataset_ref": dataset_ref,
        "report_filters": report_filters,
        "report_filter_items": report_filter_items,
        "report_measures": report_measures,
        "pages": [pages_by_id[pid] for pid in ordered_ids],
    }


def redact_report_layout_literals(layout: dict[str, Any] | None) -> dict[str, Any]:
    """Return a copy of `layout` with all business filter/slicer literal values and textbox paragraphs redacted."""
    if not isinstance(layout, dict):
        return {}
    out = copy.deepcopy(layout)

    def _scrub_str(s: str) -> str:
        # Preserve quoted table names before `[Column]`, scrub any other quoted or comparison RHS literals
        def _repl_quote(m: re.Match[str]) -> str:
            after = s[m.end() :]
            if after.lstrip().startswith("["):
                return m.group(0)
            return "'<redacted>'"

        cleaned = re.sub(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"", _repl_quote, str(s or ""))
        cleaned = re.sub(r"((?:=|<>|!=|>=|<=|>|<|\bin\b|\bcontains\b)\s*)(?!'<redacted>')[^\s,)]+", r"\1<redacted>", cleaned, flags=re.I)
        return cleaned

    def _scrub_items(items: list[dict[str, Any]]) -> None:
        for it in items or []:
            vals = it.get("values") or []
            cond = str(it.get("condition") or "")
            for val in sorted((str(v) for v in vals if v and v != "(blank)"), key=len, reverse=True):
                cond = cond.replace(val, "<redacted>")
            it["condition"] = _scrub_str(cond) if cond else ""
            if vals:
                it["values"] = ["<redacted>" for _ in vals]

    def _scrub_str_list(strs: list[Any]) -> list[str]:
        return [_scrub_str(str(x)) for x in (strs or [])]

    _scrub_items(out.get("report_filter_items") or [])
    _scrub_items(out.get("filter_items") or [])
    if "report_filters" in out:
        out["report_filters"] = _scrub_str_list(out.get("report_filters") or [])

    for pg in out.get("pages") or []:
        _scrub_items(pg.get("filter_items") or [])
        if "filters" in pg:
            pg["filters"] = _scrub_str_list(pg.get("filters") or [])
        for vis in pg.get("visuals") or []:
            _scrub_items(vis.get("filter_items") or [])
            if "filters" in vis:
                vis["filters"] = _scrub_str_list(vis.get("filters") or [])
            if "selection" in vis:
                if isinstance(vis["selection"], dict):
                    s_vals = vis["selection"].get("values") or []
                    s_cond = str(vis["selection"].get("condition") or "")
                    for val in sorted((str(v) for v in s_vals if v and v != "(blank)"), key=len, reverse=True):
                        s_cond = s_cond.replace(val, "<redacted>")
                    vis["selection"] = {"condition": _scrub_str(s_cond), "values": ["<redacted>" for _ in s_vals]}
                elif isinstance(vis["selection"], list):
                    vis["selection"] = ["<redacted>" for _ in vis["selection"]]
                elif vis["selection"]:
                    vis["selection"] = "<redacted>"
            if vis.get("text"):
                vis["text"] = "<redacted in anonymous export>"
    return out


def parse_report_definition_files(files: dict[str, str]) -> dict[str, Any]:
    """Entry point for Fabric `getDefinition` report file payloads."""
    if not files:
        return {
            "version": LAYOUT_VERSION,
            "format": "Unknown",
            "dataset_ref": "",
            "report_filters": [],
            "report_filter_items": [],
            "report_measures": [],
            "pages": [],
        }
    return parse_pbir_files_map(files)


def parse_pbix_report(pbix_path: str | Path) -> dict[str, Any]:
    """Extract report pages, visuals, filters, and report-level DAX measures from a `.pbix` file."""
    p = Path(pbix_path)
    if not p.is_file():
        return {"version": LAYOUT_VERSION, "format": "PBIX", "dataset_ref": "", "report_filters": [], "report_filter_items": [], "report_measures": [], "pages": []}
    try:
        with zipfile.ZipFile(p, "r") as z:
            names = set(z.namelist())
            if "Report/Layout" in names:
                raw = z.read("Report/Layout")
                txt = raw.decode("utf-16-le", errors="ignore").lstrip("\ufeff")
                if not txt.startswith("{"):
                    txt = raw.decode("utf-8", errors="ignore").lstrip("\ufeff")
                data = json.loads(txt)
                return parse_legacy_report_json(data, fmt_label="PBIX")

            pbir_files: dict[str, str] = {}
            for name in names:
                if name.startswith("Report/") and name.lower().endswith((".json", ".pbir")) and "resources/" not in name.lower():
                    pbir_files[name] = z.read(name).decode("utf-8-sig", errors="ignore")
            if pbir_files:
                return parse_pbir_files_map(pbir_files)
    except Exception:
        pass
    return {"version": LAYOUT_VERSION, "format": "PBIX", "dataset_ref": "", "report_filters": [], "report_filter_items": [], "report_measures": [], "pages": []}


def parse_pbip_report_dir(report_dir: str | Path) -> dict[str, Any]:
    """Extract report pages, visuals, filters, and report-level DAX measures from a `.Report` folder."""
    rdir = Path(report_dir)
    if not rdir.is_dir():
        return {"version": LAYOUT_VERSION, "format": "PBIP", "dataset_ref": "", "report_filters": [], "report_filter_items": [], "report_measures": [], "pages": []}
    files_map: dict[str, str] = {}
    pbir_ptr = rdir / "definition.pbir"
    if pbir_ptr.is_file():
        try:
            files_map["definition.pbir"] = pbir_ptr.read_text(encoding="utf-8-sig", errors="ignore")
        except Exception:
            pass
    def_dir = rdir / "definition"
    if def_dir.is_dir():
        for jf in def_dir.rglob("*.json"):
            rel = jf.relative_to(rdir).as_posix()
            if "resources/" in rel.lower():
                continue
            try:
                files_map[rel] = jf.read_text(encoding="utf-8-sig", errors="ignore")
            except Exception:
                pass
        if files_map:
            return parse_pbir_files_map(files_map)

    legacy_json = rdir / "report.json"
    if legacy_json.is_file():
        try:
            data = json.loads(legacy_json.read_text(encoding="utf-8-sig", errors="ignore"))
            out = parse_legacy_report_json(data, fmt_label="PBIR-Legacy")
            if "definition.pbir" in files_map:
                m_ds = re.search(r"semanticModelId\s*=\s*([0-9a-fA-F-]{36})", files_map["definition.pbir"], re.I)
                if m_ds:
                    out["dataset_ref"] = m_ds.group(1)
            return out
        except Exception:
            pass
    return {"version": LAYOUT_VERSION, "format": "PBIP", "dataset_ref": "", "report_filters": [], "report_filter_items": [], "report_measures": [], "pages": []}


def parse_dataflow_model_json(data: dict[str, Any]) -> dict[str, Any]:
    """Compatibility wrapper delegating Gen1/Gen2 dataflow parsing to `dataflows.parse_dataflow_definition`."""
    from .dataflows import parse_dataflow_definition

    parsed = parse_dataflow_definition({}, data if isinstance(data, dict) else {})
    return {
        "description": parsed.get("description", ""),
        "entities": parsed.get("entities", []),
        "queries": parsed.get("queries", []),
        "source_types": parsed.get("source_types", []),
    }
