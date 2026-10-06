"""Tests for the party records section.

This section puts historical vote shares and political descriptions on a public
page, so it has two distinct failure modes. A wrong NUMBER would be a false
claim about an election; a mislabelled DESCRIPTION would present this site's
summary of a party as the party's own words. Both are guarded here.
"""

from __future__ import annotations

import pytest
import yaml

from presidentielle import parties
from presidentielle.config import load_roster


@pytest.fixture(scope="module")
def payload():
    return parties.build()


@pytest.fixture(scope="module")
def raw():
    return yaml.safe_load(parties.PARTIES_FILE.read_text(encoding="utf-8"))


# ------------------------------------------------------------------- numbers


def test_every_share_is_computed_from_the_ministry_figures(payload):
    """No percentage is written down anywhere, so each one must reproduce from
    the published vote counts. Checked here independently of the code that
    built it."""
    results = parties.load_results()
    for party in payload["partis"]:
        for row in party["resultats"]:
            votes = results[row["annee"]]["candidats"][row["candidat"]]
            expected = votes / results[row["annee"]]["exprimes"]
            assert row["voix"] == votes
            assert row["part"] == pytest.approx(expected, abs=1e-5)


def test_the_record_matches_elections_people_remember(payload):
    """A spot check against the historical record, in case a future refactor
    silently reads the wrong column or the wrong block of a sheet."""
    by_id = {p["id"]: p for p in payload["partis"]}
    share = {
        (p, r["annee"]): r["part"] for p, party in by_id.items() for r in party["resultats"]
    }
    # Jean-Marie Le Pen reaching the 2002 runoff, and the Socialists' collapse.
    assert share[("rn", 2002)] == pytest.approx(0.1686, abs=0.0005)
    assert share[("ps", 2012)] == pytest.approx(0.2863, abs=0.0005)
    assert share[("ps", 2022)] == pytest.approx(0.0175, abs=0.0005)
    # Les Républicains, from winning in 2007 to 4.8% in 2022.
    assert share[("lr", 2007)] == pytest.approx(0.3118, abs=0.0005)
    assert share[("lr", 2022)] == pytest.approx(0.0478, abs=0.0005)


def test_2022_is_read_from_the_file_the_backtest_scores_against(payload):
    """Not copied into the historical file. Two copies of 2022 could drift, and
    the one the backtest uses is the one that must win."""
    historic = yaml.safe_load(parties.HISTORIC_FILE.read_text(encoding="utf-8"))
    assert 2022 not in historic, "2022 must not be duplicated into the historic file"
    results = parties.load_results()
    assert results[2022]["exprimes"] == 35132947


def test_an_unknown_candidate_fails_closed(tmp_path):
    """A party naming someone absent from that year's results is an error. If
    it were skipped, the party's record would silently show them not standing -
    a different and false claim."""
    bad = tmp_path / "partis.yaml"
    bad.write_text(
        yaml.safe_dump({
            "partis": {
                "x": {
                    "nom": "X", "bloc": "centre",
                    "resultats": {2017: "NOBODY Nobody"},
                }
            }
        }),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not in that year's results"):
        parties.build(parties=bad)


# -------------------------------------------------------------------- claims


def test_a_summary_is_never_presented_as_the_party_speaking(payload, raw):
    """`principes` is this site's description, and the page labels it as such.
    Each one must declare where it came from, so the label can be accurate."""
    assert raw["avertissement"]["fr"] and raw["avertissement"]["en"]
    for party in payload["partis"]:
        principles = party["principes"]
        assert principles["fr"] and principles["en"], party["id"]
        assert principles["source"] in {"programme", "positions"}, party["id"]


def test_every_link_is_https_or_absent(payload):
    """No link is better than a wrong one. The NPA has none deliberately: it
    split in 2022 and naming a successor would take a side."""
    for party in payload["partis"]:
        for url in (party["site"], party["principes"]["url"]):
            if url is not None:
                assert url.startswith("https://"), f"{party['id']}: {url}"
    npa = next(p for p in payload["partis"] if p["id"] == "npa")
    assert npa["site"] is None and npa["principes"]["url"] is None


def test_renamed_and_contested_lineages_are_flagged(payload):
    """A single line running from 2002 to 2022 implies a continuity that
    sometimes is not there. The three the site footnotes: LFI did not exist in
    2012 (Mélenchon stood for the Front de gauche), Bayrou's 2002 run was the
    UDF's, and the NPA split in 2022."""
    flagged = {p["id"] for p in payload["partis"] if p["lignee_contestee"]}
    assert {"lfi", "modem", "npa"} <= flagged
    for party in payload["partis"]:
        assert party["lignee"].get("fr") and party["lignee"].get("en"), party["id"]


def test_parties_that_never_stood_are_shown_rather_than_dropped(payload):
    """Horizons has never contested a presidential election, and its leader is
    second in this forecast. That absence is information."""
    horizons = next(p for p in payload["partis"] if p["id"] == "horizons")
    assert horizons["resultats"] == []
    assert horizons["dernier"] is None
    # ...and they sort last, after everyone with a record.
    order = [p["dernier"] is None for p in payload["partis"]]
    assert order == sorted(order)


def test_blocs_match_the_model(payload):
    """The section is coloured by bloc and sits beside a forecast that uses the
    same nine. A party in a tenth bloc would render unstyled."""
    known = set(load_roster().blocs)
    for party in payload["partis"]:
        assert party["bloc"] in known, f"{party['id']}: {party['bloc']}"


def test_every_election_carries_its_source(payload):
    """Per CLAUDE.md: a figure a reader cannot trace is a figure they have to
    take on faith."""
    assert [e["annee"] for e in payload["elections"]] == [2002, 2007, 2012, 2017, 2022]
    for election in payload["elections"]:
        assert election["source"].startswith("https://www.data.gouv.fr/")
        assert election["exprimes"] > 25_000_000


def test_the_published_file_is_not_stale(payload):
    """`site/data/partis.json` is what readers get. It is rewritten by every
    `presidentielle run` and committed by the daily workflow, so if it differs
    from a fresh build, a config change was edited but never published."""
    import json

    from presidentielle import paths

    published = paths.SITE_DATA / "partis.json"
    if not published.exists():
        pytest.skip("not generated yet - run `presidentielle partis`")
    on_disk = json.loads(published.read_text(encoding="utf-8"))
    assert on_disk == json.loads(json.dumps(payload, default=str)), (
        "site/data/partis.json is out of date - run `presidentielle partis`"
    )
