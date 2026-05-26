PY ?= .venv/bin/python

.PHONY: help venv install bootstrap boundary parcels sales-cook sales-dupage \
        crosscheck characteristics assessments validate export refresh-mydec refresh-cook \
        refresh-parcels refresh full clean-warehouse

help:
	@echo "Targets:"
	@echo "  venv                  Create .venv and install deps"
	@echo "  install               (Re)install deps into .venv"
	@echo "  bootstrap             Create DuckDB warehouse + load schema/views"
	@echo "  boundary              Fetch Burr Ridge village polygon"
	@echo "  parcels               Load Cook + DuPage parcels (clipped to village)"
	@echo "  sales-cook            Load CCAO Cook sales since 2013"
	@echo "  sales-dupage          Load DuPage MyDec sales since 2013"
	@echo "  crosscheck            Cross-check Cook CCAO sales against MyDec (PIN-list filter)"
	@echo "  characteristics       Load Cook CCAO + DuPage Township characteristics"
	@echo "  assessments           Load Cook CCAO assessments (DuPage AVs come via parcels + scrape)"
	@echo "  scrape-dupage-soa     Per-PIN DuPage SOA scrape (~2h): pre-2015 sales, AV history, tax bills"
	@echo "  scrape-cook-treasurer Per-PIN Cook Treasurer scrape (~80m): 20-yr tax bill history"
	@echo "  validate              Run sanity checks + recompute confidence scores"
	@echo "  export                Write headline views to data/export/ as Parquet + CSV"
	@echo "  refresh-mydec         Weekly: re-pull MyDec, refresh DuPage sales + crosscheck"
	@echo "  refresh-cook          Monthly: re-pull CCAO sales/characteristics/assessments"
	@echo "  refresh-parcels       Quarterly: re-pull parcels + boundary"
	@echo "  full                  End-to-end: bootstrap → all bulk loaders → validate → export"
	@echo "  full-with-scrape      full + per-PIN scrapes (long-running, ~3h total)"

venv:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -e .

install:
	.venv/bin/pip install -e .

bootstrap:
	$(PY) -m etl._db

boundary:
	$(PY) -m etl.boundary

parcels: boundary
	$(PY) -m etl.parcels_cook
	$(PY) -m etl.parcels_dupage

sales-cook:
	$(PY) -m etl.sales_cook

sales-dupage:
	$(PY) -m etl.sales_dupage

crosscheck:
	$(PY) -m etl.sales_crosscheck

characteristics:
	$(PY) -m etl.characteristics_cook
	$(PY) -m etl.characteristics_dupage

assessments:
	$(PY) -m etl.assessments_cook

validate:
	$(PY) -m etl.validate

export:
	$(PY) -m etl.export

scrape-dupage-soa:
	$(PY) -u -m etl.scrape_dupage_soa

scrape-cook-treasurer:
	$(PY) -u -m etl.scrape_cook_treasurer

refresh-mydec: sales-dupage crosscheck validate

refresh-cook: sales-cook characteristics assessments validate

refresh-parcels: parcels validate

full: bootstrap parcels sales-cook sales-dupage crosscheck characteristics assessments validate export

full-with-scrape: full scrape-dupage-soa scrape-cook-treasurer validate

clean-warehouse:
	rm -f data/warehouse.duckdb data/warehouse.duckdb.wal
