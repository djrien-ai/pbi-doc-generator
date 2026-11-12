FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PBI_CATALOG_DIR=/data/catalog

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY pbi_catalog ./pbi_catalog
COPY launcher.py extract.py html_template.py pbip_adapter.py tmdl_parser.py dax_parser.py mermaid_js.py excel_extractor.py ./

RUN mkdir -p /data/catalog && pip install --no-cache-dir .

ENTRYPOINT ["pbi-doc-generator", "mcp"]
