import csv
import json
import math
import zipfile
from copy import deepcopy

import numpy as np
import pytest
from docx import Document
from docx.oxml import OxmlElement
from PIL import Image
import pymupdf as fitz

from utils.analysis_recipes import calculate, run_recipe, verify_calculation
from utils.figure_presence import check_placements, image_occurrences
from utils.manuscript_completeness import audit_completeness
from utils.project_store import create_project, file_receipt, load_project
from utils.project_sources import index_sources
from utils.project_recovery import backup_project, restore_project
from utils.source_structure import (
    inspect_structure,
    allocate_source,
    allocation_findings,
)


def workbook(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="private_label" sheetId="1" state="hidden" r:id="r1"/></sheets></workbook>',
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
        )
        cells = "".join(
            f'<row r="{i}"><c r="A{i}"><v>987654321</v></c><c r="B{i}"><v>2</v></c></row>'
            for i in range(1, 8)
        )
        z.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            + cells
            + '<row r="8"><c r="C8"><f>SUM(A1:A7)</f><v>42</v></c></row></sheetData></worksheet>',
        )


def test_structural_review_finds_data_without_emitting_values(tmp_path):
    source = tmp_path / "final_statistics.xlsx"
    workbook(source)
    report = inspect_structure(source)
    sheet = report["sheets"][0]
    assert sheet["rows_with_multiple_numeric_literals"] == 7
    assert sheet["state"] == "hidden"
    assert sheet["cell_types"] == {"literal_numeric": 14, "formula": 1}
    assert "possible_row_level_data_review_required" in sheet["cues"]
    assert "987654321" not in json.dumps(report)
    assert "private_label" not in json.dumps(report)
    assert "SUM(" not in json.dumps(report)
    legacy = tmp_path / "data.xls"
    legacy.write_bytes(b"synthetic")
    assert inspect_structure(legacy)["status"] == "unsupported_preserve_and_convert"


def test_allocation_blocks_exposure_and_does_not_backup_withheld_source(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    source = tmp_path / "statistics.xlsx"
    workbook(source)
    allocate_source(
        w, source, "withheld_reference", "Technical reviewer", "Hold for unblinding"
    )
    duplicate = tmp_path / "renamed.xlsx"
    duplicate.write_bytes(source.read_bytes())
    for path in [source, duplicate]:
        with pytest.raises(ValueError, match="explicit trial-input"):
            index_sources(w, [path])
    assert not load_project(w)["sources"]
    backup = tmp_path / "private.zip"
    backup_project(w, backup)
    with zipfile.ZipFile(backup) as z:
        assert source.read_bytes() not in [z.read(n) for n in z.namelist()]
    restored = tmp_path / "restored"
    restore_project(backup, restored)
    assert (
        load_project(restored)["source_allocations"][0]["role"] == "withheld_reference"
    )
    allocate_source(
        w, source, "trial_input", "Technical reviewer", "Explicit unblinding"
    )
    index_sources(w, [source])
    with pytest.raises(ValueError, match="already indexed"):
        allocate_source(
            w, source, "withheld_reference", "Reviewer", "Cannot undo exposure"
        )
    source.write_bytes(b"changed")
    assert any(
        f["kind"] == "source_allocation_stale"
        for f in allocation_findings(load_project(w))
    )


def recipe():
    return {
        "name": "continuous_measurements",
        "sampling_unit": "One independent synthetic unit",
        "independent_units_confirmed": True,
        "units": {"x": "mm", "y": "mm"},
        "groups": {"A": "Synthetic A", "B": "Synthetic B"},
        "group_definition": "Assigned labels",
        "missingness_reason": "Synthetic blanks",
        "predictors": ["x"],
        "outcomes": ["y"],
        "seed": 9,
        "bootstrap_iterations": 100,
    }


def rows():
    return [
        {
            "unit_id": f"u{i:03}",
            "group": "A" if i < 12 else "B",
            "x": str(i),
            "y": str(3 + 2 * i + (i % 3 - 1) * 0.4),
        }
        for i in range(24)
    ]


def test_continuous_results_against_independent_formulas_and_held_out_fits():
    result = calculate(recipe(), rows())
    model = next(m for m in result["models"] if m["group"] is None)
    x = np.array([float(r["x"]) for r in rows()])
    y = np.array([float(r["y"]) for r in rows()])
    # Closed-form univariate regression, independently of the production lstsq route.
    slope = sum((x - x.mean()) * (y - y.mean())) / sum((x - x.mean()) ** 2)
    intercept = y.mean() - slope * x.mean()
    assert model["coefficients"]["x"] == pytest.approx(slope)
    assert model["coefficients"]["intercept"] == pytest.approx(intercept)
    errors = []
    for i in range(len(x)):
        xx, yy = np.delete(x, i), np.delete(y, i)
        b = sum((xx - xx.mean()) * (yy - yy.mean())) / sum((xx - xx.mean()) ** 2)
        errors.append(y[i] - (yy.mean() + b * (x[i] - xx.mean())))
    assert model["loo_rmse"] == pytest.approx(
        math.sqrt(sum(e * e for e in errors) / len(errors))
    )
    summary = next(
        r for r in result["results"] if r["group"] is None and r["variable"] == "x"
    )
    assert summary["mean"] == 11.5
    assert summary["sd"] == pytest.approx(
        math.sqrt(sum((v - 11.5) ** 2 for v in range(24)) / 23)
    )
    assert calculate(recipe(), list(reversed(rows()))) == result
    assert "u001" not in json.dumps(result)


def test_continuous_missingness_is_outcome_specific_and_not_imputed():
    data = rows()
    data[0]["y"] = ""
    data[1]["x"] = ""
    result = calculate(recipe(), data)
    model = next(m for m in result["models"] if m["group"] is None)
    assert model["complete_cases"] == 22 and model["excluded_missing"] == 2
    assert [r["missing"] for r in result["results"] if r["group"] is None] == [1, 1]
    assert any(
        w["kind"] == "missing_data_assumptions_require_review"
        for w in result["warnings"]
    )


@pytest.mark.parametrize("bad", ["NaN", "inf", "NA", "1,2", True])
def test_continuous_rejects_invalid_numeric_data(bad):
    data = rows()
    data[0]["y"] = bad
    with pytest.raises(ValueError):
        calculate(recipe(), data)


def test_continuous_rejects_duplicate_units_unknown_groups_and_unconfirmed_design():
    data = rows()
    data[1]["unit_id"] = data[0]["unit_id"]
    with pytest.raises(ValueError):
        calculate(recipe(), data)
    data = rows()
    data[0]["group"] = "C"
    with pytest.raises(ValueError):
        calculate(recipe(), data)
    spec = recipe()
    spec["independent_units_confirmed"] = False
    with pytest.raises(ValueError):
        calculate(spec, rows())


def test_rank_deficient_and_empty_groups_remain_explicit():
    data = rows()
    for row in data:
        row["x"] = "1"
    spec = recipe()
    spec["groups"]["C"] = "Absent"
    result = calculate(spec, data)
    assert all(m["status"] == "not_estimable" for m in result["models"])
    assert any(w["kind"] == "empty_defined_group" for w in result["warnings"])


def test_continuous_multiple_predictors_return_original_units():
    spec = recipe()
    spec["units"]["z"] = "cm"
    spec["predictors"] = ["x", "z"]
    data = rows()
    for i, row in enumerate(data):
        row["z"] = str((i % 5) * 100)
        row["y"] = str(7 + 3 * float(row["x"]) - .02 * float(row["z"]))
    result = calculate(spec, data)
    model = next(m for m in result["models"] if m["group"] is None)
    assert model["coefficients"] == pytest.approx({"intercept": 7, "x": 3, "z": -.02})
    assert model["r_squared"] == pytest.approx(1)
    assert model["loo_rmse"] < 1e-10


def test_continuous_receipt_replays_and_tampering_fails(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    source = tmp_path / "input.csv"
    with source.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows()[0]))
        writer.writeheader()
        writer.writerows(rows())
    record = run_recipe(
        w,
        recipe(),
        source,
        tmp_path / "analysis",
        "Technical reviewer",
        "Synthetic method check",
    )
    assert verify_calculation(record)
    backup = tmp_path / "backup.zip"
    backup_project(w, backup)
    restored = tmp_path / "restored"
    restore_project(backup, restored)
    assert verify_calculation(load_project(restored)["calculations"][0])
    source.write_text(source.read_text().replace("2.6", "2.7"))
    assert not verify_calculation(record)


def expectations():
    return {
        "schema": 1,
        "reviewer": "Technical reviewer",
        "reason": "Synthetic article expectations",
        "section_min_words": {"Discussion": 10},
        "minimum_references": 2,
        "discussion_passages": [
            {"topic": "Limitations", "quote": "A limited sample requires replication."}
        ],
    }


def test_completeness_counts_child_sections_and_flags_internal_wording():
    text = "# Discussion\nA limited sample requires replication.\n## Limitations\nFurther studies should assess accuracy.\n# References\n1. A\n2. B\n# Figures\nFigure 1."
    report = audit_completeness(text, expectations())
    assert report["status"] == "checked"
    assert report["section_word_counts"]["discussion"] == 10
    assert report["numbered_references"] == 2
    changed = text.replace(
        "A limited sample requires replication.", "Author details require confirmation."
    )
    kinds = {f["kind"] for f in audit_completeness(changed, expectations())["findings"]}
    assert {
        "internal_review_wording_in_manuscript",
        "section_below_agreed_length",
        "expected_discussion_passage_missing",
    } <= kinds
    assert audit_completeness(text)["status"] == "needs_review"


def test_completeness_cli_fails_for_unresolved_expectations(tmp_path, capsys):
    from research_project_cli import main
    manuscript = tmp_path / "draft.md"
    manuscript.write_text("# Discussion\nAuthor details require confirmation.")
    report = tmp_path / "report.json"
    with pytest.raises(SystemExit) as exc:
        main(["--workspace", str(tmp_path / "project"), "completeness-check", str(manuscript), "--output", str(report)])
    assert exc.value.code == 1
    assert "Author details" not in capsys.readouterr().out
    assert json.loads(report.read_text())["status"] == "needs_review"



def test_exact_panel_location_cannot_be_satisfied_by_another_document(tmp_path):
    image = tmp_path / "panel.png"
    Image.new("RGB", (30, 20), "red").save(image)
    doc = Document()
    doc.add_picture(str(image))
    doc.save(tmp_path / "Manuscript.docx")
    empty = Document()
    empty.add_paragraph("No illustration")
    empty.save(tmp_path / "Other.docx")
    pdf = fitz.open()
    pdf.new_page()
    page = pdf.new_page()
    page.insert_image(fitz.Rect(20, 20, 80, 60), filename=str(image))
    pdf.save(tmp_path / "Manuscript.pdf")
    pdf.close()
    figures = [{"id": "F1", "panels": [{"label": "A", "display": file_receipt(image)}]}]
    mappings = [
        {
            "figure_id": "F1",
            "panel": "A",
            "document": "Manuscript.docx",
            "location": "body:paragraph:1",
        },
        {
            "figure_id": "F1",
            "panel": "A",
            "document": "Manuscript.pdf",
            "location": "page:2",
        },
    ]
    assert check_placements(tmp_path, figures, mappings)["problems"] == []
    wrong = deepcopy(mappings)
    wrong[0]["document"] = "Other.docx"
    assert (
        check_placements(tmp_path, figures, wrong)["problems"][0]["kind"]
        == "figure_missing_at_declared_location"
    )
    wrong = deepcopy(mappings)
    wrong[1]["location"] = "page:1"
    assert check_placements(tmp_path, figures, wrong)["problems"]
    wrong[0]["document"] = "../outside.docx"
    assert any(
        r["kind"] == "invalid_figure_placement"
        for r in check_placements(tmp_path, figures, wrong)["problems"]
    )


def test_hidden_word_picture_is_not_present(tmp_path):
    image = tmp_path / "panel.png"
    Image.new("RGB", (30, 20)).save(image)
    doc = Document()
    run = doc.add_paragraph().add_run()
    run.add_picture(str(image))
    run.font.hidden = True
    path = tmp_path / "hidden.docx"
    doc.save(path)
    assert not list(image_occurrences(path))
    run.font.hidden = False
    doc.save(path)
    assert len(list(image_occurrences(path))) == 1


@pytest.mark.parametrize(
    "active,hidden,expected", [(True, False, 1), (False, False, 0), (True, True, 0)]
)
def test_pptx_uses_only_active_slide_references(tmp_path, active, hidden, expected):
    image = tmp_path / "panel.png"
    Image.new("RGB", (30, 20)).save(image)
    path = tmp_path / "slides.pptx"
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "ppt/presentation.xml",
            f'<p:presentation xmlns:p="{p}" xmlns:r="{r}"><p:sldIdLst><p:sldId r:id="r1"/></p:sldIdLst></p:presentation>',
        )
        z.writestr(
            "ppt/_rels/presentation.xml.rels",
            '<Relationships><Relationship Id="r1" Target="slides/slide1.xml"/></Relationships>',
        )
        drawing = '<a:blip r:embed="im1"/>' if active else ""
        z.writestr(
            "ppt/slides/slide1.xml",
            f'<p:sld xmlns:p="{p}" xmlns:a="{a}" xmlns:r="{r}" show="{0 if hidden else 1}">{drawing}</p:sld>',
        )
        z.writestr(
            "ppt/slides/_rels/slide1.xml.rels",
            '<Relationships><Relationship Id="im1" Target="../media/image1.png"/></Relationships>',
        )
        z.writestr("ppt/media/image1.png", image.read_bytes())
    assert len(list(image_occurrences(path))) == expected
