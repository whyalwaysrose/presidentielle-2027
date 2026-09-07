"""Who is actually on the ballot.

This is the question a French presidential forecast cannot avoid and a US one
never has to ask. In September 2026 nobody knows whether the RN will run Le Pen
or Bardella, whether the Socialists and the Greens will run separately, or
whether Philippe and Attal will both stand. Candidacies do not close until
2027-03-12, when the Conseil constitutionnel publishes the validated
parrainages.

WHERE THE PROBABILITIES COME FROM
---------------------------------
Not from judgement. From what institutes choose to test.

An institute pricing a field is spending real money on it, for a client who
wants to know about a scenario they consider live. Which candidates get tested,
and how that changes, is therefore evidence about who is expected to run. It is
a **proxy, not a measurement**, and the site says so - but it is reproducible,
it updates itself, and it does not encode the author's opinion about French
politics.

Recent evidence dominates, with exponential decay. The reason is in
``config/model.yaml``: institutes respond to news within weeks, and averaging
across a regime change gets the answer badly wrong.

TWO KINDS OF UNCERTAINTY
------------------------
*Arbitrations* are sets of candidates within a bloc who have **never** been
tested in the same field. Le Pen and Bardella co-occur exactly zero times in
165 first-round hypotheses: institutes treat them as alternatives because the
RN will nominate one of them. Exactly one option is drawn, or none.

*Independent candidacies* are everyone else. Philippe and Attal appear together
17 times, so they are not alternatives - each stands or does not, on its own.

FACTS BEAT THE PROXY
--------------------
Where a candidate has actually declared or actually withdrawn, that is not a
scenario institutes find interesting - it is a fact, and it overrides the
frequency estimate. See :mod:`presidentielle.data.candidacies`. Withdrawal is
decisive; declaring only sets a floor, because a declared candidate still needs
500 parrainages and can still change their mind.
"""

from __future__ import annotations

import datetime as dt
import itertools
import logging
from dataclasses import dataclass
from dataclasses import field as dc_field

import numpy as np

from ..config import ModelConfig, Roster
from ..data.polls import Hypothese

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Arbitration:
    """A set of mutually exclusive candidates within one bloc."""

    bloc: str
    options: list[str]
    probabilities: list[float]  # aligned with options; may sum to < 1
    p_none: float

    def as_dict(self) -> dict:
        return {
            "bloc": self.bloc,
            "options": self.options,
            "probabilities": [round(p, 4) for p in self.probabilities],
            "p_none": round(self.p_none, 4),
        }


@dataclass(frozen=True)
class BallotModel:
    candidates: list[str]
    arbitrations: list[Arbitration]
    independent: dict[str, float] = dc_field(default_factory=dict)
    weights_used: float = 0.0

    def as_dict(self) -> dict:
        return {
            "arbitrations": [a.as_dict() for a in self.arbitrations],
            "independent": {k: round(v, 4) for k, v in sorted(self.independent.items())},
            "effective_hypotheses": round(self.weights_used, 1),
        }


def _decay_weights(hyps: list[Hypothese], as_of: dt.date, half_life: float) -> np.ndarray:
    age = np.array([(as_of - h.fin).days for h in hyps], dtype=float)
    age = np.clip(age, 0.0, None)
    return 0.5 ** (age / half_life)


def _cooccurs(hyps: list[Hypothese], a: str, b: str) -> int:
    return sum(1 for h in hyps if a in h.shares and b in h.shares)


def build_ballot_model(
    hypotheses: list[Hypothese],
    *,
    cfg: ModelConfig,
    roster: Roster,
    as_of: dt.date,
    facts: dict[str, float] | None = None,
) -> BallotModel:
    """Derive arbitrations and independent candidacies from testing behaviour."""
    first = [h for h in hypotheses if h.tour == 1]
    if not first:
        raise ValueError("no first-round hypotheses")

    candidates = sorted({c for h in first for c in h.shares})
    w = _decay_weights(first, as_of, cfg.field_.half_life_days)
    total_w = float(w.sum())

    # Weighted frequency with which each candidate is tested.
    freq = {
        c: float(sum(wi for h, wi in zip(first, w, strict=True) if c in h.shares))
        for c in candidates
    }

    # Exclusivity is judged over the WHOLE history, not the decayed window. Two
    # candidates being untested together lately may only mean one of them is
    # currently out of favour; never having been tested together across two
    # years is what makes them alternatives.
    arbitrations: list[Arbitration] = []
    claimed: set[str] = set()

    for bloc in roster.bloc_keys:
        members = [c for c in candidates if roster.candidats[c].bloc == bloc]
        if len(members) < 2:
            continue
        # Group members into cliques of mutual exclusivity.
        exclusive_pairs = {
            (a, b)
            for a, b in itertools.combinations(members, 2)
            if _cooccurs(first, a, b) == 0
        }
        if not exclusive_pairs:
            continue
        group = sorted({c for pair in exclusive_pairs for c in pair})
        # Only keep it as one arbitration if every member excludes every other;
        # a partial pattern is not a nomination contest and is left to the
        # independent path, where each candidacy stands on its own.
        if not all(
            (a, b) in exclusive_pairs
            for a, b in itertools.combinations(group, 2)
        ):
            log.info("bloc %s: partial exclusivity %s - treating as independent", bloc, group)
            continue

        k = cfg.field_.shrinkage_pseudocounts
        counts = np.array([freq[c] + k for c in group], dtype=float)
        # A field where the bloc fields nobody at all. Its weight is however
        # much of the recent evidence tested none of them.
        none_w = float(
            sum(
                wi
                for h, wi in zip(first, w, strict=True)
                if not any(c in h.shares for c in group)
            )
        )
        counts = np.append(counts, none_w + k)
        probs = counts / counts.sum()
        arbitrations.append(
            Arbitration(
                bloc=bloc,
                options=group,
                probabilities=[float(p) for p in probs[:-1]],
                p_none=float(probs[-1]),
            )
        )
        claimed.update(group)

    independent = {}
    for c in candidates:
        if c in claimed:
            continue
        p = freq[c] / total_w if total_w else 0.0
        independent[c] = float(np.clip(p, 0.0, 1.0))

    # Order of precedence, weakest first:
    #   1. testing frequency        (a proxy for who is expected to stand)
    #   2. declared / withdrawn     (facts, from candidats.csv)
    #   3. config field.overrides   (a deliberate human pin, so it wins)
    #
    # A withdrawal SETS the probability to zero. A declaration only raises it to
    # a floor, and never lowers it: the frequency estimate may already be higher
    # for someone institutes test constantly, and a declaration is not stronger
    # evidence than that.
    adjustments: dict[str, tuple[str, float]] = {}
    for cid, value in (facts or {}).items():
        adjustments[cid] = ("set" if value <= 0.0 else "floor", float(value))
    for cid, value in (cfg.field_.overrides or {}).items():
        adjustments[cid] = ("set", float(value))

    for cid, (mode, value) in adjustments.items():
        if cid in independent:
            current = independent[cid]
            independent[cid] = value if mode == "set" else max(current, value)
            log.info(
                "ballot %s: %s %s -> %.3f (was %.3f)",
                cid, mode, value, independent[cid], current,
            )
            continue
        for i, arb in enumerate(arbitrations):
            if cid not in arb.options:
                continue
            probs = list(arb.probabilities)
            j = arb.options.index(cid)
            target = value if mode == "set" else max(probs[j], value)
            if target == probs[j]:
                break
            probs[j] = target
            # Renormalise the rest of the arbitration around the pinned value
            # so the options still form a distribution.
            rest = 1.0 - target
            others = sum(p for m, p in enumerate(probs) if m != j) + arb.p_none
            scale = (rest / others) if others > 0 else 0.0
            probs = [p if m == j else p * scale for m, p in enumerate(probs)]
            arbitrations[i] = Arbitration(
                bloc=arb.bloc,
                options=arb.options,
                probabilities=probs,
                p_none=arb.p_none * scale,
            )
            log.info("ballot %s: %s %.3f within the %s arbitration", cid, mode, target, arb.bloc)
            break

    for arb in arbitrations:
        log.info(
            "arbitration %s: %s",
            arb.bloc,
            ", ".join(
                f"{c} {p:.0%}" for c, p in zip(arb.options, arb.probabilities, strict=True)
            )
            + f", none {arb.p_none:.0%}",
        )

    return BallotModel(
        candidates=candidates,
        arbitrations=arbitrations,
        independent=independent,
        weights_used=total_w,
    )


def draw_fields(
    ballot: BallotModel,
    candidate_ids: list[str],
    n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """Draw ``n`` ballots. Returns an (n, C) boolean presence matrix."""
    index = {c: i for i, c in enumerate(candidate_ids)}
    out = np.zeros((n, len(candidate_ids)), dtype=bool)

    for cid, p in ballot.independent.items():
        out[:, index[cid]] = rng.random(n) < p

    for arb in ballot.arbitrations:
        probs = np.array([*arb.probabilities, arb.p_none], dtype=float)
        probs = probs / probs.sum()
        picks = rng.choice(len(probs), size=n, p=probs)
        for j, cid in enumerate(arb.options):
            out[picks == j, index[cid]] = True

    return out


def fixed_field(candidate_ids: list[str], present: list[str], n: int) -> np.ndarray:
    """A ballot fixed by a scenario, repeated ``n`` times."""
    index = {c: i for i, c in enumerate(candidate_ids)}
    row = np.zeros(len(candidate_ids), dtype=bool)
    for c in present:
        if c not in index:
            raise ValueError(f"scenario names {c!r}, which is not a modelled candidate")
        row[index[c]] = True
    return np.repeat(row[None, :], n, axis=0)
