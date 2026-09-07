"""The second round: where first-round votes go once the field collapses to two.

A French presidential forecast is not finished when it has first-round shares.
The president is whoever wins the runoff two weeks later, and a candidate can
lead the first round comfortably and still lose it - which is exactly what the
polls say about the RN.

WHY NOT JUST USE THE RUNOFF POLLS
---------------------------------
Institutes do test runoffs: 54 second-round hypotheses covering 11 matchups.
But the runoff that happens will be whichever pair finishes top two, and the
model needs a number for pairs nobody has tested. Reading the polls off
directly answers the wrong question.

WHAT IS FITTED
--------------
A transfer model. Each bloc sits at a latent left-right position, and a voter
whose first-round candidate is eliminated chooses between the two finalists,
or abstains, by proximity::

    u(voter bloc j -> finalist in bloc k) = -gamma * (x_j - x_k)^2 - delta * [k is RN]
    u(voter bloc j -> abstention)         = w_j

    P(j -> A) = softmax over {A, B, abstain}

The distance term is **squared**, not absolute. That is the canonical
quadratic-loss utility of spatial voting theory, and it is also the difference
between a model that samples and one that does not: ``|x_j - x_k|`` has a kink
wherever a voter bloc sits exactly on a finalist, the gradient is undefined
there, and NUTS grinds against it. Measured: with the absolute value, four
chains over twenty parameters and fifty-four observations had not finished
after twenty minutes; squared, the same fit takes seconds.

``delta`` is the *front republicain*: the extra reluctance to transfer to an RN
finalist, over and above ideological distance. It is one number, estimated from
the runoff polls, and it is the single most consequential parameter in the
model - the difference between the RN winning and losing is largely the
difference between the 2022 value of this and a smaller one.

Nine positions, nine abstention terms, gamma and delta is twenty parameters
against fifty-four observations. That is why it is a proximity model rather
than a free 9x9 transfer matrix, which would have eighty-one.

TWO-STAGE, AND WHY THAT IS ACCEPTABLE
-------------------------------------
This is fitted after the first-round model, taking that model's posterior mean
first-round shares as the input each runoff poll implies. Fitting both at once
would be cleaner in principle, but the second-round polls carry almost no
information about first-round shares - they name two candidates and ask a
different question - so the feedback that a joint fit would capture is
negligible, while the joint model is markedly harder to sample and to debug.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pymc as pm
import pytensor.tensor as pt

from ..config import ModelConfig, Roster

log = logging.getLogger(__name__)

# Prior ordering of the blocs on the left-right axis. The model estimates the
# positions; this only says which way round they start and stops the axis from
# flipping sign, which it otherwise could with no change to the likelihood.
PRIOR_POSITIONS = {
    "extreme_gauche": -1.00,
    "gauche_radicale": -0.75,
    "ecologiste": -0.45,
    "socialiste": -0.35,
    "centre": 0.00,
    "droite": 0.45,
    "souverainiste": 0.65,
    "reconquete": 0.90,
    "rn": 1.00,
}


@dataclass(frozen=True)
class RunoffData:
    pair_bloc: np.ndarray  # (M, 2) int, bloc index of each finalist
    pair_cand: np.ndarray  # (M, 2) int, candidate index of each finalist
    source_shares: np.ndarray  # (M, K) first-round share by bloc, eliminated only
    finalist_own: np.ndarray  # (M, 2) each finalist's own first-round share
    y: np.ndarray  # (M,) observed share for finalist 0
    n: np.ndarray  # (M,) effective sample
    labels: list[str]


def build_runoff_data(
    runoffs: list[dict],
    *,
    candidate_ids: list[str],
    bloc_keys: list[str],
    candidate_bloc: np.ndarray,
    r1_shares: np.ndarray,
    roster: Roster,
) -> RunoffData:
    """Assemble runoff observations.

    ``r1_shares`` is the posterior-mean first-round share per candidate on
    election day, under the model's own ballot. It is used to say how many
    votes each bloc has to transfer in each tested matchup.
    """
    cand_index = {c: i for i, c in enumerate(candidate_ids)}
    K = len(bloc_keys)

    pair_bloc, pair_cand, source, own, y, n, labels = [], [], [], [], [], [], []
    for rec in runoffs:
        ids = sorted(rec["shares"])
        if len(ids) != 2 or any(c not in cand_index for c in ids):
            continue
        a, b = ids
        ia, ib = cand_index[a], cand_index[b]

        # Everyone not in the runoff has votes to transfer. Their bloc totals
        # are what the transfer model acts on.
        elim = np.ones(len(candidate_ids), dtype=bool)
        elim[[ia, ib]] = False
        by_bloc = np.zeros(K)
        np.add.at(by_bloc, candidate_bloc[elim], r1_shares[elim])

        pair_bloc.append([candidate_bloc[ia], candidate_bloc[ib]])
        pair_cand.append([ia, ib])
        source.append(by_bloc)
        own.append([r1_shares[ia], r1_shares[ib]])
        y.append(rec["shares"][a])
        n.append(rec["n_effective"])
        labels.append(f"{roster.candidats[a].nom} vs {roster.candidats[b].nom}")

    if not y:
        raise ValueError("no usable second-round hypotheses")

    return RunoffData(
        pair_bloc=np.array(pair_bloc, dtype="int64"),
        pair_cand=np.array(pair_cand, dtype="int64"),
        source_shares=np.array(source, dtype="float64"),
        finalist_own=np.array(own, dtype="float64"),
        y=np.array(y, dtype="float64"),
        n=np.array(n, dtype="float64"),
        labels=labels,
    )


def _predict(
    positions: pt.TensorVariable,
    gamma: pt.TensorVariable,
    delta: pt.TensorVariable,
    abstain: pt.TensorVariable,
    pair_bloc,
    source_shares,
    finalist_own,
    rn_index: int,
):
    """Share of expressed votes for finalist 0."""
    xa = positions[pair_bloc[:, 0]][:, None]  # (M, 1)
    xb = positions[pair_bloc[:, 1]][:, None]
    xj = positions[None, :]  # (1, K)

    is_rn_a = pt.eq(pair_bloc[:, 0], rn_index)[:, None]
    is_rn_b = pt.eq(pair_bloc[:, 1], rn_index)[:, None]

    ua = -gamma * (xj - xa) ** 2 - delta * is_rn_a  # (M, K)
    ub = -gamma * (xj - xb) ** 2 - delta * is_rn_b
    uw = pt.tile(abstain[None, :], (ua.shape[0], 1))

    stack = pt.stack([ua, ub, uw], axis=2)  # (M, K, 3)
    p = pt.special.softmax(stack, axis=2)

    to_a = (source_shares * p[:, :, 0]).sum(axis=1) + finalist_own[:, 0]
    to_b = (source_shares * p[:, :, 1]).sum(axis=1) + finalist_own[:, 1]
    # Runoff polls report shares of *expressed* votes, so abstention drops out
    # of the denominator rather than counting against either finalist.
    return to_a / (to_a + to_b)


def _transfer_probs(positions, gamma, delta, abstain, bloc_a, bloc_b, rn_index):
    """(K, 3) probabilities that each bloc's voters go to A, to B, or abstain.

    The same arithmetic the aggregate predictor uses, exposed per bloc because
    the 2022 measurements are per bloc: institutes asked Melenchon voters where
    they were going, and that is a direct observation of this quantity rather
    than of the aggregate it implies.
    """
    xa = positions[bloc_a]
    xb = positions[bloc_b]
    ua = -gamma * (positions - xa) ** 2 - delta * (1.0 if bloc_a == rn_index else 0.0)
    ub = -gamma * (positions - xb) ** 2 - delta * (1.0 if bloc_b == rn_index else 0.0)
    return pt.special.softmax(pt.stack([ua, ub, abstain], axis=1), axis=1)


def build_runoff_model(
    data: RunoffData,
    cfg: ModelConfig,
    bloc_keys: list[str],
    transfers=None,
) -> pm.Model:
    """Fit the transfer model, optionally anchored on the 2022 measurements.

    Two cycles, one structure. Bloc positions, the proximity weight and each
    bloc's readiness to abstain are treated as properties of French politics
    and shared. The front republicain is NOT: whether voters will still cross
    the aisle to block the RN in 2027 as they did in 2022 is the open question,
    so it gets one value per cycle and a prior linking them.
    """
    rn_index = bloc_keys.index("rn")
    centre_index = bloc_keys.index("centre")
    prior_x = np.array([PRIOR_POSITIONS[b] for b in bloc_keys])

    coords = {"bloc": bloc_keys, "obs": data.labels}
    if transfers is not None:
        coords["transfert"] = [
            f"{o.source_candidate} ({o.institut})" for o in transfers
        ]

    with pm.Model(coords=coords) as model:
        # Positions are anchored by an informative prior on the known ordering
        # and allowed to move; without an anchor the axis can reflect and every
        # distance is unchanged.
        # Tighter than the 0.25 first used. Loose positions and delta are
        # partly confounded - moving the RN further right acts exactly like an
        # RN penalty - and at 0.25 the positions simply absorbed it.
        positions = pm.Normal("positions", mu=prior_x, sigma=0.12, dims="bloc")
        gamma = pm.HalfNormal("gamma", sigma=3.0)
        abstain = pm.Normal("abstain", mu=0.0, sigma=1.0, dims="bloc")

        # --- the front republicain --------------------------------------
        # One value, fitted on both cycles at once: the 43 measured 2022
        # transfers and the 54 hypothetical 2027 matchups.
        #
        # MEASURED, then restructured. This was first written as a per-cycle
        # delta with a multiplicative drift between them, to carry the "will
        # the front republicain still hold in 2027" question. That does not
        # work: delta came out at 0.064, essentially zero, because the
        # quadratic distance term already explains 2022's transfers on its own
        # and delta is absorbed into the bloc positions. A drift multiplying
        # zero expresses nothing.
        #
        # So the 2027 uncertainty is applied at SIMULATION time instead (see
        # simulate.py), where the 2027 runoff polls cannot fit it away. Here
        # delta only has to capture the RN-specific reluctance that distance
        # does not.
        delta = pm.HalfNormal(
            "delta_front_republicain", sigma=cfg.second_tour.rn_transfer_extra_sd * 20
        )
        delta_2022 = delta

        # --- 2022 measured transfers ------------------------------------
        if transfers is not None and len(transfers):
            t_bloc = np.array(
                [bloc_keys.index(o.bloc) for o in transfers], dtype="int64"
            )
            t_a = np.array([o.to_a for o in transfers], dtype="float64")
            t_b = np.array([o.to_b for o in transfers], dtype="float64")

            probs_2022 = _transfer_probs(
                positions, gamma, delta_2022, abstain, centre_index, rn_index, rn_index
            )
            sigma_t = pm.HalfNormal("sigma_transfert", sigma=0.08)
            pm.Normal(
                "obs_transferts_2022_a",
                mu=probs_2022[t_bloc, 0],
                sigma=sigma_t,
                observed=t_a,
                dims="transfert",
            )
            pm.Normal(
                "obs_transferts_2022_b",
                mu=probs_2022[t_bloc, 1],
                sigma=sigma_t,
                observed=t_b,
                dims="transfert",
            )

        # --- 2027 hypothetical matchups ---------------------------------
        mu = _predict(
            positions, gamma, delta, abstain,
            data.pair_bloc, data.source_shares, data.finalist_own, rn_index,
        )
        mu = pm.Deterministic("mu", pt.clip(mu, 1e-4, 1 - 1e-4), dims="obs")

        sigma_excess = pm.HalfNormal(
            "sigma_excess", sigma=cfg.election_day_error.r2_margin_error_sd
        )
        sd = pt.sqrt(mu * (1 - mu) / data.n + sigma_excess**2)
        pm.Normal("obs_runoff", mu=mu, sigma=sd, observed=data.y, dims="obs")

    return model


def predict_numpy(
    *,
    positions: np.ndarray,
    gamma: float,
    delta: float,
    abstain: np.ndarray,
    pair_bloc: np.ndarray,
    source_shares: np.ndarray,
    finalist_own: np.ndarray,
    rn_index: int,
) -> np.ndarray:
    """The same arithmetic in numpy, for the simulation stage."""
    xa = positions[pair_bloc[:, 0]][:, None]
    xb = positions[pair_bloc[:, 1]][:, None]
    xj = positions[None, :]

    ua = -gamma * (xj - xa) ** 2 - delta * (pair_bloc[:, 0] == rn_index)[:, None]
    ub = -gamma * (xj - xb) ** 2 - delta * (pair_bloc[:, 1] == rn_index)[:, None]
    uw = np.broadcast_to(abstain[None, :], ua.shape)

    stack = np.stack([ua, ub, uw], axis=2)
    stack = stack - stack.max(axis=2, keepdims=True)
    e = np.exp(stack)
    p = e / e.sum(axis=2, keepdims=True)

    to_a = (source_shares * p[:, :, 0]).sum(axis=1) + finalist_own[:, 0]
    to_b = (source_shares * p[:, :, 1]).sum(axis=1) + finalist_own[:, 1]
    return to_a / (to_a + to_b)
