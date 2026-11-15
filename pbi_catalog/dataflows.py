"""
Unified Power BI Dataflow Gen1 (`model.json`) & Microsoft Fabric Dataflow Gen2 (`mashup.pq`) Parser.

Capabilities:
- Parses Power BI Dataflow Gen1 `model.json` exports (both top-level `pbi:mashup` and `annotations[]` format),
  including `ReferenceEntity` linked entities without M code and `strip_data_locations()` privacy sanitization.
- Parses Microsoft Fabric Dataflow Gen2 definitions (`mashup.pq` + `queryMetadata.json`), including OneLake
  Lakehouse / Warehouse output destination targets.
- Delegates all Power Query M, Native SQL, connector, and step-by-step analysis to `analyzer.analyze_m_partition()`
  so semantic models and dataflows share one unified M/SQL engine.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .analyzer import analyze_m_partition
from .mparse import (
    DATAFLOW_CONNECTOR_RE,
    _GUID_RE,
    decode_m_escapes,
    find_dataflow_refs,
    referenced_dataflow_ids,
    split_m_section,
)
from .security import mask_secrets

__all__ = [
    "DATAFLOW_CONNECTOR_RE",
    "decode_m_escapes",
    "definition_dataflow_refs",
    "describe_sources",
    "find_dataflow_refs",
    "parse_dataflow_definition",
    "reference_entity_ref",
    "referenced_dataflow_ids",
    "strip_data_locations",
]


def describe_sources(code: str, params: dict[str, str], shared_names: list[str]) -> dict:
    """Delegate to the unified `analyze_m_partition` engine (kept as a clean helper for E2E lineage & tests)."""
    return analyze_m_partition(code, params, shared_names)


def _query_kind(code: str) -> str:
    compact = (code or "").replace(" ", "")
    if "IsParameterQuery=true" in compact:
        return "parameter"
    if re.search(r"^\s*(let\s+)?\w+\s*=\s*\([^)]*\)\s*=>|^\s*\([^)]*\)\s*(as\s+\w+\s*)?=>", code or "", re.M):
        return "function"
    return "query"


def _param_value(code: str) -> str:
    pm = re.search(r'^\s*"((?:[^"]|"")*)"\s+meta\s*\[', code or "")
    if pm:
        return pm.group(1).replace('""', '"')
    pm = re.search(r"^\s*([\w.\-]+)\s+meta\s*\[", code or "")
    return pm.group(1) if pm else ""


def _extract_mashup_payload(definition: dict) -> tuple[str, dict, bool, str]:
    """Return `(document, queries_metadata, allow_native_queries, generation_hint)` from Gen1 or Gen2 payload."""
    parts = definition.get("parts")
    if isinstance(parts, dict) and ("mashup.pq" in parts or "queryMetadata.json" in parts):
        doc = str(parts.get("mashup.pq") or "")
        raw_qm = parts.get("queryMetadata.json")
        qm_root = json.loads(raw_qm.lstrip("\ufeff")) if isinstance(raw_qm, str) and raw_qm.strip() else (raw_qm if isinstance(raw_qm, dict) else {})
        q_meta = (qm_root or {}).get("queriesMetadata") or {}
        allow_nq = bool((qm_root or {}).get("allowNativeQueries", (qm_root or {}).get("fastCombine", False)))
        return doc, q_meta, allow_nq, "Gen2"
    if "mashup_pq" in definition or "query_metadata" in definition:
        doc = str(definition.get("mashup_pq") or "")
        raw_qm = definition.get("query_metadata")
        qm_root = json.loads(raw_qm.lstrip("\ufeff")) if isinstance(raw_qm, str) and raw_qm.strip() else (raw_qm if isinstance(raw_qm, dict) else {})
        q_meta = (qm_root or {}).get("queriesMetadata") or {}
        allow_nq = bool((qm_root or {}).get("allowNativeQueries", (qm_root or {}).get("fastCombine", False)))
        return doc, q_meta, allow_nq, "Gen2"

    mashup = definition.get("pbi:mashup")
    if not isinstance(mashup, dict):
        mashup = {}
        for ann in definition.get("annotations") or []:
            if isinstance(ann, dict) and ann.get("name") == "pbi:mashup":
                val = ann.get("value")
                if isinstance(val, dict):
                    mashup = val
                elif isinstance(val, str):
                    try:
                        parsed_ann = json.loads(val)
                        if isinstance(parsed_ann, dict):
                            mashup = parsed_ann
                        else:
                            mashup = {"document": val}
                    except ValueError:
                        mashup = {"document": val}
                break
    doc = str(mashup.get("document") or "")
    q_meta = mashup.get("queriesMetadata") or {}
    if isinstance(q_meta, str):
        try:
            q_meta = json.loads(q_meta)
        except ValueError:
            q_meta = {}
    return doc, (q_meta if isinstance(q_meta, dict) else {}), bool(mashup.get("allowNativeQueries")), "Gen1"


def reference_entity_ref(ent: dict, definition: dict) -> dict:
    """Resolve a Gen1 `model.json` `ReferenceEntity` to `{workspace_id, dataflow_id, entity}`."""
    model_id = ent.get("modelId") or ""
    ws_id, _, df_id = model_id.rpartition("/")
    if not ws_id:
        ref_model = next(
            (r for r in definition.get("referenceModels") or [] if (r.get("id") or "").endswith(model_id)),
            {},
        )
        ws_id = (ref_model.get("id") or "").rpartition("/")[0]
    return {
        "workspace_id": ws_id,
        "dataflow_id": df_id or model_id,
        "entity": ent.get("source") or ent.get("name", ""),
    }


def _extract_gen2_destination(qm: dict, code: str) -> dict | None:
    """Detect Fabric Dataflow Gen2 data destination (Lakehouse / Warehouse / SQL) from queryMetadata or M steps."""
    dests = qm.get("destinations") or qm.get("dataDestinations") or []
    d0: dict | None = None
    if isinstance(dests, list) and dests and isinstance(dests[0], dict):
        d0 = dests[0]
    elif isinstance(qm.get("destinationSettings"), dict):
        d0 = qm["destinationSettings"]
    if d0:
        kind = d0.get("type") or d0.get("kind") or "Lakehouse"
        tbl = d0.get("tableName") or d0.get("entityName") or d0.get("table") or ""
        item_name = d0.get("itemName") or d0.get("lakehouseName") or d0.get("warehouseName") or ""
        schema_name = d0.get("schemaName") or d0.get("schema") or ""
        ws = d0.get("workspaceId") or ""
        artifact = d0.get("artifactId") or d0.get("itemId") or d0.get("lakehouseId") or d0.get("warehouseId") or ""
        return {
            "kind": str(kind),
            "table": str(tbl or item_name),
            "schema": str(schema_name),
            "item_name": str(item_name),
            "workspace_id": str(ws),
            "artifact_id": str(artifact),
        }
    if code and re.search(r"Lakehouse\.Contents|Fabric\.Warehouse", code):
        nav_m = re.search(r'Item\s*=\s*"((?:[^"]|"")*)"', code)
        if "_DataDestination" in code:
            return {
                "kind": "Warehouse" if "Fabric.Warehouse" in code else "Lakehouse",
                "table": nav_m.group(1) if nav_m else "",
                "workspace_id": "",
                "artifact_id": "",
            }
    return None


def parse_dataflow_definition(meta: dict, definition: dict) -> dict[str, Any]:
    """Parse a Gen1 `model.json` or Gen2 `mashup.pq` definition + catalog metadata into classified queries & entities."""
    if not isinstance(definition, dict):
        definition = {}
    document, q_meta, allow_nq, gen_hint = _extract_mashup_payload(definition)
    gen_raw = str(meta.get("generation") or definition.get("format") or gen_hint)
    generation = "Gen2" if "2" in gen_raw else "Gen1"

    members = split_m_section(document)
    entities_by_name: dict[str, dict] = {}
    for ent in definition.get("entities") or []:
        if isinstance(ent, dict) and ent.get("name"):
            entities_by_name[str(ent["name"])] = ent

    member_names = {m["name"] for m in members}
    reference_refs: dict[str, dict] = {}
    for ent in definition.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        ename = str(ent.get("name") or "").strip()
        if not ename:
            continue
        if ent.get("$type") == "ReferenceEntity":
            reference_refs[ename] = reference_entity_ref(ent, definition)
            if ename not in member_names:
                members.append({"name": ename, "code": "", "description": ent.get("description", ""), "linked_only": True})
                member_names.add(ename)
        elif ename not in member_names:
            part_code = ""
            for part in ent.get("partitions") or []:
                if isinstance(part, dict) and isinstance(part.get("source"), dict):
                    part_code = str(part["source"].get("expression") or "")
                    if part_code:
                        break
            members.append({"name": ename, "code": part_code, "description": ent.get("description", "")})
            member_names.add(ename)

    params: dict[str, str] = {}
    for mem in members:
        if _query_kind(mem["code"]) == "parameter":
            params[mem["name"]] = _param_value(mem["code"])

    shared_names = [mem["name"] for mem in members]
    loaded_names = set()
    for mem in members:
        mname = mem["name"]
        if mname.endswith("_DataDestination"):
            continue
        qm_item = q_meta.get(mname) if isinstance(q_meta.get(mname), dict) else {}
        default_load = (mname in entities_by_name) if entities_by_name else (_query_kind(mem["code"]) == "query")
        is_loaded = bool(qm_item.get("loadEnabled", not qm_item.get("isHidden", not default_load)))
        if mem.get("linked_only"):
            is_loaded = True
        if is_loaded:
            loaded_names.add(mname)

    # Pair Gen2 `<Query>_DataDestination` helper queries with `<Query>`
    dest_code_by_query: dict[str, str] = {}
    for mem in members:
        if mem["name"].endswith("_DataDestination"):
            base_q = mem["name"][: -len("_DataDestination")]
            dest_code_by_query[base_q] = mem["code"]

    queries: list[dict] = []
    entities_summary: list[dict] = []
    all_source_types: set[str] = set()

    for mem in members:
        name = mem["name"]
        if name.endswith("_DataDestination"):
            continue
        code = mem["code"]
        kind = _query_kind(code)
        qm = q_meta.get(name) if isinstance(q_meta.get(name), dict) else {}
        ent = entities_by_name.get(name) or {}
        load_enabled = name in loaded_names

        info = analyze_m_partition(code, params, [s for s in shared_names if s != name and not s.endswith("_DataDestination")])
        refs = list(info.get("dataflow_refs") or [])
        if not refs and name in reference_refs:
            refs = [reference_refs[name]]

        intra = [d for d in info["depends_on"] if d in shared_names]
        param_deps = [d for d in intra if d in params]
        query_deps = [d for d in intra if d not in params]

        if mem.get("linked_only"):
            role = "Linked entity"
        elif kind == "parameter":
            role = "Parameter"
        elif kind == "function":
            role = "Function"
        elif refs:
            role = "Linked entity" if load_enabled else "Linked query (staging)"
        elif load_enabled and any(d in loaded_names for d in query_deps):
            role = "Computed entity"
        elif load_enabled:
            role = "Entity"
        else:
            role = "Staging / helper query"

        columns = [
            {"name": str(a.get("name") or ""), "type": str(a.get("dataType") or "string")}
            for a in (ent.get("attributes") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        src_types_clean = [t for t in info["source_types"] if t != "Power BI Dataflow"]
        for st in src_types_clean:
            all_source_types.add(st)

        dest = _extract_gen2_destination(qm, dest_code_by_query.get(name, "")) if generation == "Gen2" else None
        masked_code = mask_secrets(code)
        desc_txt = str(mem.get("description") or ent.get("description") or "").strip()

        q_obj = {
            "name": name,
            "kind": kind,
            "role": role,
            "load_enabled": load_enabled,
            "description": desc_txt,
            "code": masked_code,
            "depends_on": query_deps,
            "parameters": param_deps,
            "dataflow_refs": refs,
            "source_types": src_types_clean,
            "sources": [s for s in info["sources"] if s["type"] != "Power BI Dataflow"],
            "endpoints": info["endpoints"],
            "files": info["files"],
            "sheets": info["sheets"],
            "objects": info["objects"],
            "native_queries": info["native_queries"],
            "native_sql": info["native_sql"],
            "step_count": info["step_count"],
            "step_items": info["step_items"],
            "columns": columns,
            "query_id": str(qm.get("queryId") or ""),
            "default_value": mask_secrets(params.get(name, "")) if kind == "parameter" else "",
            "destination": dest,
        }
        queries.append(q_obj)

        if load_enabled and kind == "query":
            entities_summary.append(
                {
                    "name": name,
                    "role": role,
                    "description": desc_txt,
                    "columns_count": len(columns),
                    "columns": columns[:80],
                    "m_code": masked_code,
                    "pq_steps": info["step_count"],
                    "step_items": info["step_items"],
                    "native_sql": info["native_sql"],
                    "source_types": src_types_clean,
                    "dataflow_refs": refs,
                    "destination": dest,
                }
            )

    return {
        "id": meta.get("id", ""),
        "name": meta.get("name") or definition.get("name") or "Dataflow",
        "description": meta.get("description") or definition.get("description") or "",
        "generation": generation,
        "workspace_id": meta.get("workspace_id", ""),
        "workspace": meta.get("workspace", ""),
        "configured_by": meta.get("configured_by", ""),
        "modified_at": meta.get("modified_at") or definition.get("modifiedTime") or "",
        "allow_native_queries": allow_nq,
        "parameters": {k: mask_secrets(v) for k, v in params.items()},
        "queries": queries,
        "entities": entities_summary,
        "source_types": sorted(all_source_types),
        "upstream_dataflows": [
            {
                "dataflow_id": u.get("targetDataflowId") or u.get("dataflowObjectId") or u.get("dataflow_id") or "",
                "workspace_id": u.get("groupId") or u.get("workspaceObjectId") or u.get("workspace_id") or "",
            }
            for u in (meta.get("upstream") or [])
            if isinstance(u, dict)
        ],
        "datasources": meta.get("datasources") or [],
    }


def definition_dataflow_refs(definition: dict) -> list[tuple[str, str]]:
    """All upstream `(workspace_id, dataflow_id)` pairs of a Gen1/Gen2 dataflow definition."""
    if not isinstance(definition, dict):
        return []
    doc, _, _, _ = _extract_mashup_payload(definition)
    pairs = referenced_dataflow_ids([doc])
    seen = {d.lower() for _, d in pairs}
    for ent in definition.get("entities") or []:
        if isinstance(ent, dict) and ent.get("$type") == "ReferenceEntity":
            r = reference_entity_ref(ent, definition)
            did = r.get("dataflow_id") or ""
            wid = r.get("workspace_id") or ""
            if _GUID_RE.match(did) and did.lower() not in seen:
                seen.add(did.lower())
                pairs.append((wid if _GUID_RE.match(wid) else "", did))
    return pairs


def strip_data_locations(definition: dict) -> dict:
    """Remove links to stored dataflow output snapshots (CSV / ADLS Gen2 / Azure Blob URLs) before saving to disk."""
    if not isinstance(definition, dict):
        return {}
    out = dict(definition)
    out.pop("pbi:dataLocations", None)
    if isinstance(out.get("entities"), list):
        clean_ents = []
        for ent in out["entities"]:
            if not isinstance(ent, dict):
                clean_ents.append(ent)
                continue
            ec = dict(ent)
            if isinstance(ec.get("partitions"), list):
                clean_parts = []
                for part in ec["partitions"]:
                    if isinstance(part, dict) and "location" in part:
                        pc = dict(part)
                        pc["location"] = "(removed - data file location not stored)"
                        clean_parts.append(pc)
                    else:
                        clean_parts.append(part)
                ec["partitions"] = clean_parts
            clean_ents.append(ec)
        out["entities"] = clean_ents
    if isinstance(out.get("referenceModels"), list):
        clean_refs = []
        for ref in out["referenceModels"]:
            if isinstance(ref, dict) and "location" in ref:
                rc = dict(ref)
                rc["location"] = "(removed)"
                clean_refs.append(rc)
            else:
                clean_refs.append(ref)
        out["referenceModels"] = clean_refs
    return out
