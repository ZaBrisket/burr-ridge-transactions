"""Load DuPage residential characteristics + assessments + tax + last-sale-fallback
from the Downers Grove Township annual Excel export.

Source: https://www.dgtownship.com/assessor/  ("Residential Export" link)
Direct URL pattern: https://www.dgtownship.com/docs/ao/downloads/Residential_Export_<YYYY-MM-DD>.xlsx

Verified columns (2025 vintage):
    ParcelNumber, NBHD Code, Property Address,
    Land AV, Building AV, Total AV, Tax Rate, Tax Amount,
    Last Sale Date, Last Sale Amount,
    Total Living Area SF, Class/Grade, Exterior, Stories/Style,
    Full Bath, Half Bath, Fixtures, Basement, Basement SF,
    Year Built, Garage SF, Lot SF, Fireplaces, AC
"""
import datetime as dt
import json
import os
import re
from pathlib import Path
import pandas as pd
from ._db import cursor, audit
from ._http import get
from ._paths import RAW
from .normalize import (
    normalize_pin_dupage, normalize_deed_type, is_arms_length,
)

DG_LANDING = "https://www.dgtownship.com/assessor/"
SOURCE_NAME = "dg_township_excel"
DOWNLOAD_PREFIX = "https://www.dgtownship.com/docs/ao/downloads/"


def _discover_latest_url() -> str | None:
    """Scrape the dgtownship landing page for the current Residential_Export URL."""
    try:
        r = get(DG_LANDING, timeout=60, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36",
        })
    except Exception as e:
        print(f"  failed to fetch landing page: {e}")
        return None
    m = re.search(
        r'href="(https?://www\.dgtownship\.com/docs/ao/downloads/Residential_Export_\d{4}-\d{2}-\d{2}\.xlsx)"',
        r.text,
    )
    return m.group(1) if m else None


def _ensure_excel(local_path: Path | None = None) -> Path:
    if local_path and local_path.exists():
        return local_path
    candidates = sorted(RAW.glob("dg_township_*.xlsx")) + sorted(RAW.glob("Residential_Export_*.xlsx"))
    if candidates:
        return candidates[-1]
    url = _discover_latest_url()
    if not url:
        raise RuntimeError(
            f"Could not auto-discover Residential Export URL. "
            f"Manually download from {DG_LANDING} into {RAW}/dg_township_<year>.xlsx"
        )
    print(f"  fetching {url}")
    r = get(url, timeout=300, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36",
    })
    out = RAW / Path(url).name
    out.write_bytes(r.content)
    print(f"  saved → {out} ({len(r.content):,} bytes)")
    return out


def _vintage(path: Path) -> int:
    m = re.search(r"(20\d{2})", path.name)
    return int(m.group(1)) if m else dt.date.today().year


def _all_dg_excels() -> list[Path]:
    """Pick up every Residential / Apartment / Commercial / Condo export sitting in raw/."""
    out = []
    for pat in ("Residential_Export_*.xlsx", "Apartment_Export_*.xlsx",
                "Commercial_Export_*.xlsx", "Condo_Export_*.xlsx",
                "dg_*_2*.xlsx"):
        out.extend(sorted(RAW.glob(pat)))
    seen, unique = set(), []
    for p in out:
        if p.name not in seen:
            seen.add(p.name)
            unique.append(p)
    return unique


def load(excel_path: str | None = None) -> int:
    if excel_path:
        paths = [Path(excel_path)]
    else:
        paths = _all_dg_excels()
        if not paths:
            paths = [_ensure_excel()]
    print(f"Loading {len(paths)} DG Township export(s): {[p.name for p in paths]}", flush=True)

    df_list = []
    for p in paths:
        d = pd.read_excel(p, sheet_name=0)
        d["_source_file"] = p.name
        df_list.append(d)
    df = pd.concat(df_list, ignore_index=True)
    vintage = max(_vintage(p) for p in paths)
    path = paths[0]
    print(f"  combined rows: {len(df):,}  vintage: {vintage}")

    with cursor() as con:
        target = {r[0] for r in con.execute(
            "SELECT pin_normalized FROM parcels WHERE county='dupage' AND valid_to IS NULL"
        ).fetchall()}

        df["_pin_norm"] = df["ParcelNumber"].astype(str).apply(normalize_pin_dupage)
        scoped = df[df["_pin_norm"].isin(target)].copy()
        print(f"  Burr Ridge DuPage matches: {len(scoped):,}")

        char_payload, assess_payload, sale_payload = [], [], []
        for _, r in scoped.iterrows():
            pin = r["_pin_norm"]

            def _i(col):
                v = r.get(col)
                if pd.isna(v):
                    return None
                try:
                    return int(float(v))
                except (TypeError, ValueError):
                    return None

            def _f(col):
                v = r.get(col)
                if pd.isna(v):
                    return None
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            full_baths = _i("Full Bath") or 0
            half_baths = _i("Half Bath") or 0
            baths = full_baths + 0.5 * half_baths if (full_baths or half_baths) else None
            sqft = _i("Total Living Area SF") or _i("Building SF")
            beds = _i("Bedrooms")  # only condos provide this column
            construction = (
                str(r.get("Stories/Style") or "")
                or str(r.get("Model") or "")
                or str(r.get("Stories") or "")
            ).strip() or None

            char_payload.append((
                "dupage", pin, vintage,
                sqft,
                _i("Year Built"),
                beds,
                baths,
                construction,
                f"dg_township:{r.get('_source_file','?')}",
            ))

            tot_av = _f("Total AV")
            if tot_av is not None:
                assess_payload.append(("dupage", pin, vintage, tot_av, None, f"dg_township:{path.name}"))

            # Capture last-known sale per parcel as a backstop / supplement to MyDec
            sale_date = r.get("Last Sale Date")
            sale_amount = _f("Last Sale Amount")
            if pd.notna(sale_date) and sale_amount and sale_amount >= 1000:
                sd_str = pd.Timestamp(sale_date).date().isoformat()
                if sd_str >= "2013-01-01":
                    deed = "warranty"  # township only records assumed-arms-length sales here
                    sale_payload.append((
                        "dupage", pin, sd_str, sale_amount,
                        f"DGT-{pin}-{sd_str}", deed, True, json.dumps([]),
                        "dg_township", path.name,
                        dt.datetime.utcnow(), None,
                    ))

        if char_payload:
            con.executemany(
                """
                INSERT INTO characteristics (county, pin_normalized, tax_year, building_sqft,
                    year_built, bedrooms, bathrooms, construction_type, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (county, pin_normalized, tax_year) DO UPDATE SET
                    building_sqft = COALESCE(EXCLUDED.building_sqft, characteristics.building_sqft),
                    year_built    = COALESCE(EXCLUDED.year_built,    characteristics.year_built),
                    bathrooms     = COALESCE(EXCLUDED.bathrooms,     characteristics.bathrooms),
                    construction_type = COALESCE(EXCLUDED.construction_type, characteristics.construction_type),
                    source        = EXCLUDED.source
                """,
                char_payload,
            )
        if assess_payload:
            con.executemany(
                """
                INSERT INTO assessments (county, pin_normalized, tax_year, assessed_value, equalized_av, source)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (county, pin_normalized, tax_year) DO UPDATE SET
                    assessed_value = COALESCE(EXCLUDED.assessed_value, assessments.assessed_value),
                    source         = EXCLUDED.source
                """,
                assess_payload,
            )
        if sale_payload:
            con.executemany(
                """
                INSERT INTO sales (county, pin_normalized, sale_date, sale_price,
                    document_number, deed_type, is_arms_length, filter_flags, source,
                    source_url, extracted_at, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (county, source, document_number, pin_normalized, sale_date) DO NOTHING
                """,
                sale_payload,
            )
        audit(con, SOURCE_NAME, DG_LANDING, len(char_payload),
              f"vintage={vintage}; assessments={len(assess_payload)}; backstop_sales={len(sale_payload)}")

    print(f"Loaded {len(char_payload):,} characteristics, "
          f"{len(assess_payload):,} assessments, "
          f"{len(sale_payload):,} backstop sales from DG Township", flush=True)
    return len(char_payload)


if __name__ == "__main__":
    load()
