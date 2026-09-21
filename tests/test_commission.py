"""Tests for the feed-versus-Commission des sondages check.

The check exists because a real voting-intention poll (OpinionWay for Fondapol,
June 2026) never reached the feed and nothing noticed. Its failure mode is the
same as the thing it guards against: silence. So these assert that each kind
of gap is REPORTED, and that the reading of notices is neither fooled by the
disclaimers institutes print nor slow enough to be dropped from the daily run.
"""

from __future__ import annotations

import datetime as dt
import time
import zlib

import pytest
import yaml

from presidentielle.data import commission as C

TODAY = dt.date(2026, 9, 21)

# ------------------------------------------------------------------ PDF text


def _pdf(*streams: tuple[bytes, bytes]) -> bytes:
    """A minimal PDF: (dictionary, uncompressed body) pairs, Flate-encoded."""
    parts = [b"%PDF-1.7\n"]
    for i, (header, body) in enumerate(streams, start=1):
        data = zlib.compress(body)
        parts.append(
            b"%d 0 obj\n<< /Filter /FlateDecode /Length %d %s >>\nstream\n"
            % (i, len(data), header)
            + data
            + b"\nendstream\nendobj\n"
        )
    return b"".join(parts)


def test_text_comes_out_of_tj_operators():
    pdf = _pdf((b"", b"BT [(Intentions ) -20 (de vote)] TJ ET BT (au 1er tour) Tj ET"))
    assert C.pdf_text(pdf) == "Intentions de vote au 1er tour"


def test_images_and_fonts_are_skipped():
    """Decompressing and scanning embedded images was most of the cost, and
    their bytes can accidentally look like text operators."""
    junk = b"[(intentions de vote)] TJ"
    pdf = _pdf((b"/Subtype /Image", junk), (b"/Length1 99", junk), (b"", b"(ok) Tj"))
    assert C.pdf_text(pdf) == "ok"


def test_a_hostile_stream_is_fast():
    """REGRESSION. The first extractor used `\\[(.*?)\\]\\s*TJ` with DOTALL,
    which backtracks quadratically on a stream full of '[' with no ']' - some
    real notices took minutes each, which would have made the daily check
    unaffordable. The patterns are bounded now."""
    pdf = _pdf((b"", b"[" * 200_000 + b"(" * 200_000 + b"Tj TJ"))
    t0 = time.perf_counter()
    C.pdf_text(pdf)
    assert time.perf_counter() - t0 < 2.0


# ---------------------------------------------------------------- classifier

PADDING = " Notice technique, echantillon de 1 000 personnes. " * 10


@pytest.mark.parametrize(
    "phrase",
    [
        "Intentions de vote au premier tour",
        "Si le premier tour de l'election presidentielle avait lieu dimanche prochain",
        "pour chacune des configurations suivantes, lequel des candidats aurait votre "
        "preference ?",
    ],
)
def test_voting_intention_notices_are_recognised(phrase):
    verdict, evidence = C.classify(PADDING + phrase + PADDING)
    assert verdict == "vote"
    assert evidence


@pytest.mark.parametrize(
    "disclaimer",
    [
        # Each of these produced a false positive during calibration.
        "Ils ne constituent ni une intention de vote ni un element predictif.",
        "Le potentiel electoral ne constitue nullement une intention de vote.",
        "Cette question n'a absolument rien a voir avec une intention de vote.",
    ],
)
def test_disclaimers_are_not_mistaken_for_voting_intentions(disclaimer):
    assert C.classify(PADDING + disclaimer + PADDING)[0] == "autre"


def test_an_unreadable_notice_is_reported_not_guessed():
    """Some notices are scanned images. Calling them 'not a poll' would be a
    guess that silently hides exactly the kind of gap this exists to find."""
    assert C.classify("12 34")[0] == "illisible"


# ------------------------------------------------------------------- check


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A catalog, a scan cache and a review file, all on disk under tmp_path."""
    monkeypatch.setattr(C, "CATALOG_FILE", tmp_path / "catalog.csv")
    monkeypatch.setattr(C, "SCAN_FILE", tmp_path / "scan.json")
    monkeypatch.setattr(C, "REVIEW_FILE", tmp_path / "reviews.yaml")

    def write(catalog, scan=None, reviews=None):
        rows = ["filename,categorie,year,pdf_path,http last-modified,pdf creation-date"]
        for name, published, cat in catalog:
            rows.append(f"{name},{cat},2026.0,archives/{name},,{published}")
        C.CATALOG_FILE.write_text("\n".join(rows) + "\n", encoding="utf-8")
        C._save_scan(scan or {})
        C.REVIEW_FILE.write_text(
            yaml.safe_dump({"notices": reviews or {}}), encoding="utf-8"
        )

    return write


def _run(feed=frozenset()):
    return C.check(set(feed), as_of=TODAY, since=dt.date(2024, 7, 8), download=False)


def test_an_old_unreviewed_voting_intention_is_a_warning(sandbox):
    sandbox(
        [("100-pres-x.pdf", "2026-08-01", "Pres")],
        scan={"100-pres-x.pdf": {"verdict": "vote", "extrait": "intentions de vote"}},
    )
    r = _run()
    assert [n["fichier"] for n in r.missing_vote] == ["100-pres-x.pdf"]
    assert not r.ok
    assert any(a.startswith("::warning") for a in C.github_annotations(r))


def test_a_fresh_one_is_only_pending(sandbox):
    """Upstream ingests on its own schedule; a notice from yesterday not being
    in the feed yet is normal, and warning about it daily would teach everyone
    to ignore the warning."""
    sandbox(
        [("101-pres-x.pdf", (TODAY - dt.timedelta(days=2)).isoformat(), "Pres")],
        scan={"101-pres-x.pdf": {"verdict": "vote", "extrait": ""}},
    )
    r = _run()
    assert r.pending_vote and not r.missing_vote


def test_a_reviewed_gap_is_reported_but_not_warned(sandbox):
    sandbox(
        [("102-pres-x.pdf", "2026-06-01", "Pres")],
        scan={"102-pres-x.pdf": {"verdict": "vote", "extrait": ""}},
        reviews={"102-pres-x.pdf": {"statut": "manquante", "note": "Fondapol"}},
    )
    r = _run()
    assert not r.missing_vote
    assert r.known_gaps[0]["note"] == "Fondapol"
    assert not any(a.startswith("::warning") for a in C.github_annotations(r))


def test_a_human_verdict_beats_the_classifier(sandbox):
    sandbox(
        [("103-pres-seconds-tours.pdf", "2026-06-01", "Pres")],
        scan={"103-pres-seconds-tours.pdf": {"verdict": "vote", "extrait": ""}},
        reviews={"103-pres-seconds-tours.pdf": {"statut": "pas_une_intention"}},
    )
    r = _run()
    assert r.ok and not r.known_gaps


def test_notices_in_the_feed_and_out_of_scope_are_ignored(sandbox):
    sandbox([
        ("104-pres-iv-x.pdf", "2026-06-01", "Pres"),      # in the feed
        ("105-mun-rodez.pdf", "2026-06-01", "Pres"),      # municipal, misfiled
        ("106-pres-old.pdf", "2023-01-01", "Pres"),       # before the feed starts
        ("107-leg-x.pdf", "2026-06-01", "Leg"),           # another election
    ])
    r = _run(feed={"104-pres-iv-x.pdf"})
    assert r.ok
    # In scope means presidential and dated since the feed starts: 104 and 105.
    assert r.notices_considered == 2 and r.in_feed == 1


def test_offline_an_unscanned_notice_is_flagged_not_skipped(sandbox):
    """`audit` and `run` never download. A notice nobody has read yet must show
    up as unread rather than passing as fine."""
    sandbox([("108-pres-new.pdf", "2026-06-01", "Pres")])
    r = _run()
    assert r.unreadable and not r.ok


# ------------------------------------------------------ the committed reviews


def test_every_review_is_well_formed_and_names_a_real_notice():
    reviews = C.load_reviews()
    assert reviews, "the review file is empty or missing"
    known = {n.filename for n in C.load_catalog()} if C.CATALOG_FILE.exists() else None
    for name, review in reviews.items():
        assert review.get("statut") in C.REVIEW_STATUSES, name
        assert review.get("note"), f"{name}: a verdict must say what was read"
        if known is not None:
            assert name in known, f"{name} is not in the Commission catalog"
