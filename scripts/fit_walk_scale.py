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

THE WALK IS NOT A RANDOM WALK, AND THE HORIZON MATTERS
-----------------------------------------------------
A Gaussian random walk implies that movement scales as sqrt(time), so the
per-day sigma must be the SAME whatever gap it is measured over. Measured on
2022, excluding rolling polls, it is not:

    gap (days)   sigma/day   implied over 221 days
      7-21        0.0157           0.234
     22-45        0.0307           0.457
     46-90        0.0290           0.431
     91-150       0.0261           0.388
    151-260       0.0222           0.329

Short gaps understate: even between separate surveys an institute reuses
panels and methods, so two readings a fortnight apart are more alike than two
independent draws on the same opinion. Long gaps then come down again, which is
mean reversion - a candidate who surges tends to give some of it back.

This was not a curiosity. Fitting on 7-60 day gaps gave 0.0142/day, and the
2022 backtest at 221 days out then covered **67% of outcomes in its 90%
intervals and 25% in its 50% intervals**. The forecast was overconfident
because the walk was calibrated at a horizon it is not used at.

So the fit is horizon-matched: the band used is the one closest to the distance
from the last poll to election day, which for this project is 151-260 days.
That is the same principle already applied to the election-day error, which is
fitted on final polls because that is when it is applied.

Run:  python scripts/fit_walk_scale.py
"""

from __future__ import annotations

import json
import math
import random
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

# The band the committed value is taken from: gaps of a length comparable to
# the forecast's own horizon. See the docstring - sigma/day is not constant, so
# the band has to match the distance the walk is actually asked to cover.
FIT_BAND = (151, 260)

# Every band reported, so the departure from sqrt(time) stays visible rather
# than being a claim in a comment.
BANDS = [(7, 21), (22, 45), (46, 90), (91, 150), (151, 260)]


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

    def sigma_for(lo: int, hi: int) -> tuple[float, int, list[float]]:
        vals: list[float] = []
        for points in data.values():
            for i in range(len(points)):
                for j in range(i + 1, len(points)):
                    (d1, p1, n1), (d2, p2, n2) = points[i], points[j]
                    gap = days_between(d1, d2)
                    if not lo <= gap <= hi:
                        continue
                    d = math.log(p2) - math.log(p1)
                    var1 = (1 - p1) / (n1 * p1)
                    var2 = (1 - p2) / (n2 * p2)
                    vals.append((d * d - var1 - var2) / gap)
        if not vals:
            return 0.0, 0, []
        return math.sqrt(max(statistics.mean(vals), 1e-9)), len(vals), vals

    horizon = 221
    print("A random walk implies ONE sigma/day at every gap length.")
    print(f"{'gap (days)':>12s} {'pairs':>7s} {'sigma/day':>11s} {'over 221d':>11s}")
    for lo, hi in BANDS:
        sd, n, _ = sigma_for(lo, hi)
        if n < 25:
            print(f"{f'{lo}-{hi}':>12s} {n:>7d}   (too few)")
            continue
        mark = "  <- fitted" if (lo, hi) == FIT_BAND else ""
        print(
            f"{f'{lo}-{hi}':>12s} {n:>7d} {sd:>11.4f} {sd * math.sqrt(horizon):>11.3f}{mark}"
        )

    sigma, pairs, contributions = sigma_for(*FIT_BAND)
    if pairs < 50:
        sys.exit(f"only {pairs} pairs in the fitted band - not enough")

    rng = random.Random(0)
    boots = []
    for _ in range(2000):
        sample = [contributions[rng.randrange(len(contributions))] for _ in contributions]
        boots.append(math.sqrt(max(statistics.mean(sample), 1e-9)))
    boots.sort()
    lo_ci, hi_ci = boots[int(0.05 * len(boots))], boots[int(0.95 * len(boots))]

    print()
    print(f"FITTED on gaps of {FIT_BAND[0]}-{FIT_BAND[1]} days, matching the forecast horizon:")
    print(f"  rw_sd_per_day  {sigma:.4f}   90% CI [{lo_ci:.4f}, {hi_ci:.4f}]   ({pairs} pairs)")
    print()
    s_h = sigma * math.sqrt(horizon)
    print(f"  implied SD over {horizon} days: {s_h:.3f} log units")
    for base in (0.33, 0.15):
        print(
            f"    a candidate on {base:.0%} today -> 90% interval "
            f"[{base * math.exp(-1.645 * s_h):.1%}, {base * math.exp(1.645 * s_h):.1%}]"
        )
    print()
    print("Split in quadrature between latent.rw_sd_per_day_prior and")
    print("latent.bloc_rw_sd_per_day_prior, and update fitted_total_rw_sd_per_day.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
