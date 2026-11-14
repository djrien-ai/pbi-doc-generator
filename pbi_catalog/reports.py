"""
Report-level measures of thin reports.

A "thin" report is live-connected to a shared semantic model. Its authors can add measures that exist
only in the report ("report-level measures"); they are stored in the report definition, not the model:

- PBIR format:   `definition/reportExtensions.json` -> entities[].measures[]
- Legacy format: `report.json` -> config (JSON string) -> modelExtensions[].entities[].measures[]

Only those measures (name, DAX, format, folder, description, host table) are kept; the rest of the
report definition (pages, visuals, filters, images) is never stored.
"""

from __future__ import annotations

import json
import re

from .security import mask_secrets


def _measure(entity: str, m: dict) -> dict | None:
    name = m.get("name") or ""
    expr = m.get("expression") or ""
    if not name:
        return None
    fmt = m.get("formatString") or ((m.get("formatInformation") or {}).get("formatString") if isinstance(m.get("formatInformation"), dict) else "") or ""
    return {
        "table": entity,
        "name": name,
        "expr": mask_secrets(expr if isinstance(expr, str) else "\n".join(expr)),
        "format": fmt,
        "folder": m.get("displayFolder") or "",
        "description": m.get("description") or "",
        "data_type": str(m.get("dataType") or ""),
        "hidden": bool(m.get("hidden")),
    }


def _from_entities(entities: list) -> list[dict]:
    out = []
    for ent in entities or []:
        if not isinstance(ent, dict):
            continue
        tname = ent.get("name") or ent.get("extends") or ""
        for m in ent.get("measures") or []:
            rec = _measure(tname, m) if isinstance(m, dict) else None
            if rec:
                out.append(rec)
    return out


def parse_report_measures(parts: dict[str, str]) -> dict:
    """Return {format, measures, dataset_ref} from decoded report definition parts."""
    lower = {k.lower(): v for k, v in parts.items()}
    measures: list[dict] = []
    fmt = ""
    ext = lower.get("definition/reportextensions.json")
    if ext:
        fmt = "PBIR"
        try:
            measures = _from_entities(json.loads(ext.lstrip("﻿")).get("entities") or [])
        except ValueError:
            pass
    legacy = lower.get("report.json")
    if legacy and not measures:
        fmt = fmt or "PBIR-Legacy"
        try:
            rep = json.loads(legacy.lstrip("﻿"))
            cfg = rep.get("config") or "{}"
            cfg = json.loads(cfg) if isinstance(cfg, str) else cfg
            for ext_obj in cfg.get("modelExtensions") or []:
                measures += _from_entities(ext_obj.get("entities") or [])
        except ValueError:
            pass
    dataset_ref = ""
    pbir = lower.get("definition.pbir")
    if pbir:
        m = re.search(r"semanticmodelid=([0-9a-fA-F-]{36})", pbir, re.I)
        dataset_ref = m.group(1) if m else ""
    return {"format": fmt or ("PBIR" if pbir else ""), "measures": measures, "dataset_ref": dataset_ref}


# ---------------------------------------------------------------------------
# Report layout: pages, visuals, the fields they use, filters and slicer selections (no data)
# ---------------------------------------------------------------------------
LAYOUT_VERSION = 1
_AGG = {0: "Sum", 1: "Average", 2: "Distinct count", 3: "Min", 4: "Max", 5: "Count", 6: "Median", 7: "Std dev", 8: "Variance"}
_CMP = {0: "=", 1: ">", 2: ">=", 3: "<", 4: "<="}


def _loads(v, default=None):
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(v) if v else default
    except (TypeError, ValueError):
        return default


def _src_entity(expr, aliases: dict) -> str:
    sref = (expr or {}).get("SourceRef") or {}
    return sref.get("Entity") or aliases.get(sref.get("Source", ""), "") or ""


def field_of(expr, aliases: dict | None = None) -> dict | None:
    """Normalise a query expression (Column / Measure / Aggregation / HierarchyLevel) to {kind, table, name, ...}."""
    aliases = aliases or {}
    if not isinstance(expr, dict):
        return None
    if "Column" in expr:
        c = expr["Column"]
        return {"kind": "column", "table": _src_entity(c.get("Expression"), aliases), "name": c.get("Property", "")}
    if "Measure" in expr:
        m = expr["Measure"]
        return {"kind": "measure", "table": _src_entity(m.get("Expression"), aliases), "name": m.get("Property", "")}
    if "Aggregation" in expr:
        a = expr["Aggregation"]
        inner = field_of(a.get("Expression"), aliases)
        if inner:
            inner["agg"] = _AGG.get(a.get("Function"), f"Aggregation {a.get('Function')}")
        return inner
    if "HierarchyLevel" in expr:
        hl = expr["HierarchyLevel"]
        h = ((hl.get("Expression") or {}).get("Hierarchy")) or {}
        he = h.get("Expression") or {}
        if "PropertyVariationSource" in he:  # auto date/time hierarchy on a date column
            pv = he["PropertyVariationSource"]
            return {"kind": "column", "table": _src_entity(pv.get("Expression"), aliases), "name": pv.get("Property", ""), "level": hl.get("Level", "")}
        return {"kind": "hierarchy", "table": _src_entity(he, aliases), "name": h.get("Hierarchy", ""), "level": hl.get("Level", "")}
    if "SparklineData" in expr:
        return field_of((expr["SparklineData"] or {}).get("Measure"), aliases)
    return None


def _literal(v) -> str:
    s = str(v)
    if s == "null":
        return "(blank)"
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1].replace("''", "'")
    if re.fullmatch(r"-?\d+(\.\d+)?[LDM]", s):
        return s[:-1]
    m = re.fullmatch(r"datetime'([^']+)'", s)
    return m.group(1) if m else s


def _fname(f) -> str:
    if not f:
        return "?"
    base = f"{f.get('table', '')}[{f.get('name', '')}]"
    return (f"{f['agg']}({base})" if f.get("agg") else base) + (f" ({f['level']})" if f.get("level") else "")


def _lit(node) -> str:
    return _literal(((node or {}).get("Literal") or {}).get("Value", ""))


def _cond_text(cond, aliases: dict) -> tuple[str, list[str]]:
    """Readable text + selected literal values of a filter condition."""
    if not isinstance(cond, dict):
        return "", []
    if "In" in cond:
        i = cond["In"]
        fields = [_fname(field_of(e, aliases)) for e in i.get("Expressions") or []]
        vals = [" / ".join(_lit(x) for x in row) for row in i.get("Values") or []]
        if not vals and i.get("Table"):
            return f"{', '.join(fields)} in (table)", []
        return f"{', '.join(fields)} in ({', '.join(vals)})", vals
    if "Not" in cond:
        t, v = _cond_text((cond["Not"] or {}).get("Expression"), aliases)
        return (t.replace(" in (", " not in (", 1) if " in (" in t else f"not ({t})"), v
    if "Comparison" in cond:
        c = cond["Comparison"]
        right = c.get("Right") or {}
        val = _lit(right) if "Literal" in right else _fname(field_of(right, aliases))
        return f"{_fname(field_of(c.get('Left'), aliases))} {_CMP.get(c.get('ComparisonKind'), '?')} {val}", [val]
    for op, word in (("And", "and"), ("Or", "or")):
        if op in cond:
            a, va = _cond_text(cond[op].get("Left"), aliases)
            b, vb = _cond_text(cond[op].get("Right"), aliases)
            return f"({a} {word} {b})", va + vb
    for op, word in (("Contains", "contains"), ("StartsWith", "starts with"), ("EndsWith", "ends with")):
        if op in cond:
            c = cond[op]
            val = _lit(c.get("Right"))
            return f"{_fname(field_of(c.get('Left'), aliases))} {word} {val}", [val]
    if "Between" in cond:
        c = cond["Between"]
        lo, hi = _lit(c.get("LowerBound")), _lit(c.get("UpperBound"))
        return f"{_fname(field_of(c.get('Expression'), aliases))} between {lo} and {hi}", [lo, hi]
    return "", []


def _filter_def(flt) -> tuple[str, list[str]]:
    flt = _loads(flt, {}) or {}
    aliases = {f.get("Name", ""): f.get("Entity", "") for f in flt.get("From") or [] if isinstance(f, dict)}
    texts, values = [], []
    for w in flt.get("Where") or []:
        t, v = _cond_text((w or {}).get("Condition"), aliases)
        if t:
            texts.append(t)
            values += v
    return " and ".join(texts), values


def _filters(raw, level: str) -> list[dict]:
    out = []
    for f in _loads(raw, []) or []:
        if not isinstance(f, dict):
            continue
        cond, values = _filter_def(f.get("filter"))
        if level == "visual" and not cond:
            continue  # auto-created per-field entries of the filter pane that filter nothing
        out.append({
            "level": level,
            "name": f.get("name", ""),
            "field": field_of(f.get("field") or f.get("expression")),
            "type": f.get("type", ""),
            "how": f.get("howCreated", ""),
            "condition": cond,
            "values": values,
            "hidden": bool(f.get("isHiddenInViewMode")),
            "locked": bool(f.get("isLockedInViewMode")),
        })
    return out


def _title(objs) -> str:
    try:
        return _literal(objs["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"])
    except (KeyError, IndexError, TypeError):
        return ""


def _text_runs(objs) -> str:
    out = []
    for g in (objs or {}).get("general") or []:
        for para in ((g.get("properties") or {}).get("paragraphs") or []):
            out.append("".join(r.get("value", "") for r in para.get("textRuns") or []))
    return "\n".join(x for x in out if x)[:2000]


def _slicer_selection(objs) -> tuple[str, list[str]]:
    for g in (objs or {}).get("general") or []:
        flt = ((g.get("properties") or {}).get("filter") or {}).get("filter")
        if flt:
            return _filter_def(flt)
    return "", []


def _visual(vid, vtype, pos, roles, title, objs, vfilters, parent, hidden) -> dict:
    v = {
        "id": vid, "type": vtype, "title": title,
        "x": round(float(pos.get("x") or 0), 1), "y": round(float(pos.get("y") or 0), 1),
        "z": float(pos.get("z") or 0), "w": round(float(pos.get("width") or 0), 1), "h": round(float(pos.get("height") or 0), 1),
        "roles": roles, "parent": parent or "", "hidden": hidden,
    }
    if vfilters:
        v["filters"] = vfilters
    if vtype == "textbox":
        v["text"] = _text_runs(objs)
    if "slicer" in (vtype or "").lower():
        cond, vals = _slicer_selection(objs)
        if cond:
            v["selection"] = {"condition": cond, "values": vals}
    return v


def _layout_legacy(rep: dict) -> dict:
    pages = []
    for order, sec in enumerate(rep.get("sections") or []):
        scfg = _loads(sec.get("config"), {}) or {}
        visuals = []
        for vc in sec.get("visualContainers") or []:
            cfg = _loads(vc.get("config"), {}) or {}
            vid = cfg.get("name", "")
            pos = {"x": vc.get("x"), "y": vc.get("y"), "z": vc.get("z"), "width": vc.get("width"), "height": vc.get("height")}
            if "singleVisualGroup" in cfg:
                g = cfg["singleVisualGroup"] or {}
                visuals.append(_visual(vid, "group", pos, {}, g.get("displayName", ""), {}, [], cfg.get("parentGroupName", ""), bool(g.get("isHidden"))))
                continue
            sv = cfg.get("singleVisual") or {}
            pq = sv.get("prototypeQuery") or {}
            aliases = {f.get("Name", ""): f.get("Entity", "") for f in pq.get("From") or [] if isinstance(f, dict)}
            by_ref = {}
            for sel in pq.get("Select") or []:
                fld = field_of(sel, aliases)
                if fld:
                    by_ref[sel.get("Name", "")] = fld
            roles: dict[str, list] = {}
            for role, items in (sv.get("projections") or {}).items():
                for it in items or []:
                    fld = by_ref.get(it.get("queryRef", ""))
                    if fld:
                        roles.setdefault(role, []).append(dict(fld))
            hidden = ((cfg.get("layouts") or [{}])[0].get("display") or {}).get("mode") == "hidden"
            visuals.append(_visual(vid, sv.get("visualType") or "?", pos, roles, _title(sv.get("vcObjects") or {}), sv.get("objects") or {},
                                   _filters(vc.get("filters"), "visual"), cfg.get("parentGroupName", ""), bool(hidden)))
        pages.append({
            "name": sec.get("name") or f"page{order}", "display": sec.get("displayName", f"Page {order + 1}"), "order": sec.get("ordinal", order),
            "width": float(sec.get("width") or 1280), "height": float(sec.get("height") or 720),
            "hidden": int(scfg.get("visibility", 0) or 0) == 1, "filters": _filters(sec.get("filters"), "page"), "visuals": visuals,
        })
    pages.sort(key=lambda p: p["order"])
    return {"pages": pages, "filters": _filters(rep.get("filters"), "report")}


def _layout_pbir(parts: dict) -> dict:
    lower = {k.lower(): k for k in parts}
    page_dirs: dict[str, dict] = {}
    for k in parts:
        m = re.match(r"(?i)definition/pages/([^/]+)/page\.json$", k)
        if m:
            page_dirs[m.group(1)] = _loads(parts[k], {}) or {}
    meta = _loads(parts.get(lower.get("definition/pages/pages.json", ""), ""), {}) or {}
    order = {n: i for i, n in enumerate(meta.get("pageOrder") or [])}
    pages = []
    for pid, pj in page_dirs.items():
        visuals = []
        for k in parts:
            m = re.match(rf"(?i)definition/pages/{re.escape(pid)}/visuals/([^/]+)/visual\.json$", k)
            if not m:
                continue
            vj = _loads(parts[k], {}) or {}
            pos = vj.get("position") or {}
            if "visualGroup" in vj:
                g = vj["visualGroup"] or {}
                visuals.append(_visual(vj.get("name", m.group(1)), "group", pos, {}, g.get("displayName", ""), {}, [],
                                       vj.get("parentGroupName", ""), bool(vj.get("isHidden"))))
                continue
            vis = vj.get("visual") or {}
            roles: dict[str, list] = {}
            for role, st in ((vis.get("query") or {}).get("queryState") or {}).items():
                for pr in (st or {}).get("projections") or []:
                    fld = field_of(pr.get("field"))
                    if fld:
                        if pr.get("displayName"):
                            fld["label"] = pr["displayName"]
                        roles.setdefault(role, []).append(fld)
            visuals.append(_visual(vj.get("name", m.group(1)), vis.get("visualType") or "?", pos, roles,
                                   _title(vis.get("visualContainerObjects") or vis.get("vcObjects") or {}), vis.get("objects") or {},
                                   _filters((vj.get("filterConfig") or {}).get("filters"), "visual"), vj.get("parentGroupName", ""),
                                   bool(vj.get("isHidden"))))
        pages.append({
            "name": pid, "display": pj.get("displayName", pid), "order": order.get(pid, 999),
            "width": float(pj.get("width") or 1280), "height": float(pj.get("height") or 720),
            "hidden": pj.get("visibility") == "HiddenInViewMode",
            "filters": _filters((pj.get("filterConfig") or {}).get("filters"), "page"), "visuals": visuals,
        })
    pages.sort(key=lambda p: (p["order"], p["display"].lower()))
    rep = _loads(parts.get(lower.get("definition/report.json", ""), ""), {}) or {}
    return {"pages": pages, "filters": _filters((rep.get("filterConfig") or {}).get("filters"), "report")}


def parse_report_layout(parts: dict) -> dict:
    """Pages and visuals of a report (PBIR or legacy report.json): positions, visual types, titles, the
    columns / measures bound to each visual role, report / page / visual filters with their selected values,
    slicer selections and text box text. Only definition metadata - no query results."""
    lower = {k.lower(): k for k in parts}
    if any(k.startswith("definition/pages/") for k in lower):
        out = _layout_pbir(parts)
        out["format"] = "PBIR"
    elif "report.json" in lower:
        out = _layout_legacy(_loads(parts[lower["report.json"]], {}) or {})
        out["format"] = "PBIR-Legacy"
    else:
        out = {"pages": [], "filters": [], "format": ""}
    out["version"] = LAYOUT_VERSION
    out["visual_count"] = sum(len(p["visuals"]) for p in out["pages"])
    return out
