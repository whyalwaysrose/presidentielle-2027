"""Tests for the 2024 legislative duels as transfer evidence.

This module puts a DIFFERENT KIND OF ELECTION into a presidential model. The
failure mode is not a crash - it is 317 local duels quietly rewriting the
geometry that decides the presidency, which is exactly what happened on the
first attempt and is recorded in `runoff.py`. These tests guard the pieces of
that which can be checked without sampling.
"""

from __future__ import annotations

import numpy as np
import pytest

from presidentielle.config import load_model_config, load_roster
from presidentielle.data import legislatives_2024 as leg


@pytest.fixture(scope="module")
def bloc_keys():
    return list(load_roster().blocs)


@pytest.fixture(scope="module")
def duels(bloc_keys):
    return leg.build(bloc_keys)


# ------------------------------------------------------------------ mapping


def test_every_nuance_maps_to_real_blocs_summing_to_one(bloc_keys):
    """A mapping weight that does not sum to one silently deletes or invents
    votes, and a typo'd bloc name would raise only once that duel is reached."""
    for nuance, weights in leg.NUANCE_BLOC.items():
        assert set(weights) <= set(bloc_keys), f"{nuance} names an unknown bloc"
        assert sum(weights.values()) == pytest.approx(1.0), nuance


def test_the_nfp_split_is_the_published_nomination_deal():
    """LFI 229, PS and Place publique 175, Les Ecologistes 92, PCF 50. The PCF
    sits with LFI in this model's roster, so the left-radical share is 279/546.
    If this is ever retuned to make a forecast come out, the number stops being
    a citation and becomes a knob."""
    assert leg.NFP_SPLIT["gauche_radicale"] == pytest.approx(279 / 546, abs=1e-6)
    assert leg.NFP_SPLIT["socialiste"] == pytest.approx(175 / 546, abs=1e-6)
    assert leg.NFP_SPLIT["ecologiste"] == pytest.approx(92 / 546, abs=1e-6)


def test_the_far_right_is_the_rn_and_its_ally_only():
    """UXD is the 2024 union with Ciotti's UDR. Reconquete is NOT in here: it
    ran against the RN, and folding it in would make some duels RN-versus-RN."""
    assert leg.FAR_RIGHT == {"RN", "UXD"}
    assert leg.NUANCE_BLOC["REC"] == {"reconquete": 1.0}


# --------------------------------------------------------------------- data


def test_the_duels_are_all_there(duels):
    """330 duels exist in the Ministry file; a handful are dropped for having
    no place on a left-right axis. A large fall here means the file or the
    mapping changed, not that French politics did."""
    assert 300 <= len(duels) <= 330
    assert len(duels.dropped) < 20


def test_unplaceable_votes_are_counted_and_tiny(duels):
    """'Divers' and the regionalists have no position on a left-right axis, so
    their votes leave the transfer pool. That is only acceptable while it is
    negligible - and it is reported rather than assumed."""
    assert duels.unmapped_share < 0.02


def test_finalist_zero_is_always_the_rn(duels, bloc_keys):
    """The whole module depends on this: `y` is the RN's share, and the model
    applies the front republicain term to finalist 0 unconditionally."""
    rn = bloc_keys.index("rn")
    assert not duels.opp_weight[:, rn].any()
    assert duels.opp_weight.sum(axis=1) == pytest.approx(1.0)


def test_shares_account_for_the_whole_first_round(duels):
    """Eliminated votes plus the two finalists' own must be the first round,
    give or take the unplaceable remainder. If these drifted apart, transfers
    would be computed against the wrong denominator - the bug that once cost
    14.5 points on one matchup (see CLAUDE.md invariant 13)."""
    total = duels.source_shares.sum(axis=1) + duels.finalist_own.sum(axis=1)
    # Four of the 577 circonscriptions have candidate votes and the official
    # Exprimes disagreeing by one or two votes in ~60 000. That is the
    # Ministry's own arithmetic, not a parsing error, and it is why this is
    # not an exact bound.
    assert total.max() <= 1.0 + 1e-4
    assert total.min() > 0.90
    assert np.median(total) > 0.98


def test_observed_shares_are_two_way(duels):
    assert (duels.y > 0.05).all() and (duels.y < 0.95).all()
    # The RN lost about three-quarters of these duels.
    assert 0.20 < (duels.y > 0.5).mean() < 0.35


def test_the_finding_survives_the_pipeline(duels):
    """The reason this data is here at all: from near-identical first-round
    positions the RN converts better against a left opponent than a centre one.
    Measured at about four points by scripts/measure_front_republicain_2024.py,
    and it must still be visible in the arrays the model actually sees."""
    left = np.array([n in {"UG", "DVG", "ECO", "SOC", "COM", "FI", "EXG"}
                     for n in duels.opp_nuance])
    centre = np.array([n in {"ENS", "HOR", "DVC", "MDM"} for n in duels.opp_nuance])
    # Comparable starting points, so the difference is about transfer.
    assert abs(duels.finalist_own[left, 0].mean()
               - duels.finalist_own[centre, 0].mean()) < 0.02
    gap = duels.y[left].mean() - duels.y[centre].mean()
    assert 0.02 < gap < 0.06, f"the left-versus-centre gap has moved: {gap:.3f}"


def test_the_ug_mixture_is_an_assumption_that_can_be_moved(bloc_keys):
    """136 opponents are NFP joint nominations and the file does not say which
    party each came from. That assumption has to be checkable, so `build` takes
    the split as an argument - which is what the sensitivity check uses."""
    lfi = leg.build(bloc_keys, nfp_split={"gauche_radicale": 1.0})
    ps = leg.build(bloc_keys, nfp_split={"socialiste": 1.0})
    g, s = bloc_keys.index("gauche_radicale"), bloc_keys.index("socialiste")
    ug = np.array([n == "UG" for n in lfi.opp_nuance])
    assert lfi.opp_weight[ug, g].min() == 1.0
    assert ps.opp_weight[ug, s].min() == 1.0
    # Everything except where the opponent sits must be untouched.
    assert lfi.y == pytest.approx(ps.y)


# ------------------------------------------------------------------- config


def test_the_legislative_scales_are_all_positive_and_declared():
    """Every one of these says how far a legislative election may differ from a
    presidential one. Setting any to zero asserts a legislative duel IS a
    presidential runoff - measured, and it moved runoff MAE from 1.90 to 3.33
    points."""
    st = load_model_config().second_tour
    for name in (
        "legislative_position_sd",
        "legislative_gamma_log_sd",
        "legislative_abstention_sd",
        "legislative_delta_shift_sd",
        "legislative_scatter_sd",
    ):
        assert getattr(st, name) > 0, f"{name} must be positive"


def test_the_front_republicain_level_is_not_imported_from_2024():
    """delta is what reaches the 2027 simulation. The legislative adjustment
    must be loose enough that 2024's own level - inflated by desistements a
    presidential runoff has no mechanism for - stays in 2024."""
    st = load_model_config().second_tour
    assert st.legislative_delta_shift_sd >= 10 * st.rn_transfer_extra_sd
