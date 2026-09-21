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


def _p_on_ballot(ballot, cid):
    """P(on the ballot), wherever the candidate sits in the ballot model."""
    if cid in ballot.independent:
        return ballot.independent[cid]
    for arb in ballot.arbitrations:
        if cid in arb.options:
            return arb.probabilities[arb.options.index(cid)]
    raise KeyError(cid)


def test_a_declaration_is_a_floor_not_a_pin(setup, candidacies):
    """Declaring raises a candidate to the floor but must never lower one whom
    institutes test more often than that - the frequency estimate is the
    stronger evidence in that direction.

    Checked for EVERY declared candidate rather than one named person. This
    test used to hard-code Tondelier as an independent candidacy; upstream
    then recorded Rousseau's withdrawal, Tondelier moved into an ecologiste
    arbitration, and the daily run went red on 2026-09-16 over a test that was
    asserting the data rather than the rule.
    """
    cfg, roster, hyps = setup
    floor = cfg.field_.declared_floor
    facts, _ = hard_overrides(candidacies, as_of=AS_OF, declared_floor=floor)
    plain = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=None)
    withf = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=facts)

    declared = [c for c, v in facts.items() if v > 0]
    assert declared, "no declared candidacies at all - the upstream field has changed"
    checked = 0
    for cid in declared:
        try:
            before, after = _p_on_ballot(plain, cid), _p_on_ballot(withf, cid)
        except KeyError:
            continue  # declared but never polled; nothing to floor
        if cid in withf.uncorroborated:
            continue  # covered by the corroboration tests below
        checked += 1
        assert after >= floor - 1e-9, f"{cid} declared but below the floor"
        assert after >= before - 1e-9, f"{cid}: a declaration LOWERED them"
        if cid in withf.independent:
            # Exact only for independent candidacies; inside an arbitration a
            # withdrawal elsewhere legitimately redistributes mass upward.
            assert after == pytest.approx(max(before, floor))
    assert checked >= 3


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


def test_a_pin_survives_a_later_floor_in_the_same_arbitration(setup):
    """Regression: precedence used to depend on dict insertion order.

    A candidate with BOTH a fact and a pin kept the fact's position, so a
    declaration floor on a rival in the same arbitration was applied after the
    pin and squeezed it - Bardella pinned at 0.40 came out at 0.15 once
    upstream recorded Le Pen's declaration. The facts are supplied directly so
    this does not depend on what the upstream file says on any given day.
    """
    from dataclasses import replace

    cfg, roster, hyps = setup
    facts = {"JB": 0.0, "MLP": cfg.field_.declared_floor}
    pinned = replace(cfg, field_=replace(cfg.field_, overrides={"JB": 0.4}))
    ballot = build_ballot_model(hyps, cfg=pinned, roster=roster, as_of=AS_OF, facts=facts)
    rn = [a for a in ballot.arbitrations if a.bloc == "rn"][0]
    p = dict(zip(rn.options, rn.probabilities, strict=True))
    assert p["JB"] == pytest.approx(0.4)
    assert sum(rn.probabilities) + rn.p_none == pytest.approx(1.0)


def test_an_uncorroborated_declaration_is_ignored_and_reported(setup, candidacies):
    """On 2026-09-16 upstream recorded declarations for candidates institutes
    barely test - Bertrand at 0.00, Royal at 0.02, five socialists at once.
    Applied uncritically they moved Le Pen from 65% to 55% with no new polling.
    A declaration now counts only where the polling corroborates it, and every
    ignored one is reported rather than dropped silently."""
    cfg, roster, hyps = setup
    threshold = cfg.field_.declaration_corroboration
    facts, _ = hard_overrides(
        candidacies, as_of=AS_OF, declared_floor=cfg.field_.declared_floor
    )
    plain = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=None)
    withf = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=facts)

    for cid in withf.uncorroborated:
        assert facts[cid] > 0, f"{cid}: only declarations may be ignored"
        before = _p_on_ballot(plain, cid)
        assert before < threshold
        assert _p_on_ballot(withf, cid) == pytest.approx(before), (
            f"{cid}: an ignored declaration still moved the ballot"
        )
    # Every declared, polled candidate is either floored or reported - none
    # falls through the gap between the two.
    for cid, v in facts.items():
        if v <= 0:
            continue
        try:
            before = _p_on_ballot(plain, cid)
        except KeyError:
            continue
        assert (before < threshold) == (cid in withf.uncorroborated), cid


def test_a_withdrawal_is_applied_however_rarely_the_candidate_is_tested(setup):
    """The rule is asymmetric on purpose: believing someone who says they are
    out costs nothing, so corroboration is never required for a withdrawal."""
    cfg, roster, hyps = setup
    facts = {"JB": 0.0, "SR": 0.0}
    ballot = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=facts)
    assert _p_on_ballot(ballot, "JB") == pytest.approx(0.0)
    assert _p_on_ballot(ballot, "SR") == pytest.approx(0.0)
    assert ballot.uncorroborated == []


def test_the_corroboration_threshold_sits_in_an_empty_gap(setup, candidacies):
    """ASSERTED, so it has to be somewhere it does not decide close cases. On
    the day it was set, declared candidates were tested either at 0.56 or
    above, or at 0.13 or below. If someone lands near the line, this fails and
    a person should look at them - and pin them in `field.overrides`."""
    cfg, roster, hyps = setup
    threshold = cfg.field_.declaration_corroboration
    facts, _ = hard_overrides(
        candidacies, as_of=AS_OF, declared_floor=cfg.field_.declared_floor
    )
    plain = build_ballot_model(hyps, cfg=cfg, roster=roster, as_of=AS_OF, facts=None)
    pinned = set(cfg.field_.overrides or {})
    close = []
    for cid, v in facts.items():
        if v <= 0 or cid in pinned:
            continue
        try:
            p = _p_on_ballot(plain, cid)
        except KeyError:
            continue
        if abs(p - threshold) < 0.10:
            close.append(f"{cid} tested at {p:.2f}")
    assert not close, (
        "declared candidates near the corroboration threshold - decide them by "
        "hand in field.overrides: " + ", ".join(close)
    )
