"""
Builds a rich, realistic, 100% fictional multi-workspace demo catalog in `demo_catalog/`
so users (and visual QA) can immediately explore the generated HTML Portal, Star-Schema diagrams,
auto-formatted DAX, visual Power Query pipelines, and Live Lineage Explorer.
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
    state = {
        "schema_version": "1.0",
        "updated_at": "2026-11-12T11:30:00Z",
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
                    {"displayName": "BI Engineering Group", "principalType": "Group", "groupUserAccessRight": "Contributor"},
                ],
                "last_scanned": "2026-11-12T11:30:00Z",
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
                ],
                "last_scanned": "2026-11-12T11:30:00Z",
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
                "last_scanned": "2026-11-12T11:30:00Z",
            },
        },
        "models": {
            "ds-otif": {
                "id": "ds-otif",
                "name": "Global Supply Chain & OTIF Core",
                "workspace_id": "ws-core",
                "workspace": "Enterprise Core Semantic Models",
                "configured_by": "clara.vance@northwind-global.example",
                "last_refresh": {"status": "Completed", "end_time": "2026-11-12T06:12:00Z"},
                "permissions": [
                    {"displayName": "Supply Chain Analysts", "principalType": "Group", "datasetUserAccessRight": "ReadExplore"},
                    {"displayName": "Clara Vance", "principalType": "User", "datasetUserAccessRight": "ReadWriteReshareExplore"},
                ],
                "workspace_users": [],
                "definition_status": "ok",
            },
            "ds-fin": {
                "id": "ds-fin",
                "name": "Group Working Capital & Margin",
                "workspace_id": "ws-fin",
                "workspace": "Corporate Finance & FP&A",
                "configured_by": "elena.rostova@northwind-global.example",
                "last_refresh": {"status": "Completed", "end_time": "2026-11-12T05:45:00Z"},
                "permissions": [],
                "workspace_users": [],
                "definition_status": "ok",
            },
            "ds-legacy": {
                "id": "ds-legacy",
                "name": "Regional Vendor Spend Tracker",
                "workspace_id": "ws-sc",
                "workspace": "Supply Chain & Procurement Analytics",
                "configured_by": "marcus.lindqvist@northwind-global.example",
                "last_refresh": {"status": "Failed", "end_time": "2026-11-11T23:10:00Z"},
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
            },
            "r-2": {
                "id": "r-2",
                "name": "Warehouse Dispatch Daily Monitor",
                "workspace_id": "ws-sc",
                "workspace": "Supply Chain & Procurement Analytics",
                "dataset_id": "ds-otif",
                "report_type": "PowerBIReport",
            },
            "r-3": {
                "id": "r-3",
                "name": "CFO Monthly Margin & Cashflow Pack",
                "workspace_id": "ws-fin",
                "workspace": "Corporate Finance & FP&A",
                "dataset_id": "ds-fin",
                "report_type": "PowerBIReport",
            },
            "r-4": {
                "id": "r-4",
                "name": "Vendor Rebate & Spend Variance",
                "workspace_id": "ws-sc",
                "workspace": "Supply Chain & Procurement Analytics",
                "dataset_id": "ds-legacy",
                "report_type": "PowerBIReport",
            },
        },
        "dataflows": {
            "df-1": {
                "id": "df-1",
                "name": "Master Vendor & Material Harmonization",
                "workspace_id": "ws-core",
                "workspace": "Enterprise Core Semantic Models",
            }
        },
        "errors": [],
    }
    store.save(state)

    # Model 1: Global Supply Chain & OTIF Core (Rich Star Schema + Multi-Tier DAX + Visual PQ)
    store.write_tmdl_bundle(
        "Global Supply Chain & OTIF Core",
        "ds-otif",
        {
            "definition/model.tmdl": "model Model\n\tculture: en-US\n",
            "definition/expressions.tmdl": (
                "/// Production SAP HANA Calculation View endpoint.\n"
                "expression pHanaServer = \"hana-ent-prod.northwind.internal:30015\" meta [IsParameterQuery=true, Type=\"Text\"]\n"
            ),
            "definition/relationships.tmdl": (
                "relationship r_cal\n\tfromColumn: 'Fact Deliveries'.DeliveryDate\n\ttoColumn: 'Dim Calendar'.Date\n"
                "relationship r_cust\n\tfromColumn: 'Fact Deliveries'.CustomerKey\n\ttoColumn: 'Dim Customer'.CustomerKey\n"
                "relationship r_plant\n\tfromColumn: 'Fact Deliveries'.PlantCode\n\ttoColumn: 'Dim Plant'.PlantCode\n"
                "relationship r_mat\n\tfromColumn: 'Fact Deliveries'.MaterialKey\n\ttoColumn: 'Dim Material'.MaterialKey\n"
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
                "/// Product hierarchy, material group, and ABC velocity classification.\n"
                "table 'Dim Material'\n"
                "\tcolumn MaterialKey\n\t\tdataType: string\n\t\tsourceColumn: MaterialKey\n"
                "\tcolumn MaterialDescription\n\t\tdataType: string\n\t\tsourceColumn: MaterialDescription\n"
                "\tcolumn ProductFamily\n\t\tdataType: string\n\t\tsourceColumn: ProductFamily\n"
                "\tpartition 'Dim Material' = m\n\t\tmode: import\n\t\tsource =\n"
                "\t\t\tlet\n"
                "\t\t\t\tSource = SapHana.Database(pHanaServer),\n"
                "\t\t\t\tView = Source{[Name=\"CV_MD_MATERIAL\"]}[Data]\n"
                "\t\t\tin\n"
                "\t\t\t\tView\n"
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
                "\t/// Year-to-date OTIF service rate across fiscal calendar.\n"
                "\tmeasure 'OTIF % YTD' = CALCULATE([OTIF %], DATESYTD('Dim Calendar'[Date]))\n"
                "\t\tformatString: 0.0%\n\t\tdisplayFolder: 03. Time Intelligence\n"
                "\t/// Year-over-year OTIF variance in percentage points.\n"
                "\tmeasure 'OTIF % vs PY' = VAR CurrentOTIF = [OTIF %] VAR PriorOTIF = CALCULATE([OTIF %], SAMEPERIODLASTYEAR('Dim Calendar'[Date])) RETURN IF(NOT ISBLANK(PriorOTIF), CurrentOTIF - PriorOTIF)\n"
                "\t\tformatString: +0.0%;-0.0%;0.0%\n\t\tdisplayFolder: 03. Time Intelligence\n"
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

    # Model 3: Regional Vendor Spend Tracker (intentionally demonstrates governance findings!)
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

    return generate_portal(store)


if __name__ == "__main__":
    demo_dir = ROOT / "demo_catalog"
    idx = build_demo(demo_dir)
    print(f"Demo portal generated at: {idx}")
