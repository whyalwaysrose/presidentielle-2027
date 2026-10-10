"""How often does the runoff fit get stuck, and is the stuck state a real mode?

WHY THIS EXISTS
---------------
The runoff fit decides P(win), and about one run in ten it misses: three chains
agree to two decimals and a fourth sits somewhere else entirely. That used to
be recorded in this repo as "the fit is bimodal", which was wrong, and the
wrong description led to two wasted fixes. This script is what settled it, and
re-running it is how anyone can check the claim rather than believe it.

WHAT IT MEASURES
----------------
1. **The miss rate**, at production settings across a run of seeds. A miss is
   r-hat above 1.05 or bulk ESS below 200 on the geometry parameters.
2. **What the stuck chain is**, when one appears: its log-likelihood against
   the healthy chains', and its bloc positions beside theirs.

WHAT IT FOUND, 2026-10-09 (before the ordered axis; re-run it to see today's)
-----------------------------------------------------------------------------
One seed in ten missed. In that run three chains sat at gamma 3.72, 3.72, 3.75
and one at 12.04. The stuck chain fitted **21 log units worse** - about a
billion times less likely - and had the left-right axis scrambled: the radical
left placed to the RIGHT of the socialists, the mainstream right to the LEFT of
the centre, roughly 8 sigma from its own prior.

So it is not a second mode. A chain wanders into high gamma during warm-up, the
proximity softmax saturates, the gradients flatten, and it can no longer move
positions back past one another. `presidentielle run` therefore retries with
another seed, and still fails closed if every attempt misses.

FIXES TRIED AND REJECTED, so nobody repeats them:

* **`initvals`** - nutpie ignores them. The output was identical to baseline
  digit for digit, including the stuck chain's 12.04. A "fix" that changes
  nothing is worse than none, because it looks like progress.
* **An `ordered` transform on the positions** - THIS IS NOW THE FIX, and this
  note used to say the opposite. The first attempt ordered the vector in the
  ROSTER's order, which is not monotonic (socialiste -0.35 is listed before
  ecologiste -0.45), so the transform got a non-increasing starting point and
  nutpie reported "All initialization points failed". That was recorded as
  nutpie being incompatible. It was not. Ordered in SORTED space and permuted
  back, the miss rate goes to 0 in 10 and bulk ESS roughly doubles. The fear
  that it would bind on real data was also unfounded: the fit resolves the
  near-tie between the centre and the socialists in the expected order.
* Earlier, and separately, **removing the scale ridge** (centring and scaling
  the position vector): no effect on the miss rate. See CLAUDE.md.

Run:  python scripts/check_runoff_convergence.py [n_seeds]
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PYTENSOR_FLAGS", "cxx=")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from presidentielle.calibration import load_results  # noqa: E402
from presidentielle.config import load_model_config, load_roster  # noqa: E402
from presidentielle.data import legislatives_2024, polls, surveys  # noqa: E402
from presidentielle.data.transfers import load as load_transfers  # noqa: E402
from presidentielle.model.design import build_model_data  # noqa: E402
from presidentielle.model.runoff import build_runoff_data, build_runoff_model  # noqa: E402

FORECAST = ROOT / "site" / "data" / "forecast.json"
GEOMETRY = ["positions", "gamma", "abstain", "delta_front_republicain"]


def main() -> int:
    import arviz as az
    import pymc as pm

    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    cfg = load_model_config()
    roster = load_roster()
    hyps, _ = polls.load(roster=roster, history_start=cfg.polls.history_start)
    weighted = surveys.weight(hyps, exponent=cfg.observation.survey_weight_exponent)
    data = build_model_data(weighted, cfg=cfg, roster=roster)

    if not FORECAST.exists():
        sys.exit("run `presidentielle run` first - this needs its first-round shares")
    fc = json.loads(FORECAST.read_text(encoding="utf-8"))
    med = {c["id"]: (c["share"]["q50"] or 0.0) for c in fc["candidats"]}
    r1 = np.array([med.get(c, 0.0) for c in data.candidate_ids])

    rdata = build_runoff_data(
        data.runoffs, candidate_ids=data.candidate_ids, bloc_keys=data.bloc_keys,
        candidate_bloc=data.candidate_bloc, r1_shares=r1, roster=roster,
    )
    transfers, _ = load_transfers(results=load_results())
    duels = legislatives_2024.build(data.bloc_keys)

    print(f"production settings: draws={cfg.sampling.draws}, tune={cfg.sampling.tune}, "
          f"chains={cfg.sampling.chains}; a miss is r-hat > 1.05 or bulk ESS < 200")
    print(f"\n{'seed':>10} {'r-hat':>7} {'ESS':>7} {'per-chain gamma':>34}")

    misses = []
    seeds = [cfg.sampling.seed + 1] + list(range(1, n_seeds))
    for seed in seeds:
        model = build_runoff_model(
            rdata, cfg, data.bloc_keys, transfers=transfers, duels_2024=duels
        )
        with model:
            idata = pm.sample(
                draws=cfg.sampling.draws, tune=cfg.sampling.tune,
                chains=cfg.sampling.chains, target_accept=cfg.sampling.target_accept,
                random_seed=seed, progressbar=False, nuts_sampler="nutpie",
            )
        summary = az.summary(idata, var_names=GEOMETRY)
        rhat = float(summary["r_hat"].max())
        ess = float(summary["ess_bulk"].min())
        gammas = idata.posterior["gamma"].mean("draw").values
        missed = rhat > 1.05 or ess < 200
        if missed:
            misses.append((seed, idata, gammas))
        print(f"{seed:>10} {rhat:7.3f} {ess:7.0f} "
              f"{np.array2string(np.round(gammas, 2)):>34}"
              f"{'   <== MISS' if missed else ''}", flush=True)

    print(f"\n{len(misses)} of {len(seeds)} seeds missed")
    if not misses:
        print("No stuck chain this time - re-run with more seeds to catch one.")
        return 0

    # Anatomy of the first miss: is the odd chain a rival answer, or trapped?
    seed, idata, gammas = misses[0]
    print(f"\n--- anatomy of seed {seed} " + "-" * 40)
    with build_runoff_model(
        rdata, cfg, data.bloc_keys, transfers=transfers, duels_2024=duels
    ):
        pm.compute_log_likelihood(idata, progressbar=False)
    per_chain = sum(
        da.sum(dim=[d for d in da.dims if d not in ("chain", "draw")]).mean("draw").values
        for da in idata.log_likelihood.values()
    )
    odd = int(np.argmax(np.abs(gammas - np.median(gammas))))
    healthy = [c for c in range(len(gammas)) if c != odd]
    best = max(healthy, key=lambda c: per_chain[c])
    print(f"odd chain {odd}: gamma {gammas[odd]:.2f}, log-likelihood {per_chain[odd]:,.1f}")
    print(f"healthy chain {best}: gamma {gammas[best]:.2f}, "
          f"log-likelihood {per_chain[best]:,.1f}")
    gap = per_chain[best] - per_chain[odd]
    print(f"the odd chain fits {gap:,.0f} log units worse "
          f"(about e^{gap:,.0f} times less likely) - not a rival answer")

    pos = idata.posterior["positions"].mean("draw").values
    print(f"\n{'bloc':16} {'odd':>8} {'healthy':>8}   (is the axis still in order?)")
    for i, bloc in enumerate(data.bloc_keys):
        print(f"{bloc:16} {pos[odd][i]:8.2f} {pos[best][i]:8.2f}")
    ordered_odd = all(np.diff(pos[odd]) > 0)
    ordered_ok = all(np.diff(pos[best]) > 0)
    print(f"\nleft-to-right ordering intact?  odd chain: {ordered_odd}   "
          f"healthy chain: {ordered_ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
