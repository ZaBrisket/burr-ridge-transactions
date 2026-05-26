"""Shared, read-only analysis frames built from the warehouse.

All analysis is read-only. We open the warehouse with ``read_only=True`` and do NOT
reuse ``etl._db.connect()`` (which connects writable and loads the spatial extension).
Physical characteristics (sqft, beds, baths, year built) are effectively time-invariant,
so the hedonic frame joins the *latest available* characteristics per PIN rather than the
sale-year row — this is what lifts hedonic complete-cases well above the convenience view.
"""

from __future__ import annotations

import datetime as _dt

import duckdb
import numpy as np
import pandas as pd

from etl._paths import WAREHOUSE

START_DATE = "2013-01-01"
# The in-progress calendar year is partial; exclude it from trend fits.
PARTIAL_YEAR = _dt.date.today().year


def connect() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(WAREHOUSE), read_only=True)


def _conf_clause(min_confidence: int | None) -> str:
    if min_confidence is None:
        return ""
    return f" AND s.confidence_score >= {int(min_confidence)}"


def arms_length(
    con: duckdb.DuckDBPyConnection,
    min_confidence: int | None = None,
    exclude_partial_year: bool = True,
) -> pd.DataFrame:
    """Arms-length sales since 2013 with a positive price."""
    sql = f"""
        SELECT s.county,
               s.pin_normalized,
               s.sale_date,
               date_part('year', s.sale_date)::INTEGER AS sale_year,
               s.sale_price,
               s.confidence_score
        FROM sales s
        WHERE s.is_arms_length = TRUE
          AND s.sale_date >= DATE '{START_DATE}'
          AND s.sale_price > 0
          {_conf_clause(min_confidence)}
    """
    df = con.execute(sql).df()
    if exclude_partial_year:
        df = df[df["sale_year"] < PARTIAL_YEAR].copy()
    return df.reset_index(drop=True)


def hedonic_frame(
    con: duckdb.DuckDBPyConnection,
    min_confidence: int | None = None,
    exclude_partial_year: bool = True,
) -> pd.DataFrame:
    """Arms-length sales joined to the latest complete characteristics per PIN.

    Complete-case on building_sqft / bedrooms / bathrooms / year_built. lot_sqft is
    included but nullable (the hedonic lane decides whether to use it). Adds ``age`` and
    ``price_per_sqft``.
    """
    sql = f"""
        WITH al AS (
            SELECT county, pin_normalized, sale_date,
                   date_part('year', sale_date)::INTEGER AS sale_year,
                   sale_price, confidence_score
            FROM sales
            WHERE is_arms_length = TRUE
              AND sale_date >= DATE '{START_DATE}'
              AND sale_price > 0
        ),
        chl AS (
            SELECT county, pin_normalized,
                   arg_max(building_sqft, tax_year) AS building_sqft,
                   arg_max(bedrooms,      tax_year) AS bedrooms,
                   arg_max(bathrooms,     tax_year) AS bathrooms,
                   arg_max(year_built,    tax_year) AS year_built
            FROM characteristics
            WHERE building_sqft IS NOT NULL AND bedrooms IS NOT NULL
              AND bathrooms IS NOT NULL AND year_built IS NOT NULL
            GROUP BY county, pin_normalized
        ),
        lot AS (
            SELECT county, pin_normalized, max(lot_sqft) AS lot_sqft
            FROM parcels
            WHERE valid_to IS NULL
            GROUP BY county, pin_normalized
        )
        SELECT al.county, al.pin_normalized, al.sale_date, al.sale_year,
               al.sale_price, al.confidence_score,
               chl.building_sqft, chl.bedrooms, chl.bathrooms, chl.year_built,
               lot.lot_sqft
        FROM al
        JOIN chl USING (county, pin_normalized)
        LEFT JOIN lot USING (county, pin_normalized)
    """
    df = con.execute(sql).df()
    df = df[(df["building_sqft"] > 0)].copy()
    df["age"] = df["sale_year"] - df["year_built"]
    df = df[df["age"] >= 0].copy()
    df["price_per_sqft"] = df["sale_price"] / df["building_sqft"]
    if min_confidence is not None:
        df = df[df["confidence_score"] >= min_confidence].copy()
    if exclude_partial_year:
        df = df[df["sale_year"] < PARTIAL_YEAR].copy()
    return df.reset_index(drop=True)


# Minimum holding period for a valid resale pair. Sub-annual pairs in this data are
# overwhelmingly same-transaction duplicates (MyDec<->CCAO cross-listings, multiple deed
# records) with a ~0% price change — they would corrupt a repeat-sales index.
MIN_YEARS_HELD = 1.0


def repeat_pairs(
    con: duckdb.DuckDBPyConnection,
    min_confidence: int | None = None,
    min_years_held: float = MIN_YEARS_HELD,
) -> pd.DataFrame:
    """Consecutive same-PIN arms-length sale pairs (genuine resale events).

    Returns one row per consecutive pair with the holding period in years and the log
    price relative. Pairs held less than ``min_years_held`` are dropped as duplicates.
    Partial-year sales are kept (a recent resale still informs the index); the BMN time
    dummies handle period coverage.
    """
    sql = f"""
        WITH al AS (
            SELECT county, pin_normalized, sale_date, sale_price, confidence_score
            FROM sales
            WHERE is_arms_length = TRUE
              AND sale_date >= DATE '{START_DATE}'
              AND sale_price > 0
              {_conf_clause(min_confidence)}
        ),
        seq AS (
            SELECT county, pin_normalized, sale_date, sale_price,
                   lag(sale_date)  OVER w AS prev_date,
                   lag(sale_price) OVER w AS prev_price
            FROM al
            WINDOW w AS (PARTITION BY county, pin_normalized ORDER BY sale_date)
        )
        SELECT county, pin_normalized,
               prev_date AS sale_date_1, prev_price AS price_1,
               sale_date AS sale_date_2, sale_price AS price_2,
               date_diff('day', prev_date, sale_date) / 365.25 AS years_held
        FROM seq
        WHERE prev_date IS NOT NULL
    """
    df = con.execute(sql).df()
    df = df[(df["years_held"] >= min_years_held) & (df["price_1"] > 0) & (df["price_2"] > 0)].copy()
    df["log_ratio"] = np.log(df["price_2"] / df["price_1"])
    df["year_1"] = pd.to_datetime(df["sale_date_1"]).dt.year
    df["year_2"] = pd.to_datetime(df["sale_date_2"]).dt.year
    return df.reset_index(drop=True)
