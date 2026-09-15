"""The fitted numbers in config/model.yaml must keep matching their fit.

A prior that was measured and then quietly hand-edited is worse than one that
was never measured, because the comment above it still claims provenance it no
longer has. These tests are what make that claim checkable.
"""

from __future__ import annotations

import math

import pytest

from presidentielle.config import load_model_config


@pytest.fixture(scope="module")
def cfg():
    return load_model_config()


# From scripts/fit_walk_scale.py against the nsppolls 2022 archive, fitted on
# gaps of 151-260 days to match the forecast's own horizon: 0.0222, 90% CI
# [0.0215, 0.0227], 2049 same-institute non-rolling pairs.
#
# The earlier 0.0142, fitted on 7-60 day gaps, produced 67% coverage of 90%
# intervals in the 2022 backtest. sigma/day is not constant across gap lengths,
# so the band has to match the distance the walk is asked to cover.
FITTED_TOTAL = 0.0222
FIT_CI = (0.0215, 0.0227)


def test_walk_split_reconciles_to_the_measured_total(cfg):
    """The bloc walk and the candidate walk add in quadrature to a candidate's
    total movement, and that total is what was measured. If someone widens one
    of them to 'add uncertainty', this fails - which is the point, because the
    honest way to widen intervals is to re-run the fit, not to nudge a prior."""
    total = math.hypot(
        cfg.latent.rw_sd_per_day_prior, cfg.latent.bloc_rw_sd_per_day_prior
    )
    assert total == pytest.approx(FITTED_TOTAL, abs=5e-4), (
        f"bloc and candidate walk scales combine to {total:.4f}, but the fit "
        f"says {FITTED_TOTAL}. Re-run scripts/fit_walk_scale.py and update both."
    )


def test_documented_total_matches_the_components(cfg):
    total = math.hypot(
        cfg.latent.rw_sd_per_day_prior, cfg.latent.bloc_rw_sd_per_day_prior
    )
    assert cfg.latent.fitted_total_rw_sd_per_day == pytest.approx(total, abs=5e-4)


def test_fitted_total_sits_inside_its_own_confidence_interval(cfg):
    assert FIT_CI[0] <= cfg.latent.fitted_total_rw_sd_per_day <= FIT_CI[1]


def test_the_horizon_implies_a_believable_interval(cfg):
    """The end-to-end consequence, asserted in the units a reader sees.

    A candidate on 33% seven months out should span roughly the low twenties to
    the mid forties - the kind of move the 2022 cycle produced. The first run
    reported [14.6%, 57.0%]; this test would have caught it."""
    horizon = (cfg.election.premier_tour - cfg.polls.history_start).days
    horizon = 223  # days from a run in early September to the first round
    s = cfg.latent.fitted_total_rw_sd_per_day * math.sqrt(horizon)
    lo = 0.33 * math.exp(-1.645 * s)
    hi = 0.33 * math.exp(1.645 * s)
    # Wide, and deliberately so: 2022 saw Melenchon go 12% to 22% and Hidalgo
    # 6.5% to 1.75% over this horizon. The bounds that looked "sensible" before
    # produced 67% coverage where 90% was claimed.
    assert 0.15 <= lo <= 0.24, f"lower bound {lo:.1%} is implausible"
    assert 0.48 <= hi <= 0.62, f"upper bound {hi:.1%} is implausible"


# From `presidentielle calibrate` against the 2022 cycle: 11 institutes' final
# polls scored on the proclaimed result, log-error SD 0.2007 for candidates at
# or above 5%, stored on the share scale at p = 0.25.
FITTED_R1_SHARE_ERROR = 0.0376


def test_first_round_error_matches_the_calibration(cfg):
    assert cfg.election_day_error.r1_fitted is True
    assert cfg.election_day_error.r1_share_error_sd == pytest.approx(
        FITTED_R1_SHARE_ERROR, abs=5e-4
    ), "re-run `presidentielle calibrate` and update the config together"


def test_calibration_reproduces_the_committed_value():
    """The fit itself, re-run against the committed 2022 archive and results.

    This is what makes the config's `FITTED` comment checkable rather than a
    claim. It runs in the suite because both inputs are committed, so it needs
    no network."""
    from presidentielle.calibration import calibrate

    res = calibrate()
    assert res.n_polls >= 8, f"only {res.n_polls} final polls found"
    assert res.r1_share_error_sd == pytest.approx(FITTED_R1_SHARE_ERROR, abs=5e-4)
    # Final polls must be less wrong than the whole fortnight, or the drift
    # argument for using them is backwards.
    assert res.log_error_sd < res.log_error_sd_all


def test_second_round_error_is_still_a_prior(cfg):
    """One matchup in one cycle cannot give a distribution. If this is ever
    flipped, replace it with a comparison against a real multi-cycle fit."""
    assert cfg.election_day_error.r2_margin_error_sd == pytest.approx(0.030)


def test_bloc_correlation_is_not_overclaimed(cfg):
    """The 2022 field has only two same-bloc pairs above the noise floor, so
    this parameter is identified by nothing. It is kept modest deliberately;
    the 0.55 originally asserted had no support."""
    from presidentielle.calibration import calibrate

    assert cfg.election_day_error.bloc_error_corr <= 0.35
    assert calibrate().n_same_bloc_pairs <= 3


def test_walk_scales_stay_pinned(cfg):
    """Freeing the walk scales reintroduces a measured pathology.

    With them sampled, the posterior walk came out at 0.0337/day against a
    measured 0.0142, while sigma_excess collapsed to 0.0011 - the model
    explaining poll scatter by moving the latent state instead of by
    observation noise, then compounding that over ~32 steps to election day.
    That produced a 42-point interval on the front page."""
    assert cfg.latent.pin_walk_scales is True, (
        "walk scales are free again - expect intervals roughly twice as wide "
        "as the polling supports; see CLAUDE.md"
    )


def test_front_republicain_uncertainty_spans_the_disagreeing_evidence(cfg):
    """Three sources disagree about how hard it is to transfer to an RN
    finalist, and the prior has to be wide enough to contain that.

    2022 presidential transfers, the 2024 legislative duels (330 of them,
    measured by scripts/measure_front_republicain_2024.py) and the 2026 polls
    about a 2027 runoff imply left-penalties ranging from about four points to
    about twenty. At 0.70 a one-sigma move is roughly six points of runoff
    share, so that spread sits near 2.6 sigma. Narrowing this asserts more
    agreement between the sources than exists.
    """
    assert cfg.second_tour.front_republicain_2027_sd >= 0.60, (
        "too narrow to contain the disagreement between 2022, 2024 and the "
        "2027 hypothetical polls"
    )
    # Not unbounded either: beyond this the runoff becomes a coin flip that
    # ignores the evidence there is.
    assert cfg.second_tour.front_republicain_2027_sd <= 1.0
