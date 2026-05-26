"""Pull CCAO Historic Assessed Values (uzyt-m557) for Burr Ridge Cook PINs.

Verified fields: pin, year, mailed_tot, certified_tot, board_tot.
We persist `certified_tot` as assessed_value (post-Assessor + Board of Review).
EAV is computed downstream via state multiplier; not stored here.
"""
import os
import sys
from sodapy import Socrata
from ._db import cursor, audit
from .normalize import normalize_pin_cook

DOMAIN = "datacatalog.cookcountyil.gov"
DATASET_ID = "uzyt-m557"
SOURCE_URL = f"https://{DOMAIN}/resource/{DATASET_ID}.json"
SOURCE_NAME = "ccao_historic_av"
START_YEAR = 2013
PAGE = 5000


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
        print(f"Pulling CCAO assessed values for {len(pins):,} PINs since {START_YEAR} ({token_status})", flush=True)

        inserted = 0
        for batch_start in range(0, len(pins), 200):
            batch = pins[batch_start:batch_start + 200]
            where = f"pin in ({','.join(repr(p) for p in batch)}) AND year >= {START_YEAR}"
            offset = 0
            batch_inserted = 0
            while True:
                rows = client.get(DATASET_ID, where=where, limit=PAGE, offset=offset)
                if not rows:
                    break
                batch_inserted += _insert(con, rows)
                if len(rows) < PAGE:
                    break
                offset += PAGE
            inserted += batch_inserted
            print(f"  PIN batch {batch_start // 200 + 1:>2d}/{(len(pins) + 199) // 200}: "
                  f"+{batch_inserted:>4d} (cumulative {inserted:,})", flush=True)

        audit(con, SOURCE_NAME, SOURCE_URL, inserted, f"since={START_YEAR}")

    print(f"\nLoaded {inserted:,} Cook assessment rows", flush=True)
    return inserted


def _insert(con, rows: list[dict]) -> int:
    payload = []
    for r in rows:
        pin = normalize_pin_cook(r.get("pin"))
        try:
            year = int(r.get("year"))
        except (TypeError, ValueError):
            continue
        if not pin or year < START_YEAR:
            continue
        try:
            av = float(r.get("certified_tot")) if r.get("certified_tot") else None
        except (TypeError, ValueError):
            av = None
        if av is None:
            try:
                av = float(r.get("mailed_tot")) if r.get("mailed_tot") else None
            except (TypeError, ValueError):
                av = None
        payload.append(("cook", pin, year, av, None, "ccao:uzyt-m557"))
    if not payload:
        return 0
    con.executemany(
        """
        INSERT INTO assessments (county, pin_normalized, tax_year, assessed_value, equalized_av, source)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (county, pin_normalized, tax_year) DO UPDATE SET
            assessed_value = COALESCE(EXCLUDED.assessed_value, assessments.assessed_value),
            source         = EXCLUDED.source
        """,
        payload,
    )
    return len(payload)


if __name__ == "__main__":
    sys.exit(0 if load() else 1)
