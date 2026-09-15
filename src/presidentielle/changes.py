"""What moved since the last run, and whether the polls are why.

A daily forecast whose only output is a level is hard to read: a reader cannot
tell 66% from 66%-up-from-62%. The archived runs in ``outputs/runs`` have been
accumulating since the first build and nothing was reading them.

THE TRAP THIS EXISTS TO AVOID
-----------------------------
Attributing the model's own changes to the electorate. Between 2026-09-07 and
2026-09-15 there were **eight distinct model fingerprints** across nineteen
runs - every one of them a change I made to the arithmetic - and the page
reported none of them. A reader watching Le Pen go from 45% to 62% would have
been watching me refit the walk scale, not French opinion moving.

So the fingerprint is compared, not merely displayed. When it differs, the
commentary says the model was re-specified and explicitly declines to credit
the movement to polling. The sibling US project carries the same rule as an
invariant, after a recalibration was once announced as a 5.6-point move "on 1
new poll".

The second case worth naming is no new data at all: `as_of` sat unchanged
through four consecutive daily runs in September, while resampling moved the
headline by a point. That is noise, and saying so is better than letting it
read as news.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# Below this, a move is sampling jitter rather than a finding. Two runs on
# identical data differ by a point or so purely from the simulation.
MIN_MOVE = 0.02


@dataclass
class Comparison:
    # Whether there WAS a previous run, kept separate from its filename.
    # describe() used to gate on the filename, which previous_run() happens to
    # set - so any other caller would have produced a silently empty change
    # line. The presence of a comparison and the name of a file are different
    # facts and are now stored as such.
    has_previous: bool = False
    previous_file: str | None = None
    previous_as_of: str | None = None
    model_changed: bool = False
    new_surveys: int = 0
    same_data: bool = False
    moves: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "has_previous": self.has_previous,
            "previous_run": self.previous_file,
            "previous_as_of": self.previous_as_of,
            "model_changed": self.model_changed,
            "new_surveys": self.new_surveys,
            "same_data": self.same_data,
            "moves": self.moves,
        }


def previous_run(runs_dir: Path) -> dict | None:
    """The most recently archived run, if there is one."""
    if not runs_dir.exists():
        return None
    files = sorted(p for p in runs_dir.glob("*.json") if p.is_file())
    if not files:
        return None
    try:
        payload = json.loads(files[-1].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read previous run %s (%s)", files[-1], exc)
        return None
    payload["_file"] = files[-1].name
    return payload


def compare(current: dict, previous: dict | None) -> Comparison:
    if not previous:
        return Comparison()

    cmp = Comparison(
        has_previous=True,
        previous_file=previous.get("_file"),
        previous_as_of=previous.get("as_of"),
        model_changed=(
            current.get("model_fingerprint") != previous.get("model_fingerprint")
        ),
        new_surveys=max(
            0,
            (current.get("sondages", {}).get("surveys") or 0)
            - (previous.get("sondages", {}).get("surveys") or 0),
        ),
        same_data=current.get("as_of") == previous.get("as_of"),
    )

    before = {c["id"]: c for c in previous.get("candidats", [])}
    for c in current.get("candidats", []):
        old = before.get(c["id"])
        if not old:
            continue
        delta = (c.get("p_win") or 0.0) - (old.get("p_win") or 0.0)
        if abs(delta) >= MIN_MOVE:
            cmp.moves.append(
                {
                    "id": c["id"],
                    "nom": c["nom"],
                    "p_win": c.get("p_win"),
                    "delta": round(delta, 4),
                }
            )
    cmp.moves.sort(key=lambda m: -abs(m["delta"]))
    return cmp


def _pts(delta: float, lang: str) -> str:
    n = round(abs(delta) * 100)
    if lang == "fr":
        return f"{'+' if delta > 0 else '−'}{n} point" + ("s" if n > 1 else "")
    return f"{'+' if delta > 0 else '−'}{n} point" + ("s" if n > 1 else "")


def describe(cmp: Comparison, current: dict) -> dict[str, str]:
    """One sentence per language, or empty strings when there is nothing to say."""
    # Written in each language, not translated, and that includes the dates:
    # "2026-09-10" in French prose is the tell that a machine produced it.
    from .commentary import date_en, date_fr

    if not cmp.has_previous:
        return {"fr": "", "en": ""}

    fr: list[str] = []
    en: list[str] = []

    # The guard comes first, because it changes what the numbers mean.
    if cmp.model_changed:
        fr.append(
            "Le modèle lui-même a été modifié depuis la dernière mise à jour : "
            "les écarts ci-dessous ne peuvent pas être attribués aux sondages."
        )
        en.append(
            "The model itself was changed since the last update, so the movement "
            "below cannot be attributed to new polling."
        )
    elif cmp.same_data:
        when_fr = date_fr(cmp.previous_as_of) if cmp.previous_as_of else "?"
        when_en = date_en(cmp.previous_as_of) if cmp.previous_as_of else "?"
        fr.append(
            f"Aucun nouveau sondage depuis le {when_fr} : les écarts éventuels "
            "relèvent du bruit de simulation, pas de l'opinion."
        )
        en.append(
            f"No new polls since {when_en}; any movement is simulation noise "
            "rather than opinion."
        )
    elif cmp.new_surveys:
        n = cmp.new_surveys
        fr.append(
            f"{n} nouvelle{'s' if n > 1 else ''} enquête{'s' if n > 1 else ''} "
            "depuis la dernière mise à jour."
        )
        en.append(f"{n} new survey{'s' if n > 1 else ''} since the last update.")
    else:
        fr.append("Données mises à jour depuis la dernière exécution.")
        en.append("Data refreshed since the last run.")

    if cmp.moves:
        top = cmp.moves[:3]
        fr.append(
            "Mouvements : "
            + ", ".join(f"{m['nom']} {_pts(m['delta'], 'fr')}" for m in top)
            + "."
        )
        en.append(
            "Movement: "
            + ", ".join(f"{m['nom']} {_pts(m['delta'], 'en')}" for m in top)
            + "."
        )
    elif not cmp.same_data and not cmp.model_changed:
        fr.append("Aucun candidat ne bouge de plus de deux points.")
        en.append("No candidate moves by more than two points.")

    return {"fr": " ".join(fr), "en": " ".join(en)}
