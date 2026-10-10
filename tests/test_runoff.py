"""Tests for the second-round transfer model.

The runoff decides the presidency, and its most important parameter - the
*front republicain* term - is a single number whose sign and effect must not
be able to invert silently. A sign error here would flip the forecast without
changing anything visible in the first round.
"""

from __future__ import annotations

import numpy as np
import pytest

from presidentielle.model.runoff import PRIOR_POSITIONS, predict_numpy

BLOCS = list(PRIOR_POSITIONS)
K = len(BLOCS)
RN = BLOCS.index("rn")
CENTRE = BLOCS.index("centre")
GAUCHE = BLOCS.index("gauche_radicale")


def _predict(delta, source=None, pair=(RN, CENTRE), own=(0.34, 0.20)):
    """Share of expressed votes for the FIRST named finalist."""
    if source is None:
        # A plausible field of eliminated voters, concentrated on the left.
        source = np.zeros(K)
        source[GAUCHE] = 0.18
        source[BLOCS.index("socialiste")] = 0.12
        source[BLOCS.index("droite")] = 0.10
        source[BLOCS.index("ecologiste")] = 0.06
    return predict_numpy(
        positions=np.array([PRIOR_POSITIONS[b] for b in BLOCS]),
        gamma=2.0,
        delta=delta,
        abstain=np.full(K, -0.5),
        pair_bloc=np.array([list(pair)]),
        source_shares=np.array([source]),
        finalist_own=np.array([list(own)]),
        rn_index=RN,
    )[0]


def test_prediction_is_a_valid_share():
    p = _predict(delta=1.0)
    assert 0.0 < p < 1.0


def test_front_republicain_penalises_the_rn_finalist():
    """THE sign test. A larger delta must LOWER the RN finalist's runoff share.
    If this inverts, the model elects the RN for a reason that looks like
    arithmetic."""
    weak = _predict(delta=0.0)
    strong = _predict(delta=2.5)
    assert strong < weak
    assert weak - strong > 0.02, "delta has almost no effect - check it is wired in"


def test_delta_only_penalises_the_rn_side():
    """A runoff with no RN finalist must be untouched by delta."""
    a = _predict(delta=0.0, pair=(CENTRE, GAUCHE), own=(0.22, 0.20))
    b = _predict(delta=2.5, pair=(CENTRE, GAUCHE), own=(0.22, 0.20))
    assert a == pytest.approx(b)


def test_proximity_beats_distance():
    """Left-bloc voters facing a left finalist and a right one should break
    left. This is the whole content of the proximity assumption."""
    source = np.zeros(K)
    source[GAUCHE] = 0.30
    # finalist 0 is the centre, finalist 1 the RN; left voters should prefer
    # the centre, so the centre's share must exceed its own first-round base.
    p = predict_numpy(
        positions=np.array([PRIOR_POSITIONS[b] for b in BLOCS]),
        gamma=2.0,
        delta=0.0,
        abstain=np.full(K, -0.5),
        pair_bloc=np.array([[CENTRE, RN]]),
        source_shares=np.array([source]),
        finalist_own=np.array([[0.20, 0.34]]),
        rn_index=RN,
    )[0]
    assert p > 0.20 / (0.20 + 0.34)


def test_the_kernel_is_smooth_everywhere():
    """The distance term is squared, not absolute, precisely so there is no
    kink for the sampler to grind against. A finite-difference check across
    the point where a voter bloc coincides with a finalist catches a
    reintroduced abs()."""
    positions = np.array([PRIOR_POSITIONS[b] for b in BLOCS])
    source = np.zeros(K)
    source[CENTRE] = 0.30

    def f(x):
        pos = positions.copy()
        pos[CENTRE] = x
        return predict_numpy(
            positions=pos, gamma=2.0, delta=0.0, abstain=np.full(K, -0.5),
            pair_bloc=np.array([[BLOCS.index("droite"), GAUCHE]]),
            source_shares=np.array([source]),
            finalist_own=np.array([[0.25, 0.25]]),
            rn_index=RN,
        )[0]

    # The kink an abs() would create sits where the moving bloc passes a
    # finalist's position; compare the one-sided slopes either side of it.
    x0 = PRIOR_POSITIONS["droite"]
    h = 1e-4
    left = (f(x0) - f(x0 - h)) / h
    right = (f(x0 + h) - f(x0)) / h
    assert left == pytest.approx(right, abs=1e-3), "kernel has a kink - is abs() back?"


def test_squared_kernel_matches_a_hand_computation():
    """Guards the arithmetic itself, not just its qualitative behaviour."""
    positions = np.zeros(K)
    positions[CENTRE] = 0.0
    positions[GAUCHE] = -1.0
    positions[RN] = 1.0
    source = np.zeros(K)
    source[CENTRE] = 0.40

    gamma, delta, w = 1.0, 0.0, -0.5
    # Centre voters choosing between a GAUCHE and an RN finalist: both are
    # distance 1 away, so they split evenly between them after abstention.
    ua = -gamma * (0.0 - (-1.0)) ** 2
    ub = -gamma * (0.0 - 1.0) ** 2
    e = np.exp([ua, ub, w])
    p = e / e.sum()
    expected_a = (0.40 * p[0] + 0.10) / (0.40 * p[0] + 0.10 + 0.40 * p[1] + 0.10)

    got = predict_numpy(
        positions=positions, gamma=gamma, delta=delta, abstain=np.full(K, w),
        pair_bloc=np.array([[GAUCHE, RN]]),
        source_shares=np.array([source]),
        finalist_own=np.array([[0.10, 0.10]]),
        rn_index=RN,
    )[0]
    assert got == pytest.approx(expected_a)
    assert got == pytest.approx(0.5), "symmetric setup must split evenly"


# ------------------------------------------------------------ identification


def _tiny_runoff_data():
    """A minimal well-formed RunoffData, enough to build the model graph."""
    from presidentielle.model.runoff import RunoffData

    source = np.zeros((2, K))
    source[:, GAUCHE] = 0.20
    source[:, BLOCS.index("droite")] = 0.15
    return RunoffData(
        pair_bloc=np.array([[CENTRE, RN], [GAUCHE, RN]], dtype="int64"),
        pair_cand=np.array([[0, 1], [2, 1]], dtype="int64"),
        source_shares=source,
        finalist_own=np.array([[0.22, 0.33], [0.18, 0.33]]),
        y=np.array([0.55, 0.45]),
        n=np.array([1000.0, 1000.0]),
        labels=["a vs b", "c vs b"],
    )


def test_the_position_prior_still_orders_the_blocs():
    """The axis must not be free to reflect: with only pairwise distances in
    the likelihood, an axis read right-to-left fits identically and every
    conclusion about who transfers to whom inverts.

    This is a prior-predictive check, so it guards the anchor rather than the
    fit. The fit's own instability is a separate, open problem - see
    `runoff.py` and `diagnostics.runoff_fit.max_rhat`.
    """
    import pymc as pm

    from presidentielle.config import load_model_config
    from presidentielle.model.runoff import build_runoff_model

    model = build_runoff_model(_tiny_runoff_data(), load_model_config(), BLOCS)
    with model:
        prior = pm.sample_prior_predictive(draws=200, random_seed=0)

    pos = prior.prior["positions"].values.reshape(-1, K)
    assert (pos[:, BLOCS.index("extreme_gauche")] < pos[:, RN]).all()
    assert pos[:, GAUCHE].mean() < pos[:, CENTRE].mean() < pos[:, RN].mean()


# ------------------------------------------------------- the ordered axis


def test_the_axis_is_ordered_by_construction():
    """THE fix for the stuck chain, and the reason it works.

    One run in ten used to land a chain at gamma 12 with the left-right axis
    scrambled - the radical left placed to the RIGHT of the socialists - 21 log
    units worse than its siblings and unable to climb back, because at that
    gamma the proximity softmax saturates and positions can no longer move past
    one another. Ordering them makes that state unreachable rather than merely
    improbable: the miss rate went from 1 in 10 to 0 in 10, and bulk ESS from
    roughly 900 to 1500.

    Checked on the MODEL GRAPH, not on draws: `sample_prior_predictive` ignores
    transforms (forward sampling bypasses them), and this suite does not sample
    - see CLAUDE.md.
    """
    from pymc.distributions.transforms import Ordered

    from presidentielle.config import load_model_config
    from presidentielle.model.runoff import build_runoff_model

    model = build_runoff_model(_tiny_runoff_data(), load_model_config(), BLOCS)
    ordered_rv = next(
        (rv for rv in model.free_RVs if rv.name == "positions_ordonnees"), None
    )
    assert ordered_rv is not None, "the ordered axis variable is gone"
    assert isinstance(model.rvs_to_transforms[ordered_rv], Ordered), (
        "positions_ordonnees has lost its ordering transform - a chain can "
        "scramble the axis again"
    )
    assert "positions" in {d.name for d in model.deterministics}, (
        "everything downstream reads `positions`; it must survive as a "
        "deterministic in the roster's own order"
    )


def test_the_ordering_is_applied_in_sorted_space_not_roster_order():
    """The subtlety that cost a wrongly abandoned fix.

    The prior positions are monotonic in `PRIOR_POSITIONS`' own order but NOT
    in the ROSTER's, which lists the socialists (-0.35) before the greens
    (-0.45). Ordering the vector as the roster lists it would assert something
    false, and handing a transform a non-increasing starting point makes nutpie
    fail to initialise at all - which was once recorded here as nutpie being
    unable to do ordered transforms. It was this instead.
    """
    from presidentielle.config import load_roster

    roster_order = list(load_roster().blocs)
    prior = np.array([PRIOR_POSITIONS[b] for b in roster_order])
    assert not (np.diff(prior) > 0).all(), (
        "the roster's bloc order is monotonic now, so the permutation may be "
        "removable - but check the sampler still initialises before removing it"
    )
    order = np.argsort(prior, kind="stable")
    assert (np.diff(prior[order]) > 0).all(), "sorted space must be increasing"
    # The permutation has to round-trip, or positions attach to the wrong blocs.
    back = np.argsort(order, kind="stable")
    assert (prior[order][back] == prior).all()


def test_the_prior_still_orders_the_blocs_left_to_right():
    """Ordering is only meaningful against the right axis: if these priors were
    ever reshuffled, the constraint would enforce a different politics."""
    assert PRIOR_POSITIONS["extreme_gauche"] < PRIOR_POSITIONS["gauche_radicale"]
    assert PRIOR_POSITIONS["gauche_radicale"] < PRIOR_POSITIONS["centre"]
    assert PRIOR_POSITIONS["centre"] < PRIOR_POSITIONS["droite"]
    assert PRIOR_POSITIONS["droite"] < PRIOR_POSITIONS["rn"]
