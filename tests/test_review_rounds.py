from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import pytest

from utils.coauthor_review import (
    register_issued,
    import_return,
    decide_return,
    supersede_item,
    coauthor_findings,
)
from utils.review_rounds import ancestors
from utils.project_store import create_project, load_project
from utils.project_recovery import backup_project, restore_project


def document(path, text):
    doc = Document()
    doc.add_paragraph(text)
    doc.save(path)
    return path


def tracked(path, before, after):
    doc = Document()
    p = doc.add_paragraph()
    for tag, text_tag, text in [("del", "delText", before), ("ins", "t", after)]:
        node = OxmlElement("w:" + tag)
        node.set(qn("w:author"), "Synthetic co-author")
        node.set(qn("w:id"), "1" if tag == "del" else "2")
        run = OxmlElement("w:r")
        t = OxmlElement("w:" + text_tag)
        t.text = text
        run.append(t)
        node.append(run)
        p._p.append(node)
    doc.save(path)
    return path


def rounds(tmp_path):
    root = tmp_path / "project"
    create_project(root)
    first = register_issued(
        root, document(tmp_path / "first.docx", "Original."), "Round one"
    )
    r1 = import_return(
        root,
        first["id"],
        tracked(tmp_path / "r1.docx", "Original.", "First revision."),
        "Author",
    )
    i1 = r1["items"][0]
    decide_return(
        root,
        r1["id"],
        i1["id"],
        "accepted",
        "Author",
        "Reviewer",
        "Checked first revision",
    )
    second = register_issued(
        root,
        document(tmp_path / "second.docx", "First revision."),
        "Round two",
        first["id"],
        "Reviewer",
        "New review round",
    )
    r2 = import_return(
        root,
        second["id"],
        tracked(tmp_path / "r2.docx", "First revision.", "Later revision."),
        "Author",
    )
    i2 = r2["items"][0]
    decide_return(
        root,
        r2["id"],
        i2["id"],
        "accepted",
        "Author",
        "Reviewer",
        "Checked later revision",
    )
    final = document(tmp_path / "final.docx", "Later revision.")
    return root, first, second, r1, r2, i1, i2, final


def test_supersession_preserves_decisions_and_survives_private_recovery(tmp_path):
    w, first, second, r1, r2, i1, i2, final = rounds(tmp_path)
    assert second["round"] == 2 and ancestors(load_project(w), second["id"]) == [
        first["id"]
    ]
    assert coauthor_findings(load_project(w), "Later revision.")
    supersede_item(
        w,
        i1["id"],
        i2["id"],
        final,
        "Reviewer",
        "Later evidence replaces earlier wording",
    )
    data = load_project(w)
    assert not coauthor_findings(data, "Later revision.")
    assert any(
        f["kind"] == "superseded_coauthor_text_present_or_ambiguous"
        for f in coauthor_findings(data, "First revision. Later revision.")
    )
    old = data["coauthor_returns"][0]["items"][0]
    assert old["status"] == "superseded" and old["decisions"][0]["status"] == "accepted"
    assert old["after"] == ["First revision."]
    from utils.coauthor_review import export_response

    export_response(w, first["id"], tmp_path / "response.docx")
    response = "\n".join(
        p.text for p in Document(tmp_path / "response.docx").paragraphs
    )
    assert "Reason for replacement: Later evidence replaces earlier wording" in response
    assert "Earlier decision reason: Checked first revision" in response
    password = "Synthetic round recovery passphrase"
    backup_project(w, tmp_path / "backup.porx", password=password)
    restore_project(tmp_path / "backup.porx", tmp_path / "restored", password)
    assert not coauthor_findings(load_project(tmp_path / "restored"), "Later revision.")
    decide_return(
        w,
        r2["id"],
        i2["id"],
        "rejected",
        "Author",
        "Reviewer",
        "Later decision withdrawn",
    )
    assert any(
        f["kind"] == "invalid_coauthor_supersession"
        for f in coauthor_findings(load_project(w))
    )


def test_new_round_does_not_clear_pending_items_and_invalid_links_fail(tmp_path):
    w, first, second, r1, r2, i1, i2, final = rounds(tmp_path)
    decide_return(
        w,
        r1["id"],
        i1["id"],
        "needs_discussion",
        "Author",
        "Reviewer",
        "Still unresolved",
    )
    assert any(
        f["kind"] == "coauthor_item_pending" for f in coauthor_findings(load_project(w))
    )
    with pytest.raises(ValueError, match="later descendant"):
        supersede_item(w, i2["id"], i2["id"], final, "Reviewer", "Invalid same round")
    with pytest.raises(ValueError, match="later decision"):
        supersede_item(
            w,
            i1["id"],
            i2["id"],
            tmp_path / "second.docx",
            "Reviewer",
            "Wrong final document",
        )
    with pytest.raises(ValueError, match="reviewer"):
        register_issued(w, final, "No attribution", second["id"])
    independent = register_issued(w, final, "Independent")
    assert independent["round"] == 1
    assert (
        load_project(w)["coauthor_returns"][0]["items"][0]["status"]
        == "needs_discussion"
    )


def test_three_round_chain_checks_latest_wording_and_detects_broken_evidence(tmp_path):
    w, first, second, r1, r2, i1, i2, final = rounds(tmp_path)
    supersede_item(
        w, i1["id"], i2["id"], final, "Reviewer", "Round two replaces round one"
    )
    third = register_issued(
        w, final, "Round three", second["id"], "Reviewer", "Final review"
    )
    r3 = import_return(
        w,
        third["id"],
        tracked(tmp_path / "r3.docx", "Later revision.", "Final wording."),
        "Author",
    )
    i3 = r3["items"][0]
    decide_return(
        w, r3["id"], i3["id"], "accepted", "Author", "Reviewer", "Checked final wording"
    )
    final3 = document(tmp_path / "final3.docx", "Final wording.")
    supersede_item(
        w, i2["id"], i3["id"], final3, "Reviewer", "Round three replaces round two"
    )
    data = load_project(w)
    assert not coauthor_findings(data, "Final wording.")
    assert any(
        f["kind"] == "coauthor_change_missing_from_pack"
        for f in coauthor_findings(data, "Later revision.")
    )
    from pathlib import Path

    Path(
        data["coauthor_returns"][0]["items"][0]["supersession"]["output"]["path"]
    ).write_bytes(b"corrupt")
    assert any(
        f["kind"] == "invalid_coauthor_supersession"
        for f in coauthor_findings(load_project(w))
    )


def test_same_file_can_be_issued_as_an_explicit_later_round(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    path = document(tmp_path / "same.docx", "Unchanged baseline.")
    first = register_issued(w, path, "First")
    second = register_issued(
        w, path, "Second", first["id"], "Reviewer", "Another review of the same text"
    )
    assert first["id"] != second["id"] and first["file"] == second["file"]


def test_pack_checks_latest_decision_and_reintroduced_superseded_text(
    tmp_path, monkeypatch
):
    from test_project_workflow import pack_fixture
    from utils.project_store import file_receipt
    from utils.project_pack import prepare_pack, check_pack

    w, first, second, r1, r2, i1, i2, final = rounds(tmp_path)
    supersede_item(w, i1["id"], i2["id"], final, "Reviewer", "Checked both rounds")
    spec = pack_fixture(w, tmp_path, monkeypatch)
    path = spec["files"][0]["path"]
    doc = Document(path)
    doc.add_paragraph("Later revision.")
    doc.save(path)
    spec["files"][0].update(file_receipt(path))
    report = prepare_pack(w, spec, tmp_path / "pack")
    assert not [p for p in report["pending"] if "coauthor" in p["kind"]]
    doc = Document(tmp_path / "pack/manuscript.docx")
    doc.add_paragraph("First revision.")
    doc.save(tmp_path / "pack/manuscript.docx")
    report = check_pack(w, tmp_path / "pack")
    assert any(
        p["kind"] == "superseded_coauthor_text_present_or_ambiguous"
        for p in report["pending"]
    )
