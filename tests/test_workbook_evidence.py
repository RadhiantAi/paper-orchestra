"""Synthetic workbook fixtures, including negative cache and media cases."""

import struct
import zipfile

import pytest

from utils.project_store import create_project, load_project
from utils.project_sources import index_sources, search_index
from utils.workbook_sources import vector_text, register_workbook_result
from utils.project_results import approve_results, approved
from utils.project_review import evidence_valid
from utils.project_recovery import backup_project, restore_project

S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"


def emf_text(text):
    body = text.encode("utf-16-le")
    header = bytearray(76)
    struct.pack_into("<II", header, 0, 84, 76 + len(body))
    struct.pack_into("<II", header, 44, len(text), 76)
    return bytes(header) + body


def workbook(path, count=7, media=True, formula=True, extra=None):
    parts = {
        "xl/workbook.xml": f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets><sheet name="Counts" sheetId="1" r:id="r1" state="hidden"/></sheets><definedNames><definedName name="Population">Counts!$B$1</definedName></definedNames></workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships xmlns="{P}"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{S}"><sheetData><row r="1"><c r="A1"><v>{count}</v></c><c r="B1"><v>10</v></c><c r="C1" t="s"><v>0</v></c>'
        + (
            '<c r="D1"><f>SUM(A1:B1)</f><v>999</v></c><c r="E1"><f>1+1</f></c>'
            if formula
            else ""
        )
        + "</row></sheetData></worksheet>",
        "xl/sharedStrings.xml": f'<sst xmlns="{S}"><si><t>Synthetic group</t></si></sst>',
    }
    if media:
        parts.update(
            {
                "xl/media/image1.emf": emf_text("Sensitivity 70%"),
                "xl/charts/chart1.xml": '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:numCache><c:pt idx="0"><c:v>70</c:v></c:pt></c:numCache></c:chartSpace>',
            }
        )
    parts.update(extra or {})
    with zipfile.ZipFile(path, "w") as z:
        for name, body in parts.items():
            z.writestr(name, body)
    return path


def project(tmp_path, **kwargs):
    w = tmp_path / "project"
    create_project(w)
    p = workbook(tmp_path / "counts.xlsx", **kwargs)
    index_sources(w, [p])
    return w, p, load_project(w)["sources"][0]


def test_cells_caches_names_and_vector_text_are_distinct_evidence(tmp_path):
    w, p, s = project(tmp_path)
    blocks = {b["locator"]: b for b in s["blocks"]}
    assert blocks["sheet:Counts!A1"]["saved_value"] == "7"
    assert blocks["sheet:Counts!C1"]["saved_value"] == "Synthetic group"
    assert blocks["sheet:Counts!D1"]["formula"] == "SUM(A1:B1)"
    assert blocks["sheet:Counts!D1"]["saved_value"] == "999"
    assert blocks["sheet:Counts!E1"]["saved_value"] is None
    assert blocks["sheet:Counts!D1"]["sheet_state"] == "hidden"
    assert any(b["kind"] == "named_range" for b in s["blocks"])
    assert search_index(load_project(w), ["Sensitivity"])
    assert len(s["images"]) == 1
    assert s["status"] == "partial"
    for loc in ["sheet:Counts!D1", "xl/media/image1.emf:text", "xl/charts/chart1.xml"]:
        proof = [
            {
                "source_id": s["id"],
                "source_sha256": s["sha256"],
                "locator": loc,
                "quote": blocks[loc]["text"],
            }
        ]
        assert not evidence_valid(proof, [s])


def test_literal_results_stale_cache_rejection_and_recovery(tmp_path):
    w, p, s = project(tmp_path)
    args = (
        w,
        s["id"],
        "sheet:Counts!A1",
        "sheet:Counts!B1",
        "sensitivity",
        "Group",
        "Detection",
    )
    register_workbook_result(*args)
    r = load_project(w)["results"][0]
    assert not approved(r)
    approve_results([r], "Reviewer", "Checked aggregate cells")
    assert approved(r)
    with pytest.raises(ValueError, match="formula caches"):
        register_workbook_result(
            w, s["id"], "sheet:Counts!D1", "sheet:Counts!B1", "x", "x", "x"
        )
    archive = tmp_path / "recovery.zip"
    backup_project(w, archive)
    restored = tmp_path / "restored"
    restore_project(archive, restored)
    rr = load_project(restored)["results"][0]
    assert rr["workbook_source"]["path"] != str(p)
    approve_results([rr], "Reviewer", "Checked restored source")
    assert approved(rr)
    workbook(p, count=8)
    assert not approved(r)
    with pytest.raises(ValueError, match="Workbook changed"):
        approve_results([r], "Reviewer", "Changed")
    with pytest.raises(ValueError, match="Workbook changed"):
        register_workbook_result(*args)


def test_vector_text_bounds_and_wmf():
    assert vector_text(emf_text("Synthetic"), ".emf") == "Synthetic"
    bad = bytearray(emf_text("Synthetic"))
    struct.pack_into("<I", bad, 48, 99999)
    with pytest.raises(ValueError, match="bounds"):
        vector_text(bad, ".emf")
    text = b"Group 7/10"
    record = (
        struct.pack("<IHH", (8 + len(text) + 4) // 2, 0x0521, len(text))
        + text
        + b"\x00" * 4
    )
    assert vector_text(b"\x00" * 18 + record, ".wmf") == "Group 7/10"
    with pytest.raises(ValueError, match="length"):
        vector_text(struct.pack("<II", 84, 0), ".emf")


def test_external_links_never_followed_and_limits_fail_closed(tmp_path, monkeypatch):
    w, p, s = project(
        tmp_path,
        extra={
            "xl/worksheets/_rels/sheet1.xml.rels": f'<Relationships xmlns="{P}"><Relationship Id="external" TargetMode="External" Target="https://example.invalid/data"/></Relationships>'
        },
    )
    assert any("external_link_not_followed" in x for x in s["warnings"])
    monkeypatch.setattr("utils.workbook_sources.MAX_CELLS", 1)
    report = index_sources(w, [p])
    assert not report["complete"]
    assert load_project(w)["sources"][0]["status"] == "unreadable"


def test_malformed_graphic_retains_original_with_warning(tmp_path):
    w, p, s = project(
        tmp_path, extra={"xl/media/image1.emf": struct.pack("<II", 84, 0)}
    )
    assert s["images"]
    assert "vector_text_unreadable:xl/media/image1.emf" in s["warnings"]
    assert not any(b["kind"] == "vector_text" for b in s["blocks"])


def test_altered_extracted_asset_is_not_silently_reused(tmp_path):
    from pathlib import Path

    w, p, s = project(tmp_path)
    Path(s["images"][0]["path"]).write_bytes(b"altered graphic")
    assert not index_sources(w, [p])["complete"]
    assert load_project(w)["sources"][0]["status"] == "unreadable"


@pytest.mark.parametrize(
    "cell",
    ['<c r="A1"><v>2</v></c><c r="A1"><v>3</v></c>', '<c r="A1" t="s"><v>-1</v></c>'],
)
def test_ambiguous_or_invalid_cells_fail_closed(tmp_path, cell):
    w, p, s = project(
        tmp_path,
        extra={
            "xl/worksheets/sheet1.xml": f'<worksheet xmlns="{S}"><sheetData><row r="1">{cell}</row></sheetData></worksheet>'
        },
    )
    assert s["status"] == "unreadable" and not s["blocks"]


def test_glyph_indices_are_not_misreported_as_unicode_text():
    data = bytearray(emf_text("Glyphs"))
    struct.pack_into("<I", data, 52, 0x10)
    with pytest.raises(ValueError, match="glyph indices"):
        vector_text(data, ".emf")
