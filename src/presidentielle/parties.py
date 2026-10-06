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


def build(
    parties: Path | None = None,
    historic: Path | None = None,
    results_2022: Path | None = None,
) -> dict:
    """The payload the page renders: parties, their records, their sources."""
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
        out.append({
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
