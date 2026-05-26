---
name: trend-analysis
description: Run the Burr Ridge property price-trend analysis end to end — refresh the deterministic statistical lanes, fan out one analyst subagent per lane to interpret the results with proper significance methodology, then synthesize a QA-checked trend report at analysis/TRENDS.md. Use when the user asks to analyze price trends, derive statistically significant trends, refresh the trend report, or run the analysis orchestrator.
---

# Burr Ridge trend-analysis orchestrator

Derives **statistically significant** residential price trends from the warehouse and writes
`analysis/TRENDS.md`. The statistics are computed deterministically in the `analysis/` Python
package; your job as orchestrator is to refresh those numbers, dispatch the interpreting
subagents, and assemble the report. **Never compute statistics yourself** — interpret what the
Python lanes emit.

## Boundaries

- **Read-only over the warehouse.** This workflow does not touch `etl/` and never refreshes or
  rebuilds the data (honor the CLAUDE.md banner). It only reads `data/warehouse.duckdb`.
- **Self-contained.** The analyst subagents carry their own significance methodology; no plugins
  are required. (Optional: installing `data@knowledge-work-plugins` adds richer interactive
  interpretation and `/build-dashboard`, but it is not needed here.)

## Steps

1. **Refresh deterministic artifacts.** Run `make analyze` (or `.venv/bin/python -m analysis.run`).
   This writes `analysis/output/<today>/` with per-lane `*.json` + `*.md` + `summary.md`, and
   committed charts in `analysis/charts/`. Note the dated output directory.

2. **Fan out the five lane analysts in parallel.** In a single message, dispatch all five via the
   Agent tool (they are independent): `quality-gate-analyst`, `trend-test-analyst`,
   `repeat-sales-analyst`, `hedonic-analyst`, `county-compare-analyst`. Tell each one the path to
   the dated output directory. Each returns a findings memo with significance framing and caveats.

3. **Synthesize.** Dispatch `trend-synthesizer`, passing it the five returned memos verbatim and
   the output-directory path. It runs a QA pass and writes `analysis/TRENDS.md` with embedded
   charts.

4. **Report back.** Tell the user where `analysis/TRENDS.md` landed and give a 3-4 line headline
   (the significant trends and the single most important caveat). Do **not** commit or push unless
   the user asks.

## What the lanes mean (for your summary)

- **quality_gate** — coverage + which lanes are statistically viable (gates the rest).
- **trend_test** — Mann-Kendall + OLS log-price CAGR per county (price-level trend).
- **repeat_sales** — quality-controlled appreciation from resale pairs (DuPage's strongest signal).
- **hedonic** — Cook-only quality-adjusted index (characteristics too sparse for DuPage).
- **county_compare** — cross-sectional Cook vs DuPage price-level comparison.

A known, important pattern to watch for: repeat-sales appreciation can exceed the median-price
trend (a mix effect — cheaper homes selling later pull the median trend down). Flag divergences
like this rather than hiding them.
