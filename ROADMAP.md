# Analysis Roadmap

A guide for analysts who want to derive **statistically significant trends** from this
warehouse. The data is already built and committed (see [README](README.md#get-the-data)) —
this document covers *what to analyze, how, and with which Claude Code tooling*.

## Reality check: this is a clean, modest dataset — not "big data"

The warehouse holds roughly:

- **~2,253 arms-length sales** (`arms_length_sales`, 2013–present)
- **~4,480 sales joined to characteristics** (`sales_with_characteristics`)
- Parcel geometry, assessments, and per-year summaries (`annual_summary`)

That's good news — DuckDB + Python handle it instantly, no Spark/warehouse-scale tooling
needed. But it constrains **statistical power**: some slices are thin (e.g. only ~18 Cook
sales in 2015). Significance claims on small cells must be made carefully. The heavy lifting
is Claude writing/running Python (statsmodels, scipy) against the DuckDB/Parquet files;
plugins provide data access, methodology guardrails, and presentation.

## Recommended Claude Code plugin stack

### Tier 1 — core (install first)

| Plugin | Marketplace | Why |
|---|---|---|
| **`data`** | `anthropics/knowledge-work-plugins` | The centerpiece: `statistical-analysis` (trend tests, hypothesis testing, significance caveats), `explore-data`, `sql-queries`, `validate-data`, `create-viz`, `build-dashboard`. |
| **`duckdb-skills`** | `anthropics/claude-plugins-official` | Reads any data file, attaches/queries DuckDB databases directly, manages extensions. Native access layer for this warehouse. |

### Tier 2 — add as analysis matures

| Plugin | Why |
|---|---|
| **`mapbox`** | Spatial viz — choropleths/heatmaps of price by parcel/sub-area. (Optional; `geopandas`/`shapely` already cover most of this.) |
| **`exa`** / **`firecrawl`** | Pull external covariates: mortgage rates (FRED), CPI for real-price deflation, school ratings, comps. |
| **`playground`** | Self-contained interactive HTML data explorers — a shareable way to publish findings. |
| **`claude-code-setup`** | Recommends tailored hooks/skills/subagents for this repo. |
| **`skill-creator`** (`anthropics/skills`) | Package the recurring analysis into a reusable `/burr-trends` skill. |

### Tier 3 — skip at this scale

`datarobot-agent-skills`, `dominodatalab`, `huggingface-skills`, `fiftyone`,
`aws-data-analytics`, `clickhouse`, `data-engineering` — enterprise ML/data-platform tools
built for millions of rows; wrong weight class for ~2–4k rows.

### Install

```
/plugin marketplace add anthropics/knowledge-work-plugins
/plugin install data@knowledge-work-plugins

/plugin marketplace add anthropics/claude-plugins-official
/plugin install duckdb-skills@claude-plugins-official
# Tier 2 examples:
/plugin install mapbox@claude-plugins-official
/plugin install exa@claude-plugins-official
/plugin install playground@claude-plugins-official
```

### Python dependencies

The `.venv` already has `duckdb`, `pandas`, `pyarrow`, `geopandas`, `shapely`. Add for stats:

```
statsmodels scipy scikit-learn pymannkendall linearmodels esda libpysal plotly
```

## Analysis workflows (methods)

Defensible ways to extract significant trends from `arms_length_sales`,
`sales_with_characteristics`, `annual_summary`, and `parcels`:

1. **Quality-adjusted price index (do this first).** Hedonic OLS:
   `log(sale_price) ~ building_sqft + bedrooms + bathrooms + age + lot_sqft + C(county) + C(sale_year)`.
   The year fixed-effect coefficients *are* the price trend, controlling for house quality.
   Report coefficients, 95% CIs, robust standard errors.
2. **Time-trend significance test.** Mann-Kendall (`pymannkendall`) on median price by year,
   per county — non-parametric, robust to small-n years. Pair with an OLS slope + p-value on
   log price.
3. **County comparison (Cook vs DuPage).** Mann-Whitney U and t-test on `$/sqft`; report
   effect size, not just p-value.
4. **Repeat-sales index.** Where a `pin_normalized` sold more than once, a Case-Shiller-style
   repeat-sales model controls for unobserved quality — the cleanest appreciation estimate.
5. **Seasonality & cyclicality.** Month-of-year effects on volume and price; STL decomposition
   of the monthly series.
6. **Spatial trends.** Map median price by parcel/sub-area; test clustering with Moran's I
   (`esda`).
7. **Real (inflation-adjusted) trends.** Deflate nominal prices by CPI; compare real vs
   nominal appreciation.
8. **Data-quality gate.** Run `validate-data` and use the existing `confidence_score` to
   exclude low-confidence rows before every analysis.

## Orchestration & automation

- **Multi-agent fan-out.** One subagent per workflow lane (trend-test, hedonic, spatial,
  county-comparison), each returning a findings memo, then a synthesis agent assembles the
  report. Best for breadth. (This is the `analysis/` orchestrator planned next.)
- **Scheduled re-runs.** Use `/schedule` or `/loop` to re-run the analysis after each
  `make refresh-mydec` / `make refresh-cook` and emit a "what changed this period" digest.
- **Durable managed agent.** The Agent SDK (`anthropics/claude-agent-sdk-python`) for a
  headless/server-side runner.
- **Reusable skill.** Once the method stabilizes, `skill-creator` → a `/burr-trends` command
  so collaborators run the whole pipeline in one step.

## Suggested first week

1. Install `data` + `duckdb-skills`; add the Python stats libs.
2. `explore-data` + `validate-data` on `sales_with_characteristics` → distribution profile +
   quality gate.
3. Run the **hedonic price index** (1) and **Mann-Kendall trend test** (2) → first defensible
   "prices rose X%/yr, p<0.05, controlling for size/quality" result.
4. `build-dashboard` / `playground` to publish it.
5. Add spatial + real-price layers (6–7) as v2.

## Statistical caveats (enforced by the `statistical-analysis` skill)

- Mind small-n years; don't over-claim on thin slices.
- Correct for multiple comparisons when testing many slices.
- Prefer robust / non-parametric tests given skewed prices.
- Report confidence intervals and effect sizes, not bare p-values.
