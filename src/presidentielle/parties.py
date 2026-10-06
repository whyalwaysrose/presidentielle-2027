"""Each party's presidential record, joined to what it says it stands for.

WHY THIS IS A MODULE AND NOT A TABLE IN THE PAGE
-------------------------------------------------
The site shows nine blocs and sixty-odd candidates, and a reader has no way to
know that the Rassemblement national polled 16.9% in 2002, or that Horizons -
whose leader is second in this forecast - has never contested a presidential
election at all. That context is the point of this section.

It is assembled rather than written down. `config/partis.yaml` names, for each
party, the CANDIDATE who carried its line in each election; every percentage
below is computed from the Interior Ministry's own vote counts in
`config/resultats_historiques.yaml` (2002-2017) and `config/resultats_2022.yaml`
(2022). Nothing here can disagree with the Ministry, because nothing here
restates it.

FAILS CLOSED, like the roster. A party naming a candidate who is not in the
results for that year is an error - a typo, or a renamed file - and it raises
rather than quietly dropping the point. A party's record with a year silently
missing would read as "they did not stand", which is a different and false
claim.

THE THREE KINDS OF CLAIM, kept apart deliberately: results are facts, lineage
is a judgement, and `principes` is this site's own summary of what a party
publishes. `config/partis.yaml` explains why that separation matters; this
module carries the distinction through to the JSON so the page can label each
one differently.
"""

from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path

import yaml

from .paths import CONFIG

log = logging.getLogger(__name__)

PARTIES_FILE = CONFIG / "partis.yaml"
HISTORIC_FILE = CONFIG / "resultats_historiques.yaml"
RESULTS_2022_FILE = CONFIG / "resultats_2022.yaml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_results(
    historic: Path | None = None, results_2022: Path | None = None
) -> dict[int, dict]:
    """Every presidential first round this project holds, as {year: {...}}.

    2022 lives in its own file because the backtest scores against it; it is
    read here rather than copied, so the two can never drift apart.
    """
    out: dict[int, dict] = {}
    for year, rec in _load(historic or HISTORIC_FILE).items():
        out[int(year)] = {
            "date": rec["date"],
            "exprimes": rec["exprimes"],
            "inscrits": rec.get("inscrits"),
            "votants": rec.get("votants"),
            "candidats": dict(rec["candidats"]),
            "source": rec.get("source_page"),
        }
    r22 = _load(results_2022 or RESULTS_2022_FILE)["premier_tour"]
    out[2022] = {
        "date": r22["date"],
        "exprimes": r22["exprimes"],
        "inscrits": None,
        "votants": None,
        "candidats": {k: v["voix"] for k, v in r22["candidats"].items()},
        "source": (
            "https://www.data.gouv.fr/datasets/election-presidentielle-des-10-et-"
            "24-avril-2022-resultats-definitifs-du-1er-tour"
        ),
    }
    return out


STALE_AFTER_DAYS = 182


def _current_candidates(party: dict, forecast: dict | None) -> dict | None:
    """This cycle's candidates for a party, and the leading one.

    WHY NOT A PARTY TOTAL. A party's 2027 "share" is not a well-defined
    quantity: the Socialists have five people in the field and at most one will
    stand, so adding their medians would count an alternative as an addition
    and invent support nobody projects. The forward-looking point is therefore
    ONE NAMED CANDIDATE's projected first-round share, labelled with their
    name, and the others are listed beside it.

    Matching is on the roster's `parti` string, with `noms_roster` for the
    cases where the roster abbreviates (UDR).
    """
    if not forecast:
        return None
    names = {party["nom"].casefold()}
    names |= {str(n).casefold() for n in (party.get("noms_roster") or [])}

    mine = [
        c for c in forecast.get("candidats", [])
        if str(c.get("parti", "")).casefold() in names
        # Someone who has withdrawn is not a projection. The MoDem's only
        # name is François Bayrou, who stood down in March 2026; showing him
        # at 0.0% would read as a forecast that the party will be wiped out,
        # when the model is saying it expects no candidate at all.
        and (c.get("p_standing") or 0) > 0.05
    ]
    if not mine:
        return None
    # The leading candidate is the one most likely to be on the ballot, broken
    # by projected share - not the highest share, which could be someone with a
    # 3% chance of standing at all.
    mine.sort(
        key=lambda c: (c.get("p_standing") or 0, (c.get("share") or {}).get("q50") or 0),
        reverse=True,
    )
    lead = mine[0]
    share = lead.get("share") or {}
    return {
        "id": lead["id"],
        "nom": lead["nom"],
        "part": share.get("q50"),
        "bas": share.get("q05"),
        "haut": share.get("q95"),
        "p_candidature": lead.get("p_standing"),
        "autres": [c["nom"] for c in mine[1:]],
    }


def build(
    parties: Path | None = None,
    historic: Path | None = None,
    results_2022: Path | None = None,
    forecast: dict | None = None,
) -> dict:
    """The payload the page renders: parties, their records, their sources.

    ``forecast`` is the run's own payload. Given it, each party also carries
    its leading 2027 candidate and that candidate's PROJECTED first-round
    share, so a party's line runs to the present instead of stopping in 2022.
    That projection is a different kind of number from the five before it - a
    model output, not a count - and the page draws it differently.
    """
    config = _load(parties or PARTIES_FILE)
    results = load_results(historic, results_2022)
    years = sorted(results)

    out = []
    for key, party in (config.get("partis") or {}).items():
        record = []
        for year in years:
            name = (party.get("resultats") or {}).get(year)
            if name is None:
                continue
            votes = results[year]["candidats"].get(name)
            if votes is None:
                raise ValueError(
                    f"{key}: {year} names {name!r}, which is not in that year's "
                    "results. Check config/partis.yaml against "
                    "config/resultats_historiques.yaml."
                )
            record.append({
                "annee": year,
                "candidat": name,
                "voix": votes,
                "part": round(votes / results[year]["exprimes"], 5),
            })

        principles = party.get("principes") or {}
        reviewed = principles.get("revu")
        stale = None
        if reviewed:
            stale = (dt.date.today() - reviewed).days > STALE_AFTER_DAYS
        out.append({
            "candidat_2027": _current_candidates(party, forecast),
            "id": key,
            "nom": party["nom"],
            "nom_en": party.get("nom_en") or party["nom"],
            "bloc": party["bloc"],
            "site": party.get("site"),
            "fonde": party.get("fonde"),
            "lignee": party.get("lignee") or {},
            # Surfaced so the page can footnote it. A reader who sees one line
            # through 2002 and 2022 is entitled to know the party was renamed.
            "lignee_contestee": bool(party.get("lignee_contestee")),
            "resultats": record,
            "meilleur": max((r["part"] for r in record), default=None),
            "dernier": record[-1]["part"] if record else None,
            "principes": {
                "fr": principles.get("fr"),
                "en": principles.get("en"),
                # "programme" means a published manifesto; "positions" means
                # there is no 2027 manifesto yet and this is drawn from what
                # the party currently publishes.
                "source": principles.get("source"),
                "url": principles.get("url"),
                # Shown on the page: prose ages, and a reader is entitled to
                # know when a description of a party was last checked.
                "revu": reviewed.isoformat() if reviewed else None,
                "perime": stale,
            },
        })

    # Most recent score first, then parties that have never stood - which is
    # itself worth seeing rather than hiding at the bottom of an alphabet.
    out.sort(key=lambda p: (p["dernier"] is None, -(p["dernier"] or 0)))

    return {
        "avertissement": config.get("avertissement") or {},
        "elections": [
            {
                "annee": y,
                "date": results[y]["date"],
                "exprimes": results[y]["exprimes"],
                "source": results[y]["source"],
            }
            for y in years
        ],
        "partis": out,
    }
