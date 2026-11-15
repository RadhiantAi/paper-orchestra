import csv
import json
import os
import struct
import subprocess
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest
from docx import Document

from utils.project_store import create_project, load_project, file_receipt
from utils.strict_trial import enable_strict_trial, allocate_host, admit_file
from utils.source_structure import allocate_source
from utils.project_sources import index_sources
from utils.project_review import import_host
from utils.project_recovery import backup_project, restore_project
from utils.review_actions import save_uploads
from utils.research_quality import fingerprint
from utils.analysis_recipes import run_recipe
from utils.continuous_results import (
    register_continuous,
    review_continuous,
    resolve_continuous,
    audit_continuous,
    selected_value,
)
from utils.legacy_workbooks import (
    compare_workbooks,
    preflight_biff,
    convert_workbook,
    verified_conversion,
)


def trial(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    enable_strict_trial(w, "Reviewer", "Synthetic blind protocol")
    return w


def allow(w, source):
    allocate_source(w, source, "trial_input", "Reviewer", "Protocol input")


def test_strict_unknown_changed_and_renamed_inputs_are_blocked(tmp_path):
    w = trial(tmp_path)
    source = tmp_path / "primary.txt"
    source.write_text("Synthetic data")
    with pytest.raises(ValueError, match="explicit"):
        index_sources(w, [source])
    with pytest.raises(ValueError):
        save_uploads(w, [("primary.txt", source.read_bytes())])
    assert not (w / "uploads").exists()
    allow(w, source)
    source.write_text("Changed synthetic data")
    with pytest.raises(ValueError):
        index_sources(w, [source])
    allocate_source(w, source, "withheld_reference", "Reviewer", "Hold out")
    renamed = tmp_path / "renamed.txt"
    renamed.write_bytes(source.read_bytes())
    with pytest.raises(ValueError):
        admit_file(w, renamed)
    assert not load_project(w)["sources"]
    allow(w, source)
    index_sources(w, [source])
    assert load_project(w)["strict_trial"]["unblinded_at"]
    with pytest.raises(ValueError):
        enable_strict_trial(w, "Reviewer", "Cannot erase exposure")


def test_strict_host_requires_exchange_and_each_source(tmp_path):
    w = trial(tmp_path)
    source = {
        "id": "s",
        "origin": "synthetic:source",
        "sha256": "a" * 64,
        "status": "read",
        "blocks": [{"locator": "p1", "text": "Synthetic evidence"}],
    }
    payload = {
        "schema": 1,
        "mode": "host_assisted",
        "host": "Fixture",
        "sources": [source],
    }
    with pytest.raises(ValueError):
        import_host(w, payload)
    allocate_host(
        w,
        "host-exchange:Fixture",
        fingerprint(payload),
        "trial_input",
        "Reviewer",
        "Approved exchange",
    )
    with pytest.raises(ValueError):
        import_host(w, payload)
    allocate_host(
        w,
        source["origin"],
        source["sha256"],
        "trial_input",
        "Reviewer",
        "Protocol input",
    )
    import_host(w, payload)
    source["blocks"][0]["text"] = "Different text with unchanged source hash"
    with pytest.raises(ValueError):
        import_host(w, payload)
    assert load_project(w)["sources"][0]["blocks"][0]["text"] == "Synthetic evidence"


@pytest.mark.parametrize("route", ["analysis", "upload", "host_exchange"])
def test_exposure_outside_source_index_cannot_be_relabelled_withheld(tmp_path, route):
    w = trial(tmp_path)
    if route == "host_exchange":
        payload = {"schema": 1, "mode": "host_assisted", "host": "Fixture"}
        sha = fingerprint(payload)
        allocate_host(
            w, "host-exchange:Fixture", sha, "trial_input", "Reviewer", "Synthetic"
        )
        import_host(w, payload)
        with pytest.raises(ValueError, match="exposed"):
            allocate_host(
                w,
                "host-exchange:Fixture",
                sha,
                "withheld_reference",
                "Reviewer",
                "Cannot reverse exposure",
            )
    else:
        source = tmp_path / "input.csv"
        source.write_text(
            "id,label,count,denominator,missing_count\na,Synthetic,3,5,0\n"
        )
        allow(w, source)
        if route == "upload":
            save_uploads(w, [(source.name, source.read_bytes())])
        else:
            run_recipe(
                w,
                {
                    "name": "binary_proportion",
                    "sampling_unit": "Synthetic independent units",
                    "independent_units_confirmed": True,
                },
                source,
                tmp_path / "analysis",
                "Reviewer",
                "Synthetic",
            )
        assert not load_project(w)["sources"]
        with pytest.raises(ValueError, match="exposed"):
            allocate_source(
                w, source, "withheld_reference", "Reviewer", "Cannot reverse exposure"
            )


def test_strict_recovery_excludes_withheld_and_stray_bytes(tmp_path):
    w = trial(tmp_path)
    source = tmp_path / "input.txt"
    source.write_text("Admitted source")
    allow(w, source)
    index_sources(w, [source])
    withheld = tmp_path / "reference.txt"
    withheld.write_text("WITHHELD_CONTENT_SENTINEL")
    allocate_source(w, withheld, "withheld_reference", "Reviewer", "Hold out")
    (w / "stray.txt").write_text("STRAY_CONTENT_SENTINEL")
    archive = tmp_path / "backup.zip"
    backup_project(w, archive)
    with zipfile.ZipFile(archive) as z:
        content = b"\n".join(z.read(n) for n in z.namelist())
        assert b"WITHHELD_CONTENT_SENTINEL" not in content
        assert b"STRAY_CONTENT_SENTINEL" not in content
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["strict_registered_files_only"]
        assert manifest["unregistered_files_excluded"] == 1
    restored = tmp_path / "restored"
    restore_project(archive, restored)
    data = load_project(restored)
    assert data["strict_trial"]["enabled"]
    assert data["allocation_history"]
    assert Path(data["sources"][0]["path"]).read_text() == "Admitted source"
    with pytest.raises(ValueError):
        admit_file(restored, withheld)


def test_strict_pack_only_reads_admitted_inputs_and_survives_recovery(
    tmp_path, monkeypatch
):
    from tests.test_project_workflow import fixture_render
    from utils.project_pack import (
        prepare_pack,
        check_pack,
        record_visual_review,
        release_pack,
    )

    monkeypatch.setattr("utils.project_pack.render_word", fixture_render)
    w = trial(tmp_path)
    sources = []
    for name, role in [("Manuscript.docx", "manuscript"), ("Title.docx", "title_page")]:
        path = tmp_path / name
        doc = Document()
        doc.add_paragraph("Synthetic " + role)
        doc.save(path)
        sources.append(
            {
                **file_receipt(path),
                "role": role,
                "name": name,
                "preserve": role == "title_page",
            }
        )
    spec = {"files": sources}
    out = w / "pack"
    with pytest.raises(ValueError):
        prepare_pack(w, spec, out)
    assert not out.exists()
    for source in sources:
        allow(w, source["path"])
    assert not prepare_pack(w, spec, out)["problems"]
    record_visual_review(w, out, "Reviewer", "Synthetic rendering fixture checked")
    release_pack(w, out, tmp_path / "review.zip")
    archive = tmp_path / "backup.zip"
    backup_project(w, archive)
    restored = tmp_path / "restored"
    restore_project(archive, restored)
    assert (restored / "pack" / "Manuscript.docx").is_file()
    # Recovery rewrites paths in pack metadata, so it requires a fresh build and review.
    d = Document(out / "Manuscript.docx")
    d.paragraphs[0].text = "Unadmitted changed content"
    d.save(out / "Manuscript.docx")
    with pytest.raises(ValueError):
        check_pack(w, out)


def continuous(tmp_path):
    from tests.test_trial_improvements import recipe, rows

    w = tmp_path / "project"
    create_project(w)
    source = tmp_path / "input.csv"
    with source.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows()[0]))
        writer.writeheader()
        writer.writerows(rows())
    calc = run_recipe(
        w, recipe(), source, tmp_path / "analysis", "Reviewer", "Synthetic method check"
    )
    selector = {"kind": "summary", "group": None, "variable": "x", "field": "mean"}
    register_continuous(w, "mean-x", calc["id"], selector, "Mean x", "Pooled mean", 2)
    return w, source, calc


def test_continuous_links_require_review_and_detect_stale_values(tmp_path):
    w, source, calc = continuous(tmp_path)
    with pytest.raises(ValueError, match="technical review"):
        resolve_continuous(load_project(w))
    review_continuous(w, ["mean-x"], "Reviewer", "Compared original calculation")
    data = load_project(w)
    assert resolve_continuous(data) == {"mean-x": "11.50"}
    mapping = [
        {
            "id": "mean-x",
            "template": "Mean: {{continuous:mean-x:value}} mm",
            "document": "Table.docx",
        }
    ]
    assert (
        audit_continuous(data, {"Table.docx": "Mean: 11.50 mm"}, mapping)["status"]
        == "checked"
    )
    assert (
        audit_continuous(data, {"Table.docx": "Mean: 11.51 mm"}, mapping)["status"]
        == "failed"
    )
    assert (
        audit_continuous(data, {"manuscript": "Mean: 11.50 mm"}, mapping)["status"]
        == "failed"
    )
    assert (
        audit_continuous(
            data,
            {"manuscript": "111.50"},
            [{"id": "mean-x", "template": "{{continuous:mean-x:value}}"}],
        )["status"]
        == "failed"
    )
    assert not data["continuous_results"][0]["author_approval"]
    row = data["continuous_results"][0]
    register_continuous(
        w, row["id"], calc["id"], row["selector"], row["label"], row["definition"], 3
    )
    with pytest.raises(ValueError, match="technical review"):
        resolve_continuous(load_project(w))
    source.write_text("changed")
    assert audit_continuous(load_project(w), {}, mapping)["status"] == "failed"


def test_continuous_pack_updates_prose_and_table_and_blocks_drift(
    tmp_path, monkeypatch
):
    from tests.test_project_workflow import fixture_render
    from utils.project_pack import (
        prepare_pack,
        check_pack,
        record_visual_review,
        release_pack,
    )

    monkeypatch.setattr("utils.project_pack.render_word", fixture_render)
    w, _, _ = continuous(tmp_path)
    review_continuous(w, ["mean-x"], "Reviewer", "Checked calculation")
    manuscript, title = tmp_path / "manuscript.docx", tmp_path / "title.docx"
    d = Document()
    d.add_paragraph("Mean: {{continuous:mean-x:value}} mm")
    d.add_table(rows=1, cols=1).cell(
        0, 0
    ).text = "Table mean: {{continuous:mean-x:value}} mm"
    d.save(manuscript)
    d = Document()
    d.add_paragraph("Synthetic title")
    d.save(title)
    spec = {
        "files": [
            {
                **file_receipt(manuscript),
                "role": "manuscript",
                "name": "Manuscript.docx",
            },
            {
                **file_receipt(title),
                "role": "title_page",
                "name": "Title.docx",
                "preserve": True,
            },
        ],
        "continuous_mappings": [
            {"id": "mean-x", "template": "Mean: {{continuous:mean-x:value}} mm"},
            {"id": "mean-x", "template": "Table mean: {{continuous:mean-x:value}} mm"},
        ],
    }
    out = tmp_path / "pack"
    report = prepare_pack(w, spec, out)
    assert not report["problems"]
    d = Document(out / "Manuscript.docx")
    assert d.tables[0].cell(0, 0).text == "Table mean: 11.50 mm"
    record_visual_review(w, out, "Reviewer", "Synthetic render fixture inspected")
    release_pack(w, out, tmp_path / "review.zip")
    d.tables[0].cell(0, 0).text = "Table mean: 11.51 mm"
    d.save(out / "Manuscript.docx")
    assert any(
        f["kind"] == "continuous_result_occurrence_mismatch"
        for f in check_pack(w, out)["problems"]
    )
    with pytest.raises(ValueError):
        release_pack(w, out, tmp_path / "bad.zip")


def test_strict_nested_host_receipts_and_email_attachments_are_not_implicitly_admitted(
    tmp_path,
):
    from email.message import EmailMessage

    w = trial(tmp_path)
    hidden = tmp_path / "hidden.txt"
    hidden.write_text("WITHHELD_ATTACHMENT_SENTINEL")
    source = {
        "id": "s",
        "origin": "fixture:s",
        "sha256": "b" * 64,
        "status": "read",
        "images": [file_receipt(hidden)],
    }
    payload = {
        "schema": 1,
        "mode": "host_assisted",
        "host": "Fixture",
        "sources": [source],
    }
    allocate_host(
        w,
        "host-exchange:Fixture",
        fingerprint(payload),
        "trial_input",
        "Reviewer",
        "Synthetic",
    )
    allocate_host(
        w, source["origin"], source["sha256"], "trial_input", "Reviewer", "Synthetic"
    )
    with pytest.raises(ValueError):
        import_host(w, payload)
    email = EmailMessage()
    email.set_content("Synthetic body")
    email.add_attachment(
        hidden.read_bytes(), maintype="text", subtype="plain", filename="hidden.txt"
    )
    eml = tmp_path / "review.eml"
    eml.write_bytes(email.as_bytes())
    allow(w, eml)
    report = index_sources(w, [eml])
    assert not report["complete"]
    assert not load_project(w)["sources"][0]["blocks"]
    assert not list((w / "assets").iterdir())


@pytest.mark.parametrize(
    "field",
    ["coefficients", "coefficient_ci", "r_squared", "loo_rmse", "complete_cases"],
)
def test_continuous_model_selectors(tmp_path, field):
    _, _, calc = continuous(tmp_path)
    value, unit = selected_value(
        calc,
        {
            "kind": "model",
            "group": None,
            "outcome": "y",
            "predictors": ["x"],
            "field": field,
            "coefficient": "x",
        },
    )
    assert value is not None and unit
    if field == "complete_cases":
        assert value == 24 and unit == "records"
    if field == "coefficient_ci":
        assert value[0] < 2 < value[1]


def book():
    return {
        "date1904": False,
        "sheets": [
            {
                "name": "Synthetic",
                "visibility": 0,
                "cells": [
                    {
                        "address": "A1",
                        "value": 3,
                        "formula": "=1+2",
                        "number_format": "0.00",
                    }
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "field,value", [("value", 4), ("formula", "=2+1"), ("number_format", "General")]
)
def test_conversion_rejects_cell_drift(field, value):
    before, after = book(), book()
    after["sheets"][0]["cells"][0][field] = value
    assert compare_workbooks(before, after)["status"] == "failed"
    assert compare_workbooks(before, before)["status"] == "checked"


@pytest.mark.parametrize("field,value", [("name", "Renamed"), ("visibility", 1)])
def test_conversion_rejects_sheet_drift(field, value):
    before, after = book(), book()
    after["sheets"][0][field] = value
    assert compare_workbooks(before, after)["status"] == "failed"


def record(kind, value):
    return struct.pack("<HH", kind, len(value)) + value


@pytest.mark.parametrize(
    "extra",
    [
        record(0x2F, b"xx"),
        record(0xD3, b""),
        record(0x1AE, b"\x01\x00\x05\x00"),
        record(0x85, b"\x00\x00\x00\x00\x00\x01\x01\x00"),
        record(0x1AD, b""),
    ],
)
def test_legacy_preflight_blocks_active_content(extra):
    ordinary = record(0x809, b"\x00\x06\x05\x00") + record(0x85, b"\x00" * 8)
    preflight_biff(ordinary)
    with pytest.raises(ValueError):
        preflight_biff(ordinary + extra)


@pytest.mark.skipif(
    os.name != "nt" or os.environ.get("RUN_EXCEL_INTEGRATION") != "1",
    reason="Requires explicitly enabled installed Excel",
)
def test_real_excel_legacy_conversion_and_recovery(tmp_path):
    w = trial(tmp_path)
    source = tmp_path / "synthetic.xls"
    script = tmp_path / "fixture.ps1"
    script.write_text(
        "param([string]$Target)\n$ErrorActionPreference='Stop'\n$e=New-Object -ComObject Excel.Application\n$e.Visible=$false\n$e.DisplayAlerts=$false\ntry {$b=$e.Workbooks.Add();$s=$b.Sheets.Item(1);$s.Cells.Item(1,1)=2;$s.Cells.Item(2,1)=3;$s.Cells.Item(3,1).Formula='=SUM(A1:A2)';$b.SaveAs($Target,56);$b.Close($false)} finally {$e.Quit()}\n"
    )
    subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(script),
            "-Target",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=90,
    )
    original = file_receipt(source)
    allow(w, source)
    conversion = convert_workbook(
        w, source, tmp_path / "conversion", "Reviewer", "Synthetic conversion"
    )
    assert conversion["status"] == "checked_cells_only"
    assert file_receipt(source) == original
    allow(w, conversion["converted"]["path"])
    index_sources(w, [source])
    assert load_project(w)["sources"][0]["blocks"]
    archive = tmp_path / "backup.zip"
    backup_project(w, archive)
    restored = tmp_path / "restored"
    restore_project(archive, restored)
    data = load_project(restored)
    assert verified_conversion(data, data["sources"][0])
    Path(conversion["converted"]["path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="stale"):
        verified_conversion(load_project(w), original)
