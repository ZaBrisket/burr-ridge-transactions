# Burr Ridge Residential Transaction Warehouse

Free, repeatable, ~95%-coverage DuckDB warehouse of residential property transactions for the Village of Burr Ridge, IL — both the Cook County and DuPage County halves — covering 2013 to present.

## Get the data

This repo ships the built warehouse so you can analyze it without running the pipeline. After `git clone`:

- **`data/warehouse.duckdb`** — the full warehouse. Query with DuckDB (Python, CLI, R, etc.).
- **`data/export/*.parquet` and `data/export/*.csv`** — flat exports of the headline views (`arms_length_sales`, `sales_with_characteristics`, `annual_summary`) for use in pandas, R, Excel, or any BI tool — no DuckDB required.

```python
import duckdb
duckdb.read_parquet("data/export/annual_summary.parquet").df()       # any DuckDB install
# or query the warehouse directly:
con = duckdb.connect("data/warehouse.duckdb")
con.execute("INSTALL spatial; LOAD spatial;")
con.execute("SELECT * FROM annual_summary").df()
```

Regenerate the flat exports anytime from the warehouse with `make export`. The rest of this README covers (re)building the warehouse from source.

## Why this exists

Burr Ridge straddles two counties with non-interoperable PIN schemes and very different open-data postures. No single registrar covers the whole village. This pipeline glues two free public sources into one analytical warehouse:

- **Cook County:** Cook County Assessor open data portal (Socrata), 1999–present, monthly refresh.
- **DuPage County:** Illinois Department of Revenue MyDec PTAX-203 transfer declarations, 2013–present, weekly refresh, served via the federated Socrata catalog at `illinois-edp.data.socrata.com` (dataset `it54-y4c6`).

Both sources are public, free, and require **no authentication**. MyDec also provides a free cross-validation layer against CCAO on the Cook side.

## Quickstart

```bash
cd burr-ridge-transactions
make venv          # one-time: create .venv, install deps
make bootstrap     # create warehouse + schema
make boundary      # download Burr Ridge polygon (Census TIGER/Line)
make parcels       # pull Cook + DuPage parcels, clip to village
make sales-cook
make sales-dupage
make crosscheck
make characteristics
make assessments
make validate
```

Or end-to-end:

```bash
make full
```

**Optional Socrata app token.** Both CCAO and MyDec are free and unauthenticated, but Socrata applies stricter rate limits to anonymous callers. If you hit throttling on a full backfill, register a free token at <https://data.cityofchicago.org/profile/app_tokens> (works for any Socrata domain), copy `.env.example` to `.env`, and set `SOCRATA_APP_TOKEN` there — the loaders pick it up automatically.

Or run the whole thing end-to-end:

```bash
make full
```

For DuPage characteristics, download the residential workbook from <https://www.dgtownship.com/assessor/> and save to `data/raw/dg_township_<year>.xlsx`. The loader auto-detects the most recent file matching that pattern.

## Refresh cadence

| Cadence | Command | Source |
|---|---|---|
| Weekly | `make refresh-mydec` | Illinois MyDec (DuPage sales + Cook cross-check) |
| Monthly | `make refresh-cook` | CCAO sales + characteristics + assessments |
| Quarterly | `make refresh-parcels` | Cook + DuPage parcel layers |
| Annually | drop new `dg_township_<year>.xlsx` into `data/raw/`, run `make characteristics` | Downers Grove Township Excel |

Suggested cron:

```
0 4 * * MON  cd /path/to/burr-ridge-transactions && make refresh-mydec
0 4 1 * *    cd /path/to/burr-ridge-transactions && make refresh-cook
0 4 1 1,4,7,10 * cd /path/to/burr-ridge-transactions && make refresh-parcels
```

## Querying the warehouse

```python
import duckdb
con = duckdb.connect("data/warehouse.duckdb")
con.execute("INSTALL spatial; LOAD spatial;")
con.execute("SELECT * FROM annual_summary").df()
con.execute("SELECT * FROM sales_with_characteristics WHERE sale_date >= '2024-01-01' ORDER BY sale_price DESC LIMIT 20").df()
```

Headline views:

- `burr_ridge_parcels` — current parcel master
- `arms_length_sales` — sales filtered to deed-type/price/exemption rules
- `sales_with_characteristics` — sales joined to parcel + characteristic + assessment
- `annual_summary` — count, median, mean by year × county

## Schema

See `sql/schema.sql`. Six tables:

- `parcels` — current parcel master (geometry + class + lot)
- `sales` — transactions from CCAO, MyDec, DG Township, and DuPage SOA scrape
- `sales_crosscheck` — Cook MyDec ↔ CCAO reconciliation
- `characteristics` — sqft, beds, baths, year built (Cook from CCAO; DuPage DG-side from Township Excel)
- `assessments` — multi-year AVs (Cook from CCAO `uzyt-m557`; DuPage from GIS layer + DuPage SOA scrape)
- `tax_bills` — multi-year tax billed/paid (Cook from Treasurer scrape; DuPage from SOA scrape)
- `source_audit` — ingest provenance log

Plus two scrape-tracking tables (`dupage_soa_scraped`, `cook_treasurer_scraped`) for resume safety.

All keyed by `(county, pin_normalized, ...)`. Cook PINs are 14-digit zero-padded; DuPage PINs are digits-only canonical (use `format_pin_dupage_dashed` / `format_pin_cook_dashed` for display).

## Optional per-PIN scrapers (long-running, fill known gaps)

The bulk loaders are fast and authoritative but leave specific gaps. Two polite per-PIN scrapers fill them:

- **`make scrape-dupage-soa`** — hits `propertylookup.dupagecounty.gov` for each DuPage PIN. Pulls (a) full conveyance history including pre-2015 sales, (b) multi-year AV history, (c) 12+ years of tax bills. ~2 hours at 1 req/sec, resume-safe.
- **`make scrape-cook-treasurer`** — hits `cookcountytreasurer.com` for each Cook PIN. Pulls 20-year tax bill history. ~1 hour at 1 req/sec, resume-safe.

Both are stateful — if interrupted, just re-run; they skip PINs already in the audit table.

The DuckDB warehouse is single-writer, so do not run both scrapers concurrently. Use `make full-with-scrape` to chain them serially.

## Confidence score (0–4 per sales row)

- +1 if appears in both CCAO and MyDec (Cook only)
- +1 if address normalizes cleanly
- +1 if PIN matches a current parcel
- +1 if an assessment exists for the same tax year
- −1 per sale_filter_* / exemption flag

Recomputed by `make validate`.

## Known gaps / caveats

- **Pre-2013 transactions** are out of scope. MyDec only goes back to 2013.
- **DuPage assessment history** before the latest Township snapshot is sparse. The warehouse only carries the years for which a Township Excel has been ingested. Save annual snapshots going forward to accumulate a series.
- **Tax-bill data** (Treasurer history) is out of scope for v1 — both county Treasurers are per-PIN scrape only.
- **Lyons Township slivers in DuPage** — confirm none exist by spot-checking a few addresses on `gis.dupageco.org/parcelviewer/`. If any do, add Lisle Township to the Excel ingest.
- **MyDec PIN format** in `line_1_primary_pin` uses dashed county-specific formats (e.g. DuPage `06-10-202-009`); the loader normalizes to digits-only for joins. Cook PINs are zero-padded to 14 digits.
- **CCAO arms_length flag** is computed locally; CCAO ships filter columns and we apply them. Validate against `github.com/ccao-data/model-sales-val` when their methodology updates.
- **Boundary source** is Census TIGER/Line 2024 places. If the village annexes new parcels mid-year, refresh `make boundary` to pick up the latest TIGER vintage.

## Verification workflow

After `make full`, run a spot check (a `notebooks/verification.ipynb` workbook is the planned home for this):

1. Pull 30 random sales (15 Cook, 15 DuPage) across years.
2. Manually verify each in:
   - Cook: <https://www.cookcountyclerkil.gov/recordings/search-recordings>
   - DuPage: <https://recorder.dupageco.org/Search.aspx>
3. Target ≥28/30 verified.

`make validate` already enforces:

- Parcel count in [3500, 5000]
- ≥2500 sales 2013–present
- Cook cross-check match ≥90%
- ≥12 distinct sale years

## Project layout

```
burr-ridge-transactions/
├── Makefile                # all targets
├── pyproject.toml
├── README.md               # this file
├── LICENSE                 # MIT
├── .env.example            # optional SOCRATA_APP_TOKEN template
├── data/
│   ├── raw/                # downloaded source files (committed)
│   ├── export/             # flat Parquet + CSV of headline views (committed)
│   └── warehouse.duckdb    # the warehouse (committed)
├── notebooks/              # spot-check workbooks (verification.ipynb planned)
├── sql/
│   ├── schema.sql          # DDL
│   └── views.sql           # analytical views
└── etl/
    ├── _db.py              # DuckDB connect + bootstrap + audit log
    ├── _http.py            # requests with retry + polite rate limit
    ├── _arcgis.py          # paginated ArcGIS REST query
    ├── _paths.py           # filesystem paths
    ├── normalize.py        # PIN, address, deed-type, arms-length rules
    ├── boundary.py         # Burr Ridge village polygon
    ├── parcels_cook.py     # Cook GIS → parcels
    ├── parcels_dupage.py   # DuPage GIS → parcels
    ├── sales_cook.py       # CCAO wvhk-k5uv → sales
    ├── sales_dupage.py     # MyDec → sales
    ├── sales_crosscheck.py # MyDec Cook → sales_crosscheck
    ├── characteristics_cook.py    # CCAO x54s-btds + 3r7i-mrz4
    ├── characteristics_dupage.py  # Downers Grove Township Excel
    ├── assessments_cook.py        # CCAO uzyt-m557
    ├── assessments_dupage.py      # delegates to characteristics_dupage
    ├── export.py           # headline views → data/export Parquet + CSV
    └── validate.py          # sanity + confidence scoring
```

## License

MIT — see [LICENSE](LICENSE). The underlying data comes from public Cook County, DuPage County, Illinois MyDec, Downers Grove Township, and US Census sources (listed under Sources above).

## Sources

- Cook County Open Data Portal — <https://datacatalog.cookcountyil.gov>
- Cook County Assessor — <https://www.cookcountyassessoril.gov/community-data>
- Cook County Clerk Recordings — <https://www.cookcountyclerkil.gov/recordings/search-recordings>
- Cook Central GIS Hub — <https://hub-cookcountyil.opendata.arcgis.com>
- DuPage County Recorder — <https://recorder.dupageco.org/Search.aspx>
- DuPage County GIS Open Data — <https://gisdata-dupage.opendata.arcgis.com>
- Downers Grove Township Assessor — <https://www.dgtownship.com/assessor/>
- Illinois MyDec dataset (Socrata) — <https://illinois-edp.data.socrata.com/d/it54-y4c6>
- Illinois MyDec landing — <https://tax.illinois.gov/localgovernments/property/mydec.html>
- IDOR confirmation that data.illinois.gov requires no login — <https://tax.illinois.gov/localgovernments/property/mydecdatafiles.html>
- US Census TIGER/Line — <https://www2.census.gov/geo/tiger/TIGER2024/PLACE/>
