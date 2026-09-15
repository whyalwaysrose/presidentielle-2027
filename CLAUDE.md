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
13. **Every polled candidate needs a first-round base, not just the ones on
    the reference ballot.** `_reference_shares` prices arbitration alternatives
    on the ballot they would actually be on. Read straight off the reference
    ballot, Bardella came back at **zero** — the RN arbitration resolves to Le
    Pen — so every Bardella runoff was fitted with him holding no first-round
    votes. It cost 14.5 points on Bardella-versus-Mélenchon, pushed runoff MAE
    from 1.97 to 3.54, and read as tension between the 2022 and 2027 evidence
    rather than as a bug. `tests/test_field.py` guards it.
14. **A run must never publish a forecast it could not fully read.**
    `presidentielle run` exits 2 if any record was skipped, unless
    `--allow-skipped`. Skipping an unreadable hypothesis is still the right
    thing - guessing a bloc would be worse - but publishing without saying so
    is not. See below.
15. **Bump `SCHEMA_VERSION` in `outputs.py` and the matching constant in
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

## The backtest is what catches overconfidence

`presidentielle backtest --as-of DATE` reruns the whole pipeline on the 2022
cycle using only what existed on that date, and scores it against the
proclaimed result.

It found the thing nothing else would have. At 221 days out - the horizon the
live forecast sits at - the model put the right pair in the runoff and had a
median absolute error of 2.85 points, but its **90% intervals covered 67% of
outcomes and its 50% intervals covered 25%**. The point predictions were fine
and the uncertainty was a fiction.

The cause was the walk scale being fitted at 7-60 day gaps and applied over 221
days (see below). After the horizon-matched refit:

| | 221d before -> after | 30d before -> after |
|---|---|---|
| 90% coverage | 67% -> **83%** | 67% -> **75%** |
| 50% coverage | 25% -> **42%** | 50% -> 50% |
| MAE (points) | 2.85 -> 2.82 | 2.80 -> 2.71 |

Coverage improved at both horizons while point accuracy held, which is what a
fix to an uncertainty parameter should look like. Re-run the backtest after
touching anything that sets interval width, and treat coverage far below
nominal as a bug rather than as noise. Scores live in `outputs/backtests/`.

**Do not tune the tails on this.** The residual gap is concentrated at 30 days,
where the 50% intervals are exactly right and the 90% ones are not - thin tails,
from a final month in which Melenchon gained ten points and Pecresse lost six.
Twelve candidates in one cycle, whose misses are one correlated story about
*vote utile*, cannot support fitting a tail parameter. Fitting one would fit the
2022 campaign, not French elections.

**No lookahead.** Polls are filtered by fieldwork end date, the 2022 measured
transfers are excluded (they were published during the April campaign), and the
2022 roster is separate because a candidate's bloc can differ between cycles -
Ciotti stood for LR in 2022 and leads the RN-allied UDR in 2027.

**The one leak that cannot be closed:** the walk scale and the election-day
error are both fitted on the 2022 cycle, so coverage measured on 2022 is partly
circular. With one cycle of French polling there is no way around it. The
backtest says so in its own output, and the non-circular parts - point
predictions, ballot simulation, which pair reaches the runoff - are what it can
genuinely validate.

## The walk is not a random walk, and the horizon matters

A Gaussian random walk implies movement scales as sqrt(time), so sigma/day must
be the same at every gap length. Measured on 2022, excluding rolling polls:

| gap (days) | sigma/day | implied over 221 days |
|---|---|---|
| 7-21 | 0.0157 | 0.234 |
| 22-45 | 0.0307 | 0.457 |
| 46-90 | 0.0290 | 0.431 |
| 91-150 | 0.0261 | 0.388 |
| **151-260** | **0.0222** | **0.329** |

Short gaps understate because an institute reuses panels and methods, so two
readings a fortnight apart are more alike than two independent draws on the
same opinion. Long gaps come back down: mean reversion.

The fit is therefore **horizon-matched** to the 151-260 band, the distance from
the last poll to election day. Same principle as the election-day error, fitted
on final polls because that is where it is applied. If the forecast horizon
ever changes materially, change the band with it.

This also overturned a judgement made earlier in the project. A 0.020 scale was
once rejected because it produced a 90% interval of [14.6%, 57.0%] for Le Pen,
which "looked absurd". The backtest says the aesthetic judgement was wrong: at
the narrower scale the model covered 67% of outcomes where it claimed 90%. 2022
really did move that much - Melenchon 12% to 22%, Hidalgo 6.5% to 1.75%.

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
54 tested matchups. The runoff decides the presidency, so a transfer model that
missed them would be asserting something the polls contradict, and only P(win)
would move — nothing else on the page would look wrong.

That diagnostic is what caught invariant 13: MAE jumped 1.97 → 3.54 with a
14.5-point miss on one matchup, which looked like the 2022 anchor fighting the
2027 polls and was actually a zero first-round base. **Check it before
believing any P(win) figure, and treat a jump as a bug until proven otherwise.**

## Never write FITTED over a number you chose

Three config comments once cited `presidentielle calibrate` as the provenance
of `excess_sd_prior`, `survey_weight_exponent` and `election_day_error`. **That
command did not exist.** The docs also called the 2022 transfers "the empirical
anchor for the runoff model" while `reports.csv` was never loaded, and claimed
ballot overrides came from `annonce_candidature` / `retrait_candidature`, which
are still never read.

A comment claiming provenance it does not have is worse than no comment,
because it stops anyone checking. `calibrate` now exists and the transfers are
now loaded; the remaining asserted numbers say **ASSERTED** and why. Keep it
that way: if you cannot name the script that produced a number, it is not
fitted.

## The election-day error is fitted; the runoff's 2027 term cannot be

`presidentielle calibrate` scores each institute's **final** 2022 poll against
the proclaimed result. Using every poll in the closing fortnight instead gives
0.310 log SD against 0.247 for finals alone — the gap is Mélenchon's late surge,
which is movement the random walk already carries, not polling error.

Fitted on candidates at or above 5% (log SD 0.201, against 0.247 for everyone
above 2%), because the model applies one constant log-scale error while real
error is not constant there. `r1_share_error_sd` went from an invented 0.0220
to a measured **0.0376**.

`bloc_error_corr` is **not** fitted and cannot be: the 2022 field has only two
same-bloc pairs above the noise floor. It is kept at 0.30 rather than the 0.55
originally asserted, and it is second-order anyway — arbitrations mean the RN
and Reconquête field one candidate at a time, so it only bites in the centre.

## Where the runoff's uncertainty lives, and why it is not a fitted parameter

The transfer model is anchored on 43 measured 2022 transfers as well as the 54
hypothetical 2027 matchups. That anchoring moved Philippe-vs-Le Pen from 44% to
53% — into line with the runoff polls the model had been under-reading.

The first attempt carried the 2027 question as a *fitted* per-cycle delta with a
drift between cycles. It did not work: `delta_2022` came out at 0.064, because
the quadratic distance term already explains 2022's transfers and delta is
absorbed into the bloc positions. A drift multiplying zero expresses nothing.
(Position priors were also tightened from 0.25 to 0.12 for the same confound.)

So `front_republicain_2027_sd` is applied **per simulated world in
simulate.py**, not fitted — because a fitted one is fitted away: the 54 runoff
hypotheses would pin it to what 2026 respondents currently say and report that
as knowledge about May 2027. Sized so the one observed cycle transition (the
RN's runoff share moving 7.3 points from 2017 to 2022) is about 1.8 sigma;
`scripts/check_runoff_sensitivity.py` translates it into points of runoff share.

## A new candidate breaks the daily run, and should

This is the expected maintenance event, not a defect. New names appear in the
polling as the field forms, the roster fails closed on anything it does not
know, and somebody has to decide which bloc they belong in. Fix: add them to
`config/candidats_2027.yaml` with a bloc, citing the upstream `parti` field and
whatever the co-occurrence pattern shows.

**It happened on 2026-09-09** with Karim Bouamrane (PS, mayor of Saint-Ouen),
first tested by OpinionWay. What went wrong was not the failure but the delay:

- 2026-09-13: the run skipped three hypotheses, warned in its logs, and
  **published anyway**. Nothing failed.
- 2026-09-14: the next day's `pytest` finally caught it, against the cache the
  13th had committed.

So two days of published forecasts were computed on a field the roster could
not fully read, and the alarm came from a step that only looks at *yesterday's*
data. Two changes close that:

1. `presidentielle run` now **fails closed** on any skipped record. Stale but
   correct beats fresh but quietly wrong - the site keeps serving the last good
   forecast until the roster is updated.
2. `daily.yml` **fetches before it tests**, so the suite's "the roster can read
   every polled candidate" assertion applies to the data that run is about to
   use, rather than to the previous day's.

`diagnostics.skipped_detail` carries the list, so an `--allow-skipped` run is
visible in the output rather than only in a log.

## Facts beat the proxy, and the two agree

Ballot probabilities come from testing frequency, which is a proxy. Where
`candidats.csv` records an actual declaration or withdrawal, that fact wins -
`src/presidentielle/data/candidacies.py`.

This is not a marginal correction. **Bardella withdrew on 2026-07-07**, the day
Le Pen's ineligibility was cut. On frequency alone the model gave him a 20%
chance of being on the ballot and roughly 14% of the presidency, after he had
stood down.

The reason a community-maintained CSV field is trusted here is that a second,
independent signal agrees with it: institutes stopped testing Bardella entirely
from July 2026, the same month. `tests/test_candidacies.py` asserts that
agreement, and will fail if the two ever diverge - which is the point at which
the CSV should stop being trusted.

Precedence, weakest to strongest: testing frequency, then declarations and
withdrawals, then `field.overrides` in the config. A withdrawal SETS the
probability to zero; a declaration only sets a FLOOR, because a declared
candidate still needs 500 parrainages and can change their mind - Darmanin
declared on 2026-08-17 and withdrew eight days later.

## Named ballots are cheap; the caveat on them is not optional

`config/scenarios_2027.yaml` defines scenarios as *modifications of the
reference ballot* (`remove: [EP]`), never as explicit lists, so they survive
the roster changing. They need **no refit**: the field is applied after
sampling, so each costs one more simulation pass.

Every number under a scenario is CONDITIONAL on that ballot, and the page must
say so while they are on screen - `.scenario-warning` renders from the same
code path as the numbers. A conditional probability shown as an unconditional
one is the most natural way for this page to mislead.

**Which scenarios are sound.** Removing one member of a bloc that has others is
exactly what the nesting parameter measures, so `sans_philippe` and
`centre_uni` rest on something fitted. Removing an ENTIRE bloc does not:
between blocs the model is a plain softmax over inclusive values with no
proximity, so a vanished bloc's vote is shared out in proportion to every other
bloc - IIA, the very thing the nesting fixes *within* a bloc.

A `sans_reconquete` scenario was built and then **removed** for this reason: it
put Le Pen at 54% against a 67% baseline, and that swing is an artefact, not a
finding. Zemmour's voters reaching Melenchon as readily as Le Pen is not how the
French right behaves. `gauche_unie` empties two blocs so its *magnitude* carries
the same caveat, but its *direction* does not - that comes from the runoff
transfer model, which is measured on 2022.

**The open modelling gap this exposes:** cross-bloc proximity in the first-round
model. Until it exists, prefer scenarios that reshuffle within a bloc.

## Accessibility: the charts were empty, not merely unlabelled

All three charts carried `role="img"` with **no accessible name**. That is worse
than omitting the role: `role="img"` makes the element a LEAF, so a screen
reader announces "image", with no name, and skips every label and number
inside. The charts were not badly labelled, they were unavailable.

The fix is the standard two-part one, in `charts.js`. Each SVG keeps
`role="img"` and gains a localised `<title>` via `aria-labelledby`, so it is
announced as something. The numbers then live in a real `<table class="sr-only">`
beside it - visually clipped, fully navigable with table commands, which beats
any amount of description on the graphic. `.sr-only` uses clipping, never
`display:none` or `hidden`, which would remove it from assistive technology too.

Also fixed: eight unnamed `<section>` landmarks (now `aria-labelledby` their own
h2), a hard-coded English `aria-label="Scenario"` on a French-default page, the
hero rendered as a pile of unrelated `<div>`s (now a list), duel bars that
announced "44%" "56%" without saying whose (now one labelled group with the
halves `aria-hidden`), decorative bars announced twice, a table with no caption
and no `scope`, a missing skip link, and no `role="alert"` on the error banner.

Switching scenario or language rewrites most of the page in place. That now
announces through `#a11y-live`, or a screen-reader user gets no indication
anything happened.

**Contrast was already fine** - measured 4.80 and 7.05 against their
backgrounds, both passing AA at their sizes. The problems here were all
semantic, so do not go changing colours looking for them.

**A trap when verifying any of this in a headless or background pane:** Chrome
does not paint `:focus` styles while `document.hasFocus()` is false, although
`element.matches(':focus')` still returns true. A skip link will look stuck
off-screen and appear broken when it is correct. Mirror the declaration on a
class to check it.

## The page shows the model's own record, with its caveats attached

`trackrecord.py` reads the committed backtest scores in `outputs/backtests/`
and `history.py` reads `outputs/runs/`, so the page cannot drift from what was
measured - nothing is retyped into HTML.

Two rules about presenting them, both load-bearing:

1. **The record never appears without its caveats.** Coverage measured on 2022
   is partly circular, because the parameters setting interval width were
   fitted on that cycle. Shown alone it would read as independent validation.
   `tests/test_record_history.py` asserts the `circular` flag is always true.
2. **The history plots one point per DATA DATE, not per run.** Of the first 23
   archived runs only four had distinct `as_of` dates - the rest were the same
   polling re-sampled, across eight model fingerprints. A line through every
   run would show a reader my edits and call it French opinion. The chart also
   states when the model changed during the period, because earlier points came
   from earlier arithmetic.

**Known false positive:** `model_fingerprint` hashes the bytes of `model.yaml`,
so editing only a COMMENT flags a model change. It errs safe - a spurious "the
model changed" is much better than a silent one - but do not be surprised by it.

## The 2024 legislatives are fitted, partially pooled, and they changed nothing

The 2024 legislative elections are the largest real test of anti-RN transfer
since 2022. 330 second-round duels where an RN or allied candidate faced
exactly one opponent; Ministry results, Licence Ouverte 2.0, committed to
`data/cache/` so everything here runs offline.

    overall     RN 37.3% round 1 -> 44.3% round 2   (+7.0 pts)
                2022 presidential: 23.2% -> 41.4%   (+18.3 pts)
                RN lost 74% of the duels

    by opponent      RN round 2    RN won
      left  n=147        46.6%       38%
      centre n=125       42.5%       16%
      right  n= 53       43.5%       19%

Two layers. `scripts/measure_front_republicain_2024.py` reports that
descriptively. `data/legislatives_2024.py` turns the duels into 317 transfer
observations that the runoff model is actually **fitted** on, alongside the 43
measured 2022 transfers and the 54 hypothetical 2027 matchups. The two share
their parsing and their nuance mapping, deliberately - they used to duplicate
it, which is a drift waiting to happen.

**Pooling them outright does not work. Do not "simplify" it back.** The obvious
implementation - one geometry, three datasets - was tried and measured:

| | without 2024 | pooled outright |
|---|---|---|
| fitted RN position | +1.07 | **+0.54** |
| gamma | 3.71 | 1.90 |
| MAE vs the 2027 matchups | 2.27 pts | **5.82 pts** |

An RN position of +0.54 puts the RN nearer the centre than the mainstream
right. 317 local duels simply outvote 97 presidential observations on every
shared parameter. `scripts/check_legislatives_2024.py` reproduces this on
demand as the `pooled outright` row.

So the cycles are **partially pooled**: positions, gamma, abstention and delta
each get a legislative version of itself, centred on the presidential one, with
an asserted scale in `config/model.yaml`. The shape crosses over; the level
stays in 2024.

**The finding, and it is a null one.** The four-points-versus-twenty conflict
between 2024 and the 2027 runoff polls is absorbed by the legislative terms,
and the difference has to be LARGE: the published fit has a legislative front
republicain of 1.08 against a presidential 0.09, with gamma at 0.80 of its
presidential value. A local election full of incumbents, personal votes and
desistements SHOULD both transfer against the RN harder and discriminate less
sharply by ideology. Once that is allowed, the duels stop contradicting the
presidential geometry, and across every defensible setting of the pooling
scales they move the reported runoff shares by about a point.

**Do not quote the split between gamma and delta.** They are partly
interchangeable and it is not sharply identified: exploratory fits loaded it
onto gamma (ratio 0.53, delta shift 0.26), the published fit onto delta (ratio
0.80, shift ~0.99). The TOTAL is stable; the decomposition is not.

**So the open question from the previous round is now closed, in the negative.**
It used to read: "the risk that the central estimate is RN-favourable remains
open". It was answerable, it was answered, and the answer is that the most
recent real election does not overturn this model. What was bought is not a
changed forecast but a tested one, with the legislative-versus-presidential
difference as an inspectable parameter (`diagnostics.gamma_legislatif_ratio`,
`delta_legislatif`) rather than a paragraph of hedging.

**Three things it still cannot settle**, none fixable here: 136 opponents are
NFP joint nominations whose actual party the Ministry file does not record (they
sit at the published seat-sharing split; the check script prices that
assumption); the pooling scales are asserted, because measuring them needs a
second legislative election, the same shortage that stops `bloc_error_corr`
being fitted; and a duel is an aggregate flow, so this is ecological inference.

**Excluded from the backtest**, which replays 2022. They happened two years
later. `cmd_backtest` passes `duels_2024=None` and says so - that is not an
omission to tidy up.

## The runoff fit is bimodal across seeds - open, and it fails closed

Found while checking whether the 2024 duels were safe to add; it predates them.
Four chains per seed:

| seed | duels off | duels on |
|---|---|---|
| 1 | **r-hat 1.54, ESS 7**, gamma 6.39 | r-hat 1.01, ESS 469, gamma 3.55 |
| 2 | r-hat 1.01, ESS 422, gamma 3.71 | r-hat 1.01, ESS 569, gamma 3.58 |
| 3 | **r-hat 1.54, ESS 7**, gamma 5.78 | **r-hat 1.54, ESS 7**, gamma 5.56 |
| 4 | r-hat 1.01, ESS 474, gamma 3.72 | r-hat 1.01, ESS 593, gamma 3.55 |

About half of seeds settle at gamma near 5.5-6.4 instead of 3.5. The duels
reduce the rate, they do not remove it.

**MAE does not catch it.** The seed-3 failure scored 2.16 points against the
tested matchups - the BEST in the table. So a bad fit looks completely normal
everywhere a reader can see, while P(win) moves.

Two consequences, both load-bearing:

1. `diagnostics.runoff_fit` carries `max_rhat` and `min_ess_bulk`. Before this,
   `diagnostics.max_rhat` covered only the FIRST-ROUND model - the transfer fit
   that decides the presidency was published unchecked. Do not remove them.
2. `presidentielle run` **exits 2** rather than publish an unconverged runoff
   fit, unless `--allow-unconverged`. Same principle as the roster failing
   closed: stale but correct beats fresh but quietly wrong. Re-running usually
   clears it, because it is seed-dependent.

**The cause is not known.** If you go looking, start by reading the rejected
hypothesis below so you do not repeat it.

## Measured, then rejected

Keep these unless new evidence overturns them. Each cost real time to establish
and each has a script that reproduces it.

- **Weighting institutes by accuracy** (`scripts/fit_pollster_quality.py`).
  Raw 2022 accuracy looks like it discriminates: RMS log error ranges from
  0.137 (Harris) to 0.280 (Atlasintel), a factor of two. It does not.
  **87% of the 2022 miss was common to every institute** - all of them missed
  Melenchon low and Pecresse high. Strip the per-candidate mean and the spread
  between institutes is indistinguishable from chance, permutation **p = 0.85**.
  Eleven institutes times four major candidates means a house's record is four
  numbers that are not independent draws but one correlated story about one
  campaign. The only institute that stands apart, Atlasintel, is not in the
  2027 field. Weighting on this would rank institutes by fit to 2022 and call
  it quality.

  The negative result is informative about structure: since the miss is
  per-candidate rather than per-institute, election-day error belongs at the
  candidate level, which is where the model puts it.

- **Tuning `survey_weight_exponent`** (`scripts/fit_survey_weight.py`). It
  cannot be measured directly - within-survey disagreement is confounded with
  the field genuinely changing the shares - so it was fitted against 2022
  backtest CRPS at two cutoffs across 0.00 to 1.00. The two cutoffs rank it
  **exactly oppositely**, paired per-candidate errors differ in opposite
  directions, and moving across the whole range changes the median 90% interval
  from 4.96 points to 4.95. The forecast is insensitive to it, because width is
  set by what happens after the last poll, not by how much each poll is
  trusted. 0.65 stays, as a mid-range value that is demonstrably not
  load-bearing.

  This also killed a hypothesis worth not resurrecting: that over-weighting
  poll noise made the latent state sluggish and explained the 30-day backtest
  missing Melenchon's late surge. It does not. **That miss remains
  unexplained**, and the survey weighting is not where to look.

- **The scale ridge as the cause of the bimodal runoff fit.**
  `gamma * (x_j - x_k)^2` depends only on pairwise distances, so shifting every
  position, or rescaling the positions against gamma, leaves the likelihood
  exactly unchanged. Two redundant directions, with only the position prior
  standing on them - and the failing fits looked the part, showing positions
  compressed by roughly the `sqrt(gamma_bad / gamma_good)` that predicts.

  Removing both by construction - centring the positions and fixing their
  spread, the same move invariant 6 makes for the softmax - changed the failure
  rate not at all, and on one seed made it WORSE, taking the duels-off failure
  rate from two seeds in four to three. The confirming arithmetic was a
  coincidence. Reverted rather than kept on a falsified rationale; the
  redundancy is real, but it is not the bug.

- **A fatter-tailed election-day error.** The 30-day backtest has calibrated
  50% intervals and thin 90% ones, so the tails are probably too light. Twelve
  candidates in one cycle, whose misses are one correlated story about *vote
  utile*, cannot support fitting a tail parameter. See the backtest section.

## Known rough edges
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
