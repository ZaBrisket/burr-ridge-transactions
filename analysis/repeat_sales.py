"""Lane 2 — repeat-sales appreciation index.

Uses genuine resale pairs (same PIN, ≥1 year apart; sub-annual duplicates already removed
in `_frame.repeat_pairs`). Reports two things per county:

1. A headline annualized appreciation rate from a no-intercept regression of the log price
   relative on the holding period, with a bootstrap 95% CI (the significance-bearing number).
2. A Bailey-Muth-Nourse (BMN) time-dummy index for the year-by-year chart.

Repeat-sales controls for unobserved, time-invariant property quality, so it needs no
characteristics — which is why it is the workhorse for DuPage.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from analysis import _frame
from analysis._artifacts import save_chart, write_result

_SEED = 12345
_BOOT = 2000


def _cagr_with_ci(years_held: np.ndarray, log_ratio: np.ndarray) -> tuple[float, list[float]]:
    # No-intercept OLS slope = sum(x*y)/sum(x*x); slope is mean annual log return.
    def slope(x, y):
        return float((x * y).sum() / (x * x).sum())

    s = slope(years_held, log_ratio)
    rng = np.random.default_rng(_SEED)
    n = len(years_held)
    boots = np.empty(_BOOT)
    for i in range(_BOOT):
        idx = rng.integers(0, n, n)
        boots[i] = slope(years_held[idx], log_ratio[idx])
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return float(np.expm1(s)), [float(np.expm1(lo)), float(np.expm1(hi))]


def _bmn_index(d) -> dict | None:
    """Bailey-Muth-Nourse log index relative to the first year (level 100)."""
    years = sorted(set(d["year_1"]).union(d["year_2"]))
    if len(years) < 3:
        return None
    base, cols = years[0], years[1:]
    X = np.zeros((len(d), len(cols)))
    col_idx = {y: j for j, y in enumerate(cols)}
    y1 = d["year_1"].to_numpy()
    y2 = d["year_2"].to_numpy()
    for i in range(len(d)):
        if y2[i] in col_idx:
            X[i, col_idx[y2[i]]] += 1
        if y1[i] in col_idx:
            X[i, col_idx[y1[i]]] -= 1
    y = d["log_ratio"].to_numpy(float)
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    index = {int(base): 100.0}
    for yr, b in zip(cols, coef):
        index[int(yr)] = float(100.0 * np.exp(b))
    return {"base_year": int(base), "index": index, "unstable": len(d) < 3 * len(cols)}


def run(con, outdir: Path, opts: dict | None = None) -> dict:
    opts = opts or {}
    counties = opts.get("counties")
    rep = _frame.repeat_pairs(con)
    if counties:
        rep = rep[rep.county.isin(counties)]

    per_county, indices = {}, {}
    for c in sorted(rep["county"].unique()):
        d = rep[rep.county == c]
        cagr, ci = _cagr_with_ci(d["years_held"].to_numpy(float), d["log_ratio"].to_numpy(float))
        bmn = _bmn_index(d)
        per_county[c] = {
            "n_pairs": int(len(d)),
            "median_years_held": float(d["years_held"].median()),
            "annualized_appreciation": cagr,
            "annualized_appreciation_95ci": ci,
            "significant_5pct": bool(ci[0] > 0 or ci[1] < 0),
            "bmn_unstable": bool(bmn["unstable"]) if bmn else None,
        }
        if bmn:
            indices[c] = bmn["index"]

    result = {"lane": "repeat_sales", "min_years_held": _frame.MIN_YEARS_HELD,
              "by_county": per_county, "chart": None}

    if indices:
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 4.5))
        for c, idx in indices.items():
            yrs = sorted(idx)
            ax.plot(yrs, [idx[y] for y in yrs], marker="o", label=f"{c} (n={per_county[c]['n_pairs']})")
        ax.axhline(100, color="grey", lw=0.8, ls="--")
        ax.set_title("Repeat-sales price index (BMN, base year = 100)")
        ax.set_xlabel("Year")
        ax.set_ylabel("Index (100 = base year)")
        ax.legend(title="County")
        ax.grid(True, alpha=0.3)
        result["chart"] = save_chart(fig, "repeat_sales")

    write_result(outdir, "repeat_sales", result, _memo(result))
    return result


def _memo(r: dict) -> str:
    lines = ["## Repeat-sales appreciation (quality-controlled)"]
    for c, x in r["by_county"].items():
        sig = "**significant**" if x["significant_5pct"] else "not significant"
        note = " _(BMN index unstable — few pairs per year; trust the headline rate, not the yearly index)_" if x["bmn_unstable"] else ""
        lines.append(
            f"- **{c}**: appreciation **{x['annualized_appreciation']*100:.1f}%/yr** "
            f"(95% CI {x['annualized_appreciation_95ci'][0]*100:.1f}–{x['annualized_appreciation_95ci'][1]*100:.1f}%) "
            f"→ {sig}. n={x['n_pairs']} resale pairs, median hold {x['median_years_held']:.1f}y.{note}"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from datetime import date

    from analysis._artifacts import OUTPUT

    con = _frame.connect()
    print(run(con, OUTPUT / date.today().isoformat()))
    con.close()
