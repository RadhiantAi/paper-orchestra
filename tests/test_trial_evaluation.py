"""Adversarial offline checks for reviewer closures, frozen trials and plots."""

import json
import zipfile
from copy import deepcopy
from pathlib import Path
import pytest
from docx import Document

from utils.project_store import load_project, update_project, file_receipt
from utils.trial_evaluation import (
    freeze_protocol,
    register_draft,
    freeze_candidate,
    unblind,
    compare_reference,
    validate_freeze,
)
from utils.source_structure import allocate_source
from utils.project_sources import index_sources
from utils.strict_trial import admit_file
from utils.project_pack import prepare_pack, record_visual_review, check_pack
from utils.project_recovery import backup_project, restore_project
from utils.analysis_recipes import run_recipe
from utils.reviewer_checks import CHECKS, review_check, review_status
from utils.reviewer_checks import source_incomplete
from utils.continuous_results import review_continuous, register_continuous
from utils.continuous_figures import (
    figure_values,
    export_continuous_figure,
    figure_current,
    audit_figures,
    copy_figures,
)
from tests.test_strict_trial_extensions import trial, allow, continuous
from tests.test_project_workflow import fixture_render


def planned(tmp_path):
    w = trial(tmp_path)
    source = tmp_path / "primary.txt"
    source.write_text("Admitted synthetic research evidence")
    allow(w, source)
    index_sources(w, [source])
    ref = tmp_path / "reference.txt"
    ref.write_text("WITHHELD_SENTINEL Result: 12.5 mm")
    allocate_source(w, ref, "withheld_reference", "Reviewer", "Holdout")
    protocol = {
        "question": "Synthetic question",
        "analysis_plan": "Describe evidence",
        "success_criteria": "Preserve accurate numbers",
        "exposure_statement": "Fixture data only",
        "recipes": [],
    }
    freeze_protocol(w, protocol, "Reviewer", "Before analysis")
    return w, source, ref


def packed(tmp_path, monkeypatch):
    monkeypatch.setattr("utils.project_pack.render_word", fixture_render)
    w, source, ref = planned(tmp_path)
    files = []
    for name, role in [("Manuscript.docx", "manuscript"), ("Title.docx", "title_page")]:
        p = tmp_path / name
        d = Document()
        d.add_paragraph(
            "Candidate synthetic result: 12.4 mm"
            if role == "manuscript"
            else "Synthetic title"
        )
        d.save(p)
        register_draft(w, p, "Reviewer", "Generated from admitted evidence")
        files.append(
            {
                **file_receipt(p),
                "role": role,
                "name": name,
                "preserve": role == "title_page",
            }
        )
    directory = w / "pack"
    assert not prepare_pack(w, {"files": files}, directory)["problems"]
    record_visual_review(w, directory, "Reviewer", "Synthetic render checked")
    return w, source, ref, directory


def test_protocol_blocks_unplanned_inputs_and_analysis_and_early_reveal(tmp_path):
    w, source, ref = planned(tmp_path)
    new = tmp_path / "new.txt"
    new.write_text("New evidence")
    with pytest.raises(ValueError, match="frozen|prespecified"):
        allocate_source(w, new, "trial_input", "Reviewer", "Unplanned")
    with pytest.raises(ValueError):
        allocate_source(w, ref, "trial_input", "Reviewer", "Early reveal")
    with pytest.raises(ValueError, match="prespecified"):
        run_recipe(
            w,
            {"name": "binary_proportion"},
            source,
            tmp_path / "calc",
            "Reviewer",
            "Unplanned",
        )
    with pytest.raises(ValueError):
        unblind(w, [file_receipt(ref)["sha256"]], "Reviewer", "Too early")
    with pytest.raises(ValueError):
        register_draft(w, ref, "Reviewer", "Cannot launder reference")
    with pytest.raises(ValueError):
        compare_reference(w, ref, tmp_path / "early.json")
    assert not (tmp_path / "early.json").exists()


def test_freeze_reveal_comparison_and_recovery(tmp_path, monkeypatch):
    w, source, ref, directory = packed(tmp_path, monkeypatch)
    frozen = freeze_candidate(w, directory, "Reviewer", "Candidate completed")
    assert not frozen["author_approval"]
    before = load_project(w)
    with pytest.raises(ValueError):
        update_project(w, lambda d: d.update(queries=[]))
    with pytest.raises(ValueError):
        update_project(
            w, lambda d: d.update(queries=[{"id": "bypass"}]), trial_operation="compare"
        )
    assert load_project(w) == before
    with pytest.raises(ValueError):
        compare_reference(w, ref, tmp_path / "early.json")
    archive = tmp_path / "backup.zip"
    backup_project(w, archive)
    with zipfile.ZipFile(archive) as z:
        assert b"WITHHELD_SENTINEL" not in b"".join(z.read(n) for n in z.namelist())
    restored = tmp_path / "restored"
    restore_project(archive, restored)
    validate_freeze(load_project(restored))
    unblind(w, [file_receipt(ref)["sha256"]], "Reviewer", "Candidate sealed")
    report = compare_reference(w, ref, tmp_path / "comparison.json")
    assert "12.4" in report["numeric_candidates"]["only_in_candidate"]
    assert "12.5" in report["numeric_candidates"]["only_in_reference"]
    assert report["status"] == "needs_human_review"
    with pytest.raises(ValueError):
        admit_file(w, ref)  # Explicit compare does not broaden ordinary ingestion.
    Path(frozen["manuscript"]["path"]).write_bytes(b"Changed")
    with pytest.raises(ValueError, match="changed"):
        compare_reference(w, ref, tmp_path / "changed.json")


def test_freeze_rejects_document_changed_during_sealing(tmp_path, monkeypatch):
    import utils.trial_evaluation as module

    w, _, _, directory = packed(tmp_path, monkeypatch)
    original = module.shutil.copyfile

    def changed(src, dst, *args, **kwargs):
        result = original(src, dst, *args, **kwargs)
        if Path(dst).name == "candidate.docx":
            Path(dst).write_bytes(b"Changed after release")
        return result

    monkeypatch.setattr(module.shutil, "copyfile", changed)
    with pytest.raises(ValueError, match="changed while sealing"):
        freeze_candidate(w, directory, "Reviewer", "Attempt")
    assert "trial_freeze" not in load_project(w)


def test_interpretation_acceptance_requires_evidence_and_reopens(tmp_path):
    w, source, calc = continuous(tmp_path)
    checks = dict.fromkeys(CHECKS["calculation_interpretation"], True)
    kind = "calculation_interpretation"
    with pytest.raises(ValueError, match="passage"):
        review_check(w, kind, calc["id"], "Reviewer", "Checked", "accepted", checks)
    text = "Exploratory estimates require external validation."
    manuscript = tmp_path / "manuscript.txt"
    manuscript.write_text(text)
    with pytest.raises(ValueError, match="present"):
        review_check(
            w,
            kind,
            calc["id"],
            "Reviewer",
            "Checked",
            "accepted",
            checks,
            manuscript,
            "Absent quote",
        )
    review_check(
        w,
        kind,
        calc["id"],
        "Reviewer",
        "Assumptions checked",
        "accepted",
        checks,
        manuscript,
        text,
    )
    assert review_status(load_project(w), kind, calc["id"], text) == "accepted"
    assert (
        review_status(load_project(w), kind, calc["id"], "Limitation deleted")
        == "stale"
    )
    manuscript.write_text("Edited evidence")
    assert review_status(load_project(w), kind, calc["id"]) == "stale"
    source.write_text("Changed source")
    with pytest.raises(ValueError, match="Reproduce"):
        review_check(
            w, kind, calc["id"], "Reviewer", "Not a waiver", "unresolved", checks
        )


def test_workbook_review_cannot_waive_failed_or_changed_cells(tmp_path):
    from utils.project_store import create_project

    w = tmp_path / "project"
    create_project(w)
    files = {}
    for k in ["source", "preserved_original", "converted", "audit", "comparison"]:
        p = tmp_path / (k + ".json")
        p.write_text(json.dumps({"status": "checked_cells_only", "fixture": k}))
        files[k] = file_receipt(p)
    row = {**files, "status": "checked_cells_only"}
    update_project(w, lambda d: d.update(legacy_conversions=[row]))
    sha = files["source"]["sha256"]
    source = {
        **files["source"],
        "status": "partial",
        "warnings": ["legacy_workbook_visual_review_required"],
    }
    checks = dict.fromkeys(CHECKS["workbook_visual"], True)
    assert source_incomplete(load_project(w), source)
    with pytest.raises(ValueError):
        review_check(
            w,
            "workbook_visual",
            sha,
            "Reviewer",
            "Incomplete",
            "accepted",
            {**checks, "charts": False},
        )
    review_check(
        w,
        "workbook_visual",
        sha,
        "Reviewer",
        "Visual fixture compared",
        "accepted",
        checks,
    )
    assert not source_incomplete(load_project(w), source)
    assert source_incomplete(
        load_project(w), {**source, "warnings": source["warnings"] + ["another_gap"]}
    )
    Path(files["converted"]["path"]).write_text("Changed cells")
    assert review_status(load_project(w), "workbook_visual", sha) == "stale"
    assert source_incomplete(load_project(w), source)
    with pytest.raises(ValueError):
        review_check(
            w, "workbook_visual", sha, "Reviewer", "Not a waiver", "accepted", checks
        )


def plot_ready(tmp_path):
    w, source, calc = continuous(tmp_path)
    register_continuous(
        w,
        "ci-x",
        calc["id"],
        {"kind": "summary", "group": None, "variable": "x", "field": "ci"},
        "Interval",
        "Mean interval",
        2,
    )
    review_continuous(w, ["mean-x", "ci-x"], "Reviewer", "Compared calculation")
    spec = {
        "id": "mean-plot",
        "title": "Mean measurement",
        "axis_label": "Measurement",
        "items": [{"result_id": "mean-x", "interval_id": "ci-x", "label": "Pooled"}],
    }
    return w, source, calc, spec


def test_plot_values_and_pack_assets_are_bound_to_calculation(tmp_path):
    w, source, calc, spec = plot_ready(tmp_path)
    values = figure_values(load_project(w), spec)
    assert values["values"][0]["value"] == 11.5
    assert values["values"][0]["display_value"] == "11.50"
    assert values["confidence"] == 0.95
    record = export_continuous_figure(w, spec, tmp_path / "plot")
    assert figure_current(load_project(w), record)
    out = tmp_path / "pack"
    out.mkdir()
    copy_figures(load_project(w), [record["id"]], out)
    assert not audit_figures(load_project(w), [record["id"]], out)
    (out / "StatisticalFigures" / "mean-plot.png").write_bytes(b"Changed graph")
    assert audit_figures(load_project(w), [record["id"]], out)
    source.write_text("Changed input")
    assert not figure_current(load_project(w), record)


def test_plot_rejects_wrong_group_interval_and_unreviewed_precision_change(tmp_path):
    w, _, calc, spec = plot_ready(tmp_path)
    register_continuous(
        w,
        "ci-a",
        calc["id"],
        {"kind": "summary", "group": "A", "variable": "x", "field": "ci"},
        "A interval",
        "Group A only",
        2,
    )
    review_continuous(w, ["ci-a"], "Reviewer", "Verified")
    bad = deepcopy(spec)
    bad["items"][0]["interval_id"] = "ci-a"
    with pytest.raises(ValueError, match="same calculation"):
        figure_values(load_project(w), bad)
    record = export_continuous_figure(w, spec, tmp_path / "plot")
    row = load_project(w)["continuous_results"][0]
    register_continuous(
        w, row["id"], calc["id"], row["selector"], row["label"], row["definition"], 3
    )
    assert not figure_current(load_project(w), record)
