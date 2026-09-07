"""Measure how fast French first-round support actually moves.

WHY THIS EXISTS
---------------
The first published run had Le Pen at 32.4% with a 90% interval of
[14.6%, 57.0%]. That is not humility, it is a 42-point interval seven months
out, and it came from ``latent.rw_sd_per_day_prior``, which was asserted rather
than measured. The random walk runs ~32 free weekly steps from the last poll to
election day, so that one number sets the width of every interval on the site.

WHAT IS MEASURED
----------------
The nsppolls archive of the 2022 cycle: real polls, over the same kind of
horizon, scored on how much a candidate's log share moved between consecutive
surveys.

    log p(t2) - log p(t1)  =  sampling noise  +  genuine movement

Sampling noise is known - Var(log p_hat) ~ (1 - p) / (n p) - so the movement
term is what is left after subtracting it:

    sigma^2 = mean[ (d^2 - var_1 - var_2) / delta_t ]

Two restrictions matter:

* **Same institute only.** A gap between an IFOP reading and an Elabe reading
  contains their house effect, which is not movement. Comparing like with like
  removes it.
* **Same hypothesis field.** In 2022 the fields were near-stable, but a poll
  that drops a candidate changes every other share mechanically.
* **No rolling polls, and a gap of at least a week.** This one is not a
  refinement, it is the difference between an answer and nonsense. Much of the
  2022 file is daily rolling waves that re-interview an overlapping panel;
  consecutive readings therefore move *less* than two independent samples
  would, and the first attempt at this fit returned a negative excess variance
  because of it. Dropping `rolling` records and requiring a seven-day gap
  leaves comparisons between genuinely distinct samples.

Run:  python scripts/fit_walk_scale.py
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data" / "cache" / "nsppolls_2022.json"

# Below this share the log transform is dominated by rounding: nsppolls reports
# to 0.5 of a point, so a candidate on 1% moves 50% in log terms by rounding
# alone. The forecast's intervals are set by the candidates who matter.
MIN_SHARE = 0.04

# Overlapping panels make two readings a few days apart far more correlated
# than two independent samples, which biases the estimator downwards - to
# negative excess variance, in the first attempt at this fit.
MIN_GAP_DAYS = 7


def load() -> list[dict]:
    if not ARCHIVE.exists():
        sys.exit(
            f"missing {ARCHIVE}\n"
            "Fetch it with:\n"
            "  curl -sL -o data/cache/nsppolls_2022.json "
            "https://raw.githubusercontent.com/nsppolls/nsppolls/master/presidentielle.json"
        )
    return json.loads(ARCHIVE.read_text(encoding="utf-8"))


def series(payload: list[dict]) -> dict[tuple[str, str], list[tuple[str, float, int]]]:
    """(institute, candidate) -> [(date, share, sample), ...]"""
    out: dict[tuple[str, str], list[tuple[str, float, int]]] = defaultdict(list)
    for poll in payload:
        inst = (poll.get("nom_institut") or "").strip()
        fin = poll.get("fin_enquete")
        n = poll.get("echantillon") or 0
        if not inst or not fin or not n:
            continue
        if poll.get("rolling"):
            continue
        for tour in poll.get("tours") or []:
            if not str(tour.get("tour", "")).lower().startswith("premier"):
                continue
            hyps = tour.get("hypotheses") or []
            if not hyps:
                continue
            # One reading per survey: the first hypothesis, so a survey pricing
            # several fields does not contribute several "movements" between
            # fields and call it change over time.
            cands = hyps[0].get("candidats") or []
            total = sum(float(c.get("intentions") or 0) for c in cands)
            if total <= 0:
                continue
            sub = hyps[0].get("sous_echantillon") or n
            for c in cands:
                share = float(c.get("intentions") or 0) / total
                if share >= MIN_SHARE:
                    out[(inst, c["candidat"])].append((fin, share, int(sub)))
    for key in out:
        out[key].sort()
    return out


def days_between(a: str, b: str) -> int:
    import datetime as dt

    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def main() -> int:
    payload = load()
    data = series(payload)

    contributions: list[float] = []
    pairs = 0
    for (_inst, _cand), points in data.items():
        for (d1, p1, n1), (d2, p2, n2) in zip(points, points[1:], strict=False):
            dt_days = days_between(d1, d2)
            # Too short a gap means overlapping panels; too long a gap spans
            # events the walk is not trying to model.
            if not MIN_GAP_DAYS <= dt_days <= 60:
                continue
            d = math.log(p2) - math.log(p1)
            var1 = (1 - p1) / (n1 * p1)
            var2 = (1 - p2) / (n2 * p2)
            excess = d * d - var1 - var2
            contributions.append(excess / dt_days)
            pairs += 1

    if pairs < 50:
        sys.exit(f"only {pairs} usable pairs - not enough to fit")

    mean_var = statistics.mean(contributions)
    # Individual terms are noisy and can be negative (a pair that moved less
    # than sampling noise alone would predict); the MEAN is the estimator, and
    # it is the mean that has to be positive.
    sigma = math.sqrt(max(mean_var, 1e-9))

    # Bootstrap for an interval, so the number can be quoted with its own
    # uncertainty rather than to three false decimal places.
    import random

    rng = random.Random(0)
    boots = []
    for _ in range(2000):
        sample = [contributions[rng.randrange(len(contributions))] for _ in contributions]
        boots.append(math.sqrt(max(statistics.mean(sample), 1e-9)))
    boots.sort()
    lo, hi = boots[int(0.05 * len(boots))], boots[int(0.95 * len(boots))]

    print(f"pairs used                 {pairs}")
    print(f"candidates x institutes    {len(data)}")
    print()
    print(f"rw_sd_per_day (log share)  {sigma:.4f}   90% CI [{lo:.4f}, {hi:.4f}]")
    print()
    horizon = 223
    print(f"implied SD over {horizon} days   {sigma * math.sqrt(horizon):.3f} log units")
    for base in (0.33, 0.15):
        s = sigma * math.sqrt(horizon)
        print(
            f"  a candidate on {base:.0%} today -> 90% interval "
            f"[{base * math.exp(-1.645 * s):.1%}, {base * math.exp(1.645 * s):.1%}]"
        )
    print()
    print("Set config/model.yaml latent.rw_sd_per_day_prior to the fitted value.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
