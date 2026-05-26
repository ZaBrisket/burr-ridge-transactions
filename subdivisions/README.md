# Burr Ridge subdivision tagging

Self-contained initiative: tag every warehouse transaction by the named/signed subdivision it
sits in. **All code, data, and docs for this work live under this folder.**

- **Spec / work plan:** [`SUBDIVISION_TAGGING_PLAN.md`](SUBDIVISION_TAGGING_PLAN.md) — read this first.
- **Code** (Python package `subdivisions`): the `*.py` modules here. Run from the repo root as
  `.venv/bin/python -m subdivisions.<module>` (the repo root is on `sys.path`; the installed
  `etl` / `analysis` packages stay importable for helpers like `etl._arcgis`).
- **Outputs:** `data/reference/` (subdivision reference layer + parcel crosswalk),
  `data/export/` (tagged transactions).
- **Docs:** `docs/` (Gate-2 review checklist + methodology).

Read-only over the warehouse (`../data/warehouse.duckdb`). Does **not** run or modify the
`etl/` pipeline. Honors the published-dataset banner in the repo-root `CLAUDE.md`.
