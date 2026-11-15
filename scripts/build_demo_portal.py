"""
Builds a rich, realistic, 100% fictional multi-workspace demo catalog in `demo_catalog/`
so users (and visual QA) can immediately explore the generated v1.1 HTML Portal:
- Modern Interactive Star-Schema Explorer with Focused Star switching (2 Fact stars + All Tables)
- SQLBI-style DAX formatting across all expressions + Collapsible Display Folders + Usage Filter Pills
- Slide-Over Report X-Ray Inspector (16:9 SVG wireframes, visual field bindings, report-level DAX, broken refs)
- Upstream Power BI Dataflow Gen1 M-pipeline bridge + Direct Lake OneLake entity binding
- Overflow-safe, logically proportioned Workspace & Dataset Principals governance table
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pbi_catalog.portal import generate_portal
from pbi_catalog.store import CatalogStore


def build_demo(out_dir: Path) -> Path:
    store = CatalogStore(out_dir)

    core_principals = [
        {"displayName": "Clara Vance (clara.vance@northwind-global.example)", "principalType": "User", "datasetUserAccessRight": "ReadWriteReshareExplore"},
        {"displayName": "BI Platform Engineering", "principalType": "Group", "datasetUserAccessRight": "ReadWriteExplore"},
        {"displayName": "SVC-Fabric-Deployment-Pipeline-Prod", "principalType": "App", "datasetUserAccessRight": "ReadWriteReshareExplore"},
        {"displayName": "Global Supply Chain Analysts", "principalType": "Group", "datasetUserAccessRight": "ReadExplore"},
        {"displayName": "EMEA Regional Plant Directors", "principalType": "Group", "datasetUserAccessRight": "Read"},
        {"displayName": "Americas Logistics Operations", "principalType": "Group", "datasetUserAccessRight": "Read"},
        {"displayName": "APAC Distribution Hub Leads", "principalType": "Group", "datasetUserAccessRight": "Read"},
        {"displayName": "Marcus Lindqvist (marcus.lindqvist@northwind-global.example)", "principalType": "User", "datasetUserAccessRight": "ReadExplore"},
        {"displayName": "Hannah Vermeulen (hannah.vermeulen@northwind-global.example)", "principalType": "User", "datasetUserAccessRight": "ReadExplore"},
        {"displayName": "Sander Peeters (sander.peeters@northwind-global.example)", "principalType": "User", "datasetUserAccessRight": "Read"},
        {"displayName": "Nadia Benali (nadia.benali@northwind-global.example)", "principalType": "User", "datasetUserAccessRight": "Read"},
        {"displayName": "Jonas Bergstrom (jonas.bergstrom@northwind-global.example)", "principalType": "User", "datasetUserAccessRight": "Read"},
        {"displayName": "Liam O'Connor (liam.oconnor@northwind-global.example)", "principalType": "User", "datasetUserAccessRight": "Read"},
        {"displayName": "Sofia Rossi (sofia.rossi@northwind-global.example)", "principalType": "User", "datasetUserAccessRight": "Read"},
        {"displayName": "Procurement Category Managers", "principalType": "Group", "datasetUserAccessRight": "Read"},
        {"displayName": "Executive SteerCo Viewers", "principalType": "Group", "datasetUserAccessRight": "Read"},
    ]

    state = {
        "schema_version": "1.1",
        "updated_at": "2026-11-14T20:30:00Z",
        "workspaces": {
            "ws-core": {
                "id": "ws-core",
                "name": "Enterprise Core Semantic Models",
                "type": "Workspace",
                "capacity_sku": "Fabric F64",
                "is_dedicated": True,
                "is_read_only": False,
                "users": [
                    {"displayName": "Clara Vance", "principalType": "User", "groupUserAccessRight": "Admin"},
                    {"displayName": "BI Platform Engineering", "principalType": "Group", "groupUserAccessRight": "Contributor"},
                ],
                "last_scanned": "2026-11-14T20:30:00Z",
            },
            "ws-sc": {
                "id": "ws-sc",
                "name": "Supply Chain & Procurement Analytics",
                "type": "Workspace",
                "capacity_sku": "Fabric F64",
                "is_dedicated": True,
                "is_read_only": False,
                "users": [
                    {"displayName": "Marcus Lindqvist", "principalType": "User", "groupUserAccessRight": "Member"},
                    {"displayName": "Global Supply Chain Analysts", "principalType": "Group", "groupUserAccessRight": "Viewer"},
                ],
                "last_scanned": "2026-11-14T20:30:00Z",
            },
            "ws-fin": {
                "id": "ws-fin",
                "name": "Corporate Finance & FP&A",
                "type": "Workspace",
                "capacity_sku": "Premium P1",
                "is_dedicated": True,
                "is_read_only": False,
                "users": [
                    {"displayName": "Elena Rostova", "principalType": "User", "groupUserAccessRight": "Admin"},
                ],
                "last_scanned": "2026-11-14T20:30:00Z",
            },
        },
        "models": {
            "ds-otif": {
                "id": "ds-otif",
                "name": "Global Supply Chain & OTIF Core",
                "workspace_id": "ws-core",
                "workspace": "Enterprise Core Semantic Models",
                "configured_by": "clara.vance@northwind-global.example",
                "last_refresh": {"status": "Completed", "end_time": "2026-11-14T06:12:00Z"},
                "permissions": core_principals,
                "workspace_users": [],
                "definition_status": "ok",
            },
            "ds-fin": {
                "id": "ds-fin",
                "name": "Group Working Capital & Margin",
                "workspace_id": "ws-fin",
                "workspace": "Corporate Finance & FP&A",
                "configured_by": "elena.rostova@northwind-global.example",
                "last_refresh": {"status": "Completed", "end_time": "2026-11-14T05:45:00Z"},
                "permissions": [
                    {"displayName": "Elena Rostova", "principalType": "User", "datasetUserAccessRight": "Admin"},
                    {"displayName": "FP&A Controllers", "principalType": "Group", "datasetUserAccessRight": "ReadExplore"},
                ],
                "workspace_users": [],
                "definition_status": "ok",
            },
            "ds-legacy": {
                "id": "ds-legacy",
                "name": "Regional Vendor Spend Tracker",
                "workspace_id": "ws-sc",
                "workspace": "Supply Chain & Procurement Analytics",
                "configured_by": "marcus.lindqvist@northwind-global.example",
                "last_refresh": {"status": "Failed", "end_time": "2026-11-13T23:10:00Z"},
                "permissions": [],
                "workspace_users": [],
                "definition_status": "ok",
            },
        },
        "reports": {
            "r-1": {
                "id": "r-1",
                "name": "Executive OTIF & Carrier Performance",
                "workspace_id": "ws-sc",
                "workspace": "Supply Chain & Procurement Analytics",
                "dataset_id": "ds-otif",
                "report_type": "PowerBIReport",
                "layout_status": "ok",
            },
            "r-2": {
                "id": "r-2",
                "name": "Warehouse Dispatch & Inventory Monitor",
                "workspace_id": "ws-sc",
                "workspace": "Supply Chain & Procurement Analytics",
                "dataset_id": "ds-otif",
                "report_type": "PowerBIReport",
                "layout_status": "ok",
            },
            "r-3": {
                "id": "r-3",
                "name": "CFO Monthly Margin & Cashflow Pack",
                "workspace_id": "ws-fin",
                "workspace": "Corporate Finance & FP&A",
                "dataset_id": "ds-fin",
                "report_type": "PowerBIReport",
                "layout_status": "ok",
            },
            "r-4": {
                "id": "r-4",
                "name": "Vendor Rebate & Spend Variance",
                "workspace_id": "ws-sc",
                "workspace": "Supply Chain & Procurement Analytics",
                "dataset_id": "ds-legacy",
                "report_type": "PowerBIReport",
                "layout_status": "ok",
            },
        },
        "dataflows": {
            "df-raw-erp": {
                "id": "df-raw-erp",
                "name": "Raw S/4HANA Master Staging",
                "description": "Layer-2 staging Dataflow extracting raw MARA & LFA1 master tables via parameterized Native SQL.",
                "generation": 1,
                "workspace_id": "ws-core",
                "workspace": "Enterprise Core Semantic Models",
                "definition_status": "ok",
            },
            "df-1": {
                "id": "df-1",
                "name": "Master Vendor & Material Harmonization",
                "description": "Centralized Power Query Dataflow harmonizing staged S/4HANA master records across regions.",
                "generation": 1,
                "workspace_id": "ws-core",
                "workspace": "Enterprise Core Semantic Models",
                "definition_status": "ok",
            },
            "df-gen2-inv": {
                "id": "df-gen2-inv",
                "name": "Warehouse Daily Inventory Ingestion (Gen2)",
                "description": "Fabric Dataflow Gen2 ingesting WMS stock snapshots into OneLake Lakehouse lh_supply_chain_gold.",
                "generation": 2,
                "workspace_id": "ws-core",
                "workspace": "Enterprise Core Semantic Models",
                "definition_status": "ok",
            },
        },
        "fabric_items": {
            "lh-sc-gold": {
                "id": "lh-sc-gold",
                "name": "lh_supply_chain_gold",
                "type": "Lakehouse",
                "description": "Curated OneLake Delta tables for daily warehouse inventory snapshots.",
                "workspace_id": "ws-core",
                "workspace": "Enterprise Core Semantic Models",
            }
        },
        "dataset_dataflow_links": {
            "ds-otif": [
                {"dataflow_id": "df-1", "workspace_id": "ws-core"},
            ],
        },
        "errors": [],
    }
    store.save(state)

    # Write Dataflow Gen1 (L2 staging -> L1 harmonized) & Fabric Dataflow Gen2 definitions
    store.write_dataflow_definition(
        "df-raw-erp",
        {
            "name": "Raw S/4HANA Master Staging",
            "description": "Layer-2 staging Dataflow extracting raw MARA & LFA1 master tables via parameterized Native SQL.",
            "entities": [
                {
                    "name": "RawMaterials",
                    "description": "Raw SAP MARA material extraction.",
                    "attributes": [
                        {"name": "MaterialKey", "dataType": "string"},
                        {"name": "MaterialDescription", "dataType": "string"},
                        {"name": "ProductFamily", "dataType": "string"},
                        {"name": "DeletionFlag", "dataType": "string"},
                    ],
                }
            ],
            "pbi:mashup": {
                "document": (
                    "section Section1;\n"
                    "shared SapClient = \"100\" meta [IsParameterQuery=true, Type=\"Text\"];\n"
                    "shared RawMaterials = let\n"
                    "    Source = Sql.Database(\"hana-sql-bridge.northwind.internal\", \"S4P\"),\n"
                    "    Extracted = Value.NativeQuery(Source, \"SELECT MANDT, MATNR AS MaterialKey, MAKTX AS MaterialDescription, SPART AS ProductFamily, LVORM AS DeletionFlag FROM sapsr3.MARA WHERE MANDT = '\" & SapClient & \"'\"),\n"
                    "    #\"Removed Client Col\" = Table.RemoveColumns(Extracted, {\"MANDT\"})\n"
                    "in\n"
                    "    #\"Removed Client Col\";\n"
                )
            },
        },
    )

    store.write_dataflow_definition(
        "df-1",
        {
            "name": "Master Vendor & Material Harmonization",
            "description": "Centralized Power Query Dataflow harmonizing staged S/4HANA master records across regions.",
            "entities": [
                {
                    "name": "HarmonizedMaterials",
                    "description": "Cleaned global material master with ABC velocity classification.",
                    "attributes": [
                        {"name": "MaterialKey", "dataType": "string"},
                        {"name": "MaterialDescription", "dataType": "string"},
                        {"name": "ProductFamily", "dataType": "string"},
                    ],
                },
                {
                    "name": "HarmonizedVendors",
                    "description": "Deduplicated global supplier master with DUNS hierarchy.",
                    "attributes": [
                        {"name": "VendorKey", "dataType": "string"},
                        {"name": "VendorName", "dataType": "string"},
                    ],
                },
            ],
            "pbi:mashup": {
                "document": (
                    "section Section1;\n"
                    "shared HarmonizedMaterials = let\n"
                    "    Source = PowerPlatform.Dataflows(null),\n"
                    "    Workspaces = Source{[Id=\"Workspaces\"]}[Data],\n"
                    "    Ws = Workspaces{[workspaceId=\"ws-core\"]}[Data],\n"
                    "    StagingDf = Ws{[dataflowId=\"df-raw-erp\"]}[Data],\n"
                    "    RawMaterials = StagingDf{[entity=\"RawMaterials\"]}[Data],\n"
                    "    #\"Filtered Active\" = Table.SelectRows(RawMaterials, each [DeletionFlag] = null),\n"
                    "    #\"Trimmed Codes\" = Table.TransformColumns(#\"Filtered Active\", {{\"MaterialKey\", Text.Trim, type text}})\n"
                    "in\n"
                    "    #\"Trimmed Codes\";\n"
                    "shared HarmonizedVendors = let\n"
                    "    Source = SapHana.Database(\"hana-ent-prod.northwind.internal:30015\"),\n"
                    "    VendorView = Source{[Name=\"CV_MD_VENDOR_GLOBAL\"]}[Data],\n"
                    "    #\"Uppercased Names\" = Table.TransformColumns(VendorView, {{\"VendorName\", Text.Upper, type text}})\n"
                    "in\n"
                    "    #\"Uppercased Names\";\n"
                )
            },
        },
    )

    store.write_dataflow_definition(
        "df-gen2-inv",
        {
            "format": "FabricDataflowGen2",
            "mashup_pq": (
                "section Section1;\n"
                "shared fact_inventory_daily = let\n"
                "    Source = Snowflake.Databases(\"northwind.eu-central-1.snowflakecomputing.com\", \"WH_ENTERPRISE\"),\n"
                "    Db = Source{[Name=\"EDW_CORE\"]}[Data],\n"
                "    RawStock = Db{[Name=\"V_WMS_DAILY_STOCK\"]}[Data],\n"
                "    #\"Filtered Positive Stock\" = Table.SelectRows(RawStock, each [StockQty] >= 0)\n"
                "in\n"
                "    #\"Filtered Positive Stock\";\n"
            ),
            "query_metadata": {
                "formatVersion": "202502",
                "queriesMetadata": {
                    "fact_inventory_daily": {
                        "queryId": "q-inv-1",
                        "queryName": "fact_inventory_daily",
                        "loadEnabled": True,
                        "destinationSettings": {
                            "kind": "Lakehouse",
                            "workspaceId": "ws-core",
                            "itemId": "lh-sc-gold",
                            "itemName": "lh_supply_chain_gold",
                            "schemaName": "gold",
                            "tableName": "fact_inventory_daily",
                            "updateMethod": "Replace",
                        },
                    }
                },
            },
        },
    )

    # Model 1: Global Supply Chain & OTIF Core (2 Fact Tables + Dataflow Gen1 + Direct Lake + Multi-Folder DAX)
    store.write_tmdl_bundle(
        "Global Supply Chain & OTIF Core",
        "ds-otif",
        {
            "definition/model.tmdl": "model Model\n\tculture: en-US\n",
            "definition/expressions.tmdl": (
                "/// Production SAP HANA Calculation View endpoint.\n"
                "expression pHanaServer = \"hana-ent-prod.northwind.internal:30015\" meta [IsParameterQuery=true, Type=\"Text\"]\n\n"
                "/// Shared OneLake SQL Analytics Endpoint for Direct Lake tables.\n"
                "expression DatabaseQuery =\n"
                "\tlet\n"
                "\t\tdatabase = Sql.Database(\"onelake-sc-prod.datawarehouse.fabric.microsoft.com\", \"lh_supply_chain_gold\")\n"
                "\tin\n"
                "\t\tdatabase\n"
            ),
            "definition/relationships.tmdl": (
                "relationship r_cal\n\tfromColumn: 'Fact Deliveries'.DeliveryDate\n\ttoColumn: 'Dim Calendar'.Date\n"
                "relationship r_cust\n\tfromColumn: 'Fact Deliveries'.CustomerKey\n\ttoColumn: 'Dim Customer'.CustomerKey\n"
                "relationship r_plant\n\tfromColumn: 'Fact Deliveries'.PlantCode\n\ttoColumn: 'Dim Plant'.PlantCode\n"
                "relationship r_mat\n\tfromColumn: 'Fact Deliveries'.MaterialKey\n\ttoColumn: 'Dim Material'.MaterialKey\n"
                "relationship r_inv_cal\n\tfromColumn: 'Fact Inventory Snapshots'.SnapshotDate\n\ttoColumn: 'Dim Calendar'.Date\n"
                "relationship r_inv_plant\n\tfromColumn: 'Fact Inventory Snapshots'.PlantCode\n\ttoColumn: 'Dim Plant'.PlantCode\n"
                "relationship r_inv_mat\n\tfromColumn: 'Fact Inventory Snapshots'.MaterialKey\n\ttoColumn: 'Dim Material'.MaterialKey\n"
            ),
            "definition/roles/Regional_Director.tmdl": (
                "role 'Regional Supply Director'\n"
                "\tmodelPermission: read\n"
                "\ttablePermission 'Dim Plant' = 'Dim Plant'[RegionEmail] == USERPRINCIPALNAME()\n"
            ),
            "definition/tables/DimCalendar.tmdl": (
                "/// Shared corporate fiscal & ISO calendar dimension (2022-2028).\n"
                "table 'Dim Calendar'\n"
                "\tcolumn Date\n\t\tdataType: dateTime\n\t\tformatString: yyyy-mm-dd\n\t\tsourceColumn: Date\n\t\tdescription: Primary calendar date key\n"
                "\tcolumn FiscalYear\n\t\tdataType: string\n\t\tsourceColumn: FiscalYear\n"
                "\tcolumn YearMonth\n\t\tdataType: string\n\t\tsourceColumn: YearMonth\n"
                "\thierarchy 'Fiscal Calendar'\n\t\tlevel FiscalYear\n\t\tlevel YearMonth\n\t\tlevel Date\n"
                "\tpartition 'Dim Calendar' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n"
                "\t\t\t\tSource = Snowflake.Databases(\"northwind.eu-central-1.snowflakecomputing.com\", \"WH_ENTERPRISE\"),\n"
                "\t\t\t\tDatabase = Source{[Name=\"EDW_CORE\"]}[Data],\n"
                "\t\t\t\t#\"Selected View\" = Database{[Name=\"DIM_CALENDAR_ISO\"]}[Data],\n"
                "\t\t\t\t#\"Filtered Active Years\" = Table.SelectRows(#\"Selected View\", each [FiscalYear] >= \"FY22\")\n"
                "\t\t\tin\n"
                "\t\t\t\t#\"Filtered Active Years\"\n"
            ),
            "definition/tables/DimCustomer.tmdl": (
                "/// Harmonized B2B customer accounts and service-level tiers.\n"
                "table 'Dim Customer'\n"
                "\tcolumn CustomerKey\n\t\tdataType: int64\n\t\tsourceColumn: CustomerKey\n"
                "\tcolumn CustomerName\n\t\tdataType: string\n\t\tsourceColumn: CustomerName\n"
                "\tcolumn ServiceTier\n\t\tdataType: string\n\t\tsourceColumn: ServiceTier\n"
                "\tcolumn Country\n\t\tdataType: string\n\t\tsourceColumn: Country\n"
                "\tpartition 'Dim Customer' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n"
                "\t\t\t\tSource = Snowflake.Databases(\"northwind.eu-central-1.snowflakecomputing.com\", \"WH_ENTERPRISE\"),\n"
                "\t\t\t\tView = Source{[Name=\"DIM_CUSTOMER_MDM\"]}[Data],\n"
                "\t\t\t\t#\"Renamed Columns\" = Table.RenameColumns(View, {{\"CUST_ID\", \"CustomerKey\"}})\n"
                "\t\t\tin\n"
                "\t\t\t\t#\"Renamed Columns\"\n"
            ),
            "definition/tables/DimPlant.tmdl": (
                "/// Manufacturing plants and distribution hubs with RLS ownership mapping.\n"
                "table 'Dim Plant'\n"
                "\tcolumn PlantCode\n\t\tdataType: string\n\t\tsourceColumn: PlantCode\n"
                "\tcolumn PlantName\n\t\tdataType: string\n\t\tsourceColumn: PlantName\n"
                "\tcolumn Region\n\t\tdataType: string\n\t\tsourceColumn: Region\n"
                "\tcolumn RegionEmail\n\t\tdataType: string\n\t\tisHidden\n\t\tsourceColumn: RegionEmail\n"
                "\tpartition 'Dim Plant' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n"
                "\t\t\t\tSource = SapHana.Database(pHanaServer),\n"
                "\t\t\t\tView = Source{[Name=\"CV_MD_PLANT_NETWORK\"]}[Data]\n"
                "\t\t\tin\n"
                "\t\t\t\tView\n"
            ),
            "definition/tables/DimMaterial.tmdl": (
                "/// Product hierarchy, material group, and ABC velocity classification sourced via Corporate Dataflow.\n"
                "table 'Dim Material'\n"
                "\tcolumn MaterialKey\n\t\tdataType: string\n\t\tsourceColumn: MaterialKey\n"
                "\tcolumn MaterialDescription\n\t\tdataType: string\n\t\tsourceColumn: MaterialDescription\n"
                "\tcolumn ProductFamily\n\t\tdataType: string\n\t\tsourceColumn: ProductFamily\n"
                "\tpartition 'Dim Material' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n"
                "\t\t\t\tSource = PowerPlatform.Dataflows(null),\n"
                "\t\t\t\tWorkspaces = Source{[Id=\"Workspaces\"]}[Data],\n"
                "\t\t\t\tWs = Workspaces{[workspaceId=\"ws-core\"]}[Data],\n"
                "\t\t\t\tDf = Ws{[dataflowId=\"df-1\"]}[Data],\n"
                "\t\t\t\tEntity = Df{[entity=\"HarmonizedMaterials\"]}[Data]\n"
                "\t\t\tin\n"
                "\t\t\t\tEntity\n"
            ),
            "definition/tables/FactDeliveries.tmdl": (
                "/// Outbound delivery lines from SAP S/4HANA via HANA Calculation View CV_SD_DELIVERY_OTIF.\n"
                "table 'Fact Deliveries'\n"
                "\t/// Total outbound delivery lines shipped in the selected period.\n"
                "\tmeasure 'Delivery Lines' = COUNTROWS('Fact Deliveries')\n"
                "\t\tformatString: #,##0\n\t\tdisplayFolder: 01. Base Volumes\n"
                "\t/// Total shipped quantity in base unit of measure.\n"
                "\tmeasure 'Shipped Quantity' = SUM('Fact Deliveries'[DeliveredQty])\n"
                "\t\tformatString: #,##0\n\t\tdisplayFolder: 01. Base Volumes\n"
                "\t/// Net commercial value of shipped goods in EUR.\n"
                "\tmeasure 'Shipped Net Value' = SUM('Fact Deliveries'[NetValueEUR])\n"
                "\t\tformatString: #,##0.00 \"EUR\"\n\t\tdisplayFolder: 01. Base Volumes\n"
                "\t/// Lines delivered both On-Time and In-Full against customer requested date.\n"
                "\tmeasure 'OTIF Lines' = CALCULATE([Delivery Lines], 'Fact Deliveries'[IsOnTime] = 1, 'Fact Deliveries'[IsInFull] = 1)\n"
                "\t\tformatString: #,##0\n\t\tdisplayFolder: 02. Service Level KPIs\n"
                "\t/// Core customer service KPI: share of delivery lines arriving on time and in full.\n"
                "\tmeasure 'OTIF %' = DIVIDE([OTIF Lines], [Delivery Lines], 0)\n"
                "\t\tformatString: 0.0%\n\t\tdisplayFolder: 02. Service Level KPIs\n"
                "\t/// Late delivery lines missing promised customer window.\n"
                "\tmeasure 'Late Lines' = CALCULATE([Delivery Lines], 'Fact Deliveries'[IsOnTime] = 0)\n"
                "\t\tformatString: #,##0\n\t\tdisplayFolder: 02. Service Level KPIs\n"
                "\t/// Year-to-date OTIF service rate across fiscal calendar.\n"
                "\tmeasure 'OTIF % YTD' = CALCULATE([OTIF %], DATESYTD('Dim Calendar'[Date]))\n"
                "\t\tformatString: 0.0%\n\t\tdisplayFolder: 03. Time Intelligence\n"
                "\t/// Year-over-year OTIF variance in percentage points.\n"
                "\tmeasure 'OTIF % vs PY' = VAR CurrentOTIF = [OTIF %] VAR PriorOTIF = CALCULATE([OTIF %], SAMEPERIODLASTYEAR('Dim Calendar'[Date])) RETURN IF(NOT ISBLANK(PriorOTIF), CurrentOTIF - PriorOTIF)\n"
                "\t\tformatString: +0.0%;-0.0%;0.0%\n\t\tdisplayFolder: 03. Time Intelligence\n"
                "\t/// Historical experimental scoring measure no longer bound to active reports.\n"
                "\tmeasure 'Legacy Buffer Safety Score' = DIVIDE(SUM('Fact Deliveries'[DeliveredQty]), COUNTROWS('Fact Deliveries'), 0)\n"
                "\t\tformatString: 0.00\n\t\tdisplayFolder: 04. Experimental & Legacy\n"
                "\tcolumn DeliveryDate\n\t\tdataType: dateTime\n\t\tsourceColumn: DeliveryDate\n"
                "\tcolumn CustomerKey\n\t\tdataType: int64\n\t\tsourceColumn: CustomerKey\n"
                "\tcolumn PlantCode\n\t\tdataType: string\n\t\tsourceColumn: PlantCode\n"
                "\tcolumn MaterialKey\n\t\tdataType: string\n\t\tsourceColumn: MaterialKey\n"
                "\tcolumn DeliveredQty\n\t\tdataType: double\n\t\tsourceColumn: DeliveredQty\n"
                "\tcolumn NetValueEUR\n\t\tdataType: decimal\n\t\tsourceColumn: NetValueEUR\n"
                "\tcolumn IsOnTime\n\t\tdataType: int64\n\t\tsourceColumn: IsOnTime\n"
                "\tcolumn IsInFull\n\t\tdataType: int64\n\t\tsourceColumn: IsInFull\n"
                "\tpartition 'Fact Deliveries' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n"
                "\t\t\t\tSource = SapHana.Database(pHanaServer),\n"
                "\t\t\t\tNavigation = Source{[Name=\"CV_SD_DELIVERY_OTIF\"]}[Data],\n"
                "\t\t\t\t#\"Filtered Completed\" = Table.SelectRows(Navigation, each [DeliveryStatus] = \"C\"),\n"
                "\t\t\t\t#\"Typed Columns\" = Table.TransformColumnTypes(#\"Filtered Completed\", {{\"NetValueEUR\", Currency.Type}})\n"
                "\t\t\tin\n"
                "\t\t\t\t#\"Typed Columns\"\n"
            ),
            "definition/tables/FactInventorySnapshots.tmdl": (
                "/// Daily warehouse stock-on-hand Delta table in OneLake (Direct Lake mode).\n"
                "table 'Fact Inventory Snapshots'\n"
                "\t/// Latest stock on hand across selected warehouse hubs.\n"
                "\tmeasure 'Stock On Hand Value' = CALCULATE(SUM('Fact Inventory Snapshots'[StockValueEUR]), LASTDATE('Dim Calendar'[Date]))\n"
                "\t\tformatString: #,##0 \"EUR\"\n\t\tdisplayFolder: 01. Inventory KPIs\n"
                "\tcolumn SnapshotDate\n\t\tdataType: dateTime\n\t\tsourceColumn: SnapshotDate\n"
                "\tcolumn PlantCode\n\t\tdataType: string\n\t\tsourceColumn: PlantCode\n"
                "\tcolumn MaterialKey\n\t\tdataType: string\n\t\tsourceColumn: MaterialKey\n"
                "\tcolumn StockQty\n\t\tdataType: double\n\t\tsourceColumn: StockQty\n"
                "\tcolumn StockValueEUR\n\t\tdataType: decimal\n\t\tsourceColumn: StockValueEUR\n"
                "\tpartition 'Fact Inventory Snapshots' = entity\n"
                "\t\tmode: directLake\n"
                "\t\tsource\n"
                "\t\t\tentityName: fact_inventory_daily\n"
                "\t\t\tschemaName: gold\n"
                "\t\t\texpressionSource: DatabaseQuery\n"
            ),
        },
    )

    # Model 2: Group Working Capital & Margin
    store.write_tmdl_bundle(
        "Group Working Capital & Margin",
        "ds-fin",
        {
            "definition/model.tmdl": "model Model\n\tculture: en-US\n",
            "definition/relationships.tmdl": "relationship r_f1\n\tfromColumn: 'Fact GL Margin'.PostingDate\n\ttoColumn: 'Dim Calendar'.Date\n",
            "definition/tables/DimCalendar.tmdl": (
                "/// Shared corporate fiscal calendar.\n"
                "table 'Dim Calendar'\n"
                "\tcolumn Date\n\t\tdataType: dateTime\n\t\tsourceColumn: Date\n"
                "\tcolumn YearMonth\n\t\tdataType: string\n\t\tsourceColumn: YearMonth\n"
                "\tpartition 'Dim Calendar' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n\t\t\t\tSource = Snowflake.Databases(\"northwind.eu-central-1.snowflakecomputing.com\", \"WH_ENTERPRISE\"),\n"
                "\t\t\t\tView = Source{[Name=\"DIM_CALENDAR_ISO\"]}[Data]\n\t\t\tin\n\t\t\t\tView\n"
            ),
            "definition/tables/FactGLMargin.tmdl": (
                "/// Consolidated General Ledger revenue and COGS postings.\n"
                "table 'Fact GL Margin'\n"
                "\tmeasure 'Gross Revenue' = SUM('Fact GL Margin'[RevenueEUR])\n\t\tformatString: #,##0 \"EUR\"\n\t\tdisplayFolder: P&L Core\n"
                "\tmeasure 'COGS' = SUM('Fact GL Margin'[CogsEUR])\n\t\tformatString: #,##0 \"EUR\"\n\t\tdisplayFolder: P&L Core\n"
                "\tmeasure 'Gross Margin %' = DIVIDE([Gross Revenue] - [COGS], [Gross Revenue], 0)\n\t\tformatString: 0.0%\n\t\tdisplayFolder: Profitability\n"
                "\tcolumn PostingDate\n\t\tdataType: dateTime\n\t\tsourceColumn: PostingDate\n"
                "\tcolumn RevenueEUR\n\t\tdataType: decimal\n\t\tsourceColumn: RevenueEUR\n"
                "\tcolumn CogsEUR\n\t\tdataType: decimal\n\t\tsourceColumn: CogsEUR\n"
                "\tpartition 'Fact GL Margin' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n\t\t\t\tSource = AzureSql.Database(\"sql-fin-prod.database.windows.net\", \"DB_FINANCE\"),\n"
                "\t\t\t\tView = Source{[Schema=\"mart\",Item=\"v_FactGLMargin\"]}[Data]\n\t\t\tin\n\t\t\t\tView\n"
            ),
        },
    )

    # Model 3: Regional Vendor Spend Tracker (intentionally demonstrates governance & broken report ref findings!)
    store.write_tmdl_bundle(
        "Regional Vendor Spend Tracker",
        "ds-legacy",
        {
            "definition/model.tmdl": "model Model\n\tculture: en-US\n",
            "definition/relationships.tmdl": (
                "relationship r_bi\n\tfromColumn: 'Fact Spend'.VendorID\n\ttoColumn: 'Dim Vendor'.VendorID\n\tcrossFilteringBehavior: bothDirections\n"
            ),
            "definition/tables/DimVendor.tmdl": (
                "table 'Dim Vendor'\n"
                "\tcolumn VendorID\n\t\tdataType: string\n\t\tsourceColumn: VendorID\n"
                "\tcolumn VendorName\n\t\tdataType: string\n\t\tsourceColumn: VendorName\n"
                "\tpartition 'Dim Vendor' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n\t\t\t\tSource = Excel.Workbook(File.Contents(\"C:\\Users\\Public\\VendorMapping_2025.xlsx\"))\n\t\t\tin\n\t\t\t\tSource\n"
            ),
            "definition/tables/FactSpend.tmdl": (
                "table 'Fact Spend'\n"
                "\tmeasure 'Total Spend' = SUM('Fact Spend'[SpendEUR])\n\t\tformatString: #,##0\n"
                "\tcolumn VendorID\n\t\tdataType: string\n\t\tsourceColumn: VendorID\n"
                "\tcolumn SpendEUR\n\t\tdataType: decimal\n\t\tsourceColumn: SpendEUR\n"
                "\tpartition 'Fact Spend' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n\t\t\t\tSource = Sql.Database(\"sql-procurement-dev.northwind.internal\", \"ProcurementDB\", [Query=\"SELECT VendorID, SpendEUR FROM dbo.SpendLines\"])\n\t\t\tin\n\t\t\t\tSource\n"
            ),
        },
    )

    # Write Report Visual Layouts for the Slide-Over Report X-Ray Inspector
    store.write_report_layout(
        "r-1",
        {
            "format": "PBIR",
            "report_filters": ["Dim Calendar[FiscalYear]"],
            "report_measures": [
                {
                    "table": "Fact Deliveries",
                    "name": "Carrier Penalty Exposure EUR",
                    "expr": "CALCULATE([Late Lines] * 125, 'Dim Customer'[ServiceTier] = \"Strategic\")",
                    "format": "#,##0 \"EUR\"",
                    "description": "Estimated contractual SLA penalty defined locally inside the Executive OTIF thin report.",
                }
            ],
            "pages": [
                {
                    "id": "p-exec",
                    "name": "1. Executive OTIF Overview",
                    "hidden": False,
                    "width": 1280,
                    "height": 720,
                    "filters": ["Dim Calendar[FiscalYear]"],
                    "visuals": [
                        {
                            "id": "grp-kpis",
                            "type": "group",
                            "type_label": "Visual Group",
                            "title": "Executive KPI Header Group",
                            "decorative": False,
                            "x": 326,
                            "y": 12,
                            "width": 938,
                            "height": 108,
                            "z": 5,
                            "fields": [],
                            "filters": [],
                        },
                        {
                            "id": "v1",
                            "type": "slicer",
                            "type_label": "Slicer",
                            "title": "Fiscal Year & Region",
                            "decorative": False,
                            "x": 24,
                            "y": 20,
                            "width": 290,
                            "height": 92,
                            "z": 10,
                            "selection": ["FY26", "EMEA"],
                            "fields": [
                                {"role": "Values", "kind": "column", "entity": "Dim Calendar", "property": "FiscalYear", "ref": "Dim Calendar[FiscalYear]", "display": "FiscalYear"},
                                {"role": "Values", "kind": "column", "entity": "Dim Plant", "property": "Region", "ref": "Dim Plant[Region]", "display": "Region"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "v2",
                            "type": "card",
                            "type_label": "KPI Card",
                            "title": "OTIF Service Rate",
                            "parent": "grp-kpis",
                            "decorative": False,
                            "x": 334,
                            "y": 20,
                            "width": 290,
                            "height": 92,
                            "z": 20,
                            "fields": [
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "OTIF %", "ref": "Fact Deliveries[OTIF %]", "display": "OTIF %"},
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "OTIF % vs PY", "ref": "Fact Deliveries[OTIF % vs PY]", "display": "OTIF % vs PY"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "v3",
                            "type": "card",
                            "type_label": "KPI Card",
                            "title": "YTD OTIF & Shipped Value",
                            "parent": "grp-kpis",
                            "decorative": False,
                            "x": 644,
                            "y": 20,
                            "width": 290,
                            "height": 92,
                            "z": 30,
                            "fields": [
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "OTIF % YTD", "ref": "Fact Deliveries[OTIF % YTD]", "display": "OTIF % YTD"},
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "Shipped Net Value", "ref": "Fact Deliveries[Shipped Net Value]", "display": "Shipped Net Value"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "v4",
                            "type": "card",
                            "type_label": "KPI Card",
                            "title": "SLA Penalty Exposure",
                            "parent": "grp-kpis",
                            "decorative": False,
                            "x": 954,
                            "y": 20,
                            "width": 302,
                            "height": 92,
                            "z": 40,
                            "fields": [
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "Carrier Penalty Exposure EUR", "ref": "Fact Deliveries[Carrier Penalty Exposure EUR]", "display": "Carrier Penalty Exposure EUR"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "v4-hidden",
                            "type": "card",
                            "type_label": "KPI Card",
                            "title": "Hidden SLA QA Check",
                            "hidden": True,
                            "decorative": False,
                            "x": 954,
                            "y": 116,
                            "width": 160,
                            "height": 48,
                            "z": 45,
                            "fields": [
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "Late Lines", "ref": "Fact Deliveries[Late Lines]", "display": "Late Lines"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "v5",
                            "type": "lineClusteredColumnComboChart",
                            "type_label": "Line & Column Chart",
                            "title": "Monthly OTIF % Trend vs. Delivery Volume",
                            "decorative": False,
                            "x": 24,
                            "y": 132,
                            "width": 760,
                            "height": 560,
                            "fields": [
                                {"role": "Category", "kind": "column", "entity": "Dim Calendar", "property": "YearMonth", "ref": "Dim Calendar[YearMonth]", "display": "YearMonth"},
                                {"role": "ColumnValues", "kind": "measure", "entity": "Fact Deliveries", "property": "Delivery Lines", "ref": "Fact Deliveries[Delivery Lines]", "display": "Delivery Lines"},
                                {"role": "LineValues", "kind": "measure", "entity": "Fact Deliveries", "property": "OTIF %", "ref": "Fact Deliveries[OTIF %]", "display": "OTIF %"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "v6",
                            "type": "clusteredBarChart",
                            "type_label": "Clustered Bar Chart",
                            "title": "OTIF % by Manufacturing Plant",
                            "decorative": False,
                            "x": 804,
                            "y": 132,
                            "width": 452,
                            "height": 560,
                            "fields": [
                                {"role": "Category", "kind": "column", "entity": "Dim Plant", "property": "PlantName", "ref": "Dim Plant[PlantName]", "display": "PlantName"},
                                {"role": "Y", "kind": "measure", "entity": "Fact Deliveries", "property": "OTIF %", "ref": "Fact Deliveries[OTIF %]", "display": "OTIF %"},
                            ],
                            "filters": ["Dim Customer[ServiceTier]"],
                        },
                    ],
                },
                {
                    "id": "p-mat",
                    "name": "2. Customer & Product Breakdown",
                    "hidden": False,
                    "width": 1280,
                    "height": 720,
                    "filters": [],
                    "visuals": [
                        {
                            "id": "v7",
                            "type": "pivotTable",
                            "type_label": "Matrix",
                            "title": "Customer Service Tier x Product Family Matrix",
                            "decorative": False,
                            "x": 24,
                            "y": 24,
                            "width": 1232,
                            "height": 672,
                            "fields": [
                                {"role": "Rows", "kind": "column", "entity": "Dim Customer", "property": "CustomerName", "ref": "Dim Customer[CustomerName]", "display": "CustomerName"},
                                {"role": "Columns", "kind": "column", "entity": "Dim Material", "property": "ProductFamily", "ref": "Dim Material[ProductFamily]", "display": "ProductFamily"},
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "Shipped Quantity", "ref": "Fact Deliveries[Shipped Quantity]", "display": "Shipped Quantity"},
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "OTIF %", "ref": "Fact Deliveries[OTIF %]", "display": "OTIF %"},
                            ],
                            "filters": [],
                        }
                    ],
                },
            ],
        },
    )

    store.write_report_layout(
        "r-2",
        {
            "format": "PBIR",
            "report_filters": [],
            "report_measures": [],
            "pages": [
                {
                    "id": "p-inv",
                    "name": "Daily Hub Stock & Dispatch",
                    "hidden": False,
                    "width": 1280,
                    "height": 720,
                    "filters": [],
                    "visuals": [
                        {
                            "id": "w1",
                            "type": "card",
                            "type_label": "KPI Card",
                            "title": "Direct Lake Stock On Hand",
                            "decorative": False,
                            "x": 24,
                            "y": 24,
                            "width": 380,
                            "height": 120,
                            "fields": [
                                {"role": "Values", "kind": "measure", "entity": "Fact Inventory Snapshots", "property": "Stock On Hand Value", "ref": "Fact Inventory Snapshots[Stock On Hand Value]", "display": "Stock On Hand Value"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "w2",
                            "type": "tableEx",
                            "type_label": "Table",
                            "title": "Plant Material Stock & Late Lines",
                            "decorative": False,
                            "x": 24,
                            "y": 164,
                            "width": 1232,
                            "height": 530,
                            "fields": [
                                {"role": "Values", "kind": "column", "entity": "Dim Plant", "property": "PlantName", "ref": "Dim Plant[PlantName]", "display": "PlantName"},
                                {"role": "Values", "kind": "column", "entity": "Dim Material", "property": "MaterialDescription", "ref": "Dim Material[MaterialDescription]", "display": "MaterialDescription"},
                                {"role": "Values", "kind": "measure", "entity": "Fact Inventory Snapshots", "property": "Stock On Hand Value", "ref": "Fact Inventory Snapshots[Stock On Hand Value]", "display": "Stock On Hand Value"},
                                {"role": "Values", "kind": "measure", "entity": "Fact Deliveries", "property": "Late Lines", "ref": "Fact Deliveries[Late Lines]", "display": "Late Lines"},
                            ],
                            "filters": [],
                        },
                    ],
                }
            ],
        },
    )

    store.write_report_layout(
        "r-3",
        {
            "format": "PBIR",
            "report_filters": [],
            "report_measures": [],
            "pages": [
                {
                    "id": "p-cfo",
                    "name": "CFO P&L Margin Summary",
                    "hidden": False,
                    "width": 1280,
                    "height": 720,
                    "filters": [],
                    "visuals": [
                        {
                            "id": "f1",
                            "type": "card",
                            "type_label": "KPI Card",
                            "title": "Gross Margin %",
                            "decorative": False,
                            "x": 24,
                            "y": 24,
                            "width": 360,
                            "height": 110,
                            "fields": [
                                {"role": "Values", "kind": "measure", "entity": "Fact GL Margin", "property": "Gross Margin %", "ref": "Fact GL Margin[Gross Margin %]", "display": "Gross Margin %"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "f2",
                            "type": "clusteredColumnChart",
                            "type_label": "Clustered Column Chart",
                            "title": "Monthly Revenue vs. COGS",
                            "decorative": False,
                            "x": 24,
                            "y": 154,
                            "width": 1232,
                            "height": 540,
                            "fields": [
                                {"role": "Category", "kind": "column", "entity": "Dim Calendar", "property": "YearMonth", "ref": "Dim Calendar[YearMonth]", "display": "YearMonth"},
                                {"role": "Y", "kind": "measure", "entity": "Fact GL Margin", "property": "Gross Revenue", "ref": "Fact GL Margin[Gross Revenue]", "display": "Gross Revenue"},
                                {"role": "Y", "kind": "measure", "entity": "Fact GL Margin", "property": "COGS", "ref": "Fact GL Margin[COGS]", "display": "COGS"},
                            ],
                            "filters": [],
                        },
                    ],
                }
            ],
        },
    )

    store.write_report_layout(
        "r-4",
        {
            "format": "ReportJson",
            "report_filters": [],
            "report_measures": [],
            "pages": [
                {
                    "id": "p-vend",
                    "name": "Vendor Spend & Rebates",
                    "hidden": False,
                    "width": 1280,
                    "height": 720,
                    "filters": [],
                    "visuals": [
                        {
                            "id": "b1",
                            "type": "clusteredBarChart",
                            "type_label": "Clustered Bar Chart",
                            "title": "Spend by Vendor",
                            "decorative": False,
                            "x": 24,
                            "y": 24,
                            "width": 600,
                            "height": 660,
                            "fields": [
                                {"role": "Category", "kind": "column", "entity": "Dim Vendor", "property": "VendorName", "ref": "Dim Vendor[VendorName]", "display": "VendorName"},
                                {"role": "Y", "kind": "measure", "entity": "Fact Spend", "property": "Total Spend", "ref": "Fact Spend[Total Spend]", "display": "Total Spend"},
                            ],
                            "filters": [],
                        },
                        {
                            "id": "b2",
                            "type": "tableEx",
                            "type_label": "Table",
                            "title": "Rebate Accrual Breakdown (Broken Field Example)",
                            "decorative": False,
                            "x": 648,
                            "y": 24,
                            "width": 608,
                            "height": 660,
                            "fields": [
                                {"role": "Values", "kind": "column", "entity": "Dim Vendor", "property": "VendorName", "ref": "Dim Vendor[VendorName]", "display": "VendorName"},
                                {"role": "Values", "kind": "column", "entity": "Fact Spend", "property": "DeletedRebateColumn", "ref": "Fact Spend[DeletedRebateColumn]", "display": "DeletedRebateColumn"},
                            ],
                            "filters": [],
                        },
                    ],
                }
            ],
        },
    )

    return generate_portal(store)


def publish_to_docs(portal_dir: Path, docs_dir: Path) -> None:
    """Copy generated demo portal into docs/ (preserving docs/media/) and add public OpenGraph + Demo Tour UX."""
    import re
    import shutil

    docs_dir.mkdir(parents=True, exist_ok=True)
    for item in portal_dir.iterdir():
        dest = docs_dir / item.name
        if item.is_dir():
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)

    og_img = "https://djrien-ai.github.io/pbi-doc-generator/media/v1_1_social_preview.png"
    index_meta = (
        '  <meta name="description" content="Interactive Power BI &amp; Microsoft Fabric Architecture Portal: 16:9 Report X-Ray, Broken Visual Audit, Dataflow Gen1/Gen2 to SQL Lineage, Star Schema &amp; PDF/SharePoint Export.">\n'
        '  <link rel="canonical" href="https://djrien-ai.github.io/pbi-doc-generator/">\n'
        '  <meta property="og:type" content="website">\n'
        '  <meta property="og:site_name" content="Power BI Doc Generator (Open-Source MIT)">\n'
        '  <meta property="og:title" content="Power BI &amp; Fabric Live Demo - 16:9 Report X-Ray, Dataflow-to-SQL Lineage &amp; Star Schema">\n'
        '  <meta property="og:description" content="Click through a live generated catalog: inspect 16:9 report layouts, jump to broken visual bindings, trace DAX KPIs back to Dataflows &amp; SQL, and preview print-ready PDFs. 100% local &amp; MIT open-source.">\n'
        '  <meta property="og:url" content="https://djrien-ai.github.io/pbi-doc-generator/">\n'
        f'  <meta property="og:image" content="{og_img}">\n'
        '  <meta property="og:image:width" content="1280">\n'
        '  <meta property="og:image:height" content="640">\n'
        '  <meta name="twitter:card" content="summary_large_image">\n'
        '  <meta name="twitter:title" content="Power BI &amp; Fabric Live Demo - Report X-Ray &amp; Visual-to-SQL Lineage">\n'
        '  <meta name="twitter:description" content="Interactive generated Power BI &amp; Fabric catalog: 16:9 Report X-Ray, Dataflow Gen1/Gen2 lineage, Star-Schema blueprints &amp; 10-tool MCP server.">\n'
        f'  <meta name="twitter:image" content="{og_img}">\n'
        '  <style>@media print { .demo-tour-bar, .demo-gh-links { display: none !important; } }</style>\n'
    )

    tour_bar = (
        '<div class="demo-tour-bar" style="background:linear-gradient(90deg,#0f172a,#1e293b);color:#f8fafc;padding:9px 24px;font-size:12.5px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;border-bottom:1px solid #334155">\n'
        '  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">\n'
        '    <span style="background:#2563eb;color:#fff;font-weight:700;padding:2px 8px;border-radius:999px;font-size:11px;letter-spacing:0.03em">LIVE v1.1 DEMO</span>\n'
        '    <span style="color:#cbd5e1">1-click tour:</span>\n'
        '    <button type="button" data-open-xray="rep:r-1" style="background:#1e293b;color:#93c5fd;border:1px solid #3b82f6;border-radius:6px;padding:3px 9px;font-size:12px;font-weight:600;cursor:pointer">16:9 Report X-Ray &rarr;</button>\n'
        '    <button type="button" data-open-xray="rep:r-4" data-xray-jump-broken="0" style="background:#450a0a;color:#fca5a5;border:1px solid #dc2626;border-radius:6px;padding:3px 9px;font-size:12px;font-weight:600;cursor:pointer">! Broken Visual Audit &rarr;</button>\n'
        '    <button type="button" data-open-xray="df:df-raw-erp" style="background:#1e293b;color:#e2e8f0;border:1px solid #475569;border-radius:6px;padding:3px 9px;font-size:12px;font-weight:600;cursor:pointer">Dataflow &rarr; Native SQL</button>\n'
        '    <a href="models/enterprise-core-semantic-models-global-supply-chain-otif-core.html" style="background:#1e293b;color:#e2e8f0;border:1px solid #475569;border-radius:6px;padding:3px 9px;font-size:12px;font-weight:600;text-decoration:none">Star-Schema Blueprint &rarr;</a>\n'
        '  </div>\n'
        '  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">\n'
        '    <a href="https://github.com/djrien-ai/pbi-doc-generator" target="_blank" rel="noopener" style="background:transparent;color:#f8fafc;border:1px solid #64748b;border-radius:6px;padding:4px 10px;font-size:12px;font-weight:700;text-decoration:none">&#9733; Star on GitHub (MIT)</a>\n'
        '    <a href="https://github.com/djrien-ai/pbi-doc-generator/releases/latest" target="_blank" rel="noopener" style="background:#2563eb;color:#fff;border:1px solid #3b82f6;border-radius:6px;padding:4px 11px;font-size:12px;font-weight:700;text-decoration:none">Download v1.1 (.zip)</a>\n'
        '  </div>\n'
        '</div>\n'
    )

    idx_file = docs_dir / "index.html"
    idx_html = idx_file.read_text(encoding="utf-8")
    idx_html = idx_html.replace("</head>", index_meta + "</head>", 1)
    idx_html = idx_html.replace("</header>", "</header>\n" + tour_bar, 1)
    # Default Tab 1 sort to 'measures' so flagship Direct Lake + Dataflow + SAP HANA model leads first
    idx_html = idx_html.replace(
        '<option value="measures">Sort: Most DAX Measures</option>',
        '<option value="measures" selected>Sort: Most DAX Measures</option>',
        1,
    )
    # Open Tab 2 accordions in the compact 3-workspace demo so visitors immediately see X-Ray & Dataflows
    idx_html = idx_html.replace('<details class="section-accordion">', '<details class="section-accordion" open>')
    idx_html = idx_html.replace(
        "</body>",
        "<script>document.addEventListener('DOMContentLoaded',function(){var s=document.getElementById('catalogSort');if(s&&s.value==='measures'){s.dispatchEvent(new Event('change'));}});</script>\n</body>",
        1,
    )
    idx_file.write_text(idx_html, encoding="utf-8")

    # Enrich individual model blueprint pages in docs/models/*.html with OpenGraph + subtle GitHub bar
    models_dir = docs_dir / "models"
    if models_dir.is_dir():
        for mf in sorted(models_dir.glob("*.html")):
            mhtml = mf.read_text(encoding="utf-8")
            t_match = re.search(r"<title>(.*?)</title>", mhtml, flags=re.S)
            page_title = t_match.group(1).strip() if t_match else "Semantic Model Blueprint - PBI Doc Generator"
            model_url = f"https://djrien-ai.github.io/pbi-doc-generator/models/{mf.name}"
            model_meta = (
                f'  <meta name="description" content="{page_title} - Interactive Star Schema, SQLBI-formatted DAX, Power Query M, Native SQL &amp; Visual Lineage.">\n'
                f'  <link rel="canonical" href="{model_url}">\n'
                '  <meta property="og:type" content="website">\n'
                f'  <meta property="og:title" content="{page_title}">\n'
                '  <meta property="og:description" content="Interactive Power BI &amp; Fabric Semantic Model Blueprint: SVG Star-Schema Explorer, DAX lineage, Power Query steps &amp; A4 PDF export.">\n'
                f'  <meta property="og:url" content="{model_url}">\n'
                f'  <meta property="og:image" content="{og_img}">\n'
                '  <meta name="twitter:card" content="summary_large_image">\n'
                f'  <meta name="twitter:image" content="{og_img}">\n'
                '  <style>@media print { .demo-tour-bar { display: none !important; } }</style>\n'
            )
            model_bar = (
                '<div class="demo-tour-bar" style="background:linear-gradient(90deg,#0f172a,#1e293b);color:#f8fafc;padding:7px 24px;font-size:12px;display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;border-bottom:1px solid #334155">\n'
                '  <div><span style="background:#2563eb;color:#fff;font-weight:700;padding:2px 8px;border-radius:999px;font-size:10.5px;margin-right:8px">LIVE v1.1 DEMO</span><a href="../index.html" style="color:#93c5fd;font-weight:600;text-decoration:none">&larr; Back to Full Multi-Workspace Catalog &amp; Report X-Ray</a></div>\n'
                '  <div style="display:flex;align-items:center;gap:8px"><a href="https://github.com/djrien-ai/pbi-doc-generator" target="_blank" rel="noopener" style="color:#f8fafc;border:1px solid #64748b;border-radius:6px;padding:3px 9px;font-weight:700;text-decoration:none">&#9733; Star on GitHub</a><a href="https://github.com/djrien-ai/pbi-doc-generator/releases/latest" target="_blank" rel="noopener" style="background:#2563eb;color:#fff;border-radius:6px;padding:3px 10px;font-weight:700;text-decoration:none">Download v1.1 (.zip)</a></div>\n'
                '</div>\n'
            )
            mhtml = mhtml.replace("</head>", model_meta + "</head>", 1)
            mhtml = mhtml.replace("<body", "<body", 1)
            # Insert right after opening <body...>
            mhtml = re.sub(r"(<body[^>]*>)", r"\1\n" + model_bar, mhtml, count=1)
            mf.write_text(mhtml, encoding="utf-8")


if __name__ == "__main__":
    demo_dir = ROOT / "demo_catalog"
    idx = build_demo(demo_dir)
    print(f"Demo portal generated at: {idx}")
    if "--publish-docs" in sys.argv:
        publish_to_docs(idx.parent, ROOT / "docs")
        print(f"Published enriched Live Demo with OpenGraph & Tour Bar to: {ROOT / 'docs'}")
