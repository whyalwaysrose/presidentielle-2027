# Présidentielle 2027 — a Bayesian forecast

A hierarchical Bayesian forecast of the French presidential election of
**18 April / 2 May 2027**, built from the polls filed with the Commission des
sondages. Static site, no backend, no build step.

*Le site est en français par défaut, avec un basculement FR/EN.*

---

## The problem this model exists to solve

A French presidential poll does not test one race. It tests several
**hypotheses** — different candidate fields — priced off a single sample.
Recent surveys average 5.6 first-round hypotheses each, and go up to 13.

That is not a nuisance to be cleaned away. It is the central fact, because
**the field itself is unknown**. Candidacies do not close until 12 March 2027.
In the current file:

```
Marine Le Pen    86 hypotheses  ┐
Jordan Bardella  79 hypotheses  ┘  co-occurring in exactly 0
```

They are alternatives, not rivals. A model that picks one hypothesis throws
away half the data. A model that pools them naively has the RN running two
candidates at once.

### What this does instead

Candidates sit in **blocs**, and the model is a **nested logit** in which each
bloc has a substitution parameter `λ_k`:

* at `λ = 1` it reproduces a plain softmax **exactly** — so the usual
  independence-of-irrelevant-alternatives model is nested inside this one
  rather than assumed away;
* as `λ → 0`, losing Le Pen sends her support to Bardella instead of sharing it
  out across Mélenchon and everyone else — while the RN's total still moves,
  because Bardella is a different candidate.

`λ` is **estimated from the data**, not asserted, and both behaviours are
asserted in the test suite.

The **ballot is then simulated**, not assumed. Who stands is drawn from
institutes' own testing behaviour, so a candidate's probability of becoming
president includes the probability of being on the ballot at all.

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -e ".[dev]"

presidentielle fetch     # refresh the cached poll file
presidentielle audit     # what the data holds, and what the roster rejected
presidentielle run       # fit, simulate, write site/data/forecast.json
```

`run` takes 30–45 minutes. For a smoke test, `presidentielle run --draws 60`
(it warns that the result is not publishable). To condition on a fixed field
instead of simulating one:

```bash
presidentielle run --scenario MLP,EP,JLM,BR,RG,MT,EZ,NDA
```

Serve the site with any static file server; `site/` is the deploy root.

---

## Data

| Layer | Source | Licence |
|---|---|---|
| Live 2027 polls | [MieuxVoter/presidentielle2027](https://github.com/MieuxVoter/presidentielle2027) | MIT |
| Primary authority | [Commission des sondages](http://www.commission-des-sondages.fr/) notice per poll | public |
| Historical calibration | [nsppolls](https://github.com/nsppolls/nsppolls) 2020–22 archive | MIT |
| 2022 measured transfers | nsppolls `reports.csv` | MIT |
| Results | [data.gouv.fr](https://www.data.gouv.fr/) / Ministère de l'Intérieur | Licence Ouverte 2.0 |

Every poll record carries the filename of its Commission des sondages notice,
and the site surfaces it, so any figure traces back to the regulator's own
document rather than to a newspaper summary.

**nsppolls is an archive, not a feed** — its presidential file stops at
2022-04-22 and its last commit is May 2022. It is still the right source for
calibration and for the 2022 transfer measurements, but a 2027 forecast built
on it would be a forecast of the wrong election.

Full provenance, including what is *mine* rather than official, is in
[`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md).

---

## Method in one page

Full detail in [`docs/METHODOLOGY.md`](docs/METHODOLOGY.md).

1. **Latent strength** per candidate: a non-centred random walk on a weekly
   grid that ends *on election day*, so no separate drift term is needed. Bloc
   walk plus candidate deviation; centred across candidates each step, because
   the softmax is shift-invariant. Its scale is **measured and pinned**, not
   sampled — 0.0142/day, fitted against the 2022 cycle by
   `scripts/fit_walk_scale.py`. Left free it reaches 0.0337/day and drives
   `sigma_excess` to zero, because a 146-node grid backed by 39 surveys will
   absorb observation noise into the latent state given the chance.
2. **Nested logit** likelihood over whichever field each hypothesis priced.
3. **House effects** per institute × bloc, sum-to-zero across institutes.
4. **One survey is one sample**: each hypothesis's effective sample is scaled
   by `m^(−0.65)`. On the current file that is 311,461 raw → 117,529 effective.
5. **Ballot simulation** from decayed testing frequency.
6. **Runoff** by quadratic-proximity transfers with an estimated *front
   républicain* term, checked against the 54 tested matchups it was fitted to
   (2.03 points MAE, −0.47 bias).
7. **Election-day error**, correlated within blocs, applied on the strength
   scale before the softmax.

---

## Known data-quality and modelling items

* **The election-day error scales are not yet fitted** (the random-walk scale
  is; these are different quantities).
  `election_day_error.fitted` is `false`; the values are priors. Fitting them
  against the 2022 archive is the next substantial piece of work. Until then
  the intervals are honest about the model's own uncertainty but not
  calibrated against how French polls have actually missed.
* **No backtest** against 2022 or 2017 yet.
* **The `front républicain` term is the largest vulnerability**, and it is
  substantive rather than technical. It is estimated from 2026 polls about a
  2027 runoff, and voters' willingness to block the RN is exactly the quantity
  least likely to be stable over that gap.
* **Ballot probabilities are a proxy.** An institute testing a candidate says
  the scenario is considered live, not that its probability equals the testing
  frequency.
* **No sub-national estimates**, deliberately. There is no département-level
  presidential polling, and a map from uniform 2022 swing would carry far more
  apparent authority than its inputs support.
* **De Villepin's bloc is the weakest roster call** — he polls as an
  anti-system figure drawing from both centre and left.

---

## What this is not

Not a prediction, and not a poll. It is what published polling implies under
the assumptions above, with the uncertainty attached. Seven months out, that
uncertainty is large — and the page says so in both languages.

A personal project, unaffiliated with any polling institute, party or news
organisation.

MIT licensed.
