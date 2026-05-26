"""Lane 3 — hedonic quality-adjusted price index (Cook-only in practice).

Two OLS fits with HC3 robust standard errors on complete-case sales:
- A fixed-effects model `log(price) ~ structural controls + C(sale_year)` → adjusted R²,
  structural coefficients, and the year fixed effects that form a quality-adjusted index.
- A continuous-year model (same controls, year linear) → a single quality-adjusted annual
  appreciation rate with a 95% CI and p-value (the significance-bearing number).

Regressors are chosen by coverage: `lot_sqft` is included only where it is well-populated
(it is DuPage-only in this warehouse), so the Cook spec drops it automatically.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from statsmodels.formula.api import ols

from analysis import _frame
from analysis._artifacts import save_chart, write_result

_STRUCTURAL = ["building_sqft", "bedrooms", "bathrooms", "age"]
_LOT_MIN_COVERAGE = 0.8


def _fit_county(d) -> dict:
    regressors = list(_STRUCTURAL)
    if d["lot_sqft"].notna().mean() >= _LOT_MIN_COVERAGE:
        regressors.append("lot_sqft")
    dd = d.dropna(subset=regressors).copy()
    dd["yc"] = dd["sale_year"] - dd["sale_year"].mean()

    base = " + ".join(regressors)
    fe = ols(f"np.log(sale_price) ~ {base} + C(sale_year)", data=dd).fit(cov_type="HC3")
    lin = ols(f"np.log(sale_price) ~ {base} + yc", data=dd).fit(cov_type="HC3")

    slope = float(lin.params["yc"])
    lo, hi = (float(v) for v in lin.conf_int(alpha=0.05).loc["yc"])
    p = float(lin.pvalues["yc"])

    # Year fixed effects -> quality-adjusted index (base year = 100).
    index = {}
    base_year = int(dd["sale_year"].min())
    index[base_year] = 100.0
    for name, coef in fe.params.items():
        if name.startswith("C(sale_year)[T."):
            yr = int(name.split("T.")[1].rstrip("]"))
            index[yr] = float(100.0 * np.exp(coef))

    structural = {
        r: {"coef": float(fe.params[r]), "p": float(fe.pvalues[r])}
        for r in regressors if r in fe.params
    }
    year_counts = {int(y): int(n) for y, n in dd.groupby("sale_year").size().items()}
    thin_index_years = sorted(y for y, n in year_counts.items() if n < 10)
    return {
        "n": int(len(dd)),
        "regressors": regressors,
        "adj_r2": float(fe.rsquared_adj),
        "structural_coefficients": structural,
        "quality_adjusted_cagr": float(np.expm1(slope)),
        "quality_adjusted_cagr_95ci": [float(np.expm1(lo)), float(np.expm1(hi))],
        "quality_adjusted_p": p,
        "significant_5pct": bool(p < 0.05),
        "index": {int(k): index[k] for k in sorted(index)},
        "index_year_counts": year_counts,
        "thin_index_years_lt10": thin_index_years,
        "caveat_modest_n": int(len(dd)) < 500,
    }


def run(con, outdir: Path, opts: dict | None = None) -> dict:
    opts = opts or {}
    counties = opts.get("counties")  # run.py passes only hedonic-viable counties
    hed = _frame.hedonic_frame(con)
    if counties:
        hed = hed[hed.county.isin(counties)]

    per_county = {}
    for c in sorted(hed["county"].unique()):
        per_county[c] = _fit_county(hed[hed.county == c])

    result = {"lane": "hedonic", "by_county": per_county, "chart": None}

    if per_county:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4.5))
        for c, x in per_county.items():
            yrs = sorted(x["index"])
            ax.plot(yrs, [x["index"][y] for y in yrs], marker="o",
                    label=f"{c} quality-adjusted (n={x['n']})")
        ax.axhline(100, color="grey", lw=0.8, ls="--")
        ax.set_title("Hedonic quality-adjusted price index (base year = 100)")
        ax.set_xlabel("Sale year")
        ax.set_ylabel("Index (100 = base year)")
        ax.legend()
        ax.grid(True, alpha=0.3)
        result["chart"] = save_chart(fig, "hedonic")

    write_result(outdir, "hedonic", result, _memo(result))
    return result


def _memo(r: dict) -> str:
    if not r["by_county"]:
        return "## Hedonic quality-adjusted index\n- No county met the complete-case threshold.\n"
    lines = ["## Hedonic quality-adjusted index"]
    for c, x in r["by_county"].items():
        sig = "**significant**" if x["significant_5pct"] else "not significant"
        lines.append(
            f"- **{c}**: quality-adjusted appreciation **{x['quality_adjusted_cagr']*100:.1f}%/yr** "
            f"(95% CI {x['quality_adjusted_cagr_95ci'][0]*100:.1f}–{x['quality_adjusted_cagr_95ci'][1]*100:.1f}%, "
            f"p={x['quality_adjusted_p']:.3g}) → {sig}. "
            f"n={x['n']}, adj R²={x['adj_r2']:.2f}, controls={x['regressors']}."
            + (" _Modest sample — treat coefficients as indicative._" if x["caveat_modest_n"] else "")
            + (f" _Index years with <10 obs (unreliable FE point): {x['thin_index_years_lt10']}._" if x["thin_index_years_lt10"] else "")
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from datetime import date

    from analysis._artifacts import OUTPUT

    con = _frame.connect()
    print(run(con, OUTPUT / date.today().isoformat(), {"counties": ["cook"]}))
    con.close()
