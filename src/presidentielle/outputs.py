"""The JSON the site reads.

SCHEMA_VERSION is checked by the page. Bump it here and in `site/js/app.js`
together whenever the shape changes, so a stale cached page says so instead of
rendering blanks.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path

import numpy as np

from .config import ModelConfig, Roster
from .model.simulate import SimulationResult, matchup_table

log = logging.getLogger(__name__)

SCHEMA_VERSION = 2

QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
QUANTILE_KEYS = ("q05", "q25", "q50", "q75", "q95")


def model_fingerprint(cfg_path: Path, module_paths: list[Path]) -> str:
    """Hash of the config and the modules that define the arithmetic.

    A model change must not be reported as a polling change. When this differs
    between runs the commentary says the model was re-specified instead of
    blaming new polls for the movement.
    """
    h = hashlib.sha256()
    for p in [cfg_path, *sorted(module_paths)]:
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _clean(x) -> float | None:
    if x is None:
        return None
    f = float(x)
    return None if np.isnan(f) else round(f, 5)


def build_forecast(
    *,
    result: SimulationResult,
    roster: Roster,
    cfg: ModelConfig,
    ballot,
    trend: dict,
    poll_summary: dict,
    recent_polls: list[dict],
    diagnostics: dict,
    fingerprint: str,
    as_of: dt.date,
    scenario: str = "modele",
) -> dict:
    p_stand = result.p_standing()
    p_qual = result.p_qualify()
    p_win = result.p_win()
    quantiles = result.share_quantiles(QUANTILES)

    candidates = []
    for i, cid in enumerate(result.candidate_ids):
        c = roster.candidats[cid]
        q = quantiles[cid]
        candidates.append(
            {
                "id": cid,
                "nom": c.nom,
                "parti": c.parti,
                "bloc": c.bloc,
                "p_standing": _clean(p_stand[i]),
                "p_qualify": _clean(p_qual[i]),
                "p_win": _clean(p_win[i]),
                "share": {k: _clean(v) for k, v in zip(QUANTILE_KEYS, q, strict=True)},
            }
        )
    candidates.sort(key=lambda c: -(c["p_win"] or 0))

    matchups = []
    for row in matchup_table(result):
        matchups.append(
            {
                "a": row["a"],
                "b": row["b"],
                "nom_a": roster.candidats[row["a"]].nom,
                "nom_b": roster.candidats[row["b"]].nom,
                "p_matchup": _clean(row["p_matchup"]),
                "p_a_wins": _clean(row["p_a_wins"]),
            }
        )

    # Days remaining count from today, not from the last poll: a reader asks
    # how long is left, not how stale the data is. Staleness is `as_of`.
    days = (cfg.election.premier_tour - dt.date.today()).days

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "as_of": as_of.isoformat(),
        "scenario": scenario,
        "model_fingerprint": fingerprint,
        "election": {
            "premier_tour": cfg.election.premier_tour.isoformat(),
            "second_tour": cfg.election.second_tour.isoformat(),
            "cloture_candidatures": cfg.election.cloture_candidatures.isoformat(),
            "jours_restants": days,
            "field_is_known": cfg.election.field_is_known(as_of),
        },
        "blocs": {
            k: {"nom_fr": b.nom_fr, "nom_en": b.nom_en, "couleur": b.couleur}
            for k, b in roster.blocs.items()
        },
        "candidats": candidates,
        "duels": matchups,
        "ballot": ballot.as_dict(),
        "tendance": trend,
        "sondages": poll_summary,
        "derniers_sondages": recent_polls,
        "diagnostics": diagnostics,
        "n_simulations": result.n_sims,
    }


def write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    log.info("wrote %s (%.1f KB)", path, path.stat().st_size / 1024)
