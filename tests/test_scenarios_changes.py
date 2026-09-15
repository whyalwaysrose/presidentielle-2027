"""Tests for named ballots and for change tracking.

Both exist to stop the page saying something false: a scenario that silently
shows the reference ballot, or a model change reported as the electorate
moving.
"""

from __future__ import annotations

import numpy as np
import pytest

from presidentielle import changes, scenarios
from presidentielle.config import load_roster


@pytest.fixture(scope="module")
def roster():
    return load_roster()


@pytest.fixture(scope="module")
def defs():
    return scenarios.load()


# ----------------------------------------------------------------- scenarios


def test_scenarios_load_and_every_id_is_known(defs, roster):
    """FAILS CLOSED. A scenario naming a candidate who does not exist would be
    a silent no-op: the page would offer 'Without Édouard Philippe' and show
    the reference ballot with him still on it."""
    assert defs
    scenarios.validate(defs, roster)


def test_validate_rejects_an_unknown_candidate(roster):
    bad = [
        scenarios.Scenario(
            id="bogus", nom_fr="x", nom_en="x", note_fr="", note_en="",
            remove=("NOT_A_CANDIDATE",),
        )
    ]
    with pytest.raises(ValueError, match="unknown candidate"):
        scenarios.validate(bad, roster)


def test_remove_takes_a_candidate_off_the_ballot():
    ids = ["A", "B", "C"]
    reference = np.array([True, True, True])
    s = scenarios.Scenario(
        id="s", nom_fr="", nom_en="", note_fr="", note_en="", remove=("B",)
    )
    field = s.field_from(reference, ids)
    assert field.tolist() == [True, False, True]
    # The reference must not be mutated - it is reused for every scenario.
    assert reference.tolist() == [True, True, True]


def test_scenarios_are_defined_against_the_reference_not_as_lists(defs):
    """Definitions are modifications, so they survive the roster changing. An
    explicit list would rot quietly as candidates enter and leave."""
    for s in defs:
        assert s.remove or s.add


def test_every_scenario_says_what_it_is_in_both_languages(defs):
    for s in defs:
        assert s.nom_fr and s.nom_en
        assert s.note_fr and s.note_en, f"{s.id} has no explanatory note"


# ------------------------------------------------------------------- changes


def _payload(fingerprint="abc", as_of="2026-09-10", surveys=42, p_win=0.60):
    return {
        "model_fingerprint": fingerprint,
        "as_of": as_of,
        "sondages": {"surveys": surveys},
        "candidats": [{"id": "MLP", "nom": "Marine Le Pen", "p_win": p_win}],
    }


def test_no_previous_run_says_nothing():
    cmp = changes.compare(_payload(), None)
    assert changes.describe(cmp, _payload()) == {"fr": "", "en": ""}


def test_a_model_change_is_never_reported_as_polling():
    """THE point of this module. Between 2026-09-07 and 2026-09-15 there were
    eight distinct fingerprints across nineteen runs, every one of them a change
    to the arithmetic, and the page credited all of it to the polls."""
    current = _payload(fingerprint="new", p_win=0.66)
    previous = _payload(fingerprint="old", p_win=0.50)
    cmp = changes.compare(current, previous)
    assert cmp.model_changed

    text = changes.describe(cmp, current)
    assert "modèle" in text["fr"].lower()
    assert "model" in text["en"].lower()
    # It must not claim new polling caused it.
    assert "sondage" not in text["fr"].split("Mouvements")[0].replace(
        "aux sondages", ""
    )
    assert "cannot be attributed to new polling" in text["en"]


def test_identical_data_is_called_noise_not_news():
    current = _payload(p_win=0.67)
    previous = _payload(p_win=0.65)
    cmp = changes.compare(current, previous)
    assert cmp.same_data
    text = changes.describe(cmp, current)
    assert "noise" in text["en"]
    assert "bruit" in text["fr"]


def test_new_surveys_are_counted():
    current = _payload(as_of="2026-09-12", surveys=45)
    previous = _payload(as_of="2026-09-10", surveys=42)
    cmp = changes.compare(current, previous)
    assert cmp.new_surveys == 3
    assert "3 new surveys" in changes.describe(cmp, current)["en"]


def test_small_moves_are_ignored():
    """Two runs on identical data differ by about a point purely from the
    simulation; reporting that as movement would be inventing news."""
    cmp = changes.compare(_payload(p_win=0.605), _payload(p_win=0.60))
    assert cmp.moves == []


def test_dates_are_written_in_the_language_not_iso():
    cmp = changes.Comparison(
        has_previous=True, previous_as_of="2026-09-10", same_data=True
    )
    text = changes.describe(cmp, {})
    assert "2026-09-10" not in text["fr"], "raw ISO date in French prose"
    assert "10 septembre 2026" in text["fr"]
    assert "10 September 2026" in text["en"]
