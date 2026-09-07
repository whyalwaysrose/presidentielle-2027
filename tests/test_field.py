"""Tests for the ballot-composition model.

The claim these protect is the one most likely to be quietly wrong: that
institutes' testing behaviour is being read correctly, and that the RN
nomination - the single most consequential fact about this ballot - is not
being averaged across the July 2026 regime change.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from presidentielle.config import load_model_config, load_roster
from presidentielle.data.polls import load
from presidentielle.model.field import build_ballot_model, draw_fields, fixed_field


@pytest.fixture(scope="module")
def setup():
    cfg = load_model_config()
    roster = load_roster()
    hyps, _ = load(roster=roster, history_start=cfg.polls.history_start)
    as_of = max(h.fin for h in hyps)
    return cfg, roster, hyps, as_of


def test_le_pen_and_bardella_are_an_arbitration(setup):
    """They have never been tested in the same field. If this stops holding,
    the RN is being modelled as able to run two candidates at once."""
    cfg, roster, hyps, as_of = setup
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    rn = [a for a in ballot.arbitrations if a.bloc == "rn"]
    assert rn, "the RN nomination is not being treated as an arbitration"
    assert set(rn[0].options) >= {"MLP", "JB"}


def test_arbitration_probabilities_form_a_distribution(setup):
    cfg, roster, hyps, as_of = setup
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    for arb in ballot.arbitrations:
        total = sum(arb.probabilities) + arb.p_none
        assert total == pytest.approx(1.0)
        assert all(0.0 <= p <= 1.0 for p in arb.probabilities)


def test_decay_tracks_the_regime_change_not_the_average(setup):
    """MEASURED: Le Pen was ineligible from 2025-03-31 and institutes tested
    Bardella; her ban was cut on 2026-07-07 and from July 2026 they test only
    her. A flat window spanning both says roughly 67/33. The decayed estimate
    must land much closer to the recent regime."""
    cfg, roster, hyps, as_of = setup
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    rn = [a for a in ballot.arbitrations if a.bloc == "rn"][0]
    p = dict(zip(rn.options, rn.probabilities, strict=True))
    assert p["MLP"] > p["JB"]
    assert p["MLP"] > 0.7, f"decay is not tracking the July 2026 change: {p}"


def test_a_longer_half_life_averages_across_the_break(setup):
    """The complement of the test above: with a long half-life the estimate
    degrades towards the misleading average. This is what the config comment
    claims, asserted rather than left as prose."""
    from dataclasses import replace

    cfg, roster, hyps, as_of = setup
    slow = replace(cfg, field_=replace(cfg.field_, half_life_days=400.0))
    ballot = build_ballot_model(hyps, cfg=slow, roster=roster, as_of=as_of)
    rn = [a for a in ballot.arbitrations if a.bloc == "rn"][0]
    p = dict(zip(rn.options, rn.probabilities, strict=True))
    assert p["MLP"] < 0.7


def test_philippe_and_attal_are_not_an_arbitration(setup):
    """They co-occur in many fields, so they are not alternatives and each
    candidacy has to stand on its own."""
    cfg, roster, hyps, as_of = setup
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    for arb in ballot.arbitrations:
        assert not ({"EP", "GA"} <= set(arb.options))
    assert "EP" in ballot.independent
    assert "GA" in ballot.independent


def test_drawn_ballots_always_have_at_least_two_candidates(setup):
    """simulate() raises on a ballot with fewer than two names, so this must
    never happen in practice."""
    cfg, roster, hyps, as_of = setup
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    ids = sorted({c for h in hyps if h.tour == 1 for c in h.shares})
    rng = np.random.default_rng(0)
    fields = draw_fields(ballot, ids, 4000, rng)
    assert fields.sum(axis=1).min() >= 2


def test_an_arbitration_never_puts_two_of_its_options_on_one_ballot(setup):
    cfg, roster, hyps, as_of = setup
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    ids = sorted({c for h in hyps if h.tour == 1 for c in h.shares})
    index = {c: i for i, c in enumerate(ids)}
    rng = np.random.default_rng(1)
    fields = draw_fields(ballot, ids, 3000, rng)
    for arb in ballot.arbitrations:
        cols = [index[c] for c in arb.options]
        assert fields[:, cols].sum(axis=1).max() <= 1


def test_override_pins_a_probability(setup):
    from dataclasses import replace

    cfg, roster, hyps, as_of = setup
    pinned = replace(cfg, field_=replace(cfg.field_, overrides={"JB": 0.0}))
    ballot = build_ballot_model(hyps, cfg=pinned, roster=roster, as_of=as_of)
    rn = [a for a in ballot.arbitrations if a.bloc == "rn"][0]
    p = dict(zip(rn.options, rn.probabilities, strict=True))
    assert p["JB"] == pytest.approx(0.0)
    assert sum(rn.probabilities) + rn.p_none == pytest.approx(1.0)


def test_fixed_field_scenario(setup):
    cfg, roster, hyps, as_of = setup
    ids = sorted({c for h in hyps if h.tour == 1 for c in h.shares})
    f = fixed_field(ids, ["MLP", "EP", "JLM"], 5)
    assert f.shape == (5, len(ids))
    assert f.sum(axis=1).tolist() == [3] * 5
    with pytest.raises(ValueError):
        fixed_field(ids, ["NOT_A_CANDIDATE"], 2)


def test_recent_evidence_outweighs_old_evidence(setup):
    """Decay is monotone: a candidate tested only long ago must end up below
    one tested only recently, whatever the raw counts."""
    cfg, roster, hyps, as_of = setup
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    old_only = max(
        (h.fin for h in hyps if h.tour == 1 and "GD" in h.shares), default=None
    )
    if old_only and (as_of - old_only) > dt.timedelta(days=200):
        assert ballot.independent.get("GD", 0.0) < 0.05


def test_arbitration_alternatives_get_a_real_first_round_share(setup):
    """REGRESSION. The runoff stage needs a first-round base for every finalist
    of every tested matchup, including candidates the reference ballot excludes.

    The reference ballot resolves the RN arbitration to Le Pen, so Bardella is
    absent from it - and reading his share straight off it returned ZERO. Every
    Bardella runoff was then fitted with him holding no first-round votes,
    which cost 14.5 points on Bardella-versus-Melenchon and pushed the runoff
    MAE from 1.97 to 3.54. It looked like tension between the 2022 and 2027
    evidence rather than a bug, which is what makes it worth a test.
    """
    import numpy as np

    from presidentielle.cli import _reference_field, _reference_shares
    from presidentielle.data.surveys import weight
    from presidentielle.model.design import build_model_data

    cfg, roster, hyps, as_of = setup
    data = build_model_data(
        weight(hyps, exponent=cfg.observation.survey_weight_exponent),
        cfg=cfg,
        roster=roster,
    )
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=as_of)
    reference = _reference_field(ballot, data.candidate_ids)

    rng = np.random.default_rng(0)
    strength = rng.normal(size=(4, data.n_candidates))
    lam = np.repeat(
        np.where(data.identified_blocs, 0.35, 1.0)[None, :], 4, axis=0
    )
    shares = _reference_shares(reference, ballot, data, strength, lam)

    index = {c: i for i, c in enumerate(data.candidate_ids)}
    assert "JB" in index and "MLP" in index
    # Bardella is NOT on the reference ballot ...
    assert not reference[index["JB"]]
    # ... but must still be priced, on the ballot he would actually be on.
    assert shares[index["JB"]] > 0.01, "arbitration alternative priced at zero"
    # And every polled candidate gets something, not just the reference field.
    assert (shares > 0).all()
