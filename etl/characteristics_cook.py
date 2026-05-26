"""Pull CCAO single/multi-family + condo characteristics for Burr Ridge Cook PINs.

Verified field names (from /columns.json):
  Single/multi-family (x54s-btds): char_bldg_sf, char_yrblt, char_beds,
    char_fbath, char_hbath, char_cnst_qlty, char_type_resd
  Condo unit (3r7i-mrz4): char_building_sf, char_unit_sf, char_bedrooms,
    char_full_baths, char_half_baths
"""
import datetime as dt
import os
import sys
from sodapy import Socrata
from ._db import cursor, audit
from .normalize import normalize_pin_cook

DOMAIN = "datacatalog.cookcountyil.gov"
SFR_DATASET = "x54s-btds"
CONDO_DATASET = "3r7i-mrz4"
SOURCE_NAME = "ccao_characteristics"
START_YEAR = 2013
PAGE = 5000


def _flush(con, payload: list[tuple]) -> int:
    if not payload:
        return 0
    con.executemany(
        """
        INSERT INTO characteristics (county, pin_normalized, tax_year, building_sqft,
            year_built, bedrooms, bathrooms, construction_type, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (county, pin_normalized, tax_year) DO UPDATE SET
            building_sqft = COALESCE(EXCLUDED.building_sqft, characteristics.building_sqft),
            year_built    = COALESCE(EXCLUDED.year_built,    characteristics.year_built),
            bedrooms      = COALESCE(EXCLUDED.bedrooms,      characteristics.bedrooms),
            bathrooms     = COALESCE(EXCLUDED.bathrooms,     characteristics.bathrooms),
            construction_type = COALESCE(EXCLUDED.construction_type, characteristics.construction_type),
            source        = EXCLUDED.source
        """,
        payload,
    )
    return len(payload)


def _row_sfr(r) -> tuple | None:
    pin = normalize_pin_cook(r.get("pin"))
    try:
        year = int(r.get("year"))
    except (TypeError, ValueError):
        return None
    if not pin or year < START_YEAR:
        return None

    def _try(v, cast):
        try:
            return cast(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    sqft = _try(r.get("char_bldg_sf"), lambda x: int(float(x)))
    yb = _try(r.get("char_yrblt"), int)
    beds = _try(r.get("char_beds"), int)
    fbath = _try(r.get("char_fbath"), int) or 0
    hbath = _try(r.get("char_hbath"), int) or 0
    baths = float(fbath) + 0.5 * float(hbath) if (fbath or hbath) else None
    cnst = r.get("char_cnst_qlty") or r.get("char_type_resd")
    return ("cook", pin, year, sqft, yb, beds, baths,
            str(cnst) if cnst else None, "ccao:x54s-btds")


def _row_condo(r) -> tuple | None:
    pin = normalize_pin_cook(r.get("pin"))
    try:
        year = int(r.get("year"))
    except (TypeError, ValueError):
        return None
    if not pin or year < START_YEAR:
        return None

    def _try(v, cast):
        try:
            return cast(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    sqft = _try(r.get("char_unit_sf") or r.get("char_building_sf"), lambda x: int(float(x)))
    yb = _try(r.get("char_yrblt"), int)
    beds = _try(r.get("char_bedrooms"), int)
    fbath = _try(r.get("char_full_baths"), int) or 0
    hbath = _try(r.get("char_half_baths"), int) or 0
    baths = float(fbath) + 0.5 * float(hbath) if (fbath or hbath) else None
    return ("cook", pin, year, sqft, yb, beds, baths, "condo", "ccao:3r7i-mrz4")


def load(app_token: str | None = None) -> int:
    app_token = app_token or os.environ.get("SOCRATA_APP_TOKEN")
    client = Socrata(DOMAIN, app_token, timeout=120)

    with cursor() as con:
        pins = [r[0] for r in con.execute(
            "SELECT DISTINCT pin_normalized FROM parcels WHERE county='cook' AND valid_to IS NULL"
        ).fetchall()]
        if not pins:
            print("No Cook parcels — run parcels_cook first")
            return 0

        token_status = "with token" if app_token else "ANONYMOUS (slow)"
        total = 0
        for dataset, row_fn in ((SFR_DATASET, _row_sfr), (CONDO_DATASET, _row_condo)):
            print(f"\nDataset {dataset} for {len(pins):,} PINs since {START_YEAR} ({token_status})", flush=True)
            for batch_start in range(0, len(pins), 200):
                batch = pins[batch_start:batch_start + 200]
                where = f"pin in ({','.join(repr(p) for p in batch)}) AND year >= {START_YEAR}"
                offset = 0
                batch_inserted = 0
                while True:
                    rows = client.get(dataset, where=where, limit=PAGE, offset=offset)
                    if not rows:
                        break
                    payload = [t for t in (row_fn(r) for r in rows) if t]
                    batch_inserted += _flush(con, payload)
                    if len(rows) < PAGE:
                        break
                    offset += PAGE
                total += batch_inserted
                print(f"  PIN batch {batch_start // 200 + 1:>2d}/{(len(pins) + 199) // 200}: "
                      f"+{batch_inserted:>4d} (cumulative {total:,})", flush=True)

        audit(con, SOURCE_NAME, f"https://{DOMAIN}/resource/", total, "SFR + condo characteristics")

    print(f"\nLoaded {total:,} characteristics rows total", flush=True)
    return total


if __name__ == "__main__":
    sys.exit(0 if load() else 1)
