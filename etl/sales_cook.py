"""Pull CCAO Parcel Sales (wvhk-k5uv) for Burr Ridge Cook PINs, write to `sales`.

CCAO Socrata API: https://datacatalog.cookcountyil.gov/resource/wvhk-k5uv.json
Field reference: https://datacatalog.cookcountyil.gov/Property-Taxation/Assessor-Parcel-Sales/wvhk-k5uv
"""
import datetime as dt
import json
from sodapy import Socrata
from ._db import cursor, audit
from .normalize import (
    normalize_pin_cook, normalize_deed_type, is_arms_length,
)

DOMAIN = "datacatalog.cookcountyil.gov"
DATASET_ID = "wvhk-k5uv"
SOURCE_URL = f"https://{DOMAIN}/resource/{DATASET_ID}.json"
SOURCE_NAME = "ccao_parcel_sales"
START_DATE = "2013-01-01"
PAGE = 5000


def _burr_ridge_cook_pins(con) -> list[str]:
    rows = con.execute(
        "SELECT DISTINCT pin_normalized FROM parcels WHERE county='cook' AND valid_to IS NULL"
    ).fetchall()
    return [r[0] for r in rows]


def _filter_flag_keys(row: dict) -> list[str]:
    return [k for k in row.keys() if k.startswith("sale_filter_") and str(row.get(k)).lower() in ("true", "1", "yes")]


def load(app_token: str | None = None, since: str | None = None) -> int:
    import os
    app_token = app_token or os.environ.get("SOCRATA_APP_TOKEN")
    client = Socrata(DOMAIN, app_token, timeout=120)

    with cursor() as con:
        pins = _burr_ridge_cook_pins(con)
        if not pins:
            print("No Cook parcels in warehouse — run parcels_cook first")
            return 0
        print(f"Pulling CCAO sales for {len(pins)} Cook PINs since {since or START_DATE}")

        inserted = 0
        for batch_start in range(0, len(pins), 200):
            batch = pins[batch_start:batch_start + 200]
            in_clause = ",".join(f"'{p}'" for p in batch)
            where = f"pin in ({in_clause}) AND sale_date >= '{since or START_DATE}'"
            offset = 0
            while True:
                rows = client.get(DATASET_ID, where=where, limit=PAGE, offset=offset)
                if not rows:
                    break
                inserted += _insert(con, rows)
                if len(rows) < PAGE:
                    break
                offset += PAGE
            print(f"  PIN batch {batch_start // 200 + 1}: cumulative inserted = {inserted}")

        audit(con, SOURCE_NAME, SOURCE_URL, inserted, f"since={since or START_DATE}")

    print(f"Loaded {inserted} Cook sales rows")
    return inserted


def _insert(con, rows: list[dict]) -> int:
    payload = []
    for r in rows:
        pin = normalize_pin_cook(r.get("pin"))
        if not pin:
            continue
        sale_date = (r.get("sale_date") or "")[:10]
        if not sale_date:
            continue
        try:
            price = float(r.get("sale_price")) if r.get("sale_price") else None
        except (TypeError, ValueError):
            price = None
        deed = normalize_deed_type(r.get("deed_type"))
        flags = _filter_flag_keys(r)
        arms_length = is_arms_length(deed, price, has_filter_flags=bool(flags))
        doc_num = r.get("sale_document_num") or r.get("doc_no") or f"CCAO-{pin}-{sale_date}"
        payload.append((
            "cook", pin, sale_date, price,
            doc_num, deed, arms_length,
            json.dumps(flags), "ccao", SOURCE_URL,
            dt.datetime.utcnow(), None,
        ))
    if not payload:
        return 0
    con.executemany(
        """
        INSERT INTO sales (county, pin_normalized, sale_date, sale_price,
            document_number, deed_type, is_arms_length, filter_flags, source,
            source_url, extracted_at, confidence_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (county, source, document_number, pin_normalized, sale_date) DO NOTHING
        """,
        payload,
    )
    return len(payload)


if __name__ == "__main__":
    load()
