"""Pull Illinois MyDec PTAX-203 transfer declarations for the DuPage portion of Burr Ridge.

Source: Socrata dataset `it54-y4c6` on illinois-edp.data.socrata.com
Public, no authentication required.

Field reference (verified against /columns.json on first deploy):
    pin             -> line_1_primary_pin   (e.g. "06-10-202-009")
    county          -> line_1_county        (text, e.g. "DuPage")
    sale_date       -> line_4_instrument_date
    recording_date  -> date_recorded
    sale_price      -> line_11_full_consideration
    doc_number      -> document_number
    deed_type       -> line_5_instrument_type   (e.g. "Warranty Deed")
    exemption       -> state_exemption / line_16_state_exemption
    address         -> full_address / line_1_street / line_1_city
"""
import datetime as dt
import json
from sodapy import Socrata
from ._db import cursor, audit
from .normalize import normalize_pin_dupage, normalize_deed_type, is_arms_length

DOMAIN = "illinois-edp.data.socrata.com"
DATASET_ID = "it54-y4c6"
SOURCE_URL = f"https://{DOMAIN}/resource/{DATASET_ID}.json"
SOURCE_NAME = "mydec_dupage"
COUNTY_NAME = "DuPage"
START_DATE = "2013-01-01"
PAGE = 5000


def _burr_ridge_pins(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT pin_normalized FROM parcels WHERE county='dupage' AND valid_to IS NULL"
    ).fetchall()]


def load(app_token: str | None = None, since: str | None = None) -> int:
    import os
    app_token = app_token or os.environ.get("SOCRATA_APP_TOKEN")
    client = Socrata(DOMAIN, app_token, timeout=120)
    since = since or START_DATE

    with cursor() as con:
        target = set(_burr_ridge_pins(con))
        if not target:
            print("No DuPage parcels in warehouse — run parcels_dupage first")
            return 0
        print(f"Pulling MyDec for DuPage county since {since}; "
              f"{len(target):,} Burr Ridge PINs to match")

        # MyDec stores PINs with dashes; we filter by county server-side then
        # match PIN client-side (server-side IN with thousands of items would be huge).
        where = f"line_1_county = '{COUNTY_NAME}' AND line_4_instrument_date >= '{since}'"
        offset = 0
        inserted = 0
        scanned = 0
        while True:
            rows = client.get(
                DATASET_ID,
                where=where,
                limit=PAGE,
                offset=offset,
                order="line_4_instrument_date",
            )
            if not rows:
                break
            scanned += len(rows)
            inserted += _insert(con, rows, target)
            if scanned % 25_000 < PAGE:
                print(f"  scanned {scanned:,} DuPage MyDec rows; matched {inserted:,}")
            if len(rows) < PAGE:
                break
            offset += PAGE

        audit(con, SOURCE_NAME, SOURCE_URL, inserted,
              f"DuPage Burr Ridge since {since}; scanned={scanned}")

    print(f"Loaded {inserted} DuPage MyDec sales (from {scanned:,} county rows)")
    return inserted


def _insert(con, rows: list[dict], target_pins: set[str]) -> int:
    payload = []
    for r in rows:
        pin_raw = r.get("line_1_primary_pin")
        pin = normalize_pin_dupage(pin_raw)
        if not pin or pin not in target_pins:
            continue

        sale_date = (r.get("line_4_instrument_date") or "")[:10]
        if not sale_date:
            continue

        try:
            price = float(r["line_11_full_consideration"])
        except (TypeError, ValueError, KeyError):
            price = None

        deed = normalize_deed_type(r.get("line_5_instrument_type"))
        exemption = r.get("state_exemption") or r.get("line_16_state_exemption")
        flags = []
        if exemption and str(exemption).strip().lower() not in ("", "none", "no exemption", "0"):
            flags.append(f"exemption:{exemption}")

        # Pull arm's-length filter signals from line_10* checkboxes
        if r.get("line_10b_sale_between_related"):
            flags.append("related_party")
        if r.get("line_10c_transfer_of_100"):
            flags.append("partial_interest")
        if r.get("line_10d_court_ordered_sale"):
            flags.append("court_ordered")
        if r.get("line_10e_sale_in_lieu_of") or r.get("line_10g_short_sale") or r.get("line_10h_bank_reo"):
            flags.append("foreclosure_related")
        if r.get("line_10i_auction_sale"):
            flags.append("auction")

        arms_length = is_arms_length(
            deed, price,
            has_filter_flags=bool(flags),
            mydec_exemption_code=str(exemption) if exemption else None,
        )

        doc_num = r.get("document_number") or f"DECL-{r.get('declaration_id')}"
        payload.append((
            "dupage", pin, sale_date, price,
            doc_num, deed, arms_length,
            json.dumps(flags), "mydec", SOURCE_URL,
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
