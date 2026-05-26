"""Deterministic statistical analysis lanes over the Burr Ridge warehouse.

Read-only. Each lane module exposes `run(con, opts) -> dict` and writes structured
results (JSON), a chart (PNG), and a markdown memo fragment. The `.claude/` orchestrator
interprets these outputs; it never computes statistics itself.
"""
