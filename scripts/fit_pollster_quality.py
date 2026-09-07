"""Do French institutes differ in accuracy by enough to weight them?

MEASURED, THEN REJECTED. The answer is no, and this script is what makes that
checkable rather than an assertion in a comment.

WHY IT WAS TRIED
----------------
The sibling US model scales each poll's non-sampling noise by its pollster's
538 predictive record, so a house with a worse history is trusted less. There is
no equivalent published rating for French institutes, but their 2022 accuracy is
computable from the archive plus the proclaimed result, so the rating could in
principle be built here.

WHAT THE RAW NUMBERS LOOK LIKE
------------------------------
Tempting. On final 2022 polls, RMS log error across the major candidates ranges
from 0.137 (Harris) to 0.280 (Atlasintel) - a factor of two between best and
worst, which looks like a real difference in quality.

WHY IT IS NOT ONE
-----------------
Almost all of that error is **shared**. Every institute missed the same
candidates in the same direction: Melenchon low, Pecresse high. Removing the
per-candidate mean leaves only 13% of the original variance, and the spread
between institutes in what remains is indistinguishable from chance -
permutation p = 0.85.

There are eleven institutes and four major candidates, so a house's "record" is
four numbers, and four numbers cannot separate skill from luck. Worse, the four
are not independent draws: they are one correlated story about the 2022
campaign. Weighting on this would rank institutes by how well they fit a single
election's idiosyncrasies and present that as quality.

The one institute that does stand apart, Atlasintel, is not in the 2027 field.

WHAT THIS DOES SUPPORT
----------------------
A negative result about house effects is a positive result about model
structure: since the miss is overwhelmingly per-candidate rather than
per-institute, election-day error belongs at the candidate level, which is
where the model already puts it.

Run:  python scripts/fit_pollster_quality.py
"""

from __future__ import annotations

import json
import math
import os
import random
import statistics
import sys
from pathlib import Path

os.environ.setdefault("PYTENSOR_FLAGS", "cxx=")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from presidentielle.calibration import (  # noqa: E402
    ARCHIVE,
    MAJOR_SHARE,
    _actual_shares,
    _first_round_polls,
    load_results,
)

PERMUTATIONS = 5000


def main() -> int:
    if not ARCHIVE.exists():
        sys.exit(f"missing {ARCHIVE}; see scripts/fit_walk_scale.py for the fetch command")
    payload = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    results = load_results()
    actual = _actual_shares(results, "premier_tour")

    polls = _first_round_polls(payload, results, results["premier_tour"]["date"])
    latest: dict[str, dict] = {}
    for p in polls:
        cur = latest.get(p["institut"])
        if cur is None or p["fin"] > cur["fin"]:
            latest[p["institut"]] = p

    cands = [c for c in actual if actual[c] >= MAJOR_SHARE]
    errors: dict[tuple[str, str], float] = {}
    for inst, p in latest.items():
        for c in cands:
            s = p["shares"].get(c)
            if s and s > 0:
                errors[(inst, c)] = math.log(s) - math.log(actual[c])

    insts = sorted(latest)
    print(f"{len(insts)} institutes x {len(cands)} major candidates = {len(errors)} cells")
    print()
    print("Raw accuracy, final 2022 poll (RMS log error):")
    raw = {}
    for inst in insts:
        e = [errors[(inst, c)] for c in cands if (inst, c) in errors]
        raw[inst] = math.sqrt(statistics.mean([x * x for x in e]))
    for inst, v in sorted(raw.items(), key=lambda kv: kv[1]):
        print(f"  {inst:22s} {v:.3f}")
    print(f"  worst / best = {max(raw.values()) / min(raw.values()):.2f}x")
    print()

    # Strip the miss that every institute shared.
    cmean = {
        c: statistics.mean([errors[(i, c)] for i in insts if (i, c) in errors])
        for c in cands
    }
    resid = {k: v - cmean[k[1]] for k, v in errors.items()}

    var_raw = statistics.pvariance(list(errors.values()))
    var_res = statistics.pvariance(list(resid.values()))
    print(f"variance of raw errors     {var_raw:.4f}")
    print(f"variance after demeaning   {var_res:.4f}")
    print(f"  => {100 * (1 - var_res / var_raw):.0f}% of the 2022 miss was COMMON to every institute")
    print()

    def between(r: dict[tuple[str, str], float]) -> float:
        means = {
            i: statistics.mean([r[(i, c)] for c in cands if (i, c) in r]) for i in insts
        }
        return statistics.pvariance(list(means.values()))

    observed = between(resid)
    rng = random.Random(0)
    values = list(resid.values())
    hits = 0
    for _ in range(PERMUTATIONS):
        shuffled = values[:]
        rng.shuffle(shuffled)
        permuted = {k: shuffled[i] for i, k in enumerate(resid)}
        if between(permuted) >= observed:
            hits += 1
    p_value = hits / PERMUTATIONS

    print(f"between-institute variance of demeaned error  {observed:.5f}")
    print(f"permutation p-value                           {p_value:.3f}  (B={PERMUTATIONS})")
    print()
    print("institute effect (demeaned mean log error, + = over-read):")
    def effect(inst: str) -> float:
        return statistics.mean(
            [resid[(inst, c)] for c in cands if (inst, c) in resid]
        )

    for inst in sorted(insts, key=effect):
        print(f"  {inst:22s} {effect(inst):+.3f}")
    print()

    if p_value < 0.05:
        print("VERDICT: institutes differ measurably. Revisit the rejection in")
        print("CLAUDE.md before acting - and note the sibling model's invariant that")
        print("quality multipliers must be centred so their poll-weighted mean is 1.0,")
        print("or the overall level of trust changes as a side effect.")
    else:
        print("VERDICT: no measurable difference between institutes (p >= 0.05).")
        print("Weighting them would fit one election's idiosyncrasies and call it")
        print("quality. Not implemented; see CLAUDE.md, 'Measured, then rejected'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
