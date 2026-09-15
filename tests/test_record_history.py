"""Tests for the track record and the headline-over-time series.

Both put numbers on a public page that describe the model's own reliability, so
the failure mode is not a crash - it is a chart that quietly flatters.
"""

from __future__ import annotations

import json

import pytest

from presidentielle import history, trackrecord

# ------------------------------------------------------------- track record


def test_track_record_reads_the_committed_scores():
    rec = trackrecord.build()
    assert rec, "no archived backtests found - the page would show no record"
    assert rec["runs"]
    for r in rec["runs"]:
        assert r["days_out"] and r["days_out"] > 0
        assert r["mae_points"] is not None


def test_track_record_always_declares_the_circularity():
    """Shown without this, the record reads as independent validation. It is
    not: the parameters setting interval width were fitted on the same cycle
    being scored."""
    assert trackrecord.build()["circular"] is True


def test_top_two_is_scored_against_who_actually_reached_the_runoff():
    assert sorted(trackrecord.FINALISTS_2022) == ["EM", "MLP"]
    rec = trackrecord.build()
    # Both archived horizons did get the pair right; if that ever changes the
    # page should say so rather than this test being relaxed.
    assert all(r["top2_correct"] for r in rec["runs"])


def test_missing_directory_yields_no_record_rather_than_a_crash(tmp_path):
    assert trackrecord.build(tmp_path) == {}


# ------------------------------------------------------------------ history


def _run(as_of, fingerprint, p_win, name="Marine Le Pen"):
    return {
        "as_of": as_of,
        "model_fingerprint": fingerprint,
        "candidats": [
            {"id": "MLP", "nom": name, "bloc": "rn", "p_win": p_win},
            {"id": "EP", "nom": "Édouard Philippe", "bloc": "centre", "p_win": 0.2},
        ],
    }


def _write(tmp_path, runs):
    for i, r in enumerate(runs):
        (tmp_path / f"2026090{i}T000000Z.json").write_text(
            json.dumps(r), encoding="utf-8"
        )
    return tmp_path


def test_one_point_per_data_date_not_per_run(tmp_path):
    """THE point of this module. Of the first 23 archived runs only four had
    distinct as_of dates; the rest were the same polling re-sampled. A line
    through every run would show the reader my edits, not French opinion."""
    d = _write(tmp_path, [
        _run("2026-09-02", "a", 0.45),
        _run("2026-09-02", "b", 0.62),   # same data, different model
        _run("2026-09-02", "c", 0.61),
        _run("2026-09-03", "c", 0.63),
    ])
    h = history.build(d)
    assert h["dates"] == ["2026-09-02", "2026-09-03"]
    assert len(h["series"]["MLP"]) == 2


def test_the_latest_run_for_a_date_wins(tmp_path):
    """Each point should be the most current arithmetic applied to that data."""
    d = _write(tmp_path, [
        _run("2026-09-02", "old", 0.45),
        _run("2026-09-02", "new", 0.62),
        _run("2026-09-03", "new", 0.63),
    ])
    h = history.build(d)
    assert h["series"]["MLP"][0] == pytest.approx(0.62)


def test_a_model_change_during_the_period_is_flagged(tmp_path):
    d = _write(tmp_path, [
        _run("2026-09-02", "a", 0.45),
        _run("2026-09-03", "b", 0.62),
    ])
    assert history.build(d)["model_changed"] is True


def test_a_stable_model_is_not_flagged(tmp_path):
    d = _write(tmp_path, [
        _run("2026-09-02", "same", 0.60),
        _run("2026-09-03", "same", 0.62),
    ])
    assert history.build(d)["model_changed"] is False


def test_a_single_date_is_not_a_history(tmp_path):
    """One point drawn as a chart implies a trend that does not exist."""
    d = _write(tmp_path, [_run("2026-09-02", "a", 0.6)])
    assert history.build(d) == {}


def test_real_archive_builds_and_flags_honestly():
    h = history.build()
    if not h:
        pytest.skip("no archived runs yet")
    assert len(h["dates"]) == len(set(h["dates"])), "duplicate dates in the series"
    assert h["dates"] == sorted(h["dates"])
    for cid, vals in h["series"].items():
        assert len(vals) == len(h["dates"])
        assert cid in h["noms"]
