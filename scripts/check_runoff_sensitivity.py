"""How much does the 2027 front-republicain term actually move a runoff?

`second_tour.front_republicain_2027_sd` is the model's honest home for its
largest substantive uncertainty: whether left and centre voters will still
cross the aisle to block the RN in May 2027. It cannot be measured - that
needs two cycles of transfers and only one exists - so it has to be *chosen*.

Choosing it blind would be arbitrary. This script makes the choice legible by
translating the parameter into the units a reader sees: points of runoff vote
share, for the matchups the forecast actually produces.

Run:  python scripts/check_runoff_sensitivity.py
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
from presidentielle.data import polls, surveys  # noqa: E402
from presidentielle.data.transfers import load as load_transfers  # noqa: E402
from presidentielle.model.design import build_model_data  # noqa: E402
from presidentielle.model.runoff import (  # noqa: E402
    build_runoff_data,
    build_runoff_model,
    predict_numpy,
)

FORECAST = ROOT / "site" / "data" / "forecast.json"


def main() -> int:
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
        data.runoffs,
        candidate_ids=data.candidate_ids,
        bloc_keys=data.bloc_keys,
        candidate_bloc=data.candidate_bloc,
        r1_shares=r1,
        roster=roster,
    )
    transfers, _ = load_transfers(results=load_results())

    import pymc as pm

    model = build_runoff_model(rdata, cfg, data.bloc_keys, transfers=transfers)
    with model:
        idata = pm.sample(
            draws=500, tune=500, chains=2, progressbar=False,
            random_seed=1, nuts_sampler="nutpie",
        )
    post = idata.posterior
    positions = post["positions"].mean(("chain", "draw")).values
    gamma = float(post["gamma"].mean())
    delta = float(post["delta_front_republicain"].mean())
    abstain = post["abstain"].mean(("chain", "draw")).values
    rn = data.bloc_keys.index("rn")

    print(f"fitted gamma {gamma:.2f}   delta {delta:.3f}")
    print(f"config front_republicain_2027_sd = {cfg.second_tour.front_republicain_2027_sd}")
    print()

    # Take the matchups the forecast says are most likely.
    duels = [d for d in fc["duels"][:5]]
    index = {c: i for i, c in enumerate(data.candidate_ids)}

    sd = cfg.second_tour.front_republicain_2027_sd
    offsets = [(-2 * sd, "-2sd"), (-sd, "-1sd"), (0.0, "fitted"), (sd, "+1sd"), (2 * sd, "+2sd")]

    print(f"{'matchup':44s} " + " ".join(f"{lab:>7s}" for _, lab in offsets))
    for d in duels:
        ia, ib = index.get(d["a"]), index.get(d["b"])
        if ia is None or ib is None:
            continue
        elim = r1.copy()
        elim[[ia, ib]] = 0.0
        source = np.zeros(len(data.bloc_keys))
        np.add.at(source, data.candidate_bloc, elim)
        row = []
        for off, _ in offsets:
            p = predict_numpy(
                positions=positions, gamma=gamma, delta=delta + off, abstain=abstain,
                pair_bloc=np.array([[data.candidate_bloc[ia], data.candidate_bloc[ib]]]),
                source_shares=np.array([source]),
                finalist_own=np.array([[r1[ia], r1[ib]]]),
                rn_index=rn,
            )[0]
            row.append(p)
        label = f"{d['nom_a']} v {d['nom_b']}"[:43]
        print(f"{label:44s} " + " ".join(f"{100*v:6.1f}%" for v in row))

    print()
    print("Read the spread between -1sd and +1sd as the share of the runoff that")
    print("hinges on how the front republicain behaves in 2027 rather than on")
    print("anything measurable today.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
