import pandas as pd
from tmdl_parser import TmdlModel

class PbipAdapter:
    """Wraps TmdlModel to expose the same interface as PBIXRay."""
    
    def __init__(self, pbip_path):
        self.model = TmdlModel.from_pbip_folder(pbip_path)
        
    @property
    def tables(self):
        return [t.name for t in self.model.tables]
        
    @property
    def power_query(self):
        rows = []
        for t in self.model.tables:
            for p in t.partitions:
                rows.append({
                    'TableName': t.name,
                    'PartitionName': p.partition_name,
                    'Expression': p.source_code
                })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=['TableName', 'PartitionName', 'Expression'])
        
    @property
    def dax_measures(self):
        rows = []
        for m in self.model.all_measures():
            rows.append({
                'TableName': m.table_name,
                'Name': m.name,
                'Expression': m.expression,
                'FormatString': m.format_string
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=['TableName', 'Name', 'Expression', 'FormatString'])
        
    @property
    def dax_columns(self):
        rows = []
        for c in self.model.calculated_columns():
            # We need to find which table this column belongs to
            # The parser currently doesn't attach table_name to ColumnInfo?
            # Let's search tables
            table_name = ""
            for t in self.model.tables:
                if c in t.columns:
                    table_name = t.name
                    break
            rows.append({
                'TableName': table_name,
                'ColumnName': c.name,
                'Expression': c.dax_expression
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=['TableName', 'ColumnName', 'Expression'])
        
    @property
    def relationships(self):
        rows = []
        for r in self.model.relationships:
            rows.append({
                'FromTableName': r.from_table,
                'FromColumnName': r.from_column,
                'ToTableName': r.to_table,
                'ToColumnName': r.to_column,
                'CrossFilteringBehavior': r.cross_filter
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=['FromTableName', 'FromColumnName', 'ToTableName', 'ToColumnName', 'CrossFilteringBehavior'])
        
    @property
    def dax_tables(self):
        rows = []
        for t in self.model.tables:
            for p in t.partitions:
                if getattr(p, 'is_calculated', False) or (p.mode == 'calculated'):
                    rows.append({
                        'TableName': t.name,
                        'Expression': getattr(p, 'dax_expression', p.source_code)
                    })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=['TableName', 'Expression'])
        
    @property
    def m_parameters(self):
        rows = []
        for p in self.model.parameters:
            rows.append({
                'ParameterName': p.name,
                'Expression': getattr(p, 'default_value', ''),
                'Description': ''
            })
        for f in self.model.helper_functions:
            rows.append({
                'ParameterName': f.name,
                'Expression': f.code,
                'Description': ''
            })
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=['ParameterName', 'Expression', 'Description'])
        
    @property
    def calculation_groups(self):
        return self.model.calculation_groups()
