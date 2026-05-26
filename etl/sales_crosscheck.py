"""Cross-validate Cook CCAO sales against MyDec for Cook county.

Filters MyDec server-side by an IN list of the 1,468 Burr Ridge Cook PINs
(formatted as MyDec's dashed 14-digit form), batched to keep WHERE clauses
under the Socrata length limit. Completes in seconds, not hours, with no
app token required.
"""
import datetime as dt
import os
import sys
from sodapy import Socrata
from ._db import cursor, audit
from .normalize import normalize_pin_cook, format_pin_cook_dashed
from .sales_dupage import DOMAIN, DATASET_ID, SOURCE_URL, START_DATE

SOURCE_NAME = "mydec_cook_crosscheck"
COUNTY_NAME = "Cook"
PIN_BATCH = 100   # ~100 dashed PINs per WHERE keeps URL well under 8KB
PAGE = 5000


def _flush(con, batch: list[tuple]) -> None:
    if not batch:
        return
    con.executemany(
        """
        INSERT INTO sales_crosscheck (county, pin_normalized, sale_date,
            ccao_price, mydec_price, price_delta, matched, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (county, pin_normalized, sale_date) DO UPDATE SET
            ccao_price = EXCLUDED.ccao_price,
            mydec_price = EXCLUDED.mydec_price,
            price_delta = EXCLUDED.price_delta,
            matched = EXCLUDED.matched,
            notes = EXCLUDED.notes
        """,
        batch,
    )


def load(app_token: str | None = None, since: str | None = None) -> int:
    app_token = app_token or os.environ.get("SOCRATA_APP_TOKEN")
    client = Socrata(DOMAIN, app_token, timeout=120)
    since = since or START_DATE

    with cursor() as con:
        cook_pins = sorted({r[0] for r in con.execute(
            "SELECT DISTINCT pin_normalized FROM parcels WHERE county='cook' AND valid_to IS NULL"
        ).fetchall()})
        if not cook_pins:
            print("No Cook parcels — run parcels_cook first")
            return 0

        ccao_index = {}
        for pin, sd, price in con.execute("""
            SELECT pin_normalized, sale_date, sale_price
            FROM sales WHERE county='cook' AND source='ccao'
        """).fetchall():
            ccao_index[(pin, sd)] = float(price) if price is not None else None

        # Wipe partial crosscheck from earlier full-county scan (different
        # query strategy; cleaner to start fresh).
        con.execute("DELETE FROM sales_crosscheck WHERE county='cook'")

        token_status = "with token" if app_token else "anonymous"
        n_batches = (len(cook_pins) + PIN_BATCH - 1) // PIN_BATCH
        print(f"Crosschecking {len(cook_pins):,} Cook PINs against MyDec since {since} "
              f"({n_batches} batches, {token_status})", flush=True)

        total_inserted = 0
        for i, batch_start in enumerate(range(0, len(cook_pins), PIN_BATCH), 1):
            batch_pins = cook_pins[batch_start:batch_start + PIN_BATCH]
            dashed = [format_pin_cook_dashed(p) for p in batch_pins]
            in_clause = ",".join(f"'{d}'" for d in dashed)
            where = (f"line_1_county = '{COUNTY_NAME}' "
                     f"AND line_4_instrument_date >= '{since}' "
                     f"AND line_1_primary_pin in ({in_clause})")
            offset = 0
            cross_rows = []
            while True:
                rows = client.get(
                    DATASET_ID, where=where, limit=PAGE, offset=offset,
                    order="line_4_instrument_date",
                )
                if not rows:
                    break
                for r in rows:
                    pin = normalize_pin_cook(r.get("line_1_primary_pin"))
                    sd = (r.get("line_4_instrument_date") or "")[:10]
                    if not pin or not sd:
                        continue
                    try:
                        mydec_price = float(r["line_11_full_consideration"])
                    except (TypeError, ValueError, KeyError):
                        mydec_price = None
                    ccao_price = ccao_index.get((pin, dt.date.fromisoformat(sd)))
                    matched = ccao_price is not None
                    delta = abs(ccao_price - mydec_price) if (ccao_price is not None and mydec_price is not None) else None
                    cross_rows.append((
                        "cook", pin, sd, ccao_price, mydec_price, delta, matched,
                        None if matched else "no CCAO row at (pin, sale_date)",
                    ))
                if len(rows) < PAGE:
                    break
                offset += PAGE
            _flush(con, cross_rows)
            total_inserted += len(cross_rows)
            print(f"  batch {i:>3d}/{n_batches}: +{len(cross_rows):>4d}  "
                  f"(cumulative {total_inserted:,})", flush=True)

        audit(con, SOURCE_NAME, SOURCE_URL, total_inserted,
              f"PIN-list query; {len(cook_pins)} Cook Burr Ridge PINs since {since}")

        matched_n = con.execute(
            "SELECT count(*) FROM sales_crosscheck WHERE county='cook' AND matched"
        ).fetchone()[0]

    pct = matched_n / max(total_inserted, 1) * 100
    print(f"\nCross-check done: {total_inserted:,} MyDec Cook rows; {matched_n:,} matched a CCAO row ({pct:.1f}%)", flush=True)
    return total_inserted


if __name__ == "__main__":
    sys.exit(0 if load() else 1)
