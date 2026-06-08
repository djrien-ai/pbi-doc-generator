import zipfile
import base64
import xml.etree.ElementTree as ET
from io import BytesIO
import re
import pandas as pd

def extract_excel_power_query(xlsx_path):
    """
    Extracts Power Query M-code from an Excel file's customXml DataMashup.
    Returns a pandas DataFrame with ['TableName', 'Expression'] or None.
    """
    pq_data = []
    
    try:
        with zipfile.ZipFile(xlsx_path, 'r') as z:
            custom_xml_files = [f for f in z.namelist() if f.startswith('customXml/item') and f.endswith('.xml')]
            
            for item_file in custom_xml_files:
                try:
                    xml_content = z.read(item_file)
                    root = ET.fromstring(xml_content)
                    if root.tag.endswith('DataMashup'):
                        base64_data = root.text
                        if not base64_data:
                            continue
                            
                        decoded = base64.b64decode(base64_data)
                        
                        # Power Query zip starts at byte 8 (first 4 bytes are length, next 4 are unknown/version)
                        zip_start = decoded.find(b'PK\x03\x04')
                        if zip_start == -1:
                            continue
                            
                        # The DataMashup payload may contain multiple ZIP archives (e.g., Mashup and Permissions).
                        # We find the End of Central Directory (EOCD) of the *first* ZIP.
                        zip_payload = decoded[zip_start:]
                        eocd_idx = zip_payload.find(b'PK\x05\x06')
                        if eocd_idx != -1:
                            # EOCD record is at least 22 bytes long
                            zip_payload = zip_payload[:eocd_idx + 22]
                            
                        try:
                            with zipfile.ZipFile(BytesIO(zip_payload)) as pq_z:
                                if 'Formulas/Section1.m' in pq_z.namelist():
                                    m_code = pq_z.read('Formulas/Section1.m').decode('utf-8')
                                    # Simple heuristic split for shared queries
                                    parts = m_code.split('shared ')[1:]
                                    for p in parts:
                                        if ' = ' in p:
                                            tbl_name, expr = p.split(' = ', 1)
                                            tbl_name = tbl_name.strip()
                                            # Handle #"Table Name"
                                            if tbl_name.startswith('#"') and tbl_name.endswith('"'):
                                                tbl_name = tbl_name[2:-1]
                                            # Remove trailing semicolon
                                            expr = expr.strip()
                                            if expr.endswith(';'):
                                                expr = expr[:-1]
                                            pq_data.append({'TableName': tbl_name, 'Expression': expr})
                        except zipfile.BadZipFile:
                            pass
                except Exception:
                    pass
    except Exception:
        pass
        
    if not pq_data:
        return None
        
    return pd.DataFrame(pq_data)
