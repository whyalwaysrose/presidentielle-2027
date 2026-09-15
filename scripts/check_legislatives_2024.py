"""What do the 2024 legislative duels do to the runoff model, and can it be trusted?

Folding a legislative election into a presidential forecast is the kind of
change that can move a published headline for a bad reason. This script is the
evidence about whether it does, and it is meant to be re-run rather than
believed.

It refits the runoff transfer model under several configurations and prints,
for each, the things that would reveal a problem:

* **fit to the hypothetical 2027 matchups.** These are the only direct evidence
  about 2027 runoffs. If adding 2024 wrecks this, the two sources are making
  incompatible claims and the model is picking a winner rather than pooling.
* **gamma against gamma_2024, and `adj`.** How sharply voters discriminate by
  ideological distance, nationally and in the duels; and the legislative front
  republicain as a shift on delta. Together they are the legislative-versus-
  presidential difference, and together is the only way to read them.
* **the headline runoff shares**, which is what a reader actually sees.
* **sampler diagnostics**, because the partial-pooling terms sit on a model
  with a known history of identifiability ridges.

WHAT IT ESTABLISHED
-------------------
Sharing the geometry outright - the obvious implementation, and the first one
tried - is not an option. 317 local duels outvote the presidential evidence on
every shared parameter: the fitted RN position collapses from +1.07 to +0.54,
putting the RN nearer the centre than the mainstream right, and the fit to the
2027 matchups falls apart. The `pooled` row below reproduces that on demand.

Under every DEFENSIBLE setting of the pooling scales, the 2024 duels move the
published runoff shares by about a point. The reason is in the `g_2024` and
`adj` columns: a legislative duel transfers against the RN much harder, and
discriminates less sharply by ideology, than a presidential runoff does -
exactly what a local election full of incumbents, personal votes and
desistements should look like. Once that difference is allowed, 2024 stops
contradicting the presidential geometry, and stops being evidence that the
geometry is wrong.

Read `g_2024` and `adj` TOGETHER, never separately. They are partly
interchangeable, and which one carries the difference moves between fits while
the total stays put.

THE SENSITIVITY THAT MATTERS
----------------------------
134 of 317 duels have a Nouveau Front populaire opponent, and the Ministry file
does not say which party each one came from. They are placed at the NFP's
published nomination split. `ug=LFI` and `ug=PS` rerun everything with that
mixture pushed to either extreme; the spread between those rows is the size of
that assumption, in points of runoff share.

Run:  python scripts/check_legislatives_2024.py
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import replace
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
from presidentielle.model.runoff import (  # noqa: E402
    build_runoff_data,
    build_runoff_model,
    predict_numpy,
)

FORECAST = ROOT / "site" / "data" / "forecast.json"

# Runoffs to report. The RN's share is printed, so a rise is a rise for the RN.
PAIRS = [("MLP", "EP"), ("MLP", "JLM"), ("MLP", "RG"), ("MLP", "GA"), ("MLP", "BR")]

# label, nfp split override, config overrides
RUNS = [
    ("off (2022 + 2027)", "none", {}),
    ("pooled outright", "nfp", dict(
        legislative_position_sd=1e-3, legislative_gamma_log_sd=1e-3,
        legislative_abstention_sd=1e-3)),
    ("as configured", "nfp", {}),
    ("  positions tight", "nfp", dict(legislative_position_sd=0.03)),
    ("  positions loose", "nfp", dict(legislative_position_sd=0.25)),
    ("  gamma shared", "nfp", dict(legislative_gamma_log_sd=0.05)),
    ("  ug = pure LFI", "lfi", {}),
    ("  ug = pure PS", "ps", {}),
]

UG_VARIANTS = {
    "nfp": None,
    "lfi": {"gauche_radicale": 1.0},
    "ps": {"socialiste": 1.0},
}


def main() -> int:
    import arviz as az
    import pymc as pm

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
    rn = data.bloc_keys.index("rn")
    index = {c: i for i, c in enumerate(data.candidate_ids)}
    pairs = [(a, b) for a, b in PAIRS if a in index and b in index]

    def runoff_shares(positions, gamma, delta, abstain):
        """RN share of each reported matchup, at the posterior mean."""
        out = {}
        for a, b in pairs:
            ia, ib = index[a], index[b]
            elim = r1.copy()
            elim[[ia, ib]] = 0.0
            src = np.zeros(len(data.bloc_keys))
            np.add.at(src, data.candidate_bloc, elim)
            out[f"{a} v {b}"] = predict_numpy(
                positions=positions, gamma=gamma, delta=delta, abstain=abstain,
                pair_bloc=np.array(
                    [[data.candidate_bloc[ia], data.candidate_bloc[ib]]]
                ),
                source_shares=np.array([src]),
                finalist_own=np.array([[r1[ia], r1[ib]]]),
                rn_index=rn,
            )[0]
        return out

    rows = []
    for label, ug, over in RUNS:
        run_cfg = (
            cfg if not over
            else replace(cfg, second_tour=replace(cfg.second_tour, **over))
        )
        duels = (
            None if ug == "none"
            else legislatives_2024.build(data.bloc_keys, nfp_split=UG_VARIANTS[ug])
        )
        model = build_runoff_model(
            rdata, run_cfg, data.bloc_keys, transfers=transfers, duels_2024=duels
        )
        with model:
            idata = pm.sample(
                draws=500, tune=500, chains=4, progressbar=False,
                random_seed=1, nuts_sampler="nutpie",
            )
        post = idata.posterior
        positions = post["positions"].mean(("chain", "draw")).values
        gamma = float(post["gamma"].mean())
        delta = float(post["delta_front_republicain"].mean())
        abstain = post["abstain"].mean(("chain", "draw")).values
        resid = post["mu"].mean(("chain", "draw")).values - rdata.y
        summary = az.summary(
            idata,
            var_names=["positions", "gamma", "abstain", "delta_front_republicain"],
        )
        rows.append({
            "label": label,
            "mae": 100 * float(np.abs(resid).mean()),
            "gamma": gamma,
            "gamma24": float(post["gamma_2024"].mean())
            if "gamma_2024" in post else None,
            "delta": delta,
            "adj": float(post["ajustement_legislatif"].mean())
            if "ajustement_legislatif" in post else None,
            "rhat": float(summary["r_hat"].max()),
            "ess": float(summary["ess_bulk"].min()),
            "positions": positions,
            "shares": runoff_shares(positions, gamma, delta, abstain),
        })
        print(f"fitted: {label}", file=sys.stderr)

    names = list(rows[0]["shares"])
    w = 20

    def opt(v, fmt, width):
        return format(v, fmt) if v is not None else format("-", f">{width}")

    print()
    print("FIT TO THE HYPOTHETICAL 2027 MATCHUPS - the only direct 2027 evidence")
    print(f"{'':{w}} {'MAE':>7} {'gamma':>7} {'g_2024':>7} {'delta':>7} "
          f"{'adj':>7} {'rhat':>6} {'ESS':>6}")
    for r in rows:
        print(f"{r['label']:{w}} {r['mae']:6.2f}p {r['gamma']:7.2f} "
              f"{opt(r['gamma24'], '7.2f', 7)} {r['delta']:7.3f} "
              f"{opt(r['adj'], '7.3f', 7)} {r['rhat']:6.3f} {r['ess']:6.0f}")

    print()
    print("RN SHARE OF THE RUNOFF, at the posterior mean")
    print(f"{'':{w}} " + " ".join(f"{n:>12}" for n in names))
    for r in rows:
        print(f"{r['label']:{w}} " + " ".join(
            f"{100 * r['shares'][n]:11.1f}%" for n in names))

    print()
    print("BLOC POSITIONS, left to right")
    print(f"{'':{w}} " + " ".join(f"{b[:7]:>8}" for b in data.bloc_keys))
    for r in rows:
        print(f"{r['label']:{w}} " + " ".join(f"{v:8.2f}" for v in r["positions"]))

    print()
    print("HOW TO READ THIS")
    print("  * `pooled outright` is the version that does not work, kept so the")
    print("    claim is checkable. Watch the RN position collapse towards the")
    print("    centre and the fit to the 2027 matchups fall apart.")
    print("  * g_2024 and `adj` TOGETHER are the substance: a legislative duel")
    print("    transfers against the RN harder (adj positive - desistements")
    print("    concentrated the anti-RN vote) and discriminates less sharply by")
    print("    ideology (g_2024 below gamma - incumbency and personal votes).")
    print("    That is what reconciles 2024 with the 2027 polls, NOT a claim")
    print("    that either source is wrong.")
    print("  * Do not quote the SPLIT between them. They are partly")
    print("    interchangeable and it is not sharply identified - it moves")
    print("    between fits while the total stays put.")
    print("  * The spread between `ug = pure LFI` and `ug = pure PS` is the cost")
    print("    of not knowing which party each NFP candidate came from.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
