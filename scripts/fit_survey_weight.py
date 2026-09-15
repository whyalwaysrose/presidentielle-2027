"""Fit `observation.survey_weight_exponent` instead of asserting it.

WHAT THE PARAMETER DOES
-----------------------
A French survey prices several candidate fields off one sample, so its
hypotheses are not independent observations. Each one's effective sample is
scaled by ``m ** -exponent`` where ``m`` is how many that survey priced:

    1.0   the sample is divided evenly between them - fully redundant
    0.0   each is a fresh survey - fully independent

It was set to 0.65 by judgement and never fitted.

WHY IT CANNOT BE MEASURED DIRECTLY
----------------------------------
The obvious approach - compare hypotheses within one survey and see how much
they disagree - does not work, because they *should* disagree: they price
different candidate fields, and the whole point of the nested logit is that the
field changes the shares. Disagreement is confounded with the thing being
modelled, so redundancy cannot be read off it.

So it is fitted against out-of-sample performance instead, on the 2022 cycle,
holding every other setting fixed.

WHY THIS MATTERS, MEASURED
--------------------------
At 0.65 the median effective sample falls from 1,501 to 490, which makes the
model treat each poll as about 2.4 points noisy. French institutes polling the
same field within three weeks of each other actually differ by **0.68 points**.
The model is distrusting individual polls roughly three and a half times more
than they disagree.

Some of that distrust is right: institutes agree closely with each other and
are wrong together - 87% of the 2022 miss was common to all of them
(`fit_pollster_quality.py`). But shared error belongs in `election_day_error`,
where it is fitted. Inflating *per-poll* noise instead makes the latent state
sluggish, and sluggishness has a cost the backtest already showed: at 30 days
out the model had Melenchon on 11.6% when he finished on 22%, having failed to
follow a real late surge.

WHAT IS SCORED
--------------
CRPS on the actual first-round result, which is a proper score and rewards
being both well-centred and appropriately confident, plus coverage and MAE for
readability. The 30-day cutoff carries the most weight for this parameter,
because that is where responsiveness to recent polling shows up.

Run:  python scripts/fit_survey_weight.py
      python scripts/fit_survey_weight.py --draws 300 --quick
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("PYTENSOR_FLAGS", "cxx=")

ROOT = Path(__file__).resolve().parents[1]

EXPONENTS = [0.0, 0.35, 0.65, 1.0]
CUTOFFS = ["2021-09-01", "2022-03-11"]


def run_one(as_of: str, exponent: float, draws: int) -> dict | None:
    out = Path(tempfile.gettempdir()) / f"bt_{as_of}_{exponent:.2f}.json"
    cmd = [
        sys.executable, "-m", "presidentielle.cli", "backtest",
        "--as-of", as_of,
        "--weight-exponent", str(exponent),
        "--quiet",
        "--json", str(out),
    ]
    if draws:
        cmd += ["--draws", str(draws)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTENSOR_FLAGS="cxx=")
    proc = subprocess.run(
        cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0 or not out.exists():
        print(f"  FAILED exponent={exponent} as_of={as_of}")
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
        for line in tail:
            print(f"    {line}")
        return None
    return json.loads(out.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--draws", type=int, default=400)
    ap.add_argument("--quick", action="store_true", help="only the 30-day cutoff")
    args = ap.parse_args()

    cutoffs = CUTOFFS[-1:] if args.quick else CUTOFFS
    results: dict[tuple[str, float], dict] = {}

    for as_of in cutoffs:
        for e in EXPONENTS:
            print(f"running as_of={as_of} exponent={e:.2f} ...", flush=True)
            r = run_one(as_of, e, args.draws)
            if r:
                results[(as_of, e)] = r

    if not results:
        sys.exit("no runs completed")

    print()
    print(f"{'cutoff':<12} {'exp':>5} {'CRPS':>7} {'MAE':>6} {'cov90':>6} {'cov50':>6} {'P(win)':>7}")
    for as_of in cutoffs:
        for e in EXPONENTS:
            r = results.get((as_of, e))
            if not r:
                continue
            print(
                f"{as_of:<12} {e:>5.2f} {r['crps_points']:>7.3f} {r['mae_points']:>6.2f} "
                f"{r['coverage_90']:>6.0%} {r['coverage_50']:>6.0%} {r['p_win_actual']:>7.0%}"
            )
        print()

    # CRPS is the score that decides; the 30-day cutoff is where this parameter
    # actually bites, so it is not averaged away against the long horizon.
    print("Ranking by CRPS (lower is better):")
    for as_of in cutoffs:
        ranked = sorted(
            ((e, results[(as_of, e)]["crps_points"]) for e in EXPONENTS if (as_of, e) in results),
            key=lambda kv: kv[1],
        )
        if ranked:
            best = ranked[0]
            print(f"  {as_of}: " + ", ".join(f"{e:.2f}={c:.3f}" for e, c in ranked))
            print(f"    best = {best[0]:.2f}")
    print()
    print("Set observation.survey_weight_exponent to the winner and re-run the")
    print("backtest at full draws to confirm, then update the config comment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
