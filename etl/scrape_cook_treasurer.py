"""Polite per-PIN scraper for Cook County Treasurer 20-year tax bill history.

Flow per PIN:
  1. GET  setsearchparameters.aspx          → __VIEWSTATE
  2. POST setsearchparameters.aspx (5-segment PIN) → results page (session-bound)
  3. GET  taxbillhistoryresults.aspx        → multi-year tax history table

Resume-safe via cook_treasurer_scraped audit table. ~1.5 sec per PIN at 1 req/sec.

Run via:  .venv/bin/python -u -m etl.scrape_cook_treasurer
"""
import datetime as dt
import re
import sys
import time
import requests
import urllib3
from bs4 import BeautifulSoup
from ._db import cursor, audit
from .scrape_dupage_soa import _ensure_tax_table

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://www.cookcountytreasurer.com"
SEARCH_URL = f"{BASE}/setsearchparameters.aspx"
HISTORY_URL = f"{BASE}/taxbillhistoryresults.aspx"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
PIN_PREFIX = "ctl00$ContentPlaceHolder1$ASPxPanel1$SearchByPIN1$"
RATE_DELAY_S = 1.0
SOURCE_NAME = "cook_treasurer_scrape"


def _money(s: str) -> float | None:
    if s is None:
        return None
    s = re.sub(r"[\$,]", "", str(s)).strip()
    try:
        return float(s) if s else None
    except ValueError:
        return None


def _ensure_audit(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS cook_treasurer_scraped (
            pin_normalized TEXT PRIMARY KEY,
            scraped_at     TIMESTAMP NOT NULL,
            n_years        INTEGER,
            note           TEXT
        )
    """)


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    s.verify = False
    return s


def _viewstate(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form")
    if not form:
        return {}
    return {i.get("name"): i.get("value", "") for i in form.find_all("input", {"type": "hidden"})}


def _scrape_one(session: requests.Session, pin14: str) -> tuple[list[dict], str | None]:
    pin = pin14.zfill(14)
    # Fresh GET to refresh __VIEWSTATE for each PIN
    r = session.get(SEARCH_URL, timeout=30)
    if r.status_code != 200:
        return [], f"GET search failed {r.status_code}"
    hidden = _viewstate(r.text)
    if not hidden:
        return [], "no viewstate on search page"

    data = dict(hidden)
    data.update({
        PIN_PREFIX + "txtPIN1": pin[0:2],
        PIN_PREFIX + "txtPIN2": pin[2:4],
        PIN_PREFIX + "txtPIN3": pin[4:7],
        PIN_PREFIX + "txtPIN4": pin[7:10],
        PIN_PREFIX + "txtPIN5": pin[10:14],
        PIN_PREFIX + "cmdContinue": "Continue",
    })
    r2 = session.post(SEARCH_URL, data=data, timeout=60)
    if r2.status_code != 200:
        return [], f"POST search failed {r2.status_code}"

    r3 = session.get(HISTORY_URL, timeout=60)
    if r3.status_code != 200:
        return [], f"GET history failed {r3.status_code}"

    soup = BeautifulSoup(r3.text, "html.parser")
    for s in soup(["script", "style"]):
        s.decompose()

    # The CCT page collapses each row into a single cell with concatenated text.
    # Parse it with regex against the row text.
    out = []
    seen = set()
    for tbl in soup.find_all("table"):
        full_text = tbl.get_text(" ", strip=True)
        if "Tax Year" not in full_text or "Total Billed Amount" not in full_text:
            continue
        for row in tbl.find_all("tr"):
            txt = re.sub(r"\s+", " ", row.get_text(" ", strip=True))
            m = re.match(
                r"^(\d{4})\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})",
                txt,
            )
            if not m:
                continue
            year = int(m.group(1))
            if year < 2013 or year in seen:
                continue
            seen.add(year)
            out.append({
                "year":   year,
                "billed": _money(m.group(2)),
                "paid":   _money(m.group(3)),
            })
        if out:
            break
    return out, None


def _write(con, pin: str, records: list[dict]) -> int:
    if not records:
        return 0
    payload = [
        ("cook", pin, r["year"], r["billed"], r["paid"], None, "cook_treasurer:taxbillhistory")
        for r in records
    ]
    con.executemany(
        """
        INSERT INTO tax_bills (county, pin_normalized, tax_year, tax_billed, tax_total, paid_date, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (county, pin_normalized, tax_year) DO UPDATE SET
            tax_billed = COALESCE(EXCLUDED.tax_billed, tax_bills.tax_billed),
            tax_total  = COALESCE(EXCLUDED.tax_total,  tax_bills.tax_total),
            source     = EXCLUDED.source
        """,
        payload,
    )
    return len(payload)


def load(limit: int | None = None) -> int:
    with cursor() as con:
        _ensure_audit(con)
        _ensure_tax_table(con)
        all_pins = [r[0] for r in con.execute(
            "SELECT pin_normalized FROM parcels WHERE county='cook' AND valid_to IS NULL ORDER BY pin_normalized"
        ).fetchall()]
        already = {r[0] for r in con.execute(
            "SELECT pin_normalized FROM cook_treasurer_scraped"
        ).fetchall()}
        todo = [p for p in all_pins if p not in already]
        if limit:
            todo = todo[:limit]
        print(f"Cook Treasurer scrape: {len(all_pins):,} PINs, {len(already):,} already done → {len(todo):,} to fetch", flush=True)
        if not todo:
            return 0

    session = _make_session()
    t0 = time.time()
    total_rows = 0
    failures = 0

    for i, pin in enumerate(todo, 1):
        if i > 1:
            time.sleep(RATE_DELAY_S)
        try:
            records, err = _scrape_one(session, pin)
        except requests.RequestException as e:
            records, err = [], f"network: {e}"

        with cursor() as con:
            n = _write(con, pin, records)
            con.execute(
                "INSERT OR REPLACE INTO cook_treasurer_scraped VALUES (?, ?, ?, ?)",
                [pin, dt.datetime.now(dt.UTC).replace(tzinfo=None), n, err],
            )
        total_rows += n
        if err:
            failures += 1

        if i % 25 == 0 or i == len(todo):
            elapsed = time.time() - t0
            rate = i / elapsed
            eta_min = (len(todo) - i) / rate / 60
            print(f"  [{i:>4d}/{len(todo)}] +rows={total_rows:>5,d}  failures={failures}  "
                  f"{rate:.2f} PIN/s  ETA {eta_min:.1f} min", flush=True)

    with cursor() as con:
        audit(con, SOURCE_NAME, BASE, len(todo), f"rows={total_rows}, failures={failures}")
    print(f"\nDone: {len(todo)} PINs, {total_rows:,} tax-year rows, {failures} failures", flush=True)
    return len(todo)


if __name__ == "__main__":
    import os
    n = int(os.environ.get("LIMIT", "0")) or None
    sys.exit(0 if load(limit=n) else 1)
