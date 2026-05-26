"""Lane 1 — price-level trend test.

Per county: a non-parametric Mann-Kendall test on the annual median sale price (robust to
the thin Cook cells), plus an OLS of log(price) on year with HC3 robust standard errors to
get a quantified annual growth rate (CAGR) with a 95% CI and p-value.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pymannkendall as mk
import statsmodels.api as sm

from analysis import _frame
from analysis._artifacts import save_chart, write_result


def _county_trend(d) -> dict:
    d = d.sort_values("sale_year")
    annual = d.groupby("sale_year")["sale_price"].median()
    mkres = mk.original_test(annual.values)

    yr = d["sale_year"].to_numpy(float)
    X = sm.add_constant(yr - yr.mean())
    y = np.log(d["sale_price"].to_numpy(float))
    res = sm.OLS(y, X).fit(cov_type="HC3")
    slope = float(res.params[1])
    lo, hi = (float(v) for v in res.conf_int(alpha=0.05)[1])
    p = float(res.pvalues[1])
    min_annual_n = int(d.groupby("sale_year").size().min())

    return {
        "n_sales": int(len(d)),
        "n_years": int(annual.size),
        "min_annual_n": min_annual_n,
        "median_price_first_year": float(annual.iloc[0]),
        "median_price_last_year": float(annual.iloc[-1]),
        "mann_kendall_trend": mkres.trend,
        "mann_kendall_p": float(mkres.p),
        "mann_kendall_tau": float(mkres.Tau),
        "sens_slope_price_per_year": float(mkres.slope),
        "ols_log_slope_per_year": slope,
        "ols_p": p,
        "cagr": float(np.expm1(slope)),
        "cagr_95ci": [float(np.expm1(lo)), float(np.expm1(hi))],
        "significant_5pct": bool(p < 0.05) and bool(mkres.p < 0.05),
        "caveat_thin": min_annual_n < 20,
    }, annual


def run(con, outdir: Path, opts: dict | None = None) -> dict:
    opts = opts or {}
    counties = opts.get("counties")
    al = _frame.arms_length(con)
    if counties:
        al = al[al.county.isin(counties)]

    per_county, series = {}, {}
    for c in sorted(al["county"].unique()):
        per_county[c], series[c] = _county_trend(al[al.county == c])

    result = {"lane": "trend_test", "by_county": per_county, "chart": None}

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4.5))
    for c, s in series.items():
        cagr = per_county[c]["cagr"]
        ax.plot(s.index, s.values / 1000, marker="o", label=f"{c} (CAGR {cagr*100:.1f}%/yr)")
    ax.set_title("Median arms-length sale price by year")
    ax.set_xlabel("Sale year")
    ax.set_ylabel("Median price ($000s)")
    ax.legend(title="County")
    ax.grid(True, alpha=0.3)
    result["chart"] = save_chart(fig, "trend_test")

    write_result(outdir, "trend_test", result, _memo(result))
    return result


def _memo(r: dict) -> str:
    lines = ["## Price-level trend (Mann-Kendall + OLS log-price)"]
    for c, x in r["by_county"].items():
        sig = "**significant**" if x["significant_5pct"] else "not significant"
        lines.append(
            f"- **{c}**: CAGR **{x['cagr']*100:.1f}%/yr** "
            f"(95% CI {x['cagr_95ci'][0]*100:.1f}–{x['cagr_95ci'][1]*100:.1f}%), "
            f"OLS p={x['ols_p']:.3g}; Mann-Kendall {x['mann_kendall_trend']} "
            f"(τ={x['mann_kendall_tau']:.2f}, p={x['mann_kendall_p']:.3g}) → {sig}. "
            f"n={x['n_sales']} over {x['n_years']} yrs."
            + (" _Thin annual cells — interpret with caution._" if x["caveat_thin"] else "")
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from datetime import date

    from analysis._artifacts import OUTPUT

    con = _frame.connect()
    print(run(con, OUTPUT / date.today().isoformat()))
    con.close()
