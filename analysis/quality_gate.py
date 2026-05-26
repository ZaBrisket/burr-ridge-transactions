"""Lane 0 — data-quality / viability gate.

Profiles the analysis frames and decides which downstream lanes have enough data to run.
This is the precondition lane: ``run.py`` consults its viability flags before dispatching
the others. No hypothesis testing here — just coverage facts and gating.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from analysis import _frame
from analysis._artifacts import save_chart, write_result

# Minimum sample sizes for a lane to be statistically defensible.
HEDONIC_MIN_N = 150
REPEAT_MIN_PAIRS = 50
TREND_MIN_YEARS = 5


def run(con, outdir: Path, opts: dict | None = None) -> dict:
    opts = opts or {}
    al = _frame.arms_length(con)
    hed = _frame.hedonic_frame(con)
    rep = _frame.repeat_pairs(con)
    counties = sorted(al["county"].unique())

    by_year = (
        al.groupby(["sale_year", "county"]).size().rename("n").reset_index()
        .pivot(index="sale_year", columns="county", values="n").fillna(0).astype(int)
    )
    hed_n = hed["county"].value_counts().to_dict()
    rep_n = rep["county"].value_counts().to_dict()

    viability = {
        "trend_test": [c for c in counties if al[al.county == c].sale_year.nunique() >= TREND_MIN_YEARS],
        "repeat_sales": [c for c in counties if rep_n.get(c, 0) >= REPEAT_MIN_PAIRS],
        "hedonic": [c for c in counties if hed_n.get(c, 0) >= HEDONIC_MIN_N],
        "county_compare": len(counties) >= 2,
    }
    thin_cells = [
        {"sale_year": int(y), "county": c, "n": int(by_year.loc[y, c])}
        for y in by_year.index for c in by_year.columns
        if 0 < by_year.loc[y, c] < 20
    ]

    result = {
        "lane": "quality_gate",
        "partial_year_excluded": _frame.PARTIAL_YEAR,
        "arms_length_total": int(len(al)),
        "arms_length_by_county": al["county"].value_counts().to_dict(),
        "year_range": [int(al.sale_year.min()), int(al.sale_year.max())],
        "hedonic_complete_cases_by_county": hed_n,
        "repeat_pairs_by_county": rep_n,
        "repeat_min_years_held": _frame.MIN_YEARS_HELD,
        "viability": viability,
        "thresholds": {
            "hedonic_min_n": HEDONIC_MIN_N,
            "repeat_min_pairs": REPEAT_MIN_PAIRS,
            "trend_min_years": TREND_MIN_YEARS,
        },
        "thin_cells_lt20": thin_cells,
        "chart": None,
    }

    fig, ax = plt.subplots(figsize=(8, 4))
    by_year.plot(kind="bar", ax=ax)
    ax.set_title("Arms-length sales by year and county")
    ax.set_xlabel("Sale year")
    ax.set_ylabel("Sales")
    ax.legend(title="County")
    result["chart"] = save_chart(fig, "quality_gate")

    memo = _memo(result)
    write_result(outdir, "quality_gate", result, memo)
    return result


def _memo(r: dict) -> str:
    v = r["viability"]
    lines = [
        "## Quality gate",
        f"- Arms-length sales (excl. partial {r['partial_year_excluded']}): "
        f"**{r['arms_length_total']}** — {r['arms_length_by_county']}",
        f"- Years covered: {r['year_range'][0]}–{r['year_range'][1]}",
        f"- Hedonic complete-cases by county: {r['hedonic_complete_cases_by_county']} "
        f"(threshold {r['thresholds']['hedonic_min_n']})",
        f"- Clean repeat-sale pairs (≥{r['repeat_min_years_held']}y held): "
        f"{r['repeat_pairs_by_county']} (threshold {r['thresholds']['repeat_min_pairs']})",
        "",
        "**Lane viability:**",
        f"- trend_test: {v['trend_test']}",
        f"- repeat_sales: {v['repeat_sales']}",
        f"- hedonic: {v['hedonic']}",
        f"- county_compare: {v['county_compare']}",
    ]
    if r["thin_cells_lt20"]:
        cells = ", ".join(f"{c['county']} {c['sale_year']}={c['n']}" for c in r["thin_cells_lt20"])
        lines += ["", f"_Thin cells (<20 sales), interpret trends there with caution: {cells}_"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    from datetime import date

    from analysis._artifacts import OUTPUT

    con = _frame.connect()
    print(run(con, OUTPUT / date.today().isoformat()))
    con.close()
