"""Bilingual commentary, written at build time.

Both languages are generated here, from the same numbers, and shipped in the
JSON. The page toggles between two texts that were each written for their own
language; it never translates in the browser. Machine-translating a sentence
about probability into French produces confident-sounding nonsense
("chances de gagner" for a posterior probability, tenses that imply the
election already happened), and the French text is the default the site opens
in, so it cannot be the derived one.

Formatting is part of writing in a language, not a detail on top of it. French
takes a non-breaking space before `%` and writes dates as "2 septembre 2026";
English does neither. Emitting ISO dates and bare percentages into French
prose is the tell that a text was generated rather than written.
"""

from __future__ import annotations

import datetime as dt

from .config import Roster

# U+00A0. French typography puts a non-breaking space before the percent sign,
# and it must not be an ordinary space or the number can wrap away from it.
NBSP = " "

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]
MONTHS_EN = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]


def date_fr(iso: str) -> str:
    d = dt.date.fromisoformat(str(iso)[:10])
    # "1er" rather than "1" for the first of the month.
    day = "1er" if d.day == 1 else str(d.day)
    return f"{day} {MOIS_FR[d.month - 1]} {d.year}"


def date_en(iso: str) -> str:
    d = dt.date.fromisoformat(str(iso)[:10])
    return f"{d.day} {MONTHS_EN[d.month - 1]} {d.year}"


def _pct_en(x: float | None) -> str:
    if x is None:
        return "-"
    if x >= 0.995:
        return ">99%"
    if x <= 0.005:
        return "<1%"
    return f"{round(x * 100)}%"


def _pct_fr(x: float | None) -> str:
    if x is None:
        return "-"
    if x >= 0.995:
        return f"> 99{NBSP}%"
    if x <= 0.005:
        return f"< 1{NBSP}%"
    return f"{round(x * 100)}{NBSP}%"


def _leaders(payload: dict, key: str, n: int) -> list[dict]:
    return sorted(payload["candidats"], key=lambda c: -(c[key] or 0))[:n]


def write_commentary(payload: dict, roster: Roster) -> dict[str, str]:
    days = payload["election"]["jours_restants"]
    n_surveys = payload["sondages"]["surveys"]
    n_hyp = payload["sondages"]["hypotheses_tour1"]
    as_of = payload["as_of"]
    cloture = payload["election"]["cloture_candidatures"]

    by_win = _leaders(payload, "p_win", 3)
    by_qual = _leaders(payload, "p_qualify", 3)
    top = by_win[0]
    duels = payload["duels"][:1]

    # ---------------- French ----------------
    fr = [
        f"À {days} jours du premier tour, le modèle s'appuie sur {n_surveys} enquêtes "
        f"({n_hyp} hypothèses de premier tour) publiées jusqu'au {date_fr(as_of)}.",
        f"{top['nom']} est le candidat le plus susceptible d'être élu "
        f"({_pct_fr(top['p_win'])}), devant {by_win[1]['nom']} ({_pct_fr(by_win[1]['p_win'])}) "
        f"et {by_win[2]['nom']} ({_pct_fr(by_win[2]['p_win'])}).",
        "Se qualifier pour le second tour est une question distincte de le remporter : "
        + ", ".join(f"{c['nom']} {_pct_fr(c['p_qualify'])}" for c in by_qual)
        + ".",
    ]
    if duels:
        d = duels[0]
        vainqueur = d["nom_a"] if d["p_a_wins"] >= 0.5 else d["nom_b"]
        fr.append(
            f"Le duel le plus probable oppose {d['nom_a']} à {d['nom_b']} "
            f"({_pct_fr(d['p_matchup'])} des simulations) ; {vainqueur} l'emporte dans "
            f"{_pct_fr(max(d['p_a_wins'], 1 - d['p_a_wins']))} de ces cas."
        )
    if not payload["election"]["field_is_known"]:
        fr.append(
            "La composition du bulletin n'est pas encore fixée : les candidatures ne sont "
            f"closes que le {date_fr(cloture)}. Le modèle simule qui se présente au lieu "
            "de le supposer, et la probabilité d'être élu intègre donc celle de figurer "
            "sur le bulletin."
        )

    # ---------------- English ----------------
    en = [
        f"With {days} days to the first round, the model uses {n_surveys} surveys "
        f"({n_hyp} first-round hypotheses) published up to {date_en(as_of)}.",
        f"{top['nom']} is the most likely winner ({_pct_en(top['p_win'])}), ahead of "
        f"{by_win[1]['nom']} ({_pct_en(by_win[1]['p_win'])}) and "
        f"{by_win[2]['nom']} ({_pct_en(by_win[2]['p_win'])}).",
        "Reaching the runoff is a separate question from winning it: "
        + ", ".join(f"{c['nom']} {_pct_en(c['p_qualify'])}" for c in by_qual)
        + ".",
    ]
    if duels:
        d = duels[0]
        winner = d["nom_a"] if d["p_a_wins"] >= 0.5 else d["nom_b"]
        en.append(
            f"The most likely runoff is {d['nom_a']} against {d['nom_b']} "
            f"({_pct_en(d['p_matchup'])} of simulations), won by {winner} in "
            f"{_pct_en(max(d['p_a_wins'], 1 - d['p_a_wins']))} of those."
        )
    if not payload["election"]["field_is_known"]:
        en.append(
            "The ballot is not yet settled - candidacies do not close until "
            f"{date_en(cloture)}. The model simulates who stands rather than assuming "
            "it, so a candidate's probability of winning includes the probability of "
            "being on the ballot at all."
        )

    return {"fr": " ".join(fr), "en": " ".join(en)}
