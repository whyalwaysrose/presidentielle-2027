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
