"""Lane 4 — cross-county comparison of the sale-price distribution.

Mann-Whitney U (robust, non-parametric) and a Welch t-test on log price, with a
rank-biserial effect size, comparing Cook vs DuPage arms-length sale prices. This is a
cross-sectional comparison of price *levels* and housing mix — not an apples-to-apples
appreciation comparison (that is narrated from the trend / repeat-sales lanes, which use
different methods per county).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import stats

from analysis import _frame
from analysis._artifacts import save_chart, write_result


def run(con, outdir: Path, opts: dict | None = None) -> dict:
    al = _frame.arms_length(con)
    counties = sorted(al["county"].unique())
    result = {"lane": "county_compare", "chart": None}

    if len(counties) < 2:
        result["note"] = "Fewer than two counties present; comparison skipped."
        write_result(outdir, "county_compare", result, "## County comparison\n- Skipped (one county).\n")
        return result

    a, b = counties[0], counties[1]
    pa = al.loc[al.county == a, "sale_price"].to_numpy(float)
    pb = al.loc[al.county == b, "sale_price"].to_numpy(float)

    u, p_mwu = stats.mannwhitneyu(pa, pb, alternative="two-sided")
    rank_biserial = float(1 - 2 * u / (len(pa) * len(pb)))  # effect size, signed for `a` vs `b`
    t, p_t = stats.ttest_ind(np.log(pa), np.log(pb), equal_var=False)
    pct_gap = float(np.median(pa) / np.median(pb) - 1)

    result.update({
        "county_a": a, "county_b": b,
        "n_a": int(len(pa)), "n_b": int(len(pb)),
        "median_a": float(np.median(pa)), "median_b": float(np.median(pb)),
        "median_gap_a_vs_b_pct": pct_gap,
        "mann_whitney_u": float(u), "mann_whitney_p": float(p_mwu),
        "rank_biserial_effect": rank_biserial,
        "welch_t_logprice": float(t), "welch_p": float(p_t),
        "significant_5pct": bool(p_mwu < 0.05),
    })

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.boxplot([pa / 1000, pb / 1000], labels=[a, b], showfliers=False)
    ax.set_title("Arms-length sale price by county (outliers hidden)")
    ax.set_ylabel("Sale price ($000s)")
    ax.grid(True, axis="y", alpha=0.3)
    result["chart"] = save_chart(fig, "county_compare")

    write_result(outdir, "county_compare", result, _memo(result))
    return result


def _memo(r: dict) -> str:
    if "median_a" not in r:
        return "## County comparison\n- Skipped (one county).\n"
    sig = "**significant**" if r["significant_5pct"] else "not significant"
    direction = "higher" if r["median_gap_a_vs_b_pct"] > 0 else "lower"
    return (
        "## Cross-county price comparison\n"
        f"- Median price **{r['county_a']}** ${r['median_a']:,.0f} (n={r['n_a']}) vs "
        f"**{r['county_b']}** ${r['median_b']:,.0f} (n={r['n_b']}): "
        f"{r['county_a']} is {abs(r['median_gap_a_vs_b_pct'])*100:.0f}% {direction}.\n"
        f"- Mann-Whitney U p={r['mann_whitney_p']:.3g} (rank-biserial effect "
        f"{r['rank_biserial_effect']:.2f}); Welch t on log-price p={r['welch_p']:.3g} → {sig}.\n"
        "- _Cross-sectional comparison of price levels / housing mix, not appreciation._\n"
    )


if __name__ == "__main__":
    from datetime import date

    from analysis._artifacts import OUTPUT

    con = _frame.connect()
    print(run(con, OUTPUT / date.today().isoformat()))
    con.close()
