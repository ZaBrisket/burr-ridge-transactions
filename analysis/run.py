"""Deterministic runner: executes Lane 0 (gate), then every lane the gate marks viable.

Writes per-lane JSON + memo fragments + charts and a combined ``summary.md`` into
``analysis/output/<run-date>/``. Charts land in the committed ``analysis/charts/``.
This is what ``make analyze`` runs; the `.claude/` orchestrator reads these artifacts.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from analysis import _frame, county_compare, hedonic, quality_gate, repeat_sales, trend_test
from analysis._artifacts import OUTPUT


def main(min_confidence: int | None = None) -> Path:
    outdir = OUTPUT / date.today().isoformat()
    outdir.mkdir(parents=True, exist_ok=True)
    opts = {"min_confidence": min_confidence}
    con = _frame.connect()
    try:
        gate = quality_gate.run(con, outdir, opts)
        v = gate["viability"]
        results = {"quality_gate": gate}
        results["trend_test"] = trend_test.run(con, outdir, {**opts, "counties": v["trend_test"]})
        results["repeat_sales"] = repeat_sales.run(con, outdir, {**opts, "counties": v["repeat_sales"]})
        results["hedonic"] = hedonic.run(con, outdir, {**opts, "counties": v["hedonic"]})
        if v["county_compare"]:
            results["county_compare"] = county_compare.run(con, outdir, opts)
    finally:
        con.close()

    # Combined summary memo (deterministic input for the synthesizer / quick human read).
    order = ["quality_gate", "trend_test", "repeat_sales", "hedonic", "county_compare"]
    parts = [(outdir / f"{name}.md").read_text() for name in order if (outdir / f"{name}.md").exists()]
    summary = (
        f"# Burr Ridge price-trend analysis — {date.today().isoformat()}\n\n"
        "_Deterministic lane outputs. The orchestrator interprets and QA-checks these into "
        "`analysis/TRENDS.md`._\n\n" + "\n".join(parts)
    )
    (outdir / "summary.md").write_text(summary)
    (outdir / "manifest.json").write_text(json.dumps({
        "run_date": date.today().isoformat(),
        "lanes": list(results),
        "viability": gate["viability"],
    }, indent=2))

    print(f"Analysis complete -> {outdir}")
    print(f"Lanes: {', '.join(results)}")
    return outdir


if __name__ == "__main__":
    main()
