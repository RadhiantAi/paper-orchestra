"""Synthetic offline controls and reproducible review workflows."""

from datetime import date
import sys
from unittest.mock import Mock

import pytest
from PIL import Image
from docx import Document
import pymupdf as fitz
from utils.network_policy import (
    OfflineModeError,
    require_online,
    offline_enabled,
    _audit,
)
from utils.project_store import create_project, load_project
from utils.project_sources import index_sources
from utils.project_review import evidence_valid
from utils.source_recovery import recover_ocr, confirm_ocr, source_inventory
from utils.analysis_recipes import (
    calculate,
    wilson,
    run_recipe,
    verify_calculation,
    register_proportions,
    calculated_result_current,
)
from utils.journal_checks import check_journal
from utils.research_quality import fingerprint
from utils.project_pack import doc_text, prepare_pack
from utils.review_actions import save_uploads, approve_selected


@pytest.mark.parametrize("mode", [None, "offline", "", "typo"])
def test_offline_fails_closed(mode, monkeypatch):
    if mode is None:
        monkeypatch.delenv("PAPER_NETWORK_MODE", raising=False)
    else:
        monkeypatch.setenv("PAPER_NETWORK_MODE", mode)
    assert offline_enabled()
    with pytest.raises(OfflineModeError):
        require_online("fixture")


@pytest.mark.parametrize("provider", ["openai", "anthropic", "gemini", "compatible"])
def test_offline_blocks_all_model_clients_and_requests(provider, monkeypatch):
    import utils.provider_backend as backend

    monkeypatch.setenv("PAPER_NETWORK_MODE", "offline")
    client = Mock()
    with pytest.raises(OfflineModeError):
        backend._client(provider)
    with pytest.raises(OfflineModeError):
        backend._request_with_client(client, provider, "fixture", [], None, None, 10)
    with pytest.raises(OfflineModeError):
        backend.call_llm_with_contents(["fixture"], provider + ":fixture")
    assert not client.mock_calls


def test_offline_blocks_http_before_transport_and_audit_denies_external(monkeypatch):
    from utils.literature_sources import SearchTransport
    import requests

    fake = Mock(side_effect=AssertionError("Network reached"))
    monkeypatch.setattr(requests, "get", fake)
    monkeypatch.setenv("PAPER_NETWORK_MODE", "offline")
    with pytest.raises(OfflineModeError):
        SearchTransport().get("fixture", "https://example.org")
    fake.assert_not_called()
    with pytest.raises(OfflineModeError):
        _audit("socket.connect", (None, ("203.0.113.1", 443)))
    with pytest.raises(OfflineModeError):
        _audit("socket.getaddrinfo", ("example.org", 443))
    _audit("socket.connect", (None, ("127.0.0.1", 8501)))


def recipe(name="binary_proportion"):
    return {
        "name": name,
        "sampling_unit": "independent synthetic pair",
        "independent_units_confirmed": True,
        "seed": 42,
        "bootstrap_iterations": 1000,
        "confidence": 0.95,
    }


def test_recipes_known_answers_and_seed_reproducibility():
    interval = wilson(5, 10)
    assert interval == pytest.approx([0.23659309, 0.76340691], abs=1e-7)
    rows = [
        {
            "id": "agreement",
            "label": "Synthetic",
            "n00": "40",
            "n01": "10",
            "n10": "10",
            "n11": "40",
        }
    ]
    a = calculate(recipe("paired_binary_agreement"), rows)
    assert a == calculate(recipe("paired_binary_agreement"), rows)
    assert a["results"][0]["kappa"] == pytest.approx(0.6)
    assert a["results"][0]["agreement"] == 0.8
    assert a["results"][0]["ci"][0] < 0.6 < a["results"][0]["ci"][1]
    rows[0].update(n00="100", n01="0", n10="0", n11="0")
    assert calculate(recipe("paired_binary_agreement"), rows)["warnings"]


@pytest.mark.parametrize(
    "changes",
    [
        {"independent_units_confirmed": False},
        {"cluster": "child"},
        {"confidence": 1},
        {"seed": -1},
        {"bootstrap_iterations": 10},
    ],
)
def test_recipe_rejects_unsupported_assumptions(changes):
    with pytest.raises(ValueError):
        calculate(
            recipe() | changes,
            [{"id": "r", "label": "Test", "count": "1", "denominator": "2"}],
        )


def test_analysis_changes_invalidate_linked_results(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    csv = tmp_path / "counts.csv"
    csv.write_text("id,label,count,denominator,missing_count\nr,Synthetic,13,20,2\n")
    receipt = run_recipe(
        w,
        recipe(),
        csv,
        tmp_path / "analysis",
        "Reviewer",
        "Synthetic assumptions reviewed",
    )
    assert verify_calculation(receipt)
    register_proportions(w, receipt["id"], "At least one specified finding")
    row = load_project(w)["results"][0]
    assert calculated_result_current(row, receipt)
    assert not calculated_result_current(row | {"count": 14}, receipt)
    approve_selected(w, ["r"], "Reviewer", "Confirmed")
    csv.write_text("id,label,count,denominator\nr,Synthetic,14,20\n")
    assert not verify_calculation(receipt)
    with pytest.raises(ValueError):
        approve_selected(w, ["r"], "Reviewer", "Stale")


def test_ocr_text_requires_confirmation_and_retains_missing_pages(
    tmp_path, monkeypatch
):
    w = tmp_path / "project"
    create_project(w)
    pdf = fitz.open()
    pdf.new_page()
    pdf.new_page()
    pdf.save(tmp_path / "scan.pdf")
    pdf.close()
    index_sources(w, [tmp_path / "scan.pdf"])
    s = load_project(w)["sources"][0]
    monkeypatch.setattr(
        "utils.source_recovery._ocr_image", lambda *a: ("Synthetic recovered label", 88)
    )
    assert recover_ocr(w, s["id"], sys.executable, max_pages=1)["pages_recovered"] == 1
    data = load_project(w)
    s = data["sources"][0]
    evidence = [
        {
            "source_id": s["id"],
            "source_sha256": s["sha256"],
            "locator": "page:1:ocr",
            "quote": "Synthetic recovered label",
        }
    ]
    assert not evidence_valid(evidence, data["sources"])
    confirm_ocr(w, s["id"], "page:1:ocr", "Reviewer", "Compared page image")
    data = load_project(w)
    assert evidence_valid(evidence, data["sources"])
    assert data["sources"][0]["status"] == "partial"
    assert any("page:2" in x for x in data["sources"][0]["warnings"])
    assert source_inventory(data)["partial"]


def test_ocr_failure_and_duplicates_are_explicit(tmp_path, monkeypatch):
    w = tmp_path / "project"
    create_project(w)
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("Same source")
    b.write_bytes(a.read_bytes())
    scan = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "white").save(scan)
    index_sources(w, [a, b, scan, tmp_path / "missing"])
    data = load_project(w)
    inventory = source_inventory(data)
    assert len(inventory["identical_files"]) == 1 and inventory["missing_roots"]
    sid = next(s["id"] for s in data["sources"] if s["path"].endswith(".png"))
    monkeypatch.setattr("utils.source_recovery._ocr_image", lambda *a: ("", None))
    with pytest.raises(ValueError, match="No text recovered"):
        recover_ocr(w, sid, sys.executable)


def profile():
    return {
        "schema": 1,
        "name": "Synthetic journal fixture",
        "source": "Synthetic instructions",
        "verified_on": date.today().isoformat(),
        "confirmed_by": "Reviewer",
        "max_words": 100,
        "max_abstract_words": 20,
        "max_references": 5,
        "max_figures": 1,
        "figure_min_width_px": 100,
        "figure_min_dpi": 0,
        "reference_style": "numeric",
        "required_sections": ["Abstract", "Methods", "Results", "Discussion"],
        "required_declarations": ["Funding"],
        "checklist_items": ["Study design"],
        "exclude_from_main_count": ["Abstract"],
        "figure_formats": ["png"],
    }


def manuscript():
    return "# Abstract\nSynthetic abstract.\n# Methods\nSynthetic study design.\n# Results\nFinding [1].\n# Discussion\nInterpretation.\n# Declarations\nFunding: none.\n# References\n1. Synthetic reference."


def test_journal_checks_and_content_bound_review():
    p = profile()
    m = manuscript()
    identity = fingerprint([p, m])
    reviews = [
        {
            "item": i,
            "identity": identity,
            "reviewer": "Reviewer",
            "reason": "Checked",
            "quote": "Synthetic",
        }
        for i in p["checklist_items"] + ["Reference formatting reviewed"]
    ]
    assert check_journal(p, m, [], reviews)["status"] == "checked"
    assert check_journal(p, m + " changed", [], reviews)["status"] == "needs_review"
    bad = check_journal(p | {"max_words": 1}, m.replace("[1]", "[2]"), [], reviews)
    assert {"journal_word_limit", "missing_cited_references"} <= {
        f["kind"] for f in bad["findings"]
    }


def test_word_table_order_and_nested_text(tmp_path):
    d = Document()
    d.add_heading("Results", 1)
    d.add_paragraph("Before")
    t = d.add_table(rows=1, cols=1)
    t.cell(0, 0).text = "Table data"
    t.cell(0, 0).add_table(rows=1, cols=1).cell(0, 0).text = "Nested data"
    d.add_heading("References", 1)
    d.add_paragraph("Reference")
    d.save(tmp_path / "doc.docx")
    text = doc_text(tmp_path / "doc.docx")
    assert (
        text.index("Before")
        < text.index("Table data")
        < text.index("Nested data")
        < text.index("# References")
    )


def test_uploads_cannot_escape_or_overwrite(tmp_path):
    create_project(tmp_path)
    paths = save_uploads(tmp_path, [("../../escape.txt", b"Synthetic")])
    assert (
        paths[0].parent == tmp_path / "uploads"
        and not (tmp_path.parent / "escape.txt").exists()
    )
    assert save_uploads(tmp_path, [("other.txt", b"Synthetic")]) == paths


def test_journal_limits_block_submission_pack(tmp_path, monkeypatch):
    from test_project_workflow import pack_fixture

    w = tmp_path / "project"
    create_project(w)
    spec = pack_fixture(w, tmp_path, monkeypatch)
    spec["journal_profile"] = profile()
    spec["stage"] = "submission"
    out = tmp_path / "pack"
    report = prepare_pack(w, spec, out)
    assert report["journal"]["status"] == "needs_review"
    assert any(x["kind"] == "unresolved_submission_checks" for x in report["problems"])


def test_complete_ocr_survives_reindex_but_tampering_invalidates(tmp_path, monkeypatch):
    from utils.project_store import update_project

    w = tmp_path / "project"
    create_project(w)
    pdf = fitz.open()
    pdf.new_page()
    pdf.save(tmp_path / "scan.pdf")
    pdf.close()
    index_sources(w, [tmp_path / "scan.pdf"])
    sid = load_project(w)["sources"][0]["id"]
    monkeypatch.setattr(
        "utils.source_recovery._ocr_image", lambda *a: ("Synthetic label", 90)
    )
    recover_ocr(w, sid, sys.executable)
    confirm_ocr(w, sid, "page:1:ocr", "Reviewer", "Compared scan")
    assert load_project(w)["sources"][0]["status"] == "read"
    index_sources(w, [tmp_path / "scan.pdf"])
    source = load_project(w)["sources"][0]
    block = next(b for b in source["blocks"] if b.get("method") == "local_ocr")
    assert source["status"] == "read" and not block["review_required"]
    update_project(
        w,
        lambda d: next(
            b for b in d["sources"][0]["blocks"] if b.get("method") == "local_ocr"
        ).update(text="Changed label"),
    )
    index_sources(w, [tmp_path / "scan.pdf"])
    source = load_project(w)["sources"][0]
    block = next(b for b in source["blocks"] if b.get("method") == "local_ocr")
    assert source["status"] == "partial" and block["review_required"]


@pytest.mark.parametrize("extension", ["docx", "pdf"])
def test_damaged_source_is_never_marked_complete(tmp_path, extension):
    w = tmp_path / "project"
    create_project(w)
    bad = tmp_path / ("bad." + extension)
    bad.write_bytes(b"Deliberately damaged synthetic file")
    assert not index_sources(w, [bad])["complete"]
    assert load_project(w)["sources"][0]["status"] == "unreadable"


def test_pack_builder_binds_exported_results_and_upload_names(tmp_path, monkeypatch):
    from test_project_workflow import pack_fixture
    from utils.review_actions import build_spec
    from utils.project_results import export_result_assets

    w = tmp_path / "project"
    create_project(w)
    spec = pack_fixture(w, tmp_path, monkeypatch)
    exports = tmp_path / "results"
    export_result_assets(load_project(w)["results"], exports)
    built = build_spec(
        w,
        spec["files"][0]["path"],
        spec["files"][1]["path"],
        [],
        spec["result_mappings"],
        "coauthor_review",
        results_folder=exports,
    )
    report = prepare_pack(w, built, tmp_path / "pack")
    assert not report["problems"]
    assert not any(
        p["kind"] == "statistical_plot_derivation_not_checked"
        for p in report["pending"]
    )
    (exports / "results.png").write_bytes(b"changed")
    with pytest.raises(ValueError, match="asset changed"):
        build_spec(
            w,
            spec["files"][0]["path"],
            spec["files"][1]["path"],
            [],
            [],
            "coauthor_review",
            results_folder=exports,
        )
    paths = save_uploads(w, [("Earlier manuscript.txt", b"Synthetic source")])
    index_sources(w, paths)
    assert load_project(w)["sources"][-1]["display_name"] == "Earlier manuscript.txt"


def test_journal_missing_figure_is_reported_and_old_profile_requires_review(tmp_path):
    p = profile() | {"verified_on": "2000-01-01"}
    figures = [
        {
            "id": "Figure 1",
            "panels": [{"display": {"path": str(tmp_path / "missing.png")}}],
        }
    ]
    report = check_journal(p, manuscript(), figures)
    kinds = {f["kind"] for f in report["findings"]}
    assert {"figure_unreadable", "journal_profile_date_needs_review"} <= kinds


def test_latest_edit_decision_takes_precedence(tmp_path):
    from utils.project_review import import_host, compare_versions
    from utils.review_actions import review_edit

    create_project(tmp_path)
    a = {
        "id": "a",
        "origin": "fixture",
        "sha256": "a" * 64,
        "status": "read",
        "blocks": [],
        "edits": [{"kind": "del", "text": "Synthetic earlier idea"}],
    }
    b = {
        "id": "b",
        "origin": "fixture",
        "sha256": "b" * 64,
        "status": "read",
        "blocks": [],
    }
    import_host(
        tmp_path,
        {"schema": 1, "mode": "host_assisted", "host": "Synthetic", "sources": [a, b]},
    )
    key = compare_versions(a, b)["edits"][0]["fingerprint"]
    review_edit(tmp_path, "a", "b", key, "retained", "Reviewer", "Keep it")
    review_edit(tmp_path, "a", "b", key, "superseded", "Reviewer", "New decision")
    assert (
        compare_versions(a, b, load_project(tmp_path)["edit_decisions"])["edits"][0][
            "status"
        ]
        == "superseded"
    )


def test_runtime_offline_audit_blocks_real_socket_before_transmission(monkeypatch):
    import socket

    # Call an audited primitive not intercepted by the test socket.connect mock.
    monkeypatch.setenv("PAPER_NETWORK_MODE", "offline")
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with pytest.raises(OfflineModeError):
            sock.sendto(b"synthetic", ("203.0.113.1", 9))
    with pytest.raises(OfflineModeError):
        socket.gethostbyname("example.org")


def test_journal_structured_abstract_and_nested_word_headings(tmp_path):
    from utils.journal_checks import journal_word_counts

    doc = Document()
    doc.add_heading("Abstract", 1)
    doc.add_heading("Methods", 2)
    doc.add_paragraph("Four abstract words here")
    doc.add_heading("Methods", 1)
    doc.add_paragraph("Three body words")
    doc.add_heading("References", 1)
    doc.add_heading("Primary sources", 2)
    doc.add_paragraph("Excluded reference words")
    path = tmp_path / "structured.docx"
    doc.save(path)
    total, abstract, _ = journal_word_counts(profile(), doc_text(path))
    assert total == 3 and abstract == 4


def test_duplicate_csv_headers_rejected(tmp_path):
    w = tmp_path / "workspace"
    create_project(w)
    source = tmp_path / "counts.csv"
    source.write_text("id,label,count,count,denominator\nr,Synthetic,1,2,3\n")
    with pytest.raises(ValueError, match="unique"):
        run_recipe(w, recipe(), source, tmp_path / "analysis", "Reviewer", "Checked")
