"""The model's own record, carried into the page.

WHY THIS IS ON THE SITE AND NOT ONLY IN THE REPO
------------------------------------------------
A reader sees "Le Pen 66%" and has no way to learn that the model was scored
against a real election, how it did, or which single assumption could move that
number by ten points. All of that existed - in `outputs/backtests/`, in
METHODOLOGY.md - and none of it was visible to the people the forecast is for.

Publishing a forecast's own calibration is unusual and it should not be. A
probability is a claim about long-run frequency; without some evidence about
whether this machinery's probabilities have ever been right, the reader is
being asked to take the number on trust.

WHAT IS AND IS NOT CLAIMED
--------------------------
The numbers come from `presidentielle backtest`, read from the committed score
files rather than retyped, so the page cannot drift from what was measured. The
caveats travel with them: one cycle, and coverage that is partly circular
because the parameters setting interval width were fitted on the same cycle
being scored. Reporting the record without that would be worse than not
reporting it, because it would look like independent validation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .paths import OUTPUTS

log = logging.getLogger(__name__)

BACKTESTS = OUTPUTS / "backtests"

# The candidates who actually reached the 2022 runoff, and the winner.
FINALISTS_2022 = ("EM", "MLP")
WINNER_2022 = "EM"


def load(directory: Path | None = None) -> list[dict]:
    """Read archived backtest scores, newest horizon last."""
    directory = directory or BACKTESTS
    if not directory.exists():
        return []
    out = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("unreadable backtest score %s (%s)", path, exc)
            continue
        out.append(payload)
    # Longest horizon first: it is the one comparable to where the live
    # forecast currently stands.
    out.sort(key=lambda p: -(p.get("days_out") or 0))
    return out


def summarise(scores: list[dict]) -> dict:
    """The shape the page renders. Empty when there is nothing scored."""
    rows = []
    for s in scores:
        top2 = s.get("predicted_top2") or []
        rows.append(
            {
                "days_out": s.get("days_out"),
                "as_of": s.get("as_of"),
                "mae_points": s.get("mae_points"),
                "crps_points": s.get("crps_points"),
                "coverage_90": s.get("coverage_90"),
                "coverage_50": s.get("coverage_50"),
                # Did it name the pair who actually reached the runoff?
                "top2_correct": sorted(top2) == sorted(FINALISTS_2022),
                "p_winner": s.get("p_win_actual"),
                "n_polls": s.get("n_polls"),
            }
        )
    return {
        "election": 2022,
        "runs": rows,
        # Stated on the page, not only here: without it the record reads as
        # independent validation, which it is not.
        "circular": True,
    }


def build(directory: Path | None = None) -> dict:
    scores = load(directory)
    if not scores:
        log.info("no archived backtests; track record omitted from the page")
        return {}
    summary = summarise(scores)
    log.info(
        "track record: %d scored run(s), horizons %s",
        len(summary["runs"]),
        ", ".join(str(r["days_out"]) for r in summary["runs"]),
    )
    return summary
