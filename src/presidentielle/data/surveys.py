"""One survey is one sample, however many hypotheses it prices.

An institute that publishes 13 first-round hypotheses has not run 13 surveys.
It asked one sample of ~1500 people about 13 candidate fields, usually back to
back in the same questionnaire. Counting them as 13 independent observations
would multiply that sample thirteenfold and make the model far too confident.

Counting them as one observation is wrong in the other direction: the
hypotheses genuinely differ, and it is precisely the *contrast* between a
field containing Le Pen and the same field containing Bardella that identifies
the nesting parameters. Discarding all but one would throw that away.

So each hypothesis keeps its own likelihood term, with its effective sample
size scaled down by ``m ** -exponent`` where ``m`` is the number of hypotheses
that survey priced for that round:

    exponent = 1.0   the sample is divided evenly - fully redundant
    exponent = 0.0   every hypothesis is a fresh survey - fully independent

The truth is in between and the exponent is fitted, not assumed. See
``presidentielle calibrate``.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from .polls import Hypothese

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeightedHypothese:
    """A hypothesis with the effective sample size the model should use."""

    hypothese: Hypothese
    n_effective: float
    n_siblings: int

    def __getattr__(self, item):  # pragma: no cover - passthrough convenience
        return getattr(self.hypothese, item)


def _dedupe(group: list[Hypothese]) -> list[Hypothese]:
    """Drop exact repeats of the same field within one survey.

    Some notices restate a field under two hypothesis labels (a rolling wave
    republished, or the same field priced with and without a sub-sample note).
    Identical fields *and* identical shares carry no extra information.
    """
    seen: dict[tuple, Hypothese] = {}
    for h in group:
        key = (h.field, tuple(sorted(h.shares.items())))
        seen.setdefault(key, h)
    return list(seen.values())


def weight(
    hypotheses: list[Hypothese],
    *,
    exponent: float,
) -> list[WeightedHypothese]:
    """Apply the shared-sample correction, per survey and per round.

    Rounds are counted separately: a survey pricing 8 first-round fields and 3
    runoffs asked its sample two different questions, and the runoff readings
    are not diluted by the number of first-round fields.
    """
    if not 0.0 <= exponent <= 1.0:
        raise ValueError(f"survey_weight_exponent must be in [0, 1], got {exponent}")

    groups: dict[tuple, list[Hypothese]] = defaultdict(list)
    for h in hypotheses:
        groups[(*h.survey_key, h.tour)].append(h)

    out: list[WeightedHypothese] = []
    for key, group in groups.items():
        kept = _dedupe(group)
        if len(kept) < len(group):
            log.debug("survey %s: dropped %d duplicate fields", key, len(group) - len(kept))
        m = len(kept)
        factor = m ** (-exponent)
        for h in kept:
            out.append(
                WeightedHypothese(
                    hypothese=h,
                    n_effective=h.echantillon * factor,
                    n_siblings=m,
                )
            )

    out.sort(key=lambda w: (w.hypothese.fin, w.hypothese.institut, w.hypothese.hypothese))
    return out


def summarise(weighted: list[WeightedHypothese]) -> dict:
    """Counts for the run log and the site's methodology panel."""
    surveys = {w.hypothese.survey_key for w in weighted}
    r1 = [w for w in weighted if w.hypothese.tour == 1]
    r2 = [w for w in weighted if w.hypothese.tour == 2]
    return {
        "hypotheses": len(weighted),
        "surveys": len(surveys),
        "hypotheses_tour1": len(r1),
        "hypotheses_tour2": len(r2),
        "instituts": sorted({w.hypothese.institut for w in weighted}),
        "raw_sample_tour1": sum(w.hypothese.echantillon for w in r1),
        "effective_sample_tour1": round(sum(w.n_effective for w in r1)),
        "date_min": min((w.hypothese.fin for w in weighted), default=None),
        "date_max": max((w.hypothese.fin for w in weighted), default=None),
    }
