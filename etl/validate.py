"""Post-load validation and confidence scoring.

Run after all ingest jobs. Reports sanity counts, cross-validation pass rate,
recomputes confidence_score on every sales row.
"""
from ._db import cursor

EXPECTED_PARCELS_RANGE = (3500, 5000)
EXPECTED_MIN_SALES = 2500


def _scalar(con, sql: str, *params) -> int | float:
    return con.execute(sql, list(params)).fetchone()[0]


def report() -> dict:
    out = {}
    with cursor() as con:
        out["parcels_total"] = _scalar(con, "SELECT count(*) FROM burr_ridge_parcels")
        out["parcels_cook"] = _scalar(con, "SELECT count(*) FROM burr_ridge_parcels WHERE county='cook'")
        out["parcels_dupage"] = _scalar(con, "SELECT count(*) FROM burr_ridge_parcels WHERE county='dupage'")
        out["sales_total"] = _scalar(con, "SELECT count(*) FROM sales WHERE sale_date >= '2013-01-01'")
        out["sales_cook"] = _scalar(con, "SELECT count(*) FROM sales WHERE county='cook' AND sale_date >= '2013-01-01'")
        out["sales_dupage"] = _scalar(con, "SELECT count(*) FROM sales WHERE county='dupage' AND sale_date >= '2013-01-01'")
        out["arms_length"] = _scalar(con, "SELECT count(*) FROM arms_length_sales")

        crosscheck_total = _scalar(con, "SELECT count(*) FROM sales_crosscheck")
        crosscheck_matched = _scalar(con, "SELECT count(*) FROM sales_crosscheck WHERE matched")
        out["crosscheck_match_pct"] = (crosscheck_matched / crosscheck_total * 100) if crosscheck_total else None

        out["years_covered"] = _scalar(
            con,
            "SELECT count(DISTINCT date_part('year', sale_date)) FROM sales WHERE sale_date >= '2013-01-01'",
        )

    print("\n=== Burr Ridge warehouse validation ===")
    for k, v in out.items():
        print(f"  {k:25s} {v}")

    warnings = []
    if not (EXPECTED_PARCELS_RANGE[0] <= out["parcels_total"] <= EXPECTED_PARCELS_RANGE[1]):
        warnings.append(f"parcel count {out['parcels_total']} outside expected {EXPECTED_PARCELS_RANGE}")
    if out["sales_total"] < EXPECTED_MIN_SALES:
        warnings.append(f"sales count {out['sales_total']} below expected min {EXPECTED_MIN_SALES}")
    if out["crosscheck_match_pct"] is not None and out["crosscheck_match_pct"] < 90:
        warnings.append(f"Cook cross-check match pct {out['crosscheck_match_pct']:.1f}% below 90% threshold")
    if out["years_covered"] < 12:
        warnings.append(f"only {out['years_covered']} years of sales — expected ≥12 (2013–present)")

    if warnings:
        print("\nWARNINGS:")
        for w in warnings:
            print(f"  ⚠ {w}")
    else:
        print("\n✓ all checks passed")

    return out


def score_confidence() -> int:
    """Recompute confidence_score for every sales row.
    +1 if matched in sales_crosscheck (Cook only)
    +1 if address normalizes (parcel has non-null address_normalized)
    +1 if PIN exists in burr_ridge_parcels
    +1 if assessment exists for the same year
    -1 if filter_flags is non-empty
    """
    with cursor() as con:
        con.execute("""
            UPDATE sales s SET confidence_score = (
                (CASE WHEN EXISTS (
                    SELECT 1 FROM sales_crosscheck c
                    WHERE c.county=s.county AND c.pin_normalized=s.pin_normalized
                      AND c.sale_date=s.sale_date AND c.matched
                ) THEN 1 ELSE 0 END)
                + (CASE WHEN EXISTS (
                    SELECT 1 FROM burr_ridge_parcels p
                    WHERE p.county=s.county AND p.pin_normalized=s.pin_normalized
                      AND p.address_normalized IS NOT NULL
                ) THEN 1 ELSE 0 END)
                + (CASE WHEN EXISTS (
                    SELECT 1 FROM burr_ridge_parcels p
                    WHERE p.county=s.county AND p.pin_normalized=s.pin_normalized
                ) THEN 1 ELSE 0 END)
                + (CASE WHEN EXISTS (
                    SELECT 1 FROM assessments a
                    WHERE a.county=s.county AND a.pin_normalized=s.pin_normalized
                      AND a.tax_year = date_part('year', s.sale_date)
                ) THEN 1 ELSE 0 END)
                - (CASE WHEN json_array_length(s.filter_flags) > 0 THEN 1 ELSE 0 END)
            )
        """)
        n = _scalar(con, "SELECT count(*) FROM sales WHERE confidence_score IS NOT NULL")
    print(f"Scored confidence on {n} sales rows")
    return n


if __name__ == "__main__":
    score_confidence()
    report()
