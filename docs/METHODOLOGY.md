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
equals the testing frequency. The site says so where the numbers appear, and
`field.overrides` exists for hard facts (a withdrawal, a validated candidacy).

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

**This is the model's largest vulnerability, and it is a substantive one, not a
technical one.** `δ` is estimated from polls taken in 2026 about a runoff in
2027, and the willingness of left and centre voters to block the RN is exactly
the quantity least likely to be stable over that period. If the front
républicain is weaker in 2027 than the runoff polling implies, this model is
wrong in a specific and predictable direction.

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
runs the runoff.

Error is applied on the strength scale, before the softmax, and correlated
within blocs (an institute that under-reads the RN under-reads every RN
candidate). Doing it there rather than on the shares keeps every share positive
and every field summing to one, and makes a candidate on 4% carry a smaller
absolute error than one on 34% — which is what historical misses look like.

First-round intervals on the site are **conditional on the candidate standing**.
An unconditional interval would fold in every world where they are not on the
ballot and report a 5th percentile of zero for half the field.

## 6. What is not done

* **The error scales are not yet fitted.** `election_day_error.fitted` is
  `false`. Fitting them against the nsppolls 2022 archive, scored on the real
  result at 0–14 days out, is the next substantial piece of work. Until then
  the intervals reflect the model's own uncertainty but are not calibrated
  against how French polls have historically missed.
* **No backtest** against 2022 or 2017 yet.
* **No sub-national estimates**, deliberately. There is no département-level
  presidential polling. A map produced by uniform swing from 2022 would carry
  far more apparent authority than its inputs support.
* **Turnout is not modelled separately.** Shares are of expressed votes, as the
  notices report them.
