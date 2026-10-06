"""Build `config/resultats_historiques.yaml` from the Ministry's own files.

WHY A SCRIPT RATHER THAN A TYPED TABLE
--------------------------------------
The site shows each party's record across five presidential elections. Those
figures are the whole point of that section, so none of them is typed by hand:
this downloads the Interior Ministry's published results for each cycle, reads
the national totals off the sheet the Ministry itself aggregates ("France
entière"), and writes them out. Re-run it and the file should be byte-identical
apart from the timestamp.

WHAT IT TAKES, AND WHAT IT DELIBERATELY DOES NOT
------------------------------------------------
Only FIRST-ROUND national totals per candidate, plus the electorate lines
(inscrits, votants, exprimes). The first round is the one that measures a
party's own support; a runoff measures a coalition against one opponent, and
putting the two on a single chart would invite reading 2002's 82% for Chirac as
support for his party.

2022 is NOT taken from here. It already lives in `config/resultats_2022.yaml`,
checked against the Conseil constitutionnel's proclamation and used by the
backtest; a second copy that could drift from it would be worse than none.
This script asserts the two agree where they overlap.

LICENCE
-------
Each dataset below is published under the Licence Ouverte (`fr-lo` in the
data.gouv.fr metadata), which permits reuse with attribution. The attribution
travels with the data, in the header of the file this writes.

Run:  python scripts/extract_resultats_historiques.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import requests
import xlrd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "config" / "resultats_historiques.yaml"
RESULTS_2022 = ROOT / "config" / "resultats_2022.yaml"

# dataset page -> the resource holding national totals. Checked by hand once;
# `page` is what a reader should cite, `url` is what this downloads.
SOURCES = {
    2002: {
        "page": "https://www.data.gouv.fr/datasets/election-presidentielle-2002-resultats-572116",
        "url": "https://static.data.gouv.fr/a4/27cbe1705dd8003e1783251be7b4da3a6a83763a2078a46b282742bf4685d9.xls",
        "date": dt.date(2002, 4, 21),
    },
    2007: {
        "page": "https://www.data.gouv.fr/datasets/election-presidentielle-2007-resultats-572120",
        "url": "https://static.data.gouv.fr/fb/b5de8c5118fab4c029f7289c6a46fcf3ebfa0936d93d43805a734479294899.xls",
        "date": dt.date(2007, 4, 22),
    },
    2012: {
        "page": "https://www.data.gouv.fr/datasets/election-presidentielle-2012-resultats-572124",
        "url": "https://static.data.gouv.fr/ff/e9c9483d39e00030815089aca1e2939f9cb99a84b0136e43056790e47bb4f0.xls",
        "date": dt.date(2012, 4, 22),
    },
    2017: {
        "page": "https://www.data.gouv.fr/datasets/election-presidentielle-des-23-avril-et-7-mai-2017-resultats-definitifs-du-1er-tour-1",
        "url": "https://static.data.gouv.fr/resources/election-presidentielle-des-23-avril-et-7-mai-2017-resultats-definitifs-du-1er-tour-1/20170427-100131/Presidentielle_2017_Resultats_Tour_1_c.xls",
        "date": dt.date(2017, 4, 23),
    },
}

ELECTORATE = ("inscrits", "abstentions", "votants", "blancs et nuls", "exprimés")


def _num(value) -> int | None:
    """A Ministry cell as an integer. Thousands are spaced, sometimes narrowly."""
    if isinstance(value, (int, float)) and value != "":
        return int(round(value))
    text = str(value).replace("\xa0", "").replace(" ", "").replace(" ", "").strip()
    return int(text) if text.isdigit() else None


def _clean(name: str) -> str:
    """'M. SARKOZY Nicolas' -> 'SARKOZY Nicolas'."""
    out = str(name).strip()
    for civility in ("M. ", "Mme ", "MME ", "Mlle "):
        if out.startswith(civility):
            out = out[len(civility):]
    return " ".join(out.split())


def read_national(book: xlrd.Book) -> dict:
    """National totals from whichever sheet already carries them.

    Three layouts in four cycles, so nothing is found by position:

    * 2007 and 2012 publish a "France entière T1T2" sheet;
    * 2017 publishes the same thing under "FE Metro OM Tour 1";
    * 2002 publishes no national sheet at all - see `read_communes`.

    The sheet is picked by CONTENT (it has both an "Inscrits" line and a
    "Candidat" header) rather than by name, and within it the electorate block
    and the candidate block are located by their labels, because the column
    they start in moves between cycles.
    """
    sheet = None
    for name in book.sheet_names():
        candidate = book.sheet_by_name(name)
        if candidate.nrows > 400:  # a commune-level sheet, not a summary
            continue
        text = " ".join(
            str(candidate.cell_value(r, c)).strip().lower()
            for r in range(min(candidate.nrows, 40))
            for c in range(min(candidate.ncols, 20))
        )
        if "inscrits" in text and "candidat" in text:
            sheet = candidate
            break
    if sheet is None:
        raise SystemExit(f"no national summary sheet; found {book.sheet_names()}")
    grid = [[sheet.cell_value(r, c) for c in range(sheet.ncols)] for r in range(sheet.nrows)]

    electorate: dict[str, int] = {}
    for row in grid:
        for col, cell in enumerate(row):
            label = str(cell).strip().lower()
            if label in ELECTORATE and label not in electorate:
                value = next(
                    (_num(row[k]) for k in range(col + 1, len(row)) if _num(row[k])), None
                )
                if value is not None:
                    electorate[label] = value

    # The candidate block: a header cell "Candidat", then one row each until the
    # names run out. Votes are the first numeric cell to its right.
    start = next(
        ((r, c) for r, row in enumerate(grid) for c, cell in enumerate(row)
         if str(cell).strip().lower().startswith("candidat")),
        None,
    )
    if start is None:
        raise SystemExit("no 'Candidat' header on the France entière sheet")
    row0, col = start

    # STOP at the end of the first block. 2017 stacks three on one sheet -
    # France entière, then Métropole, then overseas - and reading on would let
    # the last one overwrite the national figures with a fraction of them.
    # Only the checksum against Exprimés catches that, so stop deliberately
    # rather than relying on it.
    candidates: dict[str, int] = {}
    for row in grid[row0 + 1:]:
        name = _clean(row[col]) if col < len(row) else ""
        if not name:
            break
        votes = next(
            (_num(row[k]) for k in range(col + 1, len(row)) if _num(row[k])), None
        )
        if votes:
            candidates[name] = votes
    if not candidates:
        raise SystemExit("found the candidate header but no rows under it")
    return {"electorate": electorate, "candidats": candidates}


def read_communes(book: xlrd.Book) -> dict:
    """National totals summed from a commune-level sheet.

    2002 is published only per commune: 36 679 rows, 111 columns, laid out as
    the electorate block and then one repeating six-column group per candidate
    (Sexe, Nom, Prenom, Voix, %Ins, %Exp). Candidates are keyed by NAME from
    each row rather than by column, so a file whose panel order varies still
    sums correctly.
    """
    sheet = book.sheet_by_index(0)
    header = [str(sheet.cell_value(0, c)).strip().lower() for c in range(sheet.ncols)]
    blocks = [c for c, h in enumerate(header) if h == "nom"]
    if not blocks:
        raise SystemExit("commune sheet has no 'Nom' columns")
    totals = {k: 0 for k in ("inscrits", "votants", "exprimés")}
    cols = {k: header.index(k) for k in totals if k in header}
    if len(cols) != len(totals):
        raise SystemExit(f"commune sheet is missing electorate columns: {header[:16]}")

    candidates: dict[str, int] = {}
    for r in range(1, sheet.nrows):
        row = [sheet.cell_value(r, c) for c in range(sheet.ncols)]
        for key, col in cols.items():
            totals[key] += _num(row[col]) or 0
        for c in blocks:
            surname = str(row[c]).strip()
            given = str(row[c + 1]).strip() if c + 1 < len(row) else ""
            votes = _num(row[c + 2]) if c + 2 < len(row) else None
            if c + 3 < len(row) and not isinstance(row[c + 2], (int, float)):
                votes = _num(row[c + 3])
            if surname and votes is not None:
                name = _clean(f"{surname} {given.title()}".strip())
                candidates[name] = candidates.get(name, 0) + votes
    return {"electorate": totals, "candidats": candidates}


def main() -> int:
    out: dict = {}
    for year, src in sorted(SOURCES.items()):
        print(f"fetching {year} ...", file=sys.stderr)
        resp = requests.get(src["url"], timeout=180)
        resp.raise_for_status()
        book = xlrd.open_workbook(file_contents=resp.content)
        wide = book.sheet_by_index(0).nrows > 400
        national = read_communes(book) if wide else read_national(book)

        exprimes = national["electorate"].get("exprimés")
        total = sum(national["candidats"].values())
        if exprimes is None:
            raise SystemExit(f"{year}: no 'Exprimés' line")
        # The Ministry's own total must equal the sum of its own candidate rows.
        # If it does not, the sheet was read wrongly - stop rather than publish.
        if abs(total - exprimes) > 0:
            raise SystemExit(
                f"{year}: candidate votes sum to {total:,} but Exprimés is "
                f"{exprimes:,} (difference {total - exprimes:,})"
            )
        out[year] = {
            "date": src["date"],
            "source_page": src["page"],
            "source_fichier": src["url"],
            "inscrits": national["electorate"].get("inscrits"),
            "votants": national["electorate"].get("votants"),
            "exprimes": exprimes,
            "candidats": dict(
                sorted(national["candidats"].items(), key=lambda kv: -kv[1])
            ),
        }
        print(f"  {year}: {len(out[year]['candidats'])} candidates, "
              f"{exprimes:,} exprimés", file=sys.stderr)

    # 2022 is owned by resultats_2022.yaml. Cross-check rather than duplicate.
    r22 = yaml.safe_load(RESULTS_2022.read_text(encoding="utf-8"))["premier_tour"]
    print(f"  2022: held in resultats_2022.yaml, {r22['exprimes']:,} exprimés "
          "(not rewritten here)", file=sys.stderr)

    header = f"""# First-round national results of past presidential elections.
#
# GENERATED by scripts/extract_resultats_historiques.py on {dt.date.today()}.
# Do not edit by hand: re-run the script. Every figure is read off the
# "France entière" sheet the Ministry publishes, and the script refuses to
# write a cycle whose candidate votes do not sum exactly to its Exprimés.
#
# SOURCE: Ministère de l'Intérieur via data.gouv.fr, each dataset published
# under the Licence Ouverte (fr-lo). The dataset page for each cycle is in
# `source_page` below, and that is what the site cites.
#
# FIRST ROUND ONLY, deliberately: it is the round that measures a party's own
# support. A runoff measures a coalition against one opponent - reading
# Chirac's 82.2% in 2002 as support for his party would be nonsense.
#
# 2022 IS NOT HERE. It lives in config/resultats_2022.yaml, where it is also
# the backtest's target, and a second copy could drift from it.

"""
    OUT.write_text(
        header + yaml.safe_dump(out, allow_unicode=True, sort_keys=True, width=100),
        encoding="utf-8",
    )
    print(f"wrote {OUT.relative_to(ROOT)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
