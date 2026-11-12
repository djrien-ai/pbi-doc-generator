import zipfile
import base64
import xml.etree.ElementTree as ET
from io import BytesIO
import re
import pandas as pd


def _parse_section1_m_from_mashup_bytes(mashup_bytes: bytes) -> list[dict]:
    """Extract ['TableName', 'Expression'] entries from an MS-QDEFF DataMashup binary stream."""
    pq_data: list[dict] = []
    if not mashup_bytes:
        return pq_data

    zip_start = mashup_bytes.find(b"PK\x03\x04")
    if zip_start == -1:
        return pq_data

    # DataMashup stream contains a inner ZIP package followed by permissions metadata; slice at first EOCD
    zip_payload = mashup_bytes[zip_start:]
    eocd_idx = zip_payload.find(b"PK\x05\x06")
    if eocd_idx != -1:
        zip_payload = zip_payload[: eocd_idx + 22]

    try:
        with zipfile.ZipFile(BytesIO(zip_payload)) as pq_z:
            if "Formulas/Section1.m" not in pq_z.namelist():
                return pq_data
            m_code = pq_z.read("Formulas/Section1.m").decode("utf-8-sig", errors="replace")
    except zipfile.BadZipFile:
        return pq_data

    # Split at top-level `shared <Name> = ...;` declarations anchored at start of line
    chunks = re.split(r"(?m)^(?:\[[^\]]*\]\s*)*shared\s+", m_code)
    for chunk in chunks[1:]:
        m = re.match(r'^(#"(?:[^"]|"")*"|[A-Za-z0-9_]+)\s*=\s*(.*)$', chunk.strip(), flags=re.DOTALL)
        if not m:
            continue
        raw_name, expr = m.group(1).strip(), m.group(2).strip()
        if raw_name.startswith('#"') and raw_name.endswith('"'):
            tbl_name = raw_name[2:-1].replace('""', '"')
        else:
            tbl_name = raw_name
        if expr.endswith(";"):
            expr = expr[:-1].rstrip()
        if tbl_name and expr:
            pq_data.append({"TableName": tbl_name, "Expression": expr})
    return pq_data


def extract_pbix_datamashup_power_query(pbix_path: str):
    """
    Fallback extractor for legacy Compatibility Level (<1550) .pbix files where Power Query M
    is stored in the top-level `DataMashup` ZIP entry instead of TOM partition Type=4.
    Returns a pandas DataFrame with ['TableName', 'Expression'] or None.
    """
    try:
        with zipfile.ZipFile(pbix_path, "r") as z:
            if "DataMashup" not in z.namelist():
                return None
            raw = z.read("DataMashup")
        pq_data = _parse_section1_m_from_mashup_bytes(raw)
        return pd.DataFrame(pq_data) if pq_data else None
    except Exception:
        return None


def extract_excel_power_query(xlsx_path):
    """
    Extracts Power Query M-code from an Excel file's customXml DataMashup.
    Returns a pandas DataFrame with ['TableName', 'Expression'] or None.
    """
    pq_data = []

    try:
        with zipfile.ZipFile(xlsx_path, "r") as z:
            custom_xml_files = [f for f in z.namelist() if f.startswith("customXml/item") and f.endswith(".xml")]

            for item_file in custom_xml_files:
                try:
                    xml_content = z.read(item_file)
                    root = ET.fromstring(xml_content)
                    if root.tag.endswith("DataMashup") and root.text:
                        decoded = base64.b64decode(root.text)
                        pq_data.extend(_parse_section1_m_from_mashup_bytes(decoded))
                except Exception:
                    pass
    except Exception:
        pass

    if not pq_data:
        return None

    return pd.DataFrame(pq_data)
