"""Tests for the arithmetic that the forecast rests on.

These never sample. The suite has to stay fast enough to run on every edit;
sampling belongs in `presidentielle run`.
"""

from __future__ import annotations

import numpy as np
import pytest

from presidentielle.config import load_model_config, load_roster
from presidentielle.model.simulate import nested_logit_shares


@pytest.fixture(scope="module")
def roster():
    return load_roster()


@pytest.fixture(scope="module")
def cfg():
    return load_model_config()


# ----------------------------------------------------------------------
# A small synthetic setup: two blocs, three candidates.
#   bloc 0: A, B   (alternatives, e.g. Le Pen / Bardella)
#   bloc 1: C      (e.g. Melenchon)
# ----------------------------------------------------------------------
CB = np.array([0, 0, 1])
NB = 2


def shares(strength, lam, field):
    return nested_logit_shares(
        np.asarray(strength, dtype=float)[None, :],
        np.asarray(lam, dtype=float)[None, :],
        np.asarray(field, dtype=bool)[None, :],
        CB,
        NB,
    )[0]


def test_shares_sum_to_one_over_the_field():
    p = shares([1.0, 0.4, 0.7], [0.3, 1.0], [True, True, True])
    assert p.sum() == pytest.approx(1.0)
    assert (p > 0).all()


def test_absent_candidates_get_exactly_zero():
    p = shares([1.0, 0.4, 0.7], [0.3, 1.0], [True, False, True])
    assert p[1] == 0.0
    assert p.sum() == pytest.approx(1.0)


def test_lambda_one_is_exactly_the_plain_softmax():
    """IIA is nested inside the model, so at lambda = 1 it must reproduce it
    exactly. If this drifts, the nesting is no longer a generalisation of the
    obvious model and every comparison to it is meaningless."""
    u = np.array([1.0, 0.4, 0.7])
    p = shares(u, [1.0, 1.0], [True, True, True])
    sm = np.exp(u) / np.exp(u).sum()
    assert p == pytest.approx(sm, abs=1e-12)


def test_within_bloc_substitution_is_strong_at_small_lambda():
    """THE point of the model.

    Remove B from the ballot. With a small nesting parameter the vote should go
    to B's own bloc-mate A, leaving the other bloc's candidate almost untouched.
    Under IIA (lambda = 1) it would instead be shared out in proportion, which
    is what this asserts is *not* happening.
    """
    u = [0.9, 0.8, 1.0]
    with_b = shares(u, [0.15, 1.0], [True, True, True])
    without_b = shares(u, [0.15, 1.0], [True, False, True])

    gained_a = without_b[0] - with_b[0]
    gained_c = without_b[2] - with_b[2]
    lost_b = with_b[1]

    assert gained_a + gained_c == pytest.approx(lost_b)
    # A should take the overwhelming majority of it.
    assert gained_a / lost_b > 0.9
    assert gained_c / lost_b < 0.1


def test_iia_shares_the_vote_out_proportionally():
    """The contrast case: at lambda = 1 the same removal leaks across blocs."""
    u = [0.9, 0.8, 1.0]
    with_b = shares(u, [1.0, 1.0], [True, True, True])
    without_b = shares(u, [1.0, 1.0], [True, False, True])
    gained_c = without_b[2] - with_b[2]
    lost_b = with_b[1]
    # Under IIA C picks up a large share - far more than the nested model gives.
    assert gained_c / lost_b > 0.4


def test_small_lambda_keeps_the_bloc_total_near_constant_for_equal_candidates():
    """Two equally strong alternatives: dropping one should barely move the
    bloc's total, because the survivor inherits the support."""
    u = [0.9, 0.9, 1.0]
    both = shares(u, [0.1, 1.0], [True, True, True])
    one = shares(u, [0.1, 1.0], [True, False, True])
    assert one[0] == pytest.approx(both[0] + both[1], rel=0.05)


def test_a_weaker_replacement_shrinks_the_bloc():
    """Substitution being strong does not mean the bloc is indifferent. If the
    replacement is weaker, the bloc's total must fall - otherwise the model
    could not represent 'Bardella polls worse than Le Pen'."""
    strong = shares([1.4, -0.5, 1.0], [0.15, 1.0], [True, False, True])
    weak = shares([1.4, -0.5, 1.0], [0.15, 1.0], [False, True, True])
    assert weak[1] < strong[0]


# ----------------------------------------------------------------------
# Roster and config invariants
# ----------------------------------------------------------------------


def test_every_candidate_has_a_known_bloc(roster):
    for cid, c in roster.candidats.items():
        assert c.bloc in roster.blocs, f"{cid} has bloc {c.bloc!r}"


def test_roster_covers_every_polled_candidate(roster):
    """THE ROSTER FAILS CLOSED, so a name it does not know silently costs a
    whole hypothesis. This asserts the cached poll file is fully covered."""
    from presidentielle.data.polls import load

    hyps, skipped = load(roster=roster, history_start=None)
    assert not skipped, "records were skipped:\n" + "\n".join(skipped)
    assert hyps, "no hypotheses parsed"


def test_shares_within_a_hypothesis_are_normalised(roster):
    from presidentielle.data.polls import load

    hyps, _ = load(roster=roster, history_start=None)
    for h in hyps:
        assert sum(h.shares.values()) == pytest.approx(1.0)


def test_second_round_hypotheses_have_exactly_two_candidates(roster):
    from presidentielle.data.polls import load

    hyps, _ = load(roster=roster, history_start=None)
    for h in hyps:
        if h.tour == 2:
            assert len(h.shares) == 2


def test_survey_weighting_reduces_the_effective_sample(roster, cfg):
    """An institute pricing 13 fields did not run 13 surveys. If this stops
    biting, the model is treating one sample as many and every interval is too
    narrow."""
    from presidentielle.data.polls import load
    from presidentielle.data.surveys import weight

    hyps, _ = load(roster=roster, history_start=cfg.polls.history_start)
    w = weight(hyps, exponent=cfg.observation.survey_weight_exponent)
    raw = sum(h.echantillon for h in hyps if h.tour == 1)
    eff = sum(x.n_effective for x in w if x.hypothese.tour == 1)
    assert eff < raw * 0.75


def test_weight_exponent_bounds(roster):
    from presidentielle.data.polls import load
    from presidentielle.data.surveys import weight

    hyps, _ = load(roster=roster, history_start=None)
    with pytest.raises(ValueError):
        weight(hyps, exponent=1.5)


def test_election_grid_ends_on_election_day(roster, cfg):
    """INVARIANT: the fitted walk must reach election day, so that no separate
    drift term is needed. A second drift term would double-count."""
    from presidentielle.data.polls import load
    from presidentielle.data.surveys import weight
    from presidentielle.model.design import build_model_data

    hyps, _ = load(roster=roster, history_start=cfg.polls.history_start)
    w = weight(hyps, exponent=cfg.observation.survey_weight_exponent)
    data = build_model_data(w, cfg=cfg, roster=roster)
    assert data.grid_dates[-1] == cfg.election.premier_tour
    assert data.election_index == len(data.grid_dates) - 1
