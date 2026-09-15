"""The headline over time - one point per state of the data, not per run.

WHY NOT SIMPLY PLOT EVERY ARCHIVED RUN
--------------------------------------
Because most of them are not new forecasts. Of the first 23 archived runs there
were only **four distinct `as_of` dates**: twelve runs share one, six share
another. The rest of the variation is the model being re-sampled on identical
polling, and - worse - eight different model fingerprints, every one of them a
change to the arithmetic.

A line through all 23 would show the headline lurching by twenty points and
would be showing the reader my edits, not French opinion. This is the same trap
`changes.py` exists to avoid, in chart form, and it is easier to fall into
because a chart looks like data.

WHAT IS PLOTTED INSTEAD
-----------------------
One point per `as_of` date - per state of the polling - taking the LATEST run
for that date, so each point is the most current arithmetic applied to that
data. That is an honest series: "what the forecast said once it had the polls
up to this date".

It is still not a like-for-like comparison when the model changed during the
period, because earlier points were produced by earlier arithmetic. The
fingerprint travels with each point so the page can say so rather than
implying a clean series.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .paths import RUNS

log = logging.getLogger(__name__)

# How many candidates to carry. The chart is unreadable beyond a handful, and
# the ones below this are not what anybody is tracking.
TOP_N = 5


def load_runs(runs_dir: Path | None = None) -> list[dict]:
    runs_dir = runs_dir or RUNS
    if not runs_dir.exists():
        return []
    out = []
    for path in sorted(runs_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("unreadable run %s (%s)", path, exc)
            continue
        if payload.get("as_of"):
            payload["_file"] = path.name
            out.append(payload)
    return out


def build(runs_dir: Path | None = None, top_n: int = TOP_N) -> dict:
    """One point per as_of date, latest run wins."""
    runs = load_runs(runs_dir)
    if not runs:
        return {}

    # Files are named by run timestamp, so the last one for a date is the most
    # recent arithmetic applied to that data.
    by_date: dict[str, dict] = {}
    for r in runs:
        by_date[r["as_of"]] = r
    dates = sorted(by_date)
    if len(dates) < 2:
        log.info("history: only %d distinct data date(s); chart omitted", len(dates))
        return {}

    latest = by_date[dates[-1]]
    tracked = [
        c["id"]
        for c in sorted(
            latest.get("candidats", []), key=lambda c: -(c.get("p_win") or 0)
        )[:top_n]
    ]
    names = {c["id"]: c["nom"] for c in latest.get("candidats", [])}
    blocs = {c["id"]: c["bloc"] for c in latest.get("candidats", [])}

    series: dict[str, list] = {cid: [] for cid in tracked}
    fingerprints = []
    for d in dates:
        run = by_date[d]
        fingerprints.append(run.get("model_fingerprint"))
        found = {c["id"]: c for c in run.get("candidats", [])}
        for cid in tracked:
            c = found.get(cid)
            series[cid].append(round(c["p_win"], 4) if c and c.get("p_win") is not None else None)

    changed = len({f for f in fingerprints if f}) > 1
    log.info(
        "history: %d data dates, %d candidates, model changed during period: %s",
        len(dates), len(tracked), changed,
    )
    return {
        "dates": dates,
        "series": series,
        "noms": {cid: names.get(cid, cid) for cid in tracked},
        "blocs": {cid: blocs.get(cid) for cid in tracked},
        # True when earlier points came from different arithmetic, so the page
        # can decline to present the line as a clean comparison.
        "model_changed": changed,
        "n_runs": len(runs),
    }
