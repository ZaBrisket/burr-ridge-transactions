"""Artifact paths and writers shared by the analysis lanes.

Charts are written to the committed ``analysis/charts/`` directory (so they render in
TRENDS.md on GitHub); per-run JSON + memo fragments go to the gitignored
``analysis/output/<run-date>/``.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless
import matplotlib.pyplot as plt  # noqa: E402

from etl._paths import ROOT  # noqa: E402

ANALYSIS = ROOT / "analysis"
CHARTS = ANALYSIS / "charts"
OUTPUT = ANALYSIS / "output"


def write_result(outdir: Path, name: str, result: dict, memo: str) -> None:
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / f"{name}.json").write_text(json.dumps(result, indent=2, default=str))
    (outdir / f"{name}.md").write_text(memo)


def save_chart(fig, name: str) -> str:
    CHARTS.mkdir(parents=True, exist_ok=True)
    path = CHARTS / f"{name}.png"
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return f"charts/{name}.png"  # path relative to analysis/ (for TRENDS.md embeds)
