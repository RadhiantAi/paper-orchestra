"""Real Office rendering on a synthetic complex manuscript; no model calls."""

import os
import shutil
import unicodedata
import pytest
import pymupdf as fitz
from PIL import Image
from docx import Document
from docx.shared import Inches
from docx.oxml import OxmlElement
from docx.opc.part import Part
from docx.opc.packuri import PackURI
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from lxml import etree as E
from utils.project_pack import render_word
from utils.run_control import digest


def assert_rendered(path):
    with fitz.open(path) as pdf:
        text = unicodedata.normalize("NFKC", " ".join(p.get_text() for p in pdf))
        assert len(pdf) >= 2, "missing page break"
        for phrase in [
            "Synthetic manuscript",
            "Nested table value",
            "Figure 1",
            "Page two marker",
            "Synthetic footnote",
        ]:
            assert phrase in text, "missing " + phrase
        assert "INTERNAL_REVIEW_COMMENT" not in text, "comment leaked"
        assert any(p.get_images() for p in pdf), "missing figure image"
        assert "x = 2" in text, "missing equation"


def complex_document(root):
    doc = Document()
    doc.add_heading("Synthetic manuscript", 0)
    p = doc.add_paragraph("Paragraph with a footnote")
    ref = OxmlElement("w:footnoteReference")
    ref.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id", "1")
    p.add_run()._r.append(ref)
    footnotes = OxmlElement("w:footnotes")
    foot = OxmlElement("w:footnote")
    foot.set("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id", "1")
    fp = OxmlElement("w:p")
    fr = OxmlElement("w:r")
    ft = OxmlElement("w:t")
    ft.text = "Synthetic footnote"
    fr.append(ft)
    fp.append(fr)
    foot.append(fp)
    footnotes.append(foot)
    part = Part(
        PackURI("/word/footnotes.xml"),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
        E.tostring(footnotes),
        doc.part.package,
    )
    doc.part.relate_to(part, RT.FOOTNOTES)
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Table heading"
    table.cell(1, 0).add_table(rows=1, cols=1).cell(0, 0).text = "Nested table value"
    p = doc.add_paragraph()
    math = OxmlElement("m:oMath")
    run = OxmlElement("m:r")
    text = OxmlElement("m:t")
    text.text = "x = 2"
    run.append(text)
    math.append(run)
    p._p.append(math)
    image = root / "synthetic.png"
    Image.new("RGB", (240, 120), "blue").save(image)
    doc.add_picture(str(image), width=Inches(2))
    doc.add_paragraph("Figure 1. Synthetic blue panel.")
    comment = doc.add_paragraph("Comment anchor")
    doc.add_comment(
        comment.runs, "INTERNAL_REVIEW_COMMENT", author="Synthetic reviewer"
    )
    doc.add_page_break()
    doc.add_heading("Page two marker", 1)
    doc.add_paragraph("End of synthetic manuscript.")
    source = root / "complex.docx"
    doc.save(source)
    return source


@pytest.mark.skipif(
    os.getenv("RUN_OFFICE_INTEGRATION") != "1",
    reason="Real Office rendering runs in the dedicated CI job",
)
def test_real_office_rendering(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_NETWORK_MODE", "offline")
    engine = os.getenv("OFFICE_TEST_ENGINE", "libreoffice")
    executable = os.getenv("LIBREOFFICE_EXECUTABLE") or shutil.which("soffice")
    if engine == "libreoffice":
        assert executable, "Install LibreOffice for this integration job"
    source = complex_document(tmp_path)
    original = digest(source)
    pdf = tmp_path / "complex.pdf"
    render_word(source, pdf, None if engine == "word" else executable)
    assert digest(source) == original
    assert_rendered(pdf)


def test_render_check_rejects_missing_content(tmp_path):
    bad = tmp_path / "bad.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((30, 30), "Synthetic manuscript")
        pdf.save(bad)
    with pytest.raises(AssertionError):
        assert_rendered(bad)


@pytest.mark.parametrize(
    "defect,reason",
    [
        ("footnote", "missing Synthetic footnote"),
        ("image", "missing figure image"),
        ("equation", "missing equation"),
        ("comment", "comment leaked"),
    ],
)
def test_render_check_rejects_specific_missing_features(tmp_path, defect, reason):
    import io

    text = "Synthetic manuscript\nNested table value\nFigure 1\nPage two marker\nSynthetic footnote\nx = 2"
    if defect == "footnote":
        text = text.replace("Synthetic footnote", "")
    if defect == "equation":
        text = text.replace("x = 2", "")
    if defect == "comment":
        text += "\nINTERNAL_REVIEW_COMMENT"
    bad = tmp_path / "bad.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((30, 30), text)
        if defect != "image":
            image = io.BytesIO()
            Image.new("RGB", (20, 20), "blue").save(image, format="PNG")
            page.insert_image(fitz.Rect(20, 200, 60, 240), stream=image.getvalue())
        pdf.new_page()
        pdf.save(bad)
    with pytest.raises(AssertionError, match=reason):
        assert_rendered(bad)
