"""Tests for declared candidacies and withdrawals.

These now move the headline number. Before they were wired in, the model gave
Bardella a 20% chance of being on the ballot and roughly 14% of the presidency
on the strength of how often institutes tested him - after he had withdrawn.
"""

from __future__ import annotations

import datetime as dt

import pytest

from presidentielle.config import load_model_config, load_roster
from presidentielle.data.candidacies import hard_overrides, load
from presidentielle.data.polls import load as load_polls
from presidentielle.model.field import build_ballot_model

AS_OF = dt.date(2026, 9, 2)


@pytest.fixture(scope="module")
def candidacies():
    return load()


@pytest.fixture(scope="module")
def setup():
    cfg = load_model_config()
    roster = load_roster()
    hyps, _ = load_polls(roster=roster, history_start=cfg.polls.history_start)
    return cfg, roster, hyps


def test_bardella_is_recorded_as_withdrawn(candidacies):
    """The fact that motivated the whole feature. He stood down on the day Le
    Pen's ineligibility was cut to 15 months."""
    jb = candidacies["JB"]
    assert jb.retrait == dt.date(2026, 7, 7)
    assert jb.status(AS_OF) == "withdrawn"


def test_the_polling_record_corroborates_the_withdrawal(setup):
    """Two independent signals agreeing is what makes a community-maintained
    CSV field trustworthy here: institutes stopped testing Bardella from the
    same month he withdrew."""
    _, _, hyps = setup
    first = [h for h in hyps if h.tour == 1]
    after = [h for h in first if h.fin >= dt.date(2026, 7, 7)]
    assert after, "no polls after the withdrawal date"
    assert not any("JB" in h.shares for h in after), (
        "Bardella is still being tested after his recorded withdrawal - "
        "the two signals disagree, so check the CSV before trusting it"
    )


def test_withdrawal_removes_a_candidate_from_the_ballot(setup, candidacies):
    cfg, roster, hyps = setup
    facts, _ = hard_overrides(
        candidacies, as_of=AS_OF, declared_floor=cfg.field_.declared_floor
    )
    ballot = build_ballot_model(
        hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=facts
    )
    rn = [a for a in ballot.arbitrations if a.bloc == "rn"][0]
    p = dict(zip(rn.options, rn.probabilities, strict=True))
    assert p["JB"] == pytest.approx(0.0)
    assert p["MLP"] > 0.9, "with Bardella out, the RN nomination is Le Pen's"
    assert sum(rn.probabilities) + rn.p_none == pytest.approx(1.0)


def test_without_the_facts_bardella_still_looks_live(setup):
    """The contrast case, so the value of the feature is asserted and not just
    claimed: on testing frequency alone he is a fifth of the RN nomination."""
    cfg, roster, hyps = setup
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=None)
    rn = [a for a in ballot.arbitrations if a.bloc == "rn"][0]
    p = dict(zip(rn.options, rn.probabilities, strict=True))
    assert p["JB"] > 0.1


def test_a_declaration_is_a_floor_not_a_pin(setup, candidacies):
    """Declaring raises a candidate to the floor but must never lower one whom
    institutes test more often than that - the frequency estimate is the
    stronger evidence in that direction."""
    cfg, roster, hyps = setup
    facts, _ = hard_overrides(
        candidacies, as_of=AS_OF, declared_floor=cfg.field_.declared_floor
    )
    plain = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=None)
    withf = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=facts)
    assert facts["MT"] == pytest.approx(cfg.field_.declared_floor)
    assert withf.independent["MT"] >= plain.independent["MT"]
    assert withf.independent["MT"] == pytest.approx(
        max(plain.independent["MT"], cfg.field_.declared_floor)
    )


def test_facts_are_ignored_before_they_happened(candidacies):
    """NO LOOKAHEAD. Bardella had not withdrawn in January 2026."""
    early, _ = hard_overrides(
        candidacies, as_of=dt.date(2026, 1, 1), declared_floor=0.85
    )
    assert "JB" not in early
    late, _ = hard_overrides(candidacies, as_of=AS_OF, declared_floor=0.85)
    assert late["JB"] == 0.0


def test_a_withdrawal_after_a_declaration_wins(candidacies):
    """Darmanin declared on 2026-08-17 and withdrew eight days later, which is
    also why declaring is only a floor."""
    gd = candidacies["GD"]
    assert gd.annonce == dt.date(2026, 8, 17)
    assert gd.retrait == dt.date(2026, 8, 25)
    assert gd.status(dt.date(2026, 8, 20)) == "declared"
    assert gd.status(AS_OF) == "withdrawn"
    facts, _ = hard_overrides(candidacies, as_of=AS_OF, declared_floor=0.85)
    assert facts["GD"] == 0.0


def test_config_override_beats_a_recorded_fact(setup, candidacies):
    """The manual pin is the last word, so a wrong upstream field can always be
    corrected without editing code."""
    from dataclasses import replace

    cfg, roster, hyps = setup
    facts, _ = hard_overrides(
        candidacies, as_of=AS_OF, declared_floor=cfg.field_.declared_floor
    )
    pinned = replace(cfg, field_=replace(cfg.field_, overrides={"JB": 0.4}))
    ballot = build_ballot_model(
        hyps, cfg=pinned, roster=roster, as_of=AS_OF, facts=facts
    )
    rn = [a for a in ballot.arbitrations if a.bloc == "rn"][0]
    p = dict(zip(rn.options, rn.probabilities, strict=True))
    assert p["JB"] == pytest.approx(0.4)
