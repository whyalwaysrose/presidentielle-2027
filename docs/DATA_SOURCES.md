# Data sources and provenance

Every number on the site is in one of three categories. They are kept separate
here deliberately, because the difference between "this is what the regulator
published" and "this is my assumption" is the difference between a forecast a
reader can check and one they have to trust.

| | What it is | Where it comes from |
|---|---|---|
| **Official** | Published by a French public body or by the pollster itself | Commission des sondages, Ministère de l'Intérieur |
| **Compiled** | Official figures transcribed by a third party under an open licence | MieuxVoter, nsppolls |
| **Mine** | Assumptions, groupings and modelling choices | This repository |

---

## 1. Polls — official, via a compiled source

**`MieuxVoter/presidentielle2027`** — <https://github.com/MieuxVoter/presidentielle2027>
MIT licence. Auto-updating; a GitHub Action in that repo commits a new build
whenever a poll is added. As of 2026-09-07 it carried 219 hypothesis records
across 39 surveys, from 2024-07-08 onward, from eight institutes.

The underlying authority is the **Commission des sondages**
(<http://www.commission-des-sondages.fr/>), the statutory regulator. Any poll
published in France about an election must be filed with it together with a
*notice* stating the method, the sample, the dates and the full results. Each
record in the compiled file carries the filename of its notice, and the site
surfaces it, so any individual figure can be traced back to the regulator's own
document rather than to a newspaper's summary of it.

The same repository's **`candidats.csv`** records declared candidacies and
withdrawals. These are treated as facts that override the testing-frequency
proxy — see `src/presidentielle/data/candidacies.py`. It is community
maintained, so it is trusted only because the polling record independently
corroborates its most consequential entry: Bardella's withdrawal on 2026-07-07
coincides exactly with institutes ceasing to test him.

This project is affiliated with neither, and says so on the page.

**Why not nsppolls.** <https://github.com/nsppolls/nsppolls> was the
well-known open compilation of French polling and is still the one most people
cite. Its presidential file **stops at 2022-04-22** and its last commit is
2022-05-23. It is an archive of the 2022 cycle, not a live feed, and using it
for 2027 would produce a forecast of the wrong election. It remains valuable
for calibration (below).

### 1b. Checking the feed against the Commission itself

The feed is only as complete as its own ingestion, and that is known to leak:
MieuxVoter/presidentielle2027#182 (open) documents its new-poll detector filing
at most ten polls per run and silently skipping the rest — six were lost that
way on 2026-09-12. So every `presidentielle fetch` compares the feed with the
Commission's full notice list, via
[MieuxVoter/sondages-commission-index](https://github.com/MieuxVoter/sondages-commission-index),
which mirrors both the list and the PDFs (`src/presidentielle/data/commission.py`).

The Commission files popularity barometers and opinion questions under the
same "Pres" category as voting intentions, and filenames do not tell them
apart — only 14 of the 46 notices in the feed say so in their name. So each
notice the feed lacks is **read**: downloaded once, its text extracted, and
classified by whether it asks a vote question. Verdicts are cached in
`data/cache/commission_scan.json`.

**Calibrated on 2026-09-21** against the 135 presidential notices since the
feed begins. Of the 44 in the feed — all genuine voting intentions — the
classifier recognises 42. One is a scanned image with no text; one (a Cluster17
barometer) carries its question in a form the extractor cannot read, so **a
missing Cluster17 poll could pass unnoticed**. The classifier's false
positives were institutes' own disclaimers ("*ne constitue nullement une
intention de vote*"), now filtered.

What it found on that first run:

| notice | verdict |
|---|---|
| Toluna Harris Interactive / Regards, 24–25 Apr 2025 | **missing** — first-round voting intentions |
| OpinionWay / Fondapol, 1–8 Jun 2026 | **missing** — second-round head-to-heads |
| Verian / L'Hémicycle, Dec 2025 | in the feed, as the earlier notice for the same fieldwork |
| Odoxa / Mascaret, Mar 2026 | in the feed, under a non-Commission filename |
| four others | not voting intentions (desired runoffs, potential vote, a legislative question, expectations of the next president) |

Human verdicts live in `config/notices_commission.yaml`, each with a note on
what was read. A gap is **reported, never repaired**: the check does not add
polls to the model, because a notice's numbers transcribed by hand are
unreviewed input. It shows in `audit`, in `diagnostics.couverture_commission`
in the published JSON, and on the GitHub run — as a warning for an unreviewed
gap older than seven days, as a notice for known gaps and unreadable PDFs. It
never fails the run: a missing poll is upstream's to fix.

## 2. Historical polls, for calibration — official, via a compiled source

**nsppolls** again: 409 polls covering the 2020–2022 period, with the same
notice-level provenance. This is what the election-day error scales are fitted
against — polls taken 0–14 days out, scored on the actual result.

**`nsppolls/reports.csv`** additionally carries *measured second-round vote
transfers* for 2022: for each first-round candidate, the share of their voters
going to Macron, to Le Pen, or to abstention. 609 rows across nine institutes,
reduced to **43 observations** by taking each institute's final wave per
candidate. This is the empirical anchor for the runoff transfer model — a real
measurement of where votes went during the actual campaign, rather than an
inference from hypothetical matchups.

## 3. Results — official

**data.gouv.fr**, Ministère de l'Intérieur: the *résultats définitifs*
proclaimed by the Conseil constitutionnel, aggregated from the department-level
files to national totals in `config/resultats_2022.yaml`. The aggregation is
checked — summed candidate votes equal summed *exprimés* exactly in both rounds.

These are what `presidentielle calibrate` scores the 2022 polls against.

Only the derived totals are committed, not the Ministry's files: the
data.gouv.fr metadata for those datasets states `license: notspecified`, and
twelve vote counts are facts about a public election rather than a substantial
extraction of a database.

The 2017 second-round figures are also used, once, to size a prior — see
`second_tour.front_republicain_2027_sd`. That publication is the Ministry's
election-night file and is explicitly **provisional**, which is why it is used
only for an order of magnitude and not as a calibration target.

## 3b. 2024 legislative results — official

**data.gouv.fr**, Ministère de l'Intérieur, **Licence Ouverte 2.0** — explicitly
open, so the two circonscription-level files are committed to `data/cache/`
and the analysis is reproducible offline.

The 330 second-round duels where an RN or allied candidate faced exactly one
opponent are the largest real-world test of anti-RN transfer since 2022, and
they postdate the cycle everything else in the model is calibrated on.

- `scripts/measure_front_republicain_2024.py` reports them descriptively.
- `src/presidentielle/data/legislatives_2024.py` turns them into 317 transfer
  observations the runoff model is fitted on, **partially pooled** with the
  presidential cycles. See §4 of `METHODOLOGY.md`.

Two limitations of the source matter, and are handled rather than ignored.
136 of the opponents carry the nuance `UG` — the Nouveau Front populaire joint
nomination — and **the file does not record which party each one came from**;
they are placed at the NFP's published seat-sharing split, and the sensitivity
to that is traced by `scripts/check_legislatives_2024.py`. The "divers" and
regionalist nuances have no position on a left-right axis, so their votes leave
the transfer pool; that is 0.8% of the first-round vote, reported by the loader
rather than assumed away, and duels where it exceeds 5% are dropped.

## 4. Election dates — official

First round **18 April 2027**, second round **2 May 2027**, both fixed by the
*décret de convocation des électeurs* under Article 7 of the Constitution.
Candidacies close **12 March 2027**, when the Conseil constitutionnel publishes
the validated *parrainages*. Held in `config/model.yaml`.

---

## 5. What is mine, and where it could be wrong

These are modelling choices, not data. They are listed so a reader can disagree
with a specific one rather than with the whole thing.

**The bloc assignments** (`config/candidats_2027.yaml`). Which candidates are
treated as close substitutes. Grounded where evidence exists — Roussel is placed
with LFI rather than the PS because his 2022 measured transfers look more like
Mélenchon's — but several are judgement. The weakest is **de Villepin**, who
polls as an anti-system figure drawing from both the centre and the left and is
placed in the centre nest.

**The nesting structure itself.** That substitution runs mainly *within* these
groups is an assumption. How strong it is inside each group is estimated from
the data, not assumed.

**Ballot probabilities.** Derived from how often institutes test each
candidate, with exponential decay, *except* where a declaration or withdrawal
is recorded — those are facts and take precedence. The frequency part remains a
**proxy**: an institute testing a candidate says the scenario is considered
live, not that its probability equals the testing frequency. The site states
this where the numbers appear.

**The declared-candidacy floor** (0.85) is mine. Withdrawal is treated as
decisive, which is close to a fact; the floor for a declaration is a judgement
about how much a declaration is worth given that *parrainages* still have to be
collected.

**The `front républicain` in 2027.** Now sized against three disagreeing
sources rather than one: 2022 presidential transfers, the 2024 legislative
duels, and 2026 polls about a 2027 runoff. They imply left-penalties ranging
from about four points to about twenty, and the prior is set wide enough to
contain that spread. The transfer structure is now fitted on
the 2022 *measurements* as well as the 2027 hypotheticals, so it is no longer
an inference from stated intentions about a runoff two years away. What remains
irreducibly mine is `front_republicain_2027_sd`: how far 2027 may differ. It is
sized against the only cycle transition anyone has observed (the RN's runoff
share moved 7.3 points between 2017 and 2022) and applied per simulated world,
so the 2027 polls cannot fit it away. It is still the model's largest
substantive vulnerability.

**The two-stage fit.** The runoff transfer model is fitted after the
first-round model rather than jointly. See `src/presidentielle/model/runoff.py`.

**Not modelled at all.** Sub-national results (there is no département-level
polling to support them); turnout as a distinct quantity; the *parrainages*
constraint as a mechanism rather than as part of the observed testing
behaviour; and the overseas electorate, which the metropolitan-only sample
universes exclude.
