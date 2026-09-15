# Methodology

## 0. What is being forecast

The French presidential election of **18 April 2027** (first round) and
**2 May 2027** (runoff). The output is a distribution over: who stands, what
each candidate scores in the first round, which pair reaches the runoff, and
who wins it.

## 1. Why this is not the same problem as a US forecast

Three differences drive every design decision here.

**The field is unknown.** Candidacies do not close until 12 March 2027. In
September 2026 the RN's nominee is unresolved, the left has not settled on one
candidate or several, and the centre may field one, two or three. A model that
conditions on a fixed field is answering a question nobody asked.

**One poll is many polls.** A French presidential survey prices several
*hypotheses* — different candidate fields — off one sample. Recent surveys
average 5.6 first-round hypotheses each and go up to 13.

**Two rounds.** The first round decides who competes, not who wins. A candidate
can lead it by ten points and lose the presidency, which is exactly what the
current polling implies for the RN.

## 2. The first-round model

### 2.1 Latent strength

Each candidate *c* has a strength `u_c(t)` on a log scale, evolving as a
non-centred Gaussian random walk on a weekly grid that ends **on election day**.
Because the fitted walk already reaches the election, there is no separate
drift-to-election-day term; adding one would double-count.

Strength is a bloc-level walk plus a candidate deviation, so candidates in the
same bloc move together. The state is then **centred across candidates at each
step**: the softmax is shift-invariant, so that one degree of freedom is
removed rather than left for the sampler to wander along.

Two ridges had to be closed before this would sample at all, and both are
recorded as invariants:

* No per-bloc starting level. It is exactly absorbed by the starting levels of
  that bloc's own members — nine redundant dimensions.
* Bloc-level walks only for blocs with more than one *polled* candidate. With
  one member, the bloc innovation and the candidate innovation are exchangeable
  at every one of ~145 steps.

With both present the sampler did not finish. With both removed, 50 warmup + 50
draws across 2 chains takes under two minutes.

### 2.1.1 The walk's scale is measured

The innovation SD is the single most consequential number on the site, because
the walk runs about 32 free weekly steps from the last poll to election day and
nothing constrains it over that stretch. It is fitted, not chosen.

`scripts/fit_walk_scale.py` takes the 2022 cycle from the nsppolls archive and
measures how far a candidate's log share moved between consecutive polls **by
the same institute**, with sampling noise subtracted:

    sigma^2 = mean[ (log p2 - log p1)^2 - var_1 - var_2 ] / delta_t

giving **0.0142 per day**, 90% CI [0.0025, 0.0206] over 787 pairs. Split in
quadrature between the bloc and candidate walks, that is the committed config,
and `tests/test_calibration.py` asserts the split still reconciles.

Two restrictions are load-bearing rather than cosmetic. Pairs are compared
within an institute, because a gap between two houses contains their house
effect and not movement. And **rolling polls are excluded**: much of the 2022
file is daily waves re-interviewing an overlapping panel, so consecutive
readings move *less* than two independent samples would — including them made
the measured excess variance negative, which is not a small bias but no answer
at all.

The scales are then **pinned** to that measurement rather than sampled, and the
reason is worth stating because the first attempt at this misdiagnosed it.

The first full run gave Le Pen 32.4% with a 90% interval of [14.6%, 57.0%].
Tightening the *prior* to the measured value changed almost nothing — 32.2%
[14.5%, 56.3%] — because a weak prior does not bind against 1,695
observations. Inspecting the posterior showed what was actually happening:

| | |
|---|---|
| walk scale measured from real polls | 0.0142/day |
| walk scale the model fitted | **0.0337/day** (2.4×) |
| `sigma_excess`, non-sampling poll error | **0.0011** (≈ zero) |

A 146-node weekly grid backed by 39 surveys is far more flexible than a single
observation-noise term, so the model explained poll-to-poll *scatter* by moving
the latent state, and concluded that French polls have essentially no
non-sampling error. That inflated volatility then compounded over ~32
unconstrained steps to election day and set every interval on the site.

Pinning is the honest resolution rather than a fudge: these are not parameters
about which nothing is known — `fit_walk_scale.py` measures exactly this
quantity, from real French polls, net of sampling noise. With the scales held
there, `sigma_excess` rose to 0.0034 and Le Pen's interval became
**35.0% [24.3%, 47.9%]**, against published polling of 33–38%.
`pin_walk_scales: false` reproduces the pathology.

### 2.2 Nested logit, and why not a softmax

The obvious likelihood is a softmax over whoever is on the ballot. It assumes
**independence of irrelevant alternatives**: remove Le Pen and her support is
shared out in proportion to everyone else's, so Mélenchon gains at the same
rate per point of support as Bardella does.

The data contradict this directly. Le Pen appears in 86 first-round hypotheses,
Bardella in 79, and they co-occur in **zero**. Comparing those fields, the RN
total moves modestly while other candidates barely move at all.

So candidates sit in blocs, each with a nesting parameter `λ_k ∈ (0, 1]`:

```
within bloc      log P(c | k) = u_c/λ_k − LSE_k
inclusive value  IV_k         = λ_k · LSE_k
between blocs    log P(k)     = IV_k − LSE_blocs

log p_c = u_c/λ_k − LSE_k + IV_k − LSE_blocs
```

* `λ = 1` reproduces the plain softmax **exactly** (asserted to 1e-12 in the
  suite), so IIA is nested inside the model rather than assumed away.
* `λ → 0` makes substitution inside the bloc total: removing Le Pen sends her
  support to Bardella and leaves other blocs untouched — while the RN's own
  total still moves, because Bardella is a different candidate. Both halves of
  that are tested.

`λ_k` is estimated. It is only identified for a bloc polled both with and
without a given member; a bloc with one polled candidate is pinned to 1 rather
than left to sample its prior.

### 2.3 Observation model

Shares are observed with binomial sampling noise from the **effective** sample
size plus a fitted non-sampling term. House effects are per institute × bloc,
constrained sum-to-zero across institutes.

Per bloc rather than per candidate: eight institutes × 26 candidates is 208
parameters against 165 hypotheses, and the systematic differences between
French institutes are about how they treat the RN vote and the abstention
screen — a bloc-level story.

### 2.4 One survey is one sample

Each hypothesis keeps its own likelihood term with effective sample
`n · m^(−exponent)`, where `m` is how many hypotheses that survey priced for
that round.

Counting them as independent would multiply one sample of 1,500 people
thirteenfold. Keeping only one would throw away the contrast between a field
with Le Pen and the same field with Bardella — which is precisely what
identifies the nesting. On the current file this takes the first-round sample
from 311,461 raw to 117,529 effective.

## 3. Who is on the ballot

Two kinds of uncertainty, both read off institutes' testing behaviour rather
than asserted.

**Arbitrations** are candidates within a bloc who have never been tested
together — Le Pen and Bardella, Zemmour and Knafo. Exactly one is drawn, or
none.

**Independent candidacies** are everyone else. Philippe and Attal co-occur 17
times, so each stands or does not on its own.

Probabilities come from decayed testing frequency. The decay is a **measurement,
not a preference**: Le Pen was ruled ineligible on 2025-03-31 and institutes
switched to Bardella (tested in 50–100% of monthly fields through June 2026);
her ban was cut on 2026-07-07 and since July she is in 100% of fields and he is
in none. A flat 120-day window spans the break and reports 67/33. A 45-day
half-life reports 78/20.

This is a **proxy and not a measurement of intent**. An institute testing a
candidate is saying the scenario is considered live, not that its probability
equals the testing frequency.

### Where a fact exists, the fact wins

`candidats.csv` records declarations and withdrawals, and those override the
proxy. It matters most in the single most consequential place on this ballot:
**Bardella withdrew on 2026-07-07**, the day Le Pen's ineligibility was cut to
15 months. On testing frequency alone the model gave him a 20% chance of
standing and about 14% of the presidency, after he had stood down.

A community-maintained field is trusted here because a second and completely
independent signal agrees with it: institutes stopped testing Bardella from that
same month. The test suite asserts the agreement and fails if it breaks.

Withdrawal is decisive. Declaring is only a floor — a declared candidate still
needs 500 validated *parrainages*, and Darmanin declared on 2026-08-17 and
withdrew eight days later. Precedence runs: testing frequency, then recorded
facts, then the manual `field.overrides` pin.

### Institutes are not weighted by accuracy

The sibling US model scales each poll's noise by its pollster's published
record. Doing the same here was measured and rejected: **87% of the 2022 miss
was common to every institute**, and once the shared miss is removed the
spread between them is indistinguishable from chance (permutation p = 0.85, on
eleven institutes and four major candidates). `scripts/fit_pollster_quality.py`
reproduces it.

## 4. The runoff

For a pair of finalists, voters of each eliminated candidate choose between
them or abstain, by proximity on a latent left-right axis:

```
u(bloc j → finalist in bloc k) = −γ·(x_j − x_k)² − δ·[k is RN]
u(bloc j → abstention)         = w_j
```

The distance is **squared**. That is the canonical quadratic-loss utility of
spatial voting theory, and it is also the difference between a model that
samples and one that does not: `|x_j − x_k|` has a kink wherever a voter bloc
sits exactly on a finalist, its gradient is undefined there, and NUTS grinds
against it — measured, four chains over twenty parameters and fifty-four
observations had not finished after twenty minutes. Squared, the same fit takes
seconds. `tests/test_runoff.py` finite-differences across the kink point so an
`abs()` cannot come back unnoticed.

`δ` is the **front républicain**: extra reluctance to transfer to an RN
finalist beyond ideological distance. Twenty parameters against 54 observations,
which is why it is a proximity model rather than a free 9×9 transfer matrix
(81 parameters).

Priors on the positions come from the known ordering of French blocs and are
anchored so the axis cannot reflect. The 2022 measured transfers
(nsppolls `reports.csv`) are the empirical reference point.

### Anchored on what actually happened in 2022

Fitting `δ` on 2026 polls about a 2027 runoff alone would be inferring the
*front républicain* from stated intentions about a hypothetical. The model is
therefore fitted on both cycles at once, adding **43 measured transfers** from
`nsppolls/reports.csv` — institutes asking 2022 voters, during the real
campaign between the two real finalists, where their first-round vote was
going. Each institute contributes its final wave per candidate.

The measurements are unambiguous: Zemmour's voters split 82% to Le Pen,
Jadot's 63% to Macron, Mélenchon's 41% Macron / 20% Le Pen / 39% abstention.

The effect on the forecast is not cosmetic. Anchoring moved Philippe against
Le Pen from **44% to 53%** — into line with the runoff polls, which the
unanchored model had been systematically under-reading.

Bloc positions and each bloc's readiness to abstain are shared across cycles,
as properties of French politics. Position priors were tightened from 0.25 to
0.12 because loose positions and `δ` are confounded: moving the RN further
right acts exactly like an RN-specific penalty.

### The 2027 question is not a fitted parameter

Whether left and centre voters will still cross the aisle in May 2027 is the
model's largest substantive vulnerability, and it is genuinely unknowable
today.

It was first written as a fitted per-cycle `δ` with a drift between them. That
failed, informatively: `delta_2022` came out at 0.064, essentially zero,
because the quadratic distance term already accounts for 2022's transfers
without needing an RN-specific penalty. A drift multiplying zero carries no
uncertainty at all.

More fundamentally, a *fitted* 2027 term gets fitted away — the 54 runoff
hypotheses would pin it to whatever 2026 respondents currently say and report
that as knowledge about 2027. So `front_republicain_2027_sd` is applied **per
simulated world**, after fitting, exactly as election-day error is.

Its size is chosen against the evidence that exists, which now disagrees with
itself — and that disagreement is the point.

**2024 legislatives.** The largest real test of anti-RN transfer since 2022:
330 second-round duels of an RN or allied candidate against exactly one
opponent (`scripts/measure_front_republicain_2024.py`, Ministry results under
Licence Ouverte 2.0). The RN went from 37.3% in round one to 44.3% in round
two — a gain of 7.0 points, against the 18.3 Le Pen gained in the 2022
presidential runoff — and lost 74% of those duels. The *front républicain* was
not merely alive in 2024; it was stronger than in 2022.

It also depends on who the alternative is, which is what this model's proximity
structure claims. From near-identical first-round positions the RN converted
46.6% against a left opponent and 42.5% against a centre one, winning 38% of
duels against the left and 16% against the centre.

The magnitude is where the sources part company. That measured left penalty is
about four points. The 2027 hypothetical polls imply nearer twenty — Le Pen
around 68% against Mélenchon and under 50% against Philippe. A legislative duel
is not a presidential runoff (local candidates, incumbency, and *désistements*
that concentrate the anti-RN vote by a mechanism a two-candidate runoff lacks),
and the 2024 "left" is the NFP coalition rather than one polarising figure — so
the two are not directly comparable. But three credible readings spanning four
to twenty points is exactly what a prior on this term has to contain.

Also relevant: the RN's runoff share moved from 34.1% in 2017 to 41.45% in
2022, +7.3 points.
`scripts/check_runoff_sensitivity.py` translates the parameter into the same
unit. At **0.70**, one sigma is roughly six points of runoff share: the
2017→2022 swing sits near 1.2 sigma and the sixteen-point disagreement between
2024 and the 2027 polls near 2.6 — uncommon, not implausible.

It was **widened symmetrically rather than shifted**, deliberately. The 2024
evidence leans towards this model being RN-favourable, since the real *front
républicain* outperformed 2022 and the left penalty looked smaller than the
hypotheticals imply. That is enough to widen the uncertainty. It is not enough
to move the central estimate on the strength of a different kind of election.

### Checking it against the polls it was fitted to

A transfer model that failed to reproduce the tested matchups would be
asserting something the runoff polls directly contradict, and it would do so
invisibly, because only P(win) would move. `diagnostics.runoff_fit` therefore
reports the model's error against all 54 tested second-round hypotheses:
**2.03 points MAE, −0.47 points bias**.

That is the number to check before believing any P(win) figure on the site.

### Two-stage fit

The runoff model is fitted after the first-round model, on its posterior-mean
shares. A joint fit would be cleaner in principle, but the runoff polls carry
almost no information about first-round shares — they name two candidates and
ask a different question — so the feedback a joint model would capture is
negligible against a markedly harder sampling problem.

## 5. Simulation

Each simulated world takes one posterior draw, draws a ballot, applies
**election-day error**, computes first-round shares, takes the top two, and
runs the runoff — with its own draw of the 2027 transfer term.

The election-day error is fitted, not assumed: `presidentielle calibrate`
scores each institute's final 2022 poll against the proclaimed result, giving a
log-error SD of 0.201 for candidates at or above 5%, or 0.0376 on the share
scale at p = 0.25. The previous value, 0.0220, was invented.

Error is applied on the strength scale, before the softmax, and correlated
within blocs (an institute that under-reads the RN under-reads every RN
candidate). Doing it there rather than on the shares keeps every share positive
and every field summing to one, and makes a candidate on 4% carry a smaller
absolute error than one on 34% — which is what historical misses look like.

First-round intervals on the site are **conditional on the candidate standing**.
An unconditional interval would fold in every world where they are not on the
ballot and report a 5th percentile of zero for half the field.

## 5b. Named ballots, and the limit of them

The headline marginalises over who stands. A scenario fixes the ballot instead
and re-runs only the simulation — no refitting, because the field is applied
after sampling. Every probability inside one is **conditional on that ballot**,
which the page states while the scenario is active.

They are also a good test of where the nesting does and does not reach.
Removing one member of a populated bloc is precisely what λ measures. Removing
a whole bloc is not: between blocs the model is a plain softmax over inclusive
values, with **no cross-bloc proximity**, so a vanished bloc's vote is
redistributed proportionally to every other bloc — IIA at the bloc level, the
thing the nesting removes *within* a bloc.

That is a real limitation, and it was found by building a scenario that
depended on it. A "without Reconquête" scenario put Le Pen 13 points below the
baseline, because Zemmour's vote spread as readily to Mélenchon as to Le Pen.
It was removed rather than shipped. Closing the gap means giving the
between-bloc choice a proximity structure of the kind the runoff model already
has.

## 6. Backtest

`presidentielle backtest --as-of DATE` reruns the entire pipeline on the 2022
cycle from only what existed on that date, and scores it on the Ministry's
proclaimed result. It is the only end-to-end check that the nested logit, the
ballot simulation and the runoff work *together*.

Nothing from after the cutoff is used: polls are filtered by fieldwork end
date, and the 2022 measured transfers are excluded because they were published
during the April campaign. The 2022 roster is separate, since a candidate's
bloc can differ between cycles.

### What it found, and what changed because of it

Two cutoffs, both scored on the proclaimed result. "before" is the walk scale
fitted on 7-60 day gaps; "after" is the horizon-matched refit in §2.1.1.

| | 221 days out | | 30 days out | |
|---|---|---|---|---|
| | before | after | before | after |
| median absolute error | 2.85 pts | 2.82 pts | 2.80 pts | 2.71 pts |
| **90% interval coverage** | 67% | **83%** | 67% | **75%** |
| **50% interval coverage** | 25% | **42%** | 50% | 50% |
| model's own top two | correct | correct | correct | correct |
| P(Macron reaches runoff) | 89% | 82% | 100% | 99% |
| P(Le Pen reaches runoff) | 87% | 80% | 75% | 75% |
| P(Macron elected) | 69% | 60% | 93% | 92% |

The structure was never the problem: at both horizons the model put the right
pair in the runoff and the right man in the Elysee, with a median error under
three points. The **uncertainty** was the problem, and the horizon-matched
refit is what fixed most of it — coverage improved at both cutoffs while the
point predictions barely moved, which is what a correction to an uncertainty
parameter should look like rather than a fudge to the central estimate.

Scores are archived in `outputs/backtests/`.

### What is still wrong, and why it is not being tuned away

Coverage is still short of nominal, and the 30-day case shows where. There the
50% intervals are exactly right while the 90% intervals cover 75%: the middle
of the distribution is calibrated and the **tails are too thin**. That is not
about the walk, which contributes almost nothing over a month.

It is the final month of 2022 being genuinely extraordinary — Melenchon gained
about ten points, Pecresse lost six, Zemmour five, as the left consolidated
behind the one candidate who could reach the runoff and the right fragmented.
A Gaussian election-day error cannot cover a ten-point miss.

The obvious response is a fatter-tailed error, and it is deliberately **not**
being made. There are twelve candidates in one cycle here; four of them missing
their 90% interval is the entire evidence base, and the misses are not
independent draws but one correlated story about *vote utile*. Fitting a tail
parameter to that would be fitting the model to the 2022 campaign rather than to
French elections. The honest position is that the tails are probably too thin,
that one cycle cannot say by how much, and that the forecast's own page should
not claim more precision than that supports.

### What it cannot tell you

Both parameters that set interval width — the walk scale and the election-day
error — are themselves fitted on the 2022 cycle, so coverage measured on 2022
is partly circular. There is one cycle of French polling available and no way
around this. What is *not* circular, and is what the backtest genuinely
validates: the point predictions, the ballot simulation on a field that was
still unsettled (Zemmour had not declared in September 2021), and which pair
the model puts into the runoff.

## 7. What is not done

* **`bloc_error_corr` is not fitted and cannot be** from 2022: the field
  offers only two same-bloc pairs above the 2% noise floor. Kept at 0.30, down
  from an asserted 0.55, and second-order in any case because arbitrations mean
  the RN and Reconquête field one candidate at a time.
* **`survey_weight_exponent` is asserted.** Fitting it needs the same institute
  pricing the same field twice on independent samples, which the data do not
  contain.
* **No backtest** against 2022 or 2017 yet.
* **No sub-national estimates**, deliberately. There is no département-level
  presidential polling. A map produced by uniform swing from 2022 would carry
  far more apparent authority than its inputs support.
* **Turnout is not modelled separately.** Shares are of expressed votes, as the
  notices report them.
