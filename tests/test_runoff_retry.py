"""Tests for refitting the runoff when a chain gets stuck.

About one run in ten, one chain of four wanders into high gamma, the proximity
softmax saturates and it can no longer move bloc positions past one another.
Measured: that chain fits 21 log units worse than its siblings and sits about
8 sigma from its own prior, so it is a trap rather than a rival answer, and
refitting past it is legitimate (`scripts/check_runoff_convergence.py`).

These test the RETRY LOGIC itself, with fake fits. An untested retry that
silently never retried would reproduce the very bug it exists to cover - the
mistake already made once in this repo with a failure notifier that could not
see half of its own workflow.
"""

from __future__ import annotations

from presidentielle.cli import (
    RUNOFF_MAX_RHAT,
    RUNOFF_MIN_ESS,
    RUNOFF_SEED_STRIDE,
    fit_until_converged,
)

GOOD = (1.01, 800.0)
STUCK = (1.53, 7.0)          # the real numbers from the 2026-10-09 measurement
THIN = (1.00, 90.0)          # converged-looking, but too few effective draws


def _fitter(results):
    """A fake sampler: returns the next canned result, recording its seeds."""
    seeds: list[int] = []
    sequence = list(results)

    def fit(seed):
        seeds.append(seed)
        return sequence.pop(0)

    return fit, seeds


def test_a_healthy_fit_is_used_as_is(caplog):
    fit, seeds = _fitter([GOOD])
    idata, attempts = fit_until_converged(fit, lambda r: r, 100)
    assert idata == GOOD
    assert seeds == [100], "a converged fit must not be refitted"
    assert attempts == [{"seed": 100, "rhat": 1.01, "ess": 800}]


def test_a_stuck_chain_is_refitted_with_a_different_seed():
    fit, seeds = _fitter([STUCK, GOOD])
    idata, attempts = fit_until_converged(fit, lambda r: r, 100)
    assert idata == GOOD, "the second, healthy fit must be the one used"
    assert seeds == [100, 100 + RUNOFF_SEED_STRIDE]
    assert len(attempts) == 2
    # The failure is published, not swallowed: a reader of the JSON can see
    # that the first attempt was discarded, and why.
    assert attempts[0] == {"seed": 100, "rhat": 1.53, "ess": 7}


def test_too_few_effective_draws_also_counts_as_stuck():
    """r-hat alone is not enough. A chain can look mixed and still carry almost
    no information about the geometry."""
    assert THIN[0] <= RUNOFF_MAX_RHAT and THIN[1] < RUNOFF_MIN_ESS
    fit, seeds = _fitter([THIN, GOOD])
    _, attempts = fit_until_converged(fit, lambda r: r, 1)
    assert len(attempts) == 2


def test_it_gives_up_rather_than_refitting_for_ever():
    """Three attempts, then hand back the last one. `cmd_run` fails closed on
    it: retrying until something passes would be seed-shopping, and a run that
    cannot converge should stop rather than publish."""
    fit, seeds = _fitter([STUCK, STUCK, STUCK])
    idata, attempts = fit_until_converged(fit, lambda r: r, 100)
    assert idata == STUCK
    assert len(attempts) == 3 and len(seeds) == 3
    assert len(set(seeds)) == 3, "each attempt needs its own seed"
    assert all(a["rhat"] > RUNOFF_MAX_RHAT for a in attempts)


def test_the_thresholds_are_the_ones_the_run_enforces():
    """The gate in `cmd_run` and the retry must agree. If they drifted apart,
    a run could retry three times and then publish the result anyway."""
    import inspect

    from presidentielle import cli

    source = inspect.getsource(cli.cmd_run)
    assert 'runoff_fit["max_rhat"] > RUNOFF_MAX_RHAT' in source
    assert 'runoff_fit["min_ess_bulk"] < RUNOFF_MIN_ESS' in source
