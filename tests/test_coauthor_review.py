from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import pytest
from utils.project_store import create_project, load_project
from utils.coauthor_review import (
    register_issued,
    import_return,
    decide_return,
    apply_returned_edits,
    return_conflicts,
    export_response,
    coauthor_findings,
    record_manual_reconciliation,
)


def returned(path, replacement):
    d = Document()
    p = d.add_paragraph()
    for tag, text_tag, text in [
        ("del", "delText", "Original statement."),
        ("ins", "t", replacement),
    ]:
        node = OxmlElement("w:" + tag)
        node.set(qn("w:id"), "1" if tag == "del" else "2")
        node.set(qn("w:author"), "Synthetic reviewer")
        run = OxmlElement("w:r")
        t = OxmlElement("w:" + text_tag)
        t.text = text
        run.append(t)
        node.append(run)
        p._p.append(node)
    d.save(path)


def fixture(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    d = Document()
    d.add_paragraph("Original statement.")
    d.save(tmp_path / "issued.docx")
    issue = register_issued(w, tmp_path / "issued.docx", "Synthetic issued copy")
    return w, issue


def test_returned_edits_require_decision_and_preserve_issued(tmp_path):
    w, issue = fixture(tmp_path)
    returned(tmp_path / "return.docx", "Revised statement.")
    review = import_return(w, issue["id"], tmp_path / "return.docx", "Reviewer")
    assert review["base_verified"] and review["tracked_edits"]
    with pytest.raises(ValueError, match="No accepted"):
        apply_returned_edits(w, issue["id"], tmp_path / "early.docx")
    decide_return(
        w,
        review["id"],
        review["items"][0]["id"],
        "accepted",
        "Reviewer",
        "Author",
        "Compared baseline",
    )
    assert any(
        f["kind"] == "coauthor_change_not_reconciled"
        for f in coauthor_findings(load_project(w))
    )
    apply_returned_edits(w, issue["id"], tmp_path / "new.docx")
    assert not coauthor_findings(load_project(w), "Revised statement.")
    assert any(
        f["kind"] == "coauthor_change_missing_from_pack"
        for f in coauthor_findings(load_project(w), "Original statement.")
    )
    assert Document(tmp_path / "new.docx").paragraphs[0].text == "Revised statement."
    assert Document(issue["file"]["path"]).paragraphs[0].text == "Original statement."
    export_response(w, issue["id"], tmp_path / "response.docx")
    assert "Compared baseline" in "\n".join(
        p.text for p in Document(tmp_path / "response.docx").paragraphs
    )
    decide_return(
        w,
        review["id"],
        review["items"][0]["id"],
        "rejected",
        "Reviewer",
        "Author",
        "Reconsidered",
    )
    assert any(
        f["kind"] == "rejected_coauthor_text_present_or_ambiguous"
        for f in coauthor_findings(load_project(w), "Revised statement.")
    )
    assert not coauthor_findings(load_project(w), "Original statement.")


def test_conflicting_returns_block_application_and_untracked_base_is_unverified(
    tmp_path,
):
    w, issue = fixture(tmp_path)
    for n in range(2):
        path = tmp_path / f"return{n}.docx"
        returned(path, f"Alternative {n}.")
        review = import_return(w, issue["id"], path, f"Reviewer {n}")
        decide_return(
            w,
            review["id"],
            review["items"][0]["id"],
            "accepted",
            "Reviewer",
            "Author",
            "Considered",
        )
    assert return_conflicts(load_project(w), issue["id"])
    with pytest.raises(ValueError, match="conflicting"):
        apply_returned_edits(w, issue["id"], tmp_path / "bad.docx")
    d = Document()
    d.add_paragraph("Untracked change")
    d.save(tmp_path / "untracked.docx")
    assert not import_return(w, issue["id"], tmp_path / "untracked.docx", "Reviewer")[
        "base_verified"
    ]


def test_return_comments_retain_author_context_and_assignment(tmp_path):
    w, issue = fixture(tmp_path)
    d = Document(tmp_path / "issued.docx")
    d.add_comment(d.paragraphs[0].runs, "Consider a new study.", author="Co-author")
    d.save(tmp_path / "comments.docx")
    review = import_return(w, issue["id"], tmp_path / "comments.docx", "Assistant")
    item = review["items"][0]
    assert (
        item["recorded_author"] == "Co-author"
        and item["context"] == "Original statement."
    )
    decide_return(
        w,
        review["id"],
        item["id"],
        "needs_discussion",
        "Lead author",
        "Assistant",
        "Needs confirmation",
    )
    assert load_project(w)["coauthor_returns"][0]["items"][0]["owner"] == "Lead author"


def test_manual_reconciliation_binds_to_current_output(tmp_path):
    w, issue = fixture(tmp_path)
    doc = Document()
    doc.add_paragraph("Untracked revision.")
    doc.save(tmp_path / "manual.docx")
    review = import_return(w, issue["id"], tmp_path / "manual.docx", "Reviewer")
    item = review["items"][0]
    decide_return(
        w,
        review["id"],
        item["id"],
        "accepted",
        "Owner",
        "Reviewer",
        "Verified manually",
    )
    with pytest.raises(ValueError):
        record_manual_reconciliation(
            w,
            issue["id"],
            tmp_path / "issued.docx",
            [item["id"]],
            "Reviewer",
            "Wrong output",
        )
    record_manual_reconciliation(
        w,
        issue["id"],
        tmp_path / "manual.docx",
        [item["id"]],
        "Reviewer",
        "Compared exact source and text",
    )
    assert not coauthor_findings(load_project(w), "Untracked revision.")
    doc.add_paragraph("Later change")
    doc.save(tmp_path / "manual.docx")
    assert coauthor_findings(load_project(w))


def test_pending_return_enters_submission_pack_gate(tmp_path, monkeypatch):
    from test_project_workflow import pack_fixture
    from utils.project_pack import prepare_pack

    w, issue = fixture(tmp_path)
    returned(tmp_path / "return.docx", "Revised statement.")
    import_return(w, issue["id"], tmp_path / "return.docx", "Reviewer")
    spec = pack_fixture(w, tmp_path, monkeypatch)
    spec["stage"] = "submission"
    report = prepare_pack(w, spec, tmp_path / "submission")
    assert report["status"] == "failed"
    assert any(f["kind"] == "coauthor_item_pending" for f in report["pending"])
def test_original_view_excludes_deletions_inside_inserted_text(tmp_path):
    """Rejecting an inserted passage also rejects nested revisions within it."""
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from utils.coauthor_review import _paragraphs

    baseline = tmp_path / "baseline.docx"
    doc = Document()
    doc.add_paragraph("Original paragraph.")
    doc.save(baseline)
    returned = tmp_path / "returned.docx"
    paragraph = doc.paragraphs[0]
    inserted = OxmlElement("w:ins")
    inserted.set(qn("w:author"), "Synthetic reviewer")
    deleted = OxmlElement("w:del")
    run = OxmlElement("w:r")
    text = OxmlElement("w:delText")
    text.text = " Obsolete text within the new insertion."
    run.append(text)
    deleted.append(run)
    inserted.append(deleted)
    run = OxmlElement("w:r")
    text = OxmlElement("w:t")
    text.text = " New text."
    run.append(text)
    inserted.append(run)
    paragraph._p.append(inserted)
    doc.save(returned)
    assert _paragraphs(returned, original=True) == ["Original paragraph."]
    assert _paragraphs(returned) == ["Original paragraph. New text."]

    workspace = tmp_path / "review"
    create_project(workspace)
    issued = register_issued(workspace, baseline, "Synthetic clean baseline")
    review = import_return(workspace, issued["id"], returned, "Synthetic owner")
    assert review["base_verified"]
    assert review["items"][0]["before"] == ["Original paragraph."]
    assert review["items"][0]["after"] == ["Original paragraph. New text."]

    # A baseline containing the nested deletion must fail the ancestry check.
    bad = Document()
    bad.add_paragraph("Original paragraph. Obsolete text within the new insertion.")
    bad.save(tmp_path / "wrong.docx")
    wrong = register_issued(workspace, tmp_path / "wrong.docx", "Wrong baseline")
    mismatch = import_return(workspace, wrong["id"], returned, "Synthetic owner")
    assert not mismatch["base_verified"]
