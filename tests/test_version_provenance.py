from pathlib import Path

import pytest
from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from utils.project_store import create_project, load_project
from utils.project_sources import index_sources
from utils.project_review import compare_versions
from utils.coauthor_review import register_issued, import_return
from utils.version_provenance import set_source_provenance, provenance_status
from utils.project_recovery import backup_project, restore_project


def documents(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    doc = Document()
    doc.add_paragraph("Earlier interpretation.")
    baseline = tmp_path / "baseline.docx"
    doc.save(baseline)
    ins = OxmlElement("w:ins")
    ins.set(qn("w:author"), "Synthetic reviewer")
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = " Proposed future study."
    run.append(text)
    ins.append(run)
    doc.paragraphs[0]._p.append(ins)
    returned = tmp_path / "return.docx"
    doc.save(returned)
    return w, baseline, returned


def test_reconstructed_text_match_never_confirms_issuance(tmp_path):
    w, baseline, returned = documents(tmp_path)
    issued = register_issued(
        w,
        baseline,
        "Reconstructed",
        reviewer="Reviewer",
        reason="Original text recovered",
        provenance="reconstructed",
        evidence_file=returned,
    )
    review = import_return(w, issued["id"], returned, "Owner")
    assert review["base_text_matches"] and review["base_verified"]
    assert review["baseline_provenance"] == "reconstructed"
    assert review["author_approval"] is False
    assert provenance_status(issued) == "reconstructed"
    wrong = Document()
    wrong.add_paragraph("Not the original.")
    wrong.save(tmp_path / "wrong.docx")
    with pytest.raises(ValueError, match="original-text view"):
        register_issued(
            w,
            tmp_path / "wrong.docx",
            "Wrong",
            reviewer="R",
            reason="R",
            provenance="reconstructed",
            evidence_file=returned,
        )


def test_issued_copy_requires_evidence_and_tracks_staleness(tmp_path):
    w, baseline, returned = documents(tmp_path)
    with pytest.raises(ValueError, match="supporting sent record"):
        register_issued(
            w,
            baseline,
            "Issued",
            reviewer="Reviewer",
            reason="Sent",
            provenance="confirmed_issued",
        )
    sent = tmp_path / "sent.eml"
    sent.write_text(
        "Subject: Synthetic issued version\n\nSent baseline attached in source archive."
    )
    issued = register_issued(
        w,
        baseline,
        "Issued",
        reviewer="Reviewer",
        reason="Compared sent record and attachment",
        provenance="confirmed_issued",
        evidence_file=sent,
    )
    assert provenance_status(issued) == "confirmed_issued"
    Path(issued["provenance"]["evidence"]["path"]).write_text("Changed evidence")
    assert provenance_status(issued) == "stale_evidence"


def test_comparison_history_and_restore_preserve_distinctions(tmp_path):
    w, baseline, returned = documents(tmp_path)
    index_sources(w, [baseline, returned])
    a, b = load_project(w)["sources"]
    set_source_provenance(
        w, a["id"], "reconstructed", "Reviewer", "Derived original view", returned
    )
    set_source_provenance(w, b["id"], "working_draft", "Reviewer", "Returned revision")
    index_sources(w, [baseline, returned])
    a, b = load_project(w)["sources"]
    report = compare_versions(a, b)["change_report"]
    assert report["before_provenance"] == "reconstructed"
    assert report["changes"][0]["after"] == [
        "Earlier interpretation. Proposed future study."
    ]
    assert report["author_approval"] is False
    archive = tmp_path / "backup.zip"
    backup_project(w, archive)
    restored = tmp_path / "restored"
    restore_project(archive, restored)
    sources = load_project(restored)["sources"]
    assert provenance_status(sources[0]) == "reconstructed"
    assert sources[0]["provenance"]["evidence"]["path"].startswith(str(restored))
    doc = Document(baseline)
    doc.add_paragraph("Changed")
    doc.save(baseline)
    index_sources(w, [baseline])
    changed = next(s for s in load_project(w)["sources"] if s["id"] == a["id"])
    assert provenance_status(changed) == "unknown"


def test_legacy_baselines_are_explicitly_unknown(tmp_path):
    w, baseline, returned = documents(tmp_path)
    issued = register_issued(w, baseline, "Legacy")
    assert provenance_status(issued) == "unknown"
    assert provenance_status({"file": issued["file"]}) == "unknown"
    from utils.version_provenance import set_baseline_provenance

    set_baseline_provenance(
        w, issued["id"], "reconstructed", "Reviewer", "Compared original text", returned
    )
    updated = load_project(w)["issued_versions"][0]
    assert updated["provenance_history"][0]["kind"] == "unknown"
    assert provenance_status(updated) == "reconstructed"


def test_altered_provenance_evidence_blocks_dependency_check(tmp_path):
    from utils.project_store import dependency_status

    w, baseline, returned = documents(tmp_path)
    index_sources(w, [baseline])
    s = load_project(w)["sources"][0]
    set_source_provenance(
        w, s["id"], "reconstructed", "Reviewer", "Text match", returned
    )
    data = load_project(w)
    assert not dependency_status(data)
    Path(data["sources"][0]["provenance"]["evidence"]["path"]).write_text("changed")
    assert dependency_status(data)[0]["status"] == "version_evidence_changed_or_missing"
