"""Named ballots, simulated from the same posterior as the headline forecast.

The default view marginalises over who stands. That is the right headline and
the wrong answer to the question people actually ask, which is "what if
Philippe does not run". A scenario fixes the ballot and re-runs only the
simulation - no refitting, because the field is applied after sampling - so the
reader can see the conditional answer instead of an average that hides it.

EVERY NUMBER IN A SCENARIO IS CONDITIONAL on its ballot. That is the one thing
this module cannot enforce and the page must not forget.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from .paths import CONFIG

log = logging.getLogger(__name__)

SCENARIOS_CONFIG = CONFIG / "scenarios_2027.yaml"


@dataclass(frozen=True)
class Scenario:
    id: str
    nom_fr: str
    nom_en: str
    note_fr: str
    note_en: str
    remove: tuple[str, ...] = ()
    add: tuple[str, ...] = ()

    def field_from(
        self, reference: np.ndarray, candidate_ids: list[str]
    ) -> np.ndarray:
        index = {c: i for i, c in enumerate(candidate_ids)}
        row = reference.copy()
        for cid in self.remove:
            if cid in index:
                row[index[cid]] = False
        for cid in self.add:
            if cid in index:
                row[index[cid]] = True
        return row


def load(path: Path | None = None) -> list[Scenario]:
    with (path or SCENARIOS_CONFIG).open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out = []
    for s in raw.get("scenarios") or []:
        out.append(
            Scenario(
                id=s["id"],
                nom_fr=s["nom_fr"],
                nom_en=s["nom_en"],
                note_fr=(s.get("note_fr") or "").strip(),
                note_en=(s.get("note_en") or "").strip(),
                remove=tuple(s.get("remove") or ()),
                add=tuple(s.get("add") or ()),
            )
        )
    return out


def validate(scenarios: list[Scenario], roster) -> None:
    """Fail closed on an id the roster does not know.

    A scenario naming a candidate who does not exist would otherwise be a
    silent no-op: the page would offer "Without Édouard Philippe" and quietly
    show the reference ballot with him still on it.
    """
    known = set(roster.candidats)
    for s in scenarios:
        unknown = [c for c in (*s.remove, *s.add) if c not in known]
        if unknown:
            raise ValueError(
                f"scenario {s.id!r} names unknown candidate(s) "
                f"{', '.join(unknown)} - check config/scenarios_2027.yaml"
            )


def summarise(result, roster, candidate_ids: list[str]) -> dict:
    """The same shape the main forecast uses, for one fixed ballot."""
    from .model.simulate import matchup_table
    from .outputs import QUANTILE_KEYS, QUANTILES, _clean

    p_stand = result.p_standing()
    p_qual = result.p_qualify()
    p_win = result.p_win()
    quantiles = result.share_quantiles(QUANTILES)

    candidats = []
    for i, cid in enumerate(candidate_ids):
        if p_stand[i] <= 0:
            continue  # not on this ballot at all
        c = roster.candidats[cid]
        q = quantiles[cid]
        candidats.append(
            {
                "id": cid,
                "nom": c.nom,
                "parti": c.parti,
                "bloc": c.bloc,
                "p_standing": 1.0,
                "p_qualify": _clean(p_qual[i]),
                "p_win": _clean(p_win[i]),
                "share": {k: _clean(v) for k, v in zip(QUANTILE_KEYS, q, strict=True)},
            }
        )
    candidats.sort(key=lambda c: -(c["p_win"] or 0))

    duels = [
        {
            "a": row["a"],
            "b": row["b"],
            "nom_a": roster.candidats[row["a"]].nom,
            "nom_b": roster.candidats[row["b"]].nom,
            "p_matchup": _clean(row["p_matchup"]),
            "p_a_wins": _clean(row["p_a_wins"]),
        }
        for row in matchup_table(result)
    ]
    return {"candidats": candidats, "duels": duels}


def run_all(
    scenarios: list[Scenario],
    *,
    reference: np.ndarray,
    candidate_ids: list[str],
    roster,
    simulate_fn,
    n_sims: int,
    seed: int,
) -> list[dict]:
    """Simulate each named ballot against the posterior already fitted."""
    out = []
    for offset, s in enumerate(scenarios, start=1):
        field = s.field_from(reference, candidate_ids)
        if field.sum() < 2:
            log.warning("scenario %s leaves fewer than two candidates; skipped", s.id)
            continue
        fields = np.repeat(field[None, :], n_sims, axis=0)
        # A distinct seed per scenario, derived not random, so a rerun on the
        # same data reproduces the same page.
        result = simulate_fn(fields, np.random.default_rng(seed + offset))
        summary = summarise(result, roster, candidate_ids)
        summary.update(
            {
                "id": s.id,
                "nom_fr": s.nom_fr,
                "nom_en": s.nom_en,
                "note_fr": s.note_fr,
                "note_en": s.note_en,
                "sur_le_bulletin": [
                    c for c, on in zip(candidate_ids, field, strict=True) if on
                ],
            }
        )
        out.append(summary)
        top = summary["candidats"][0] if summary["candidats"] else None
        log.info(
            "scenario %-18s %d candidates, leader %s %s",
            s.id,
            int(field.sum()),
            top["nom"] if top else "-",
            f"{top['p_win']:.0%}" if top else "",
        )
    return out
