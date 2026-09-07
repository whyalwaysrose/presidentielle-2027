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


# From scripts/fit_walk_scale.py against the nsppolls 2022 archive:
#   0.0142, 90% CI [0.0025, 0.0206], 787 same-institute non-rolling pairs.
FITTED_TOTAL = 0.0142
FIT_CI = (0.0025, 0.0206)


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
    assert 0.20 <= lo <= 0.27, f"lower bound {lo:.1%} is implausible"
    assert 0.40 <= hi <= 0.52, f"upper bound {hi:.1%} is implausible"


def test_election_day_error_is_flagged_as_unfitted(cfg):
    """These scales are still priors. The flag is what stops the README and the
    site claiming otherwise; when `calibrate` lands, flip it and this test
    should be replaced by a real comparison against the fit."""
    assert cfg.election_day_error.fitted is False, (
        "election_day_error.fitted is now true - replace this test with one "
        "that checks the config against the calibration output"
    )


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
