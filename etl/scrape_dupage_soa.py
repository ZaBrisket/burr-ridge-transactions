"""Polite per-PIN scraper for DuPage Supervisor of Assessments Property Lookup.

Fills three gaps that bulk sources miss:
  - conveyance      → pre-MyDec sales (pre-2015) and additional DuPage transfers
  - values_hist     → multi-year DuPage assessed-value series
  - tax_collection  → multi-year DuPage tax-bill paid history

ONE polite session per PIN, three GETs, ~3 sec per PIN at 1 req/sec.
Resume-safe: skips PINs already in `dupage_soa_scraped` audit.

Run via:  .venv/bin/python -u -m etl.scrape_dupage_soa
"""
import datetime as dt
import json
import os
import re
import sys
import time
import requests
from bs4 import BeautifulSoup
from ._db import cursor, audit
from .normalize import normalize_pin_dupage, normalize_deed_type, is_arms_length

BASE = "https://propertylookup.dupagecounty.gov/datalets/datalet.aspx"
LANDING = "https://propertylookup.dupagecounty.gov/forms/htmlframe.aspx?mode=content/home.htm"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
RATE_DELAY_S = 1.0
SOURCE_NAME = "dupage_soa_scrape"


# ---------- table-extract helpers ----------

def _kv_pairs(soup) -> list[tuple[str, str]]:
    """Pull (label, value) pairs from any 2-col table."""
    out = []
    for tbl in soup.find_all("table"):
        for tr in tbl.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in tr.find_all("td")]
            if len(cells) == 2 and cells[0].endswith(":"):
                out.append((cells[0].rstrip(":").strip(), cells[1].strip()))
    return out


def _data_rows(soup, header_keywords: list[str]) -> list[list[str]]:
    """Find tables whose header row contains all the keywords; return body rows."""
    out = []
    for tbl in soup.find_all("table"):
        rows = tbl.find_all("tr")
        if not rows:
            continue
        header_cells = [h.get_text(" ", strip=True) for h in rows[0].find_all(["th", "td"])]
        htxt = " ".join(header_cells).lower()
        if all(k.lower() in htxt for k in header_keywords):
            for r in rows[1:]:
                cells = [c.get_text(" ", strip=True) for c in r.find_all(["td", "th"])]
                if cells and any(c for c in cells):
                    out.append(cells)
    return out


def _money(s: str) -> float | None:
    if s is None:
        return None
    s = re.sub(r"[\$,]", "", str(s)).strip()
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _date(s: str) -> str | None:
    if not s:
        return None
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(s))
    if not m:
        return None
    mo, d, y = (int(x) for x in m.groups())
    return f"{y:04d}-{mo:02d}-{d:02d}"


# ---------- fetch ----------

def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get(LANDING, timeout=60)
    return s


def _fetch(session, mode: str, pin: str) -> BeautifulSoup | None:
    url = f"{BASE}?mode={mode}&UseSearch=no&pin={pin}"
    try:
        r = session.get(url, timeout=60)
        if r.status_code != 200:
            return None
        return BeautifulSoup(r.text, "html.parser")
    except requests.RequestException:
        return None


# ---------- parse ----------

def parse_conveyance(soup) -> list[dict]:
    """Each conveyance is a sequence of kv pairs in the document order.
    Detect record boundaries by occurrences of 'Primary Parcel:'."""
    if not soup:
        return []
    pairs = _kv_pairs(soup)
    records = []
    cur: dict[str, str] = {}
    for k, v in pairs:
        if k.lower() == "primary parcel" and cur:
            records.append(cur)
            cur = {}
        cur[k] = v
    if cur:
        records.append(cur)

    out = []
    seen_keys = set()
    for r in records:
        recorded = _date(r.get("Recorded Date", ""))
        instr_no = r.get("Instrument #", "").strip()
        cons = _money(r.get("Full Actual Consideration $", "")) or _money(r.get("Net Consideration for RP", ""))
        instr_type = r.get("Instrument Type", "")
        if not recorded or not instr_no:
            continue
        key = (recorded, instr_no)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append({
            "recorded": recorded,
            "instr_no": instr_no,
            "instr_type": instr_type,
            "consideration": cons,
            "exempt": (r.get("Transfer Exempt Indicator", "") or "").strip(),
            "short_sale": r.get("Short Sale", "") == "Y",
            "bank_reo": r.get("Bank REO", "") == "Y",
            "court_ordered": r.get("Court-Ordered Sale", "") == "Y",
            "related": r.get("Sale Between Rel Ind or Corp Affil", "") == "Y",
            "auction": r.get("Auction Sale", "") == "Y",
            "total_av": _money(r.get("Total Assessed Value", "")),
            "year_prior": r.get("Year Prior to Sale", ""),
        })
    return out


def parse_values_hist(soup) -> list[dict]:
    """Find the AV history table by its column headers."""
    if not soup:
        return []
    rows = _data_rows(soup, ["Asmt Year", "Total AV"])
    out = []
    seen = set()
    for r in rows:
        if len(r) < 6:
            continue
        try:
            year = int(re.match(r"(\d{4})", r[0]).group(1))
        except (AttributeError, ValueError):
            continue
        if year in seen or year < 2013:
            continue
        seen.add(year)
        out.append({
            "year": year,
            "land_av": _money(r[3]),
            "bldg_av": _money(r[4]),
            "total_av": _money(r[5]),
            "eav":     _money(r[6]) if len(r) > 6 else None,
        })
    return out


def parse_tax_history(soup) -> list[dict]:
    """The lower 'Year | Tax | Interest | Penalty | Cost | Total | Date Paid | Pay Type' table."""
    if not soup:
        return []
    rows = _data_rows(soup, ["Year", "Tax", "Total", "Date Paid"])
    out = []
    seen = set()
    for r in rows:
        if len(r) < 7:
            continue
        try:
            year = int(re.match(r"(\d{4})", r[0]).group(1))
        except (AttributeError, ValueError):
            continue
        if year in seen or year < 2013:
            continue
        seen.add(year)
        out.append({
            "year": year,
            "tax":     _money(r[1]),
            "total":   _money(r[5]),
            "paid":    _date(r[6]),
        })
    return out


# ---------- write ----------

def _write_conveyances(con, pin: str, records: list[dict]) -> int:
    if not records:
        return 0
    payload = []
    for r in records:
        if r["consideration"] is None or r["consideration"] < 1000:
            continue
        deed = normalize_deed_type(r["instr_type"])
        flags = []
        if r["short_sale"]: flags.append("short_sale")
        if r["bank_reo"]: flags.append("bank_reo")
        if r["court_ordered"]: flags.append("court_ordered")
        if r["related"]: flags.append("related_party")
        if r["auction"]: flags.append("auction")
        if r["exempt"]: flags.append(f"exempt:{r['exempt']}")
        arms = is_arms_length(deed, r["consideration"], has_filter_flags=bool(flags),
                              mydec_exemption_code=r["exempt"] or None)
        payload.append((
            "dupage", pin, r["recorded"], r["consideration"],
            f"DPSOA-{r['instr_no']}", deed, arms,
            json.dumps(flags), "dupage_soa", BASE,
            dt.datetime.now(dt.UTC).replace(tzinfo=None), None,
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


def _write_values(con, pin: str, records: list[dict]) -> int:
    if not records:
        return 0
    payload = [
        ("dupage", pin, r["year"], r["total_av"], r["eav"], "dupage_soa:values_hist")
        for r in records if r["total_av"] is not None
    ]
    if not payload:
        return 0
    con.executemany(
        """
        INSERT INTO assessments (county, pin_normalized, tax_year, assessed_value, equalized_av, source)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (county, pin_normalized, tax_year) DO UPDATE SET
            assessed_value = COALESCE(EXCLUDED.assessed_value, assessments.assessed_value),
            equalized_av   = COALESCE(EXCLUDED.equalized_av,   assessments.equalized_av),
            source         = EXCLUDED.source
        """,
        payload,
    )
    return len(payload)


def _ensure_tax_table(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS tax_bills (
            county          TEXT NOT NULL,
            pin_normalized  TEXT NOT NULL,
            tax_year        INTEGER NOT NULL,
            tax_billed      DOUBLE,
            tax_total       DOUBLE,
            paid_date       DATE,
            source          TEXT,
            PRIMARY KEY (county, pin_normalized, tax_year)
        )
    """)


def _write_taxes(con, pin: str, records: list[dict]) -> int:
    if not records:
        return 0
    _ensure_tax_table(con)
    payload = [
        ("dupage", pin, r["year"], r["tax"], r["total"], r["paid"], "dupage_soa:tax_collection")
        for r in records
    ]
    con.executemany(
        """
        INSERT INTO tax_bills (county, pin_normalized, tax_year, tax_billed, tax_total, paid_date, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (county, pin_normalized, tax_year) DO UPDATE SET
            tax_billed = COALESCE(EXCLUDED.tax_billed, tax_bills.tax_billed),
            tax_total  = COALESCE(EXCLUDED.tax_total,  tax_bills.tax_total),
            paid_date  = COALESCE(EXCLUDED.paid_date,  tax_bills.paid_date),
            source     = EXCLUDED.source
        """,
        payload,
    )
    return len(payload)


# ---------- driver ----------

def _ensure_audit_table(con) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS dupage_soa_scraped (
            pin_normalized TEXT PRIMARY KEY,
            scraped_at     TIMESTAMP NOT NULL,
            n_conv         INTEGER,
            n_values       INTEGER,
            n_taxes        INTEGER
        )
    """)


def load(limit: int | None = None, only_missing_chars: bool = False) -> int:
    with cursor() as con:
        _ensure_audit_table(con)
        _ensure_tax_table(con)

        if only_missing_chars:
            sql = """
                SELECT p.pin_normalized FROM parcels p
                LEFT JOIN characteristics c ON p.county=c.county AND p.pin_normalized=c.pin_normalized
                WHERE p.county='dupage' AND p.valid_to IS NULL AND c.pin_normalized IS NULL
                ORDER BY p.pin_normalized
            """
        else:
            sql = """
                SELECT pin_normalized FROM parcels
                WHERE county='dupage' AND valid_to IS NULL
                ORDER BY pin_normalized
            """
        all_pins = [r[0] for r in con.execute(sql).fetchall()]
        already = {r[0] for r in con.execute("SELECT pin_normalized FROM dupage_soa_scraped").fetchall()}
        todo = [p for p in all_pins if p not in already]
        if limit:
            todo = todo[:limit]
        print(f"DuPage SOA scrape: {len(all_pins):,} target PINs, "
              f"{len(already):,} already done → {len(todo):,} to fetch", flush=True)
        if not todo:
            return 0

    session = _make_session()
    t0 = time.time()
    total_conv = total_val = total_tax = 0

    for i, pin in enumerate(todo, 1):
        if i > 1:
            time.sleep(RATE_DELAY_S)
        try:
            sc = _fetch(session, "conveyance", pin)
            time.sleep(0.4)
            sv = _fetch(session, "values_hist", pin)
            time.sleep(0.4)
            st = _fetch(session, "tax_collection", pin)
        except Exception as e:
            print(f"  [{i}/{len(todo)}] PIN {pin}: fetch error {e}", flush=True)
            continue

        conv = parse_conveyance(sc)
        vals = parse_values_hist(sv)
        taxes = parse_tax_history(st)

        with cursor() as con:
            n1 = _write_conveyances(con, pin, conv)
            n2 = _write_values(con, pin, vals)
            n3 = _write_taxes(con, pin, taxes)
            con.execute(
                "INSERT OR REPLACE INTO dupage_soa_scraped VALUES (?, ?, ?, ?, ?)",
                [pin, dt.datetime.now(dt.UTC).replace(tzinfo=None), n1, n2, n3],
            )
        total_conv += n1
        total_val += n2
        total_tax += n3

        if i % 25 == 0 or i == len(todo):
            elapsed = time.time() - t0
            rate = i / elapsed
            eta_min = (len(todo) - i) / rate / 60
            print(f"  [{i:>4d}/{len(todo)}] +sales={total_conv:>4d} +av={total_val:>5d} "
                  f"+tax={total_tax:>5d}  {rate:.2f} PIN/s  ETA {eta_min:.1f} min", flush=True)

    with cursor() as con:
        audit(con, SOURCE_NAME, BASE, len(todo),
              f"sales={total_conv} av={total_val} tax={total_tax}")
    print(f"\nDone: {len(todo)} PINs scraped. "
          f"+{total_conv} sales, +{total_val} AV rows, +{total_tax} tax rows.", flush=True)
    return len(todo)


if __name__ == "__main__":
    n = int(os.environ.get("LIMIT", "0")) or None
    sys.exit(0 if load(limit=n) else 1)
