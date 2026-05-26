# Burr Ridge Residential Transaction Warehouse

> **This is a published dataset, not a pipeline to run on open.**
> The warehouse (`data/warehouse.duckdb`) and flat exports (`data/export/`) are already
> built and committed — clone and analyze them directly. Everything below documents how
> the data was assembled, for maintainers who want to *refresh* it. Do **not** re-run the
> ETL unless the user explicitly asks: it makes live API calls, takes hours, and a fresh
> clone can't run it as-is (it needs a Socrata token setup and manual Township Excel drops —
> see Gotchas). For analysis, start with `data/export/`.

Local DuckDB warehouse of Burr Ridge, IL residential sales (Cook + DuPage counties, 2013–present). Full architecture, schema, and source-by-source detail is in [README.md](README.md); this file covers only what's needed to run the pipeline correctly.

## Working directory

Run all `cd` and `make` commands from the repository root (the directory containing this file and the `Makefile`).

## Environment setup

The optional Socrata App Token lives in `.env` (gitignored; copy `.env.example` to start). Load it before any `make` target that hits Socrata (Cook sales/characteristics/assessments, DuPage sales, Cook crosscheck):

```bash
set -a; source .env; set +a
```

Verify with `echo $SOCRATA_APP_TOKEN`. When loaders log `with token` (not `ANONYMOUS (slow)`), it's active.

First-time only: `make venv` to create `.venv` and install deps.

## Running the pipeline

| Goal | Command |
|---|---|
| Full rebuild | `make full` |
| Full rebuild + per-PIN scrapers (~3hr extra) | `make full-with-scrape` |
| Refresh DuPage sales + Cook crosscheck | `make refresh-mydec` |
| Refresh Cook sales/characteristics/assessments | `make refresh-cook` |
| Refresh parcel layers | `make refresh-parcels` |
| Re-score confidence + run sanity gates | `make validate` |

DuckDB is **single-writer** — never run two write-stage targets concurrently. The `full-with-scrape` target already serializes the scrapers.

## Verifying a run

`make validate` enforces: parcel count ∈ [3500, 5000], ≥2500 sales since 2013, ≥90% Cook MyDec↔CCAO match, ≥12 distinct sale years. If any fail, it exits non-zero and names the failing gate.

For manual spot-checks, see [notebooks/verification.ipynb](notebooks/verification.ipynb).

## Code layout (key files)

- [Makefile](Makefile) — every target, single source of truth for run order
- [sql/schema.sql](sql/schema.sql) — DDL for the 6 tables + audit/scrape-tracking
- [sql/views.sql](sql/views.sql) — `arms_length_sales`, `sales_with_characteristics`, `annual_summary`
- [etl/_db.py](etl/_db.py) — DuckDB connect, bootstrap, audit log
- [etl/_http.py](etl/_http.py) — retry + polite rate limit
- [etl/normalize.py](etl/normalize.py) — PIN/address/deed-type/arms-length rules
- [etl/validate.py](etl/validate.py) — confidence scoring + sanity gates

Source-specific loaders are named `<stage>_<county>.py` in [etl/](etl/).

## Gotchas

- **PIN formats differ by county.** Cook is 14-digit zero-padded; DuPage is digits-only canonical. Use `format_pin_cook_dashed` / `format_pin_dupage_dashed` only for display.
- **MyDec only goes back to 2013** — pre-2013 sales are out of scope (per-PIN DuPage SOA scrape backfills some).
- **DuPage characteristics need an annual Excel drop** at `data/raw/dg_township_<year>.xlsx` from <https://www.dgtownship.com/assessor/>. Loader picks up the most recent file matching that pattern.
- **`make full` ≠ scrapers.** Tax bills and pre-2015 DuPage sales only land via `make scrape-dupage-soa` / `make scrape-cook-treasurer` (or the chained `full-with-scrape`).
