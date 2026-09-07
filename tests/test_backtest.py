"""Tests for the 2022 backtest.

A backtest that quietly uses the future is worse than no backtest, because it
produces a reassuring number. Most of these check that it cannot.
"""

from __future__ import annotations

import datetime as dt

import pytest

from presidentielle.backtest import (
    R1_2022,
    config_for_2022,
    load_archive,
    load_roster_2022,
    parse_nsppolls,
)
from presidentielle.config import load_model_config


@pytest.fixture(scope="module")
def archive():
    return load_archive()


@pytest.fixture(scope="module")
def roster22():
    return load_roster_2022()


def test_2022_roster_uses_the_same_blocs_as_2027(roster22):
    """Blocs are defined once, in candidats_2027.yaml. If the 2022 file grew
    its own copy they would drift apart and the nests would stop meaning the
    same thing across cycles."""
    from presidentielle.config import load_roster

    assert roster22.blocs == load_roster().blocs


def test_the_2022_roster_covers_the_archive(roster22, archive):
    """FAILS CLOSED, so a missing name costs a whole hypothesis. The only thing
    that may be skipped is the archive's records with a null candidate name."""
    _, skipped = parse_nsppolls(
        archive,
        roster=roster22,
        as_of=dt.date(2022, 4, 9),
        history_start=dt.date(2021, 1, 1),
    )
    unexpected = [s for s in skipped if "None" not in s]
    assert not unexpected, "unrecognised candidates:\n" + "\n".join(unexpected[:10])


def test_ciotti_is_in_a_different_bloc_from_2027(roster22):
    """The reason the 2022 roster exists at all: he stood for LR in 2022 and
    leads the RN-allied UDR in 2027. One file cannot hold both."""
    from presidentielle.config import load_roster

    assert roster22.candidats["EC"].bloc == "droite"
    assert load_roster().candidats["EC"].bloc == "reconquete"


def test_no_poll_after_the_cutoff_is_used(roster22, archive):
    """THE test. Everything else is detail."""
    cutoff = dt.date(2021, 9, 1)
    hyps, _ = parse_nsppolls(
        archive, roster=roster22, as_of=cutoff, history_start=dt.date(2021, 1, 1)
    )
    assert hyps
    assert max(h.fin for h in hyps) <= cutoff


def test_a_later_cutoff_sees_strictly_more(roster22, archive):
    early, _ = parse_nsppolls(
        archive, roster=roster22, as_of=dt.date(2021, 9, 1),
        history_start=dt.date(2021, 1, 1),
    )
    late, _ = parse_nsppolls(
        archive, roster=roster22, as_of=dt.date(2022, 3, 11),
        history_start=dt.date(2021, 1, 1),
    )
    assert len(late) > len(early)


def test_backtest_config_targets_the_2022_election():
    cfg = config_for_2022(load_model_config(), dt.date(2021, 1, 1))
    assert cfg.election.premier_tour == R1_2022
    assert cfg.election.second_tour == dt.date(2022, 4, 24)
    assert cfg.polls.history_start == dt.date(2021, 1, 1)


def test_shares_are_normalised(roster22, archive):
    hyps, _ = parse_nsppolls(
        archive, roster=roster22, as_of=dt.date(2022, 4, 9),
        history_start=dt.date(2021, 1, 1),
    )
    for h in hyps:
        assert sum(h.shares.values()) == pytest.approx(1.0)
        if h.tour == 2:
            assert len(h.shares) == 2


def test_zemmour_is_polled_before_he_declared(roster22, archive):
    """A property of the data worth knowing about, and the reason the ballot
    simulation matters in a backtest: in September 2021 institutes were already
    pricing a Zemmour candidacy that did not formally exist. The model has to
    treat standing as uncertain rather than given."""
    hyps, _ = parse_nsppolls(
        archive, roster=roster22, as_of=dt.date(2021, 9, 1),
        history_start=dt.date(2021, 1, 1),
    )
    first = [h for h in hyps if h.tour == 1]
    tested = sum(1 for h in first if "EZ" in h.shares)
    assert 0 < tested < len(first), "Zemmour should be tested in some fields, not all"
