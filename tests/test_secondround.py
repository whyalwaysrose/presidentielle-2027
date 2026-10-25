"""Tests for the second-round diagnostic.

This reports the single largest judgement in the forecast - how far the
transfer model departs from runoff polls - so its failure mode is a confident
wrong number. The sign conventions are where that would hide: a correction
reported against the wrong candidate would read as the model favouring the RN
when it does the opposite. Most of what follows is about direction.
"""

from __future__ import annotations

import datetime as dt
import json

import numpy as np
import pytest
import yaml

from presidentielle import secondround as S
from presidentielle.config import load_roster
from presidentielle.data.polls import Hypothese
from presidentielle.model.simulate import SimulationResult, matchup_table

AS_OF = dt.date(2026, 10, 8)


def _h(a: str, share_a: float, b: str, share_b: float, fin: dt.date) -> Hypothese:
    return Hypothese(
        poll_id=f"{a}{b}{fin}", institut="Test", commanditaire="Test",
        debut=fin, fin=fin, echantillon=1000, population="inscrits",
        hypothese="h", tour=2, notice="n.pdf",
        shares={a: share_a, b: share_b},
    )


# ------------------------------------------------------------ implied share


def test_a_candidates_duel_share_is_recovered_from_the_winners_share():
    """`runoff_share` is the WINNER's share, so half the simulations need
    flipping. Getting that backwards would invert every correction."""
    # Two sims of the same duel: candidate 0 wins 55-45, then loses 48-52.
    result = SimulationResult(
        candidate_ids=["A", "B"],
        shares=np.zeros((2, 2)),
        standing=np.ones((2, 2), dtype=bool),
        finalists=np.array([[0, 1], [0, 1]]),
        winner=np.array([0, 1]),
        runoff_share=np.array([0.55, 0.52]),
        n_sims=2,
    )
    row = matchup_table(result)[0]
    assert row["a"] == "A" and row["b"] == "B"
    assert row["p_a_wins"] == pytest.approx(0.5)
    # A's shares are 0.55 (won) and 0.48 (lost), median 0.515.
    assert row["part_a"] == pytest.approx(0.515)


def test_the_share_and_the_win_probability_agree_about_who_is_ahead():
    """They are the same claim in different clothes; if they ever disagree,
    one of them is being computed wrong."""
    rng = np.random.default_rng(0)
    share_a = rng.normal(0.53, 0.04, size=4000).clip(0, 1)
    a_wins = share_a > 0.5
    result = SimulationResult(
        candidate_ids=["A", "B"],
        shares=np.zeros((4000, 2)),
        standing=np.ones((4000, 2), dtype=bool),
        finalists=np.tile([0, 1], (4000, 1)),
        winner=np.where(a_wins, 0, 1),
        runoff_share=np.where(a_wins, share_a, 1 - share_a),
        n_sims=4000,
    )
    row = matchup_table(result)[0]
    assert (row["part_a"] > 0.5) == (row["p_a_wins"] > 0.5)
    assert row["part_a"] == pytest.approx(0.53, abs=0.01)
    assert row["part_a_q05"] < row["part_a"] < row["part_a_q95"]


# --------------------------------------------------------------- the polls


def test_only_recent_two_way_runoff_polls_are_averaged():
    """A first-round hypothesis, a three-way, and anything outside the window
    are all the wrong thing to compare a duel against."""
    old = AS_OF - dt.timedelta(days=S.POLL_WINDOW_DAYS + 5)
    hyps = [
        _h("MLP", 0.55, "EP", 0.45, AS_OF),
        _h("MLP", 0.57, "EP", 0.43, AS_OF - dt.timedelta(days=10)),
        _h("MLP", 0.80, "EP", 0.20, old),          # too old
    ]
    hyps.append(Hypothese(
        poll_id="r1", institut="T", commanditaire="T", debut=AS_OF, fin=AS_OF,
        echantillon=1, population="p", hypothese="h", tour=1, notice="n",
        shares={"MLP": 0.3, "EP": 0.2},
    ))
    out = S.poll_shares(hyps, as_of=AS_OF)
    assert list(out) == [frozenset({"MLP", "EP"})]
    share_ep, share_mlp, n = out[frozenset({"MLP", "EP"})]  # sorted: EP, MLP
    assert n == 2
    assert share_ep == pytest.approx(0.44)
    assert share_mlp == pytest.approx(0.56)


# ---------------------------------------------------------------- the sign


def test_the_correction_is_reported_against_the_right_candidate():
    """The whole point. The model has Philippe ahead where the polls have him
    behind, so the gap must come out POSITIVE for Philippe and NEGATIVE for
    the RN."""
    roster = load_roster()
    matchups = [{
        "a": "EP", "b": "MLP", "p_matchup": 0.30,
        "part_a": 0.503, "part_a_q05": 0.40, "part_a_q95": 0.60,
    }]
    hyps = [_h("MLP", 0.55, "EP", 0.45, AS_OF)]
    report = S.compare(matchups, roster, hyps, as_of=AS_OF)
    duel = report.duels[0]

    assert duel.sondages_a == pytest.approx(0.45), "picked the wrong side's poll"
    assert duel.ecart == pytest.approx(0.053, abs=1e-6)
    assert duel.rn == "MLP"
    # Harsher on the RN than the polls are, so negative for the RN.
    assert duel.ecart_rn == pytest.approx(-0.053, abs=1e-6)


def test_the_sign_follows_the_rn_whichever_side_it_is_listed_on():
    """`a` is whichever candidate sorts first by index, not by bloc, so the RN
    can be either side and the reported correction must not depend on that."""
    roster = load_roster()
    hyps = [_h("MLP", 0.55, "EP", 0.45, AS_OF)]
    as_a = S.compare(
        [{"a": "MLP", "b": "EP", "p_matchup": 0.3, "part_a": 0.497,
          "part_a_q05": 0.4, "part_a_q95": 0.6}],
        roster, hyps, as_of=AS_OF,
    ).duels[0]
    as_b = S.compare(
        [{"a": "EP", "b": "MLP", "p_matchup": 0.3, "part_a": 0.503,
          "part_a_q05": 0.4, "part_a_q95": 0.6}],
        roster, hyps, as_of=AS_OF,
    ).duels[0]
    assert as_a.ecart_rn == pytest.approx(as_b.ecart_rn, abs=1e-6)
    assert as_a.ecart_rn < 0


def test_a_duel_nobody_has_polled_is_reported_as_such(capsys):
    """Silence would read as agreement with the polls. It is the absence of
    any."""
    roster = load_roster()
    report = S.compare(
        [{"a": "EP", "b": "BR", "p_matchup": 0.05, "part_a": 0.6,
          "part_a_q05": 0.5, "part_a_q95": 0.7}],
        roster, [], as_of=AS_OF,
    )
    duel = report.duels[0]
    assert duel.sondages_a is None and duel.ecart is None and duel.ecart_rn is None
    assert any("no runoff poll" in line for line in report.lines())


def test_rare_pairings_are_left_out():
    roster = load_roster()
    report = S.compare(
        [{"a": "EP", "b": "MLP", "p_matchup": S.MIN_MATCHUP_PROB / 2,
          "part_a": 0.5, "part_a_q05": 0.4, "part_a_q95": 0.6}],
        roster, [], as_of=AS_OF,
    )
    assert report.duels == []


# ------------------------------------------------------------ the reference


def test_the_2022_reference_is_measured_not_asserted():
    """The one presidential runoff this repository can score. Final-fortnight
    polls had Le Pen near 45; she took 41.5."""
    error, n = S.historical_error()
    assert n >= 20, "too few final 2022 polls to mean anything"
    assert error == pytest.approx(0.038, abs=0.005), (
        "the 2022 runoff poll error moved - check the cached polls and "
        "config/resultats_2022.yaml before trusting any correction"
    )
    # Positive means the polls FLATTERED the RN, which is the direction the
    # model corrects in.
    assert error > 0


def test_the_reference_reproduces_from_the_published_result():
    """Computed here independently of the module, so a change to its parsing
    cannot quietly redefine what the reference means."""
    second = yaml.safe_load(
        S.RESULTS_2022_FILE.read_text(encoding="utf-8"))["second_tour"]
    votes = {k: v["voix"] for k, v in second["candidats"].items()}
    actual_rn = votes["LE PEN"] / sum(votes.values())
    assert actual_rn == pytest.approx(0.4147, abs=0.001)

    payload = json.loads(S.POLLS_2022_FILE.read_text(encoding="utf-8"))
    records = payload if isinstance(payload, list) else payload["polls"]
    polled = [
        c["intentions"] / 100
        for rec in records
        if dt.date.fromisoformat(rec["fin_enquete"]) >= S.FINAL_FORTNIGHT_2022
        for tour in rec.get("tours", [])
        if tour.get("tour") == "Deuxième tour"
        for hyp in tour.get("hypotheses", [])
        for c in hyp.get("candidats", [])
        if c["candidat"] == "Marine Le Pen"
        and {x["candidat"] for x in hyp["candidats"]} == {"Emmanuel Macron", "Marine Le Pen"}
    ]
    assert S.historical_error()[0] == pytest.approx(
        sum(polled) / len(polled) - actual_rn, abs=1e-9
    )


def test_a_missing_reference_says_so_rather_than_guessing(tmp_path):
    """A diagnostic that invents its own benchmark is worse than one that
    admits it has none."""
    error, n = S.historical_error(
        results_2022=tmp_path / "nope.yaml", polls_2022=tmp_path / "nope.json"
    )
    assert error is None and n == 0
