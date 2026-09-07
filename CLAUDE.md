# Notes for Claude Code

Context for working in this repo. Read `docs/METHODOLOGY.md` before changing
anything in `src/presidentielle/model/`.

## Environment

- Windows, Python 3.12 in `.venv`. Use `.venv\Scripts\python.exe`.
- Always set `PYTENSOR_FLAGS=cxx=` — there is no C++ compiler and none is
  needed. Sampling goes through **nutpie** (Numba). The `g++ not available`
  warning is expected noise.
- `pytest -q` runs in ~8 seconds and never samples. Keep it that way; sampling
  belongs in `presidentielle run`.
- A full run is ~30–45 minutes. Use `presidentielle run --draws 60` for a smoke
  test; it prints a warning that the result is not publishable.

## Invariants — do not break these silently

1. **The nested logit must reduce to a plain softmax at lambda = 1.**
   `tests/test_model.py` asserts it to 1e-12. IIA is deliberately *nested
   inside* the model rather than assumed away; if this drifts, every claim
   about what the nesting buys becomes unverifiable.
2. **House effects must stay sum-to-zero across institutes.** Without the
   constraint a constant moves freely between the house effects and the latent
   strengths for an identical likelihood, and the sampler rides that ridge.
3. **Random walks must stay non-centred.** Cumulative sums of standard normals
   scaled by a separately sampled SD.
4. **There is no `bloc_start`, and there must not be one.** A starting level
   per bloc is exactly absorbed by the starting levels of that bloc's own
   members — nine redundant dimensions. It was there in the first draft and
   sampling did not finish; removing it, plus item 5, is what made the model
   tractable.
5. **Bloc-level walks exist only for blocs with more than one polled
   candidate.** With a single member, the bloc innovation and that candidate's
   own innovation are exchangeable at every one of ~145 steps. Same ridge, far
   larger. `identified_blocs` in `design.py` is what gates this.
6. **The latent state is centred across candidates at every time step.** The
   softmax is shift-invariant; this removes exactly that one degree of freedom.
7. **The roster fails closed.** A candidate id not in
   `config/candidats_2027.yaml` causes the whole hypothesis to be skipped, not
   the candidate to be dropped. Dropping one candidate would renormalise
   everyone else upward — a poll where an unknown name polled 12% would inflate
   every other candidate in it by about 14%. `presidentielle audit` lists
   anything skipped, and a test asserts the list is empty.
8. **One survey is one sample.** `surveys.py` scales each hypothesis's
   effective sample by `m ** -exponent`. An institute pricing 13 fields asked
   one sample of ~1500 people 13 times. Remove this and every interval narrows
   for no reason; a test asserts the effective sample stays below 75% of raw.
9. **The grid ends on election day, so there is no separate drift term.**
   Adding one double-counts the movement between now and April.
10. **Ballot probabilities use a half-life, never a flat window.** See below —
    this is measured, not stylistic.
11. **`site/data/forecast.json` and `outputs/runs/**` stay committed.** The
    daily workflow diffs against the previous archived run.
12. **The random-walk scales are MEASURED and PINNED. Do not hand-edit, and do
    not free them.** `latent.rw_sd_per_day_prior` and
    `bloc_rw_sd_per_day_prior` combine in quadrature to 0.0142/day, measured by
    `scripts/fit_walk_scale.py`, and `tests/test_calibration.py` asserts they
    still do. `pin_walk_scales: true` holds them there during sampling. This
    sets the width of every interval on the site — the walk runs ~32 free
    weekly steps from the last poll to election day. If intervals look wrong,
    re-run the fit; do not nudge the prior and do not free the parameter.
13. **Bump `SCHEMA_VERSION` in `outputs.py` and the matching constant in
    `site/js/app.js` together.** The page checks it and shows a banner rather
    than rendering blanks.

## The RN half-life is a measurement, not a preference

The single most consequential fact about this ballot is who the RN runs. The
testing pattern is a **step function**:

| period | Le Pen tested | Bardella tested |
|---|---|---|
| 2025-04 → 2026-06 (she is ineligible) | 17–50% | 50–100% |
| 2026-07 → now (ban cut on 2026-07-07) | **100%** | **0%** |

A flat 120-day window spans the break and reports Le Pen 67% / Bardella 33%.
The 45-day half-life reports 78% / 20%. `tests/test_field.py` asserts both
directions — that the decayed estimate exceeds 0.7, and that a long half-life
degrades below it. If you change `half_life_days`, expect that test to move and
think about which side of the break you are averaging over.

## Where things live

| Task | File |
|---|---|
| Change a prior or hyperparameter | `config/model.yaml` (never hard-code in Python) |
| Add or re-bloc a candidate | `config/candidats_2027.yaml` |
| Pin a candidacy to a known fact | `config/model.yaml` → `field.overrides` |
| Change the first-round model | `src/presidentielle/model/hierarchical.py` |
| Change the ballot simulation | `src/presidentielle/model/field.py` |
| Change the runoff | `src/presidentielle/model/runoff.py` |
| Change how worlds are simulated | `src/presidentielle/model/simulate.py` |
| Change what the JSON contains | `src/presidentielle/outputs.py` |
| Change the page | `site/` — plain HTML/CSS/JS, no build step |
| Change wording in either language | `site/js/i18n.js` and `src/presidentielle/commentary.py` |

## Language

French is the default and the source of truth. The English is a translation,
not the other way round. Commentary is generated **in both languages at build
time**, never machine-translated in the browser — probability language does not
survive that (`chances de gagner` for a posterior, tenses implying the election
has happened).

`localStorage` is read through a guard in `i18n.js`. `getItem` *throws*
(SecurityError) with cookies blocked or inside some in-app webviews, and an
unguarded read at startup takes the whole script down, leaving a page that
renders perfectly and responds to nothing.

## Cache-busting: bump the assets AND expect the shell to be stale

`site/index.html` references every asset with `?v=N`, and `BUILD` in `app.js`
carries the same number. Bump them together, as one edit.

That alone is not sufficient, and it bit during development: the browser had
`index.html` itself cached, so it kept requesting the *old* `?v=1` URLs and a
fixed `i18n.js` sat on the server unused, while the page looked simply
unchanged. When testing a front-end fix, load `index.html?bust=<something>` or
hard-reload; when a deployed change appears not to have landed, check
`Array.from(document.scripts).map(s => s.src)` before touching the JS again.

## The walk absorbs observation noise unless you pin it

Worth reading before touching anything about uncertainty, because the first
attempt at this got the diagnosis wrong.

The first full run reported Le Pen at 32.4% with a 90% interval of
**[14.6%, 57.0%]** — a 42-point band. Sampling had converged (R-hat 1.006, ESS
3375) and the nesting was well identified, so the fit was not the problem.

**First diagnosis, wrong.** The prior `rw_sd_per_day_prior` was an asserted
0.020. `scripts/fit_walk_scale.py` measures the real figure from the 2022 cycle
— **0.0142/day**, 90% CI [0.0025, 0.0206], 787 same-institute non-rolling pairs
— so the prior was tightened to match. The intervals barely moved: 32.2%
[14.5%, 56.3%]. A weak prior does not bind; the likelihood overrides it.

**Actual cause, measured.** With the scales free, the posterior came out at:

| | |
|---|---|
| walk scale measured from real polls | 0.0142/day |
| walk scale the model fitted | **0.0337/day** (2.4x) |
| `sigma_excess` (non-sampling poll error) | **0.0011** (~zero) |

A 146-node weekly grid backed by 39 surveys is far more flexible than a single
observation-noise term, so the model explained poll-to-poll *scatter* by moving
the latent state and concluded French polls have essentially no non-sampling
error. That inflated volatility then compounded over ~32 unconstrained steps to
election day.

**Fix:** `pin_walk_scales: true` holds the scales at the measured value. This is
not a fudge — these are not parameters we lack information about;
`fit_walk_scale.py` measures exactly this quantity from real polls, net of
sampling noise. After pinning, `sigma_excess` rose to 0.0034 and Le Pen's
interval became 35.0% [24.3%, 47.9%], against published polling of 33–38%.
Set the flag false to reproduce the pathology.

Two things about the fit script matter if it is re-run. The 2022 file is full of
**daily rolling waves on an overlapping panel**, whose consecutive readings move
*less* than two independent samples would; including them returned a negative
excess variance, i.e. no answer at all. And pairs are compared **within an
institute**, because a gap between two houses contains their house effect rather
than movement.

## The runoff model is checked against the polls it was fitted to

`diagnostics.runoff_fit` reports MAE and bias of the transfer model against the
54 tested matchups — currently **2.03 points MAE, −0.47 bias**. The runoff
decides the presidency, so a transfer model that missed the tested matchups
would be asserting something the polls contradict. Check this before believing
any P(win) figure.

## Known rough edges

- **Election-day error scales are not yet fitted.** `election_day_error.fitted`
  is `false` and the values are priors. `presidentielle calibrate` against the
  nsppolls 2022 archive is the next substantial piece of work; until it exists,
  the intervals are honest about the model's own uncertainty but not calibrated
  against how French polls have actually missed.
- **The runoff is a two-stage fit.** Justified in `runoff.py`, but a joint fit
  would be cleaner.
- **No sub-national estimates**, deliberately. There is no département-level
  polling; a map from uniform 2022 swing would look far more authoritative than
  it is.
- **The population/universe effect is not modelled.** All three sample
  universes in the data are general-population, with no likely-voter screen to
  separate. The one real difference — metropolitan-only universes excluding the
  overseas départements — affects about 10% of records and ~2% of the
  electorate.
