# Work Plan — Tag Burr Ridge transactions by named/signed subdivision

> **Status:** Approved plan, not yet executed. This document is self-contained so a fresh
> Claude Code session can pick it up. Read `CLAUDE.md` and `README.md` (repo root) first for
> warehouse context. **All work here is additive and read-only over the warehouse** — do not
> run the `etl/` pipeline and do not modify `data/warehouse.duckdb` until Review Gate 3.
>
> **All new files for this initiative live under this `subdivisions/` tree.** See "Repository
> layout" below.

## Objective

For every transaction in the warehouse, attach:

- `subdivision_name` (nullable)
- `has_recognized_name` (bool) — the neighborhood goes by a real/marketed name
- `has_entrance_sign` (enum: `confirmed_yes | likely | unknown | confirmed_no`) + `sign_confidence`
- `match_method` (`point_in_polygon | street_name | manual | none`) + `match_confidence`

A transaction counts as "in a subdivision" if `has_recognized_name` **OR** `has_entrance_sign`.
The two flags are tracked **independently** (per the owner's decision).

**Definition of done:** a committed subdivision reference layer, a parcel→subdivision
crosswalk, a tagged transactions export, a validation report, and a methodology note — all
under `subdivisions/`.

## Repository layout (everything under one tree)

```
subdivisions/
├── README.md                       # what this tree is + pointer to this plan
├── SUBDIVISION_TAGGING_PLAN.md     # this plan (the approved spec)
├── __init__.py                     # makes `subdivisions` an importable package
├── _paths.py                       # paths rooted at this tree (Phase 0)
├── _geo.py                         # spatial backbone: centroids, CRS helpers (Phase 0)
├── reference.py                    # build candidate reference layer (Phase 1)
├── assign.py                       # parcel -> subdivision spatial assignment (Phase 2)
├── classify.py                     # name + sign flags (Phase 3)
├── tag.py                          # tag transactions + coverage (Phase 4)
├── validate.py                     # validation / QA (Phase 5)
├── data/
│   ├── reference/
│   │   ├── subdivisions.geojson    # one row per subdivision (+ .csv attributes)
│   │   ├── subdivisions.csv
│   │   └── parcel_subdivision.csv  # one row per PIN (crosswalk)
│   └── export/
│       └── sales_tagged.{parquet,csv}   # the deliverable: sales + subdivision fields
└── docs/
    ├── subdivision_review.md       # Gate-2 human checklist (entrance coords + StreetView)
    └── SUBDIVISIONS_METHOD.md      # methodology + coverage / limitations
```

**Running code:** invoke modules from the **repo root** as
`.venv/bin/python -m subdivisions.<module>` (e.g. `-m subdivisions.reference`). The repo root
is on `sys.path`, so `import subdivisions` resolves, and the already-installed `etl` / `analysis`
packages remain importable for helpers (e.g. `from etl._arcgis import query_features`). **No
`pyproject.toml` change is required.** (Optional: if you later want `make` targets or a clean
`pip install -e .` to include this package, add `"subdivisions*"` to
`[tool.setuptools.packages.find].include` — not needed for `-m` execution.)

**Paths in code:** `subdivisions/_paths.py` should resolve the repo root as
`Path(__file__).resolve().parents[1]`, then `WAREHOUSE = REPO_ROOT/"data"/"warehouse.duckdb"`
(read-only input), and write outputs under `Path(__file__).resolve().parent/"data"/...` and
`.../"docs"/...`. The only pre-existing files this initiative reads are the warehouse, the raw
village boundary (`data/raw/burr_ridge_boundary.geojson`), and `etl` helper modules — all
read-only.

## Why this is not just "read the plat map"

There are three different "subdivision" concepts and they do not line up:

1. **Plat of subdivision (legal):** every parcel belongs to one. Names range from branded
   ("Braemoor") to bureaucratic ("Assessor's Division of the SE ¼…"). **100% coverage.**
2. **Assessor neighborhood code:** admin grouping (DuPage Township export has `NBHD Code`,
   e.g. "GD2"). Near-100% coverage, codes not names.
3. **Vernacular / marketed / signed subdivision:** what people call it, what's on the
   monument sign, what an HOA governs. **Partial coverage — this is the target.**

The target is a **named, signed subset** of the plat universe. Strategy: **start from
authoritative plat/OSM geometry, then filter and confirm down** to the recognized-name +
signed subset using HOA / listing / signage evidence, with light human-in-the-loop
confirmation. There is **no single authoritative "has a sign" dataset** (the Village
publishes no HOA/subdivision directory) — so signage is a graded enum, not a hard fact.

## Design decisions (locked)

| Decision | Choice |
|---|---|
| Qualification | Track **name AND sign as separate flags**; "in a subdivision" = name OR sign |
| Input set | The repo's **warehouse** transactions (`sales` / `arms_length_sales`) |
| Sign confirmation | **Hybrid** — proxies rank/auto-confirm; owner reviews only uncertain ones |
| Geographic scope | **Match current dataset footprint** (loaded village parcels; no expansion) |
| Output location | **All under `subdivisions/`**; warehouse untouched until Gate 3 |

## Grounding facts (verified during planning — 2026-05-26)

**Warehouse / spatial backbone (verified locally via DuckDB):**

- 4,528 current parcels (1,468 Cook + 3,060 DuPage), **100% have polygon geometry** (WGS84).
- **100% of sales join to a current parcel by PIN** (911 Cook, 3,569 DuPage; arms-length
  445 + 1,808). Every transaction is taggable via its parcel — no orphan-sale fallback needed.
- **Cook parcels have 0 addresses; DuPage parcels are 100% addressed.** → Geometry
  (point-in-polygon on parcel centroid) is the **universal key**; address/street-name methods
  are a **DuPage-only** complement.
- Cook `property_class` = CCAO 3-digit codes (203/204/208/209/278…, EX=exempt);
  DuPage `property_class` = R/I/C/E/F (R = residential, 2,777 of 3,060).
- Cook township = "Town of Lyons" (all); DuPage township not loaded (NULL).
- Parcel bbox: Cook lon −87.9165..−87.8863, lat 41.7258..41.7894; DuPage lon
  −87.9447..−87.9148, lat 41.7125..41.782.
- DuPage Township Excel (`data/raw/dg_township_2025.xlsx`) has `NBHD Code` (grouping hint),
  no subdivision-name column.

**Reference sources (verified via research):**

- **DuPage — authoritative subdivision polygon layer EXISTS (the spine for the DuPage side):**
  `https://gis.dupageco.org/arcgis/rest/services/OpenData/Subdivision/MapServer/1`
  — 18,163 countywide polygons; fields `Name` (alias "Sub Name"), `SubName_Alt`, `SUB_DOC`
  (recorded doc #). Polygon geometry. Clip to Burr Ridge parcel envelope. (Older copy:
  `DuPage_County_IL/Subdivision_Polygons/MapServer`.)
- DuPage parcel layer `Tyler/ParcelsRealEstateCCWGS84SR4326/MapServer/0` also exposes
  `LEGALDES1–9` / `LEGALCODE1–9` (secondary subdivision/plat carrier at parcel level).
- **Cook — NO public subdivision polygon layer.** Assessor REST is token-gated (HTTP 499);
  parcels carry only a numeric `neighborhood` code. Public parcels are on the Cook Central
  hub (`hub-cookcountyil.opendata.arcgis.com`). → Cook subdivisions come from **OSM polygons
  + real-estate name lists + manual polygon drawing.**
- **OSM** has ~18 named residential/neighbourhood polygons inside the village (Fieldstone,
  Chestnut Hills, Burr Ridge Club, Carriage Way, Tartan Ridge, Ambriance, Babson Park,
  Heatherfields, Longwood, Savoy Club, Highland Fields, Chasemoor, Burr Oaks Glen…). Partial,
  unverified, but a real Cook-side asset. (One noise entry: "Legacy Usallc".)
- **Starter name list (~30, union of sources)** — seeds the reference layer + validation set:
  Ambriance (gated), Babson Park, Braemoor, Burr Oaks Glen North/South, Burr Ridge Club (HOA),
  Burr Ridge Estates, Burr Ridge Meadows, Burr Ridge Village Center (condo HOA), Cambridge
  Estates, Carriage Way (+ Club / Condominiums), Chasemoor (HOA), Chestnut Hills, Devon Ridge,
  Falling Water, Fieldstone (+ Club HOA), Forest Edge, Heatherfields, Highland Fields (HOA),
  Hinsdale Countryside Estates, Lake Ridge Club, Longwood, Madison Club, Oak Creek Club, Oak
  Ridge Creek (HOA), Savoy Club, Secret Forest, Tartan Ridge, Timberlake Estates, Woodview
  Estates.
  Sources: gogambino.com/burr-ridge-illinois-subdivisions.html; patch.com top-10; Wikipedia
  "Burr Ridge, Illinois"; homesbymarco (403 to bots, exists); OSM. **No Village HOA directory
  found.**

**Central consequence:** even the authoritative plat layer is *over-inclusive* (18k plats,
many bureaucratic). The job is filtering/confirming down to the recognized-name + signed
subset. **Cook (20% of data) needs a more manual pipeline than DuPage.**

## Output schema

`subdivisions/data/reference/subdivisions.geojson` (+ `.csv` for attributes) — one row per
subdivision: `subdivision_id, name, aliases[], county(cook|dupage|both), geometry(WGS84
polygon), geom_source(dupage_plat|osm|manual), has_recognized_name, name_evidence,
hoa(bool|unknown), has_entrance_sign(enum), sign_confidence, sign_evidence, streetview_url,
reviewed(bool), notes`.

`subdivisions/data/reference/parcel_subdivision.csv` — one row per PIN:
`county, pin_normalized, subdivision_id(nullable), match_method, match_confidence,
dist_to_boundary_ft`.

`subdivisions/data/export/sales_tagged.{parquet,csv}` = `sales` ⋈ PIN ⋈ `parcel_subdivision`
⋈ `subdivisions` (the deliverable the owner actually uses).

## Phases

### Phase 0 — Spatial backbone (low risk)
Create the `subdivisions/` package (`__init__.py`, `_paths.py`, `_geo.py`). Build a
parcel-centroid frame; do point-in-polygon and distance work in projected **EPSG:3435**
(IL-East ftUS) for robustness, store results in WGS84 (4326). Read the warehouse with
`read_only=True` (mirror `analysis/_frame.py`). geopandas/shapely are in the venv. *No gate.*

### Phase 1 — Build the candidate reference layer
- **1A DuPage (authoritative):** pull `OpenData/Subdivision/MapServer/1` via `etl/_arcgis.py`
  `query_features` (pass a `geometry_envelope` of the DuPage parcel bbox). Keep polygons that
  intersect ≥1 Burr Ridge parcel. Carry `Name`, `SubName_Alt`, `SUB_DOC`.
- **1B Cook (no county layer):** harvest OSM named residential/neighbourhood polygons via
  Overpass, clipped to the village boundary (`data/raw/burr_ridge_boundary.geojson`); seed
  from the name list. Known Cook subdivisions with no polygon → queue for manual drawing (1D).
- **1C Bottom-up name list:** assemble the ~30-name list + aliases (Firecrawl/WebSearch on the
  sources above). This is the reconciliation key and the validation set.
- **1D Reconcile + dedupe:** fuzzy-match plat/OSM polygons to the name list (alias table);
  flag name-list entries lacking a polygon for manual drawing.
- **⛔ REVIEW GATE 1:** owner eyeballs the candidate list (names / which have geometry / which
  need drawing / suspected bureaucratic plats) before classification.

### Phase 2 — Spatial assignment (parcels → subdivision)
- Point-in-polygon on parcel centroid = primary. For centroids just outside a boundary, snap
  within a small tolerance and record `dist_to_boundary_ft`.
- DuPage-only complement: **street-name → subdivision** map for small 1–2-street
  subdivisions (catches polygon misses + cross-checks).
- Resolve overlaps (parcel in >1 polygon → prefer smallest/most-specific named plat; log
  conflicts). Write `subdivisions/data/reference/parcel_subdivision.csv`. *Internal QA, no gate.*

### Phase 3 — Classify the two flags
- **`has_recognized_name`** (mostly automatable): true if the subdivision appears in the name
  list / OSM with a real marketing name, or the plat `Name` is a genuine name. Build a
  reject-regex for bureaucratic plats ("Assessor's Division", "Subdivision of part of…", pure
  section/township legals).
- **`has_entrance_sign`** (proxy + hybrid): score each named subdivision on proxies — HOA
  evidence, gated/single-entrance street geometry, OSM named-polygon presence, name
  brandedness, listing recurrence. High score → `likely`. Generate
  `subdivisions/docs/subdivision_review.md` with a derived entrance coordinate (where internal
  streets meet a collector road) + a Google Street View URL per subdivision.
- **⛔ REVIEW GATE 2 (the hybrid step):** owner confirms only the uncertain ones (Y/N);
  fold answers back into `subdivisions`.

### Phase 4 — Tag transactions
Join `sales` → `parcel_subdivision` → `subdivisions`; write
`subdivisions/data/export/sales_tagged.{parquet,csv}`; produce coverage stats (% sales/parcels
with a name; with a sign; residual unnamed, split by county).

### Phase 5 — Validation & QA
No-overlap/containment checks; spot-check ~20 parcels per match_method vs Street View / known
addresses; confirm every name-list subdivision was found or explained; sanity-check that
famous subdivisions capture sensible price tiers; honest Cook-vs-DuPage coverage note.

### Phase 6 — Deliverables
Finalize reference layer + write `subdivisions/docs/SUBDIVISIONS_METHOD.md` + findings summary.
**⛔ REVIEW GATE 3:** decide whether to promote `subdivisions` + `parcel_subdivision` into
`warehouse.duckdb` (tables/views) or leave as side files under `subdivisions/data/`.

## Risks & open decisions
- **Cook is the hard 20%** — no authoritative polygons, no addresses; OSM + manual drawing.
  Expect lower automated coverage / more Gate-2 work there. Non-named Cook parcels →
  `no_named_subdivision`.
- **"Sign" is irreducibly partial** — proxies + spot review yield confirmed/likely/unknown,
  not certainty for every entry. Hence the graded enum.
- **Listing data (Zillow/Redfin) ToS** — use only as weak corroborating signal via permitted
  search, not bulk scraping.
- **Over-inclusion of bureaucratic plats** — handled by Phase 3 reject rules; review at Gate 1.

## Effort & sequencing
Phases 0–2 mostly deterministic (~1–1.5 days build). Gates 1 + 2 need owner time (~1–2 hrs
total). Phases 4–6 ~½ day. Critical path: DuPage plat pull → assignment → classification; Cook
manual polygons run in parallel.

## How to start (for the executing session)
1. `cd` to repo root; confirm `.venv` has geopandas/shapely (`pyproject.toml` core deps).
2. Flesh out the `subdivisions/` package (`__init__.py` exists; add `_paths.py`, `_geo.py`).
3. Phase 0 → Phase 1A (pull the DuPage subdivision layer) → stop at **Gate 1** for owner review.
4. Write only under `subdivisions/`. Keep `etl/` and `data/warehouse.duckdb` untouched.
5. Run modules as `.venv/bin/python -m subdivisions.<module>` from the repo root.
6. **Network note:** Phase 1 makes live calls (DuPage ArcGIS subdivision layer + OSM Overpass)
   — ensure network access.
