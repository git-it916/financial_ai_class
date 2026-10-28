"""Cleaning audit trail.

Every step that drops, changes or flags rows is one line in reports/tables/cleaning_log.csv.
Dropped rows (and before/after values of changed rows) are kept in
data/processed/removed/{source}__{step}.parquet so any removal can be inspected or undone.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from ..collect.common import ROOT

LOG = ROOT / "reports" / "tables" / "cleaning_log.csv"
REMOVED = ROOT / "data" / "processed" / "removed"
FIELDS = ["run_at_utc", "source", "step", "kind", "rows_before", "rows_after", "rows_affected", "reason", "kept_in"]


def reset(source: str) -> None:
    """Start a fresh log for one source (a rerun replaces its previous lines and files)."""
    if LOG.exists():
        old = pd.read_csv(LOG)
        old[old.source != source].to_csv(LOG, index=False)
    for p in REMOVED.glob(f"{source}__*.parquet"):
        p.unlink()


def record(source: str, step: str, kind: str, before: int, after: int, reason: str,
           rows: pd.DataFrame | None = None, affected: int | None = None) -> None:
    """kind: drop | change | flag | info."""
    kept = ""
    if rows is not None and len(rows):
        REMOVED.mkdir(parents=True, exist_ok=True)
        path = REMOVED / f"{source}__{step}.parquet"
        rows.astype({c: "string" for c in rows.columns if rows[c].dtype == object}).to_parquet(path, index=False)
        kept = str(path.relative_to(ROOT)).replace("\\", "/")
    n = affected if affected is not None else (before - after if kind == "drop" else len(rows) if rows is not None else 0)
    line = pd.DataFrame([{
        "run_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "source": source, "step": step,
        "kind": kind, "rows_before": before, "rows_after": after, "rows_affected": n, "reason": reason, "kept_in": kept,
    }], columns=FIELDS)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line.to_csv(LOG, mode="a", header=not LOG.exists(), index=False)
    print(f"[{source}] {step}: {kind} {n:,} ({before:,} -> {after:,}) {reason}", flush=True)
