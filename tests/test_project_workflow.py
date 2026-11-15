"""Synthetic regressions derived from a private manuscript trial. No clinical data."""

from copy import deepcopy
from email.message import EmailMessage
import json
import zipfile

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
import numpy as np
from PIL import Image
import pymupdf as fitz
import pytest

from utils.project_store import (
    create_project,
    load_project,
    file_receipt,
    REPO,
)
from utils.project_sources import index_sources, search_index
from utils.project_review import (
    import_host,
    decide_query,
    query_status,
    compare_versions,
    discussion_coverage,
    section_word_counts,
)
from utils.project_results import (
    approve_results,
    approved,
    render_results,
    export_result_assets,
    audit_occurrences,
)
from utils.project_figures import (
    mask_image,
    verify_mask,
    match_images,
    figure_identity,
    figure_issues,
)
from utils.project_pack import (
    prepare_pack,
    check_pack,
    record_visual_review,
    release_pack,
    doc_text,
    paragraph_replace,
    reviewed_span,
)
from utils.run_control import digest


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "project"
    create_project(p)
    return p


def result():
    return {
        "id": "region",
        "label": "Synthetic region",
        "definition": "At least one specified finding",
        "source": "synthetic aggregate table",
        "method": "Approved union of binary findings",
        "count": 13,
        "denominator": 20,
        "precision": 1,
    }


def host(**kw):
    return {"schema": 1, "mode": "host_assisted", "host": "Synthetic host", **kw}


def source():
    return {
        "id": "s",
        "sha256": "a" * 64,
        "origin": "https://example.org/source",
        "status": "read",
        "blocks": [{"locator": "page:1", "text": "The original label is synthetic."}],
    }


def evidence():
    return [
        {
            "source_id": "s",
            "source_sha256": "a" * 64,
            "locator": "page:1",
            "quote": "original label",
        }
    ]


def query():
    return {
        "id": "q",
        "owner": "Reviewer",
        "question": "Confirm the diagnosis.",
        "target": "manuscript",
        "quote": "Synthetic description.",
        "evidence": evidence(),
        "conditions": [
            {
                "id": "same",
                "kind": "source_evidence",
                "description": "Original label recovered and reviewed.",
            }
        ],
    }


def test_private_boundary_and_preserved_sessions(project):
    with pytest.raises(ValueError):
        create_project(REPO / "private" / "trial")
    with pytest.raises(ValueError):
        create_project(project)


def test_inventory_reads_edits_comments_legacy_and_attachments(project, tmp_path):
    root = tmp_path / "inputs"
    root.mkdir()
    d = Document()
    p = d.add_paragraph("Current finding.")
    d.add_comment(p.runs, "Recover this idea.", author="Prior reviewer")
    ins = OxmlElement("w:ins")
    ins.set(qn("w:author"), "Editor")
    ins.set(qn("w:id"), "1")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "Added proposal."
    r.append(t)
    ins.append(r)
    p._p.append(ins)
    deleted = OxmlElement("w:del")
    deleted.set(qn("w:id"), "2")
    deleted.set(qn("w:author"), "Editor")
    r = OxmlElement("w:r")
    t = OxmlElement("w:delText")
    t.text = "Earlier finding."
    r.append(t)
    deleted.append(r)
    p._p.append(deleted)
    d.save(root / "revised.docx")
    (root / "older.doc").write_bytes(b"legacy")
    msg = EmailMessage()
    msg["Subject"] = "Synthetic correspondence"
    msg.set_content("Earlier version attached.")
    msg.add_attachment(
        (root / "revised.docx").read_bytes(),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename="earlier.docx",
    )
    (root / "thread.eml").write_bytes(msg.as_bytes())
    (root / "unknown.bin").write_bytes(b"unknown")
    report = index_sources(project, [root])
    assert not report["complete"]
    data = load_project(project)
    assert len(data["sources"]) == 4
    word = next(s for s in data["sources"] if s["path"].endswith("revised.docx"))
    assert {e["kind"] for e in word["edits"]} == {"ins", "del", "comment"}
    assert "Earlier finding." not in word["blocks"][0]["text"]
    email = next(s for s in data["sources"] if s["path"].endswith("thread.eml"))
    assert any("attachment:" in b["locator"] for b in email["blocks"])
    assert any("legacy_conversion_required" in s["warnings"] for s in data["sources"])
    assert search_index(data, ["Added", "proposal"])
    assert not index_sources(project, [tmp_path / "missing"])["complete"]
    assert index_sources(project, [root], max_files=1)["truncated"]


def test_presentation_labels_and_pdf_pages(project, tmp_path):
    root = tmp_path / "inputs"
    root.mkdir()
    xml = '<p xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Synthetic label</a:t></p>'
    with zipfile.ZipFile(root / "labels.pptx", "w") as z:
        z.writestr("ppt/slides/slide1.xml", xml)
        z.writestr("ppt/notesSlides/notesSlide1.xml", xml.replace("label", "notes"))
    pdf = fitz.open()
    pdf.new_page().insert_text((30, 30), "Synthetic caption")
    pdf.new_page()
    pdf.save(root / "thesis.pdf")
    index_sources(project, [root])
    data = load_project(project)
    assert search_index(data, ["notes"])
    assert any("ocr_required" in w for s in data["sources"] for w in s["warnings"])


def test_conditional_confirmation_requires_exact_proof_and_expires(project):
    import_host(project, host(sources=[source()], queries=[query()]))
    decide_query(project, "q", "Author", "Yes, if unchanged.")
    data = load_project(project)
    assert query_status(data["queries"][0], data["sources"]) == "conditional_pending"
    with pytest.raises(ValueError):
        decide_query(
            project,
            "q",
            "Author",
            "Checked",
            condition_proofs=[
                {"id": "same", "evidence": [dict(evidence()[0], quote="invented")]}
            ],
        )
    decide_query(
        project,
        "q",
        "Author",
        "Checked against original.",
        condition_proofs=[{"id": "same", "evidence": evidence()}],
    )
    data = load_project(project)
    assert query_status(data["queries"][0], data["sources"]) == "resolved"
    changed = source()
    changed["sha256"] = "b" * 64
    import_host(project, host(sources=[changed]))
    data = load_project(project)
    assert query_status(data["queries"][0], data["sources"]) == "stale_evidence"
    q = query()
    q["quote"] = "Changed description."
    import_host(project, host(queries=[q]))
    data = load_project(project)
    assert query_status(data["queries"][0], data["sources"]) == "open"


def test_host_exchange_is_atomic_and_never_accepts_actions(project):
    before = (project / "project.json").read_bytes()
    with pytest.raises(ValueError):
        import_host(project, host(sources=[source()], queries=[{"id": "q"}]))
    assert before == (project / "project.json").read_bytes()
    with pytest.raises(ValueError):
        import_host(project, host(execute="delete everything"))
    q = query()
    q["decisions"] = []
    with pytest.raises(ValueError):
        import_host(project, host(queries=[q]))


def test_lost_editorial_points_and_discussion_coverage():
    a = {
        "id": "a",
        "sha256": "a",
        "blocks": [{"text": "Earlier"}],
        "edits": [
            {"kind": "comment", "text": "Investigate mechanism."},
            {"kind": "ins", "text": "Keep this."},
        ],
    }
    b = {"id": "b", "sha256": "b", "blocks": [{"text": "Keep this."}]}
    report = compare_versions(a, b)
    assert [r["status"] for r in report["edits"]] == [
        "unresolved",
        "present_needs_review",
    ]
    d = {
        "fingerprint": report["edits"][0]["fingerprint"],
        "status": "rejected",
        "reviewer": "Author",
        "reason": "Outside scope.",
    }
    assert compare_versions(a, b, [d])["edits"][0]["status"] == "rejected"
    data = {
        "sources": [source()],
        "topics": [
            {
                "id": "idea",
                "kind": "hypothesis",
                "text": "Mechanism",
                "source_id": "s",
                "manuscript_quote": "This mechanism remains to be verified.",
                "qualification": "remains to be verified",
            }
        ],
    }
    assert (
        discussion_coverage(data, "This mechanism remains to be verified.")["status"]
        == "checked"
    )
    assert (
        discussion_coverage(data, "The mechanism is established.")["status"]
        == "needs_review"
    )
    counts = section_word_counts(
        "# Discussion\nOne two three.\n# References\nFour five."
    )
    assert counts["excluding_references"] == 3


def test_result_approvals_propagation_and_different_denominators(tmp_path):
    rows = approve_results([result()], "Author", "Confirmed aggregate.")
    assert render_results("{{result:region:pair}}", rows) == "13 (65.0%)"
    template = "Synthetic region: {{result:region:pair}}."
    mapping = [{"id": "region", "template": template}]
    assert (
        audit_occurrences("Synthetic region: 13 (65.0%).", rows, mapping)["status"]
        == "checked"
    )
    assert (
        audit_occurrences("Synthetic region: 14 (70.0%).", rows, mapping)["status"]
        == "needs_review"
    )
    changed = deepcopy(rows)
    changed[0]["count"] = 14
    assert not approved(changed[0])
    with pytest.raises(ValueError):
        render_results(template, changed)
    other = result()
    other.update(id="subset", count=3, denominator=10)
    approve_results([other], "Author", "Different eligible denominator.")
    assert render_results("{{result:subset:pair}}", [other]) == "3 (30.0%)"
    receipt = export_result_assets(rows, tmp_path / "generated")
    assert len(receipt["files"]) == 4
    with pytest.raises(ValueError):
        export_result_assets(changed, tmp_path / "bad")


def synthetic_image(path, seed=1):
    pixels = np.random.default_rng(seed).integers(0, 256, (400, 400, 3), dtype=np.uint8)
    Image.fromarray(pixels).save(path)


def test_masking_identity_and_caption_independence(tmp_path):
    original = tmp_path / "original.png"
    synthetic_image(original)
    masked = tmp_path / "masked.png"
    receipt = mask_image(
        original, masked, [[0, 0, 400, 40]], "Author", "Approved margins."
    )
    assert verify_mask(receipt)
    with pytest.raises(ValueError):
        mask_image(original, original, [[0, 0, 10, 10]], "Author", "Mask")
    matches = match_images(masked, [original])
    assert len(matches) == 1 and matches[0]["candidate_only"]
    other = tmp_path / "other.png"
    synthetic_image(other, 9)
    assert not match_images(masked, [other])
    fig = {
        "id": "Figure 6",
        "caption": "Figure 6. Synthetic description.",
        "panels": [
            {
                "label": "a",
                "source_id": "s",
                "source_locator": "slide:1",
                "source_label": "Synthetic",
                "original": file_receipt(original),
                "display": file_receipt(masked),
                "mask_receipt": receipt,
            }
        ],
    }
    fig["checks"] = {
        k: {
            "status": "confirmed",
            "reviewer": "Author",
            "reason": "Reviewed",
            "identity": figure_identity(fig),
        }
        for k in [
            "image_identity",
            "caption",
            "clinical",
            "cohort",
            "reproduction",
            "privacy",
        ]
    }
    assert not figure_issues(fig)
    fig["caption"] = "Figure 6. Incorrect diagnosis."
    assert any(i["kind"] == "clinical_needs_confirmation" for i in figure_issues(fig))
    changed = np.asarray(Image.open(masked)).copy()
    changed[200, 200] = 0
    Image.fromarray(changed).save(masked)
    with pytest.raises(ValueError):
        verify_mask(receipt)


def fixture_render(source, destination, libreoffice=None):
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_textbox(fitz.Rect(30, 30, 560, 800), doc_text(source), fontsize=11)
    pdf.save(destination)


def pack_fixture(project, tmp_path, monkeypatch):
    monkeypatch.setattr("utils.project_pack.render_word", fixture_render)
    inp = tmp_path / "input"
    inp.mkdir()
    d = Document()
    d.add_paragraph("Synthetic region: {{result:region:pair}}.")
    d.add_paragraph("Synthetic description.")
    d.save(inp / "manuscript.docx")
    d = Document()
    d.add_paragraph("Retained author title page.")
    d.save(inp / "title.docx")
    q = query()
    q["conditions"] = []
    import_host(
        project,
        host(
            sources=[source()],
            queries=[q],
            results=approve_results([result()], "Author", "Confirmed."),
        ),
    )
    spec = {
        "stage": "coauthor_review",
        "files": [
            {
                "role": "manuscript",
                "name": "manuscript.docx",
                **file_receipt(inp / "manuscript.docx"),
            },
            {
                "role": "title_page",
                "name": "title.docx",
                "preserve": True,
                **file_receipt(inp / "title.docx"),
            },
        ],
        "result_mappings": [
            {"id": "region", "template": "Synthetic region: {{result:region:pair}}."}
        ],
    }
    return spec


def test_complete_pack_and_negative_release_fixtures(project, tmp_path, monkeypatch):
    spec = pack_fixture(project, tmp_path, monkeypatch)
    out = tmp_path / "pack"
    report = prepare_pack(project, spec, out)
    assert not report["problems"]
    d = Document(out / "manuscript.docx")
    assert len(d.comments) == 1
    assert digest(out / "title.docx") == spec["files"][1]["sha256"]
    with pytest.raises(FileNotFoundError):
        release_pack(project, out, tmp_path / "early.zip")
    record_visual_review(project, out, "Reviewer", "Fixture rendering inspected.")
    receipt = release_pack(project, out, tmp_path / "review.zip")
    assert receipt["sent"] is False
    with zipfile.ZipFile(tmp_path / "review.zip") as z:
        assert (
            "pack_spec.json" not in z.namelist() and "project.json" not in z.namelist()
        )
        assert z.testzip() is None
    d = Document(out / "title.docx")
    d.paragraphs[0].text = "Unapproved author"
    d.save(out / "title.docx")
    assert any(
        p["kind"] == "preserved_file_changed"
        for p in check_pack(project, out)["problems"]
    )
    with pytest.raises(ValueError):
        release_pack(project, out, tmp_path / "bad.zip")


def test_highlight_and_stale_approval_block_release(project, tmp_path, monkeypatch):
    spec = pack_fixture(project, tmp_path, monkeypatch)
    out = tmp_path / "pack"
    prepare_pack(project, spec, out)
    d = Document(out / "manuscript.docx")
    for p in d.paragraphs:
        for r in p.runs:
            r.font.highlight_color = None
    d.save(out / "manuscript.docx")
    assert any(
        p["kind"] == "query_highlight_missing"
        for p in check_pack(project, out)["problems"]
    )
    with pytest.raises(ValueError):
        record_visual_review(
            project, out, "Reviewer", "Incorrectly cleared highlights."
        )


def test_resolved_generated_annotations_clear_on_rebuild(
    project, tmp_path, monkeypatch
):
    from docx.enum.text import WD_COLOR_INDEX

    spec = pack_fixture(project, tmp_path, monkeypatch)
    first = tmp_path / "first"
    assert not prepare_pack(project, spec, first)["problems"]
    d = Document(first / "manuscript.docx")
    d.add_comment(
        d.paragraphs[0].runs[0], "Independent editorial comment", author="Editor"
    )
    d.save(first / "manuscript.docx")
    decide_query(project, "q", "Author", "Verified exact description.")
    spec["files"][0].update(file_receipt(first / "manuscript.docx"))
    second = tmp_path / "second"
    assert not prepare_pack(project, spec, second)["problems"]
    d = Document(second / "manuscript.docx")
    assert (
        len(d.comments) == 1
        and next(iter(d.comments)).text == "Independent editorial comment"
    )
    assert not any(
        r.text and r.font.highlight_color == WD_COLOR_INDEX.YELLOW
        for p in d.paragraphs
        for r in p.runs
    )


def test_failed_build_marker_and_case_collisions_block(project, tmp_path, monkeypatch):
    spec = pack_fixture(project, tmp_path, monkeypatch)
    out = tmp_path / "pack"
    prepare_pack(project, spec, out)
    (out / "build_failure.json").write_text("{}")
    assert any(
        p["kind"] == "failed_build_requires_new_output"
        for p in check_pack(project, out)["problems"]
    )
    spec["files"][1]["name"] = "MANUSCRIPT.docx"
    with pytest.raises(ValueError, match="Duplicate"):
        prepare_pack(project, spec, tmp_path / "collision")


def test_html_email_and_pdf_repeat_locations(project, tmp_path):
    msg = EmailMessage()
    msg["Subject"] = "Synthetic HTML message"
    msg.set_content(
        "<p>Recovered earlier proposal.</p><script>ignored()</script>", subtype="html"
    )
    (tmp_path / "message.eml").write_bytes(msg.as_bytes())
    pic = tmp_path / "image.png"
    synthetic_image(pic)
    pdf = fitz.open()
    for _ in range(2):
        page = pdf.new_page()
        page.insert_text((30, 30), "Synthetic label")
        page.insert_image(fitz.Rect(30, 60, 430, 460), filename=str(pic))
    pdf.save(tmp_path / "repeated.pdf")
    pdf.close()
    index_sources(project, [tmp_path / "message.eml", tmp_path / "repeated.pdf"])
    data = load_project(project)
    assert search_index(data, ["earlier proposal"])
    assert not search_index(data, ["ignored()"])
    pdfsource = next(s for s in data["sources"] if s["path"].endswith(".pdf"))
    assert len(pdfsource["images"]) == 1
    assert len(pdfsource["images"][0]["occurrences"]) == 2


def test_submission_does_not_accept_pending_questions(project, tmp_path, monkeypatch):
    spec = pack_fixture(project, tmp_path, monkeypatch)
    spec["stage"] = "submission"
    out = tmp_path / "pack"
    report = prepare_pack(project, spec, out)
    assert any(x["kind"] == "unresolved_submission_checks" for x in report["problems"])


def test_replacement_preserves_surrounding_formatting():
    d = Document()
    p = d.add_paragraph()
    p.add_run("Before ").bold = True
    p.add_run("exact ")
    p.add_run("quote")
    p.add_run(" after").italic = True
    paragraph_replace(p, "exact quote", "replacement", True)
    assert p.text == "Before replacement after"
    assert p.runs[0].bold and p.runs[-1].italic


def test_review_markers_must_cover_the_exact_query():
    from docx.enum.text import WD_COLOR_INDEX

    d = Document()
    p = d.add_paragraph()
    neighbour = p.add_run("Other question. ")
    neighbour.font.highlight_color = WD_COLOR_INDEX.YELLOW
    d.add_comment(neighbour, "Unrelated comment", author="Reviewer")
    target = p.add_run("Verify this.")
    assert reviewed_span(p, "Verify this.") == (False, False)
    target.font.highlight_color = WD_COLOR_INDEX.YELLOW
    assert reviewed_span(p, "Verify this.") == (True, False)
    d.add_comment(target, "Confirm target", author="Reviewer")
    assert reviewed_span(p, "Verify this.") == (True, True)


def test_unmasked_original_embedded_in_pdf_blocks_pack(project, tmp_path, monkeypatch):
    spec = pack_fixture(project, tmp_path, monkeypatch)
    original, masked = tmp_path / "original.png", tmp_path / "masked.png"
    synthetic_image(original)
    receipt = mask_image(
        original, masked, [[0, 0, 400, 40]], "Reviewer", "Mask approved."
    )
    fig = {
        "id": "Figure 1",
        "caption": "Figure 1. Synthetic illustration.",
        "panels": [
            {
                "label": "a",
                "source_id": "s",
                "source_locator": "page:1",
                "source_label": "Synthetic",
                "original": file_receipt(original),
                "display": file_receipt(masked),
                "mask_receipt": receipt,
            }
        ],
    }
    fig["checks"] = {
        k: {
            "status": "confirmed",
            "reviewer": "Reviewer",
            "reason": "Synthetic fixture",
            "identity": figure_identity(fig),
        }
        for k in [
            "image_identity",
            "caption",
            "clinical",
            "cohort",
            "reproduction",
            "privacy",
        ]
    }
    import_host(project, host(figures=[fig]))
    d = Document(spec["files"][0]["path"])
    d.add_paragraph(fig["caption"])
    d.save(spec["files"][0]["path"])
    spec["files"][0].update(file_receipt(spec["files"][0]["path"]))
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_image(fitz.Rect(30, 30, 430, 430), filename=str(original))
    pdf.save(tmp_path / "unsafe.pdf")
    pdf.close()
    spec["files"].append(
        {
            "role": "supplement",
            "name": "unsafe.pdf",
            "preserve": True,
            **file_receipt(tmp_path / "unsafe.pdf"),
        }
    )
    spec["files"].append(
        {
            "role": "image",
            "name": "masked.png",
            "preserve": True,
            **file_receipt(masked),
        }
    )
    report = prepare_pack(project, spec, tmp_path / "pack")
    assert {p["kind"] for p in report["problems"]} == {"unmasked_original_in_pack"}
    receipt["rectangles"] = [[-1, 0, 400, 40]]
    with pytest.raises(ValueError):
        verify_mask(receipt)


def test_exact_caption_condition_rejects_similar_source_label(project):
    s = source()
    s["blocks"][0]["text"] = "Synthetic description. Similar label."
    q = query()
    q["conditions"][0]["kind"] = "exact_text_match"
    q["evidence"] = [dict(evidence()[0], quote="Synthetic description.")]
    import_host(project, host(sources=[s], queries=[q]))
    e = dict(evidence()[0], quote="Similar label.")
    decide_query(
        project,
        "q",
        "Author",
        "Original recovered.",
        condition_proofs=[{"id": "same", "evidence": [e]}],
    )
    data = load_project(project)
    assert query_status(data["queries"][0], data["sources"]) == "conditional_pending"
    e["quote"] = "Synthetic description."
    decide_query(
        project,
        "q",
        "Author",
        "Exact caption verified.",
        condition_proofs=[{"id": "same", "evidence": [e]}],
    )
    data = load_project(project)
    assert query_status(data["queries"][0], data["sources"]) == "resolved"


def test_pdf_repeated_headers_do_not_break_spanning_paragraph(tmp_path):
    pdf = fitz.open()
    for n, body in enumerate(["Paragraph begins here", "and continues here."], 1):
        p = pdf.new_page()
        p.insert_text((30, 30), "REPEATED RUNNING HEADER")
        p.insert_text((30, 100), body)
        p.insert_text((250, 820), str(n))
    pdf.save(tmp_path / "pages.pdf")
    text = doc_text(tmp_path / "pages.pdf")
    assert (
        "HEADER" not in text
        and "Paragraph begins here" in text
        and "continues here." in text
    )


def test_source_edit_invalidates_confirmation_without_reindex(project, tmp_path):
    f = tmp_path / "source.txt"
    f.write_text("Synthetic description.")
    index_sources(project, [f])
    data = load_project(project)
    s = data["sources"][0]
    q = query()
    q["conditions"] = []
    q["evidence"] = [
        {
            "source_id": s["id"],
            "source_sha256": s["sha256"],
            "locator": "text",
            "quote": "Synthetic description.",
        }
    ]
    import_host(project, host(queries=[q]))
    decide_query(project, "q", "Author", "Verified.")
    f.write_text("Changed interpretation.")
    data = load_project(project)
    assert query_status(data["queries"][0], data["sources"]) == "stale_evidence"


def test_stale_result_assets_and_comment_loss_fail(project, tmp_path, monkeypatch):
    spec = pack_fixture(project, tmp_path, monkeypatch)
    receipt = export_result_assets(load_project(project)["results"], tmp_path / "plots")
    spec["result_assets"] = [
        {
            "receipt": str(tmp_path / "plots/results_receipt.json"),
            "files": {"results.png": "plot.png"},
        }
    ]
    spec["files"].append(
        {
            "role": "statistical_figure",
            "name": "plot.png",
            "preserve": True,
            **file_receipt(tmp_path / "plots/results.png"),
        }
    )
    out = tmp_path / "pack"
    assert not prepare_pack(project, spec, out)["problems"]
    receipt["results_fingerprint"] = "wrong"
    (tmp_path / "plots/results_receipt.json").write_text(json.dumps(receipt))
    assert any(
        p["kind"] == "stale_result_plot_or_table"
        for p in check_pack(project, out)["problems"]
    )
    d = Document(out / "manuscript.docx")
    for node in d._element.xpath(".//w:commentRangeStart"):
        node.getparent().remove(node)
    d.save(out / "manuscript.docx")
    assert any(
        p["kind"] == "broken_comment_anchors"
        for p in check_pack(project, out)["problems"]
    )
