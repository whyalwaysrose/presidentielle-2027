"""Tests for the 2022 measured transfers.

These are now a load-bearing input: anchoring on them moved Philippe against
Le Pen from 44% to 53%, so a silent regression here moves the headline
probability of who becomes president.
"""

from __future__ import annotations

import pytest

from presidentielle.calibration import load_results
from presidentielle.data.transfers import FINALIST_A, FINALIST_B, load


@pytest.fixture(scope="module")
def transfers():
    obs, skipped = load(results=load_results())
    return obs, skipped


def test_nothing_is_silently_skipped(transfers):
    """FAILS CLOSED, like the roster. A first-round candidate the mapping does
    not recognise would remove a whole bloc's evidence with nothing looking
    wrong."""
    _, skipped = transfers
    assert not skipped, "records were skipped:\n" + "\n".join(skipped)


def test_enough_observations_across_enough_blocs(transfers):
    obs, _ = transfers
    assert len(obs) >= 30
    assert len({o.bloc for o in obs}) >= 5
    assert len({o.institut for o in obs}) >= 5


def test_destinations_form_a_distribution(transfers):
    obs, _ = transfers
    for o in obs:
        assert o.to_a + o.to_b + o.to_abstention == pytest.approx(1.0)
        assert min(o.to_a, o.to_b, o.to_abstention) >= 0.0


def test_finalists_are_not_treated_as_transfer_sources(transfers):
    """Macron's and Le Pen's own voters are retention, not transfer; the model
    handles them as the finalist's own first-round vote. Counting them here
    would double-count the finalists' base."""
    obs, _ = transfers
    assert FINALIST_A not in {o.source_candidate for o in obs}
    assert FINALIST_B not in {o.source_candidate for o in obs}
    assert "Abstention" not in {o.source_candidate for o in obs}


def test_one_wave_per_institute_and_candidate(transfers):
    """A house publishing weekly must not outvote one publishing once."""
    obs, _ = transfers
    keys = [(o.institut, o.source_candidate) for o in obs]
    assert len(keys) == len(set(keys))


def test_the_measured_ordering_is_the_expected_one(transfers):
    """A sanity check on the join, in the terms the 2022 campaign is known in.

    If the bloc mapping were wrong, this is what would catch it: Zemmour's
    voters went overwhelmingly to Le Pen and the Greens' overwhelmingly to
    Macron, and no plausible mis-join preserves both."""
    import statistics

    obs, _ = transfers
    by_bloc = {}
    for o in obs:
        by_bloc.setdefault(o.bloc, []).append(o)

    def mean_to(bloc, attr):
        return statistics.mean(getattr(o, attr) for o in by_bloc[bloc])

    assert mean_to("reconquete", "to_b") > 0.7, "Zemmour's voters should break RN"
    assert mean_to("ecologiste", "to_a") > 0.5, "Green voters should break Macron"
    assert mean_to("ecologiste", "to_a") > mean_to("droite", "to_a")
    assert mean_to("souverainiste", "to_b") > mean_to("gauche_radicale", "to_b")


def test_radical_left_abstention_is_the_largest(transfers):
    """The defining fact of the 2022 runoff: Mélenchon's electorate abstained
    more than it transferred to either finalist. A transfer model that loses
    this will over-state whoever faces the RN."""
    import statistics

    obs, _ = transfers
    by_bloc = {}
    for o in obs:
        by_bloc.setdefault(o.bloc, []).append(o)
    abst = {b: statistics.mean(o.to_abstention for o in v) for b, v in by_bloc.items()}
    assert abst["gauche_radicale"] == max(abst.values())
    assert abst["gauche_radicale"] > 0.3
