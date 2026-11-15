"""Preserved XLS conversion with independent cached-value and Excel formula checks."""

import io
import json
import math
import os
from pathlib import Path
import shutil
import struct
import subprocess

import olefile
import xlrd
from utils.project_store import file_receipt, current_file, private_path, update_project
from utils.run_control import write_json, digest
from utils.strict_trial import admit_file, register_derived


def preflight_biff(raw):
    if (
        len(raw) < 8
        or struct.unpack_from("<HH", raw)[0] != 0x0809
        or struct.unpack_from("<H", raw, 4)[0] != 0x0600
    ):
        raise ValueError("Only BIFF8 XLS workbooks are supported.")
    offset, sheets = 0, 0
    # Reject encryption, macros, query tables, external connections and external
    # supporting books before Excel opens the document (including Excel 4 macros).
    blocked = {0x002F, 0x00D3, 0x01AD, 0x080A, 0x0807, 0x0806, 0x0018}
    while offset + 4 <= len(raw):
        kind, size = struct.unpack_from("<HH", raw, offset)
        if kind == 0 and size == 0:
            if any(raw[offset:]):
                raise ValueError("Unexpected BIFF padding.")
            break
        if offset + 4 + size > len(raw):
            raise ValueError("Malformed BIFF record.")
        value = raw[offset + 4 : offset + 4 + size]
        if kind in blocked:
            raise ValueError(
                "Encrypted, macro-enabled, named-formula or externally connected XLS is unsupported."
            )
        if kind == 0x0085:
            if len(value) < 8 or value[5] != 0:
                raise ValueError("Only ordinary worksheet substreams are supported.")
            sheets += 1
        if kind == 0x01AE and (
            len(value) < 4 or struct.unpack_from("<H", value, 2)[0] != 0x0401
        ):
            raise ValueError(
                "External workbook, DDE/OLE or add-in links are unsupported."
            )
        offset += 4 + size
    if not sheets:
        raise ValueError("No worksheets found.")
    if offset < len(raw) and any(raw[offset:]):
        raise ValueError("Unexpected trailing BIFF data.")


def inspect_xls(path):
    if Path(path).stat().st_size > 32 * 1024**2:
        raise ValueError("Legacy workbook exceeds 32 MB.")
    with olefile.OleFileIO(str(path)) as ole:
        allowed = {
            ("Workbook",),
            ("Book",),
            ("\x05SummaryInformation",),
            ("\x05DocumentSummaryInformation",),
            ("\x01CompObj",),
        }
        if any(tuple(p) not in allowed for p in ole.listdir()):
            raise ValueError(
                "Embedded objects or additional OLE streams require manual review."
            )
        stream = "Workbook" if ole.exists("Workbook") else "Book"
        preflight_biff(ole.openstream(stream).read())
    book = xlrd.open_workbook(str(path), on_demand=True, logfile=io.StringIO())
    try:
        sheets, total = [], 0
        for sheet in book.sheets():
            total += sheet.nrows * sheet.ncols
            if total > 100000:
                raise ValueError("Workbook cell budget exceeded.")
            cells = []
            for row in range(sheet.nrows):
                for col in range(sheet.ncols):
                    cell = sheet.cell(row, col)
                    if cell.ctype in {xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK}:
                        continue
                    if cell.ctype == xlrd.XL_CELL_ERROR:
                        raise ValueError("Error cells require manual review.")
                    value = (
                        bool(cell.value)
                        if cell.ctype == xlrd.XL_CELL_BOOLEAN
                        else cell.value
                    )
                    cells.append(
                        {
                            "address": xlrd.formula.colname(col) + str(row + 1),
                            "value": value,
                        }
                    )
            sheets.append(
                {"name": sheet.name, "visibility": sheet.visibility, "cells": cells}
            )
        return {"date1904": bool(book.datemode), "sheets": sheets}
    finally:
        book.release_resources()


def equal_value(a, b):
    if type(a) in {float, int} and type(b) in {float, int}:
        return (
            math.isfinite(a)
            and math.isfinite(b)
            and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-12)
        )
    return type(a) == type(b) and a == b


def compare_workbooks(before, after, formulas=True):
    changes = []
    if before["date1904"] != after["date1904"]:
        changes.append({"kind": "date_system_changed"})
    if [(s["name"], s["visibility"]) for s in before["sheets"]] != [
        (s["name"], s["visibility"]) for s in after["sheets"]
    ]:
        changes.append({"kind": "sheet_order_name_or_visibility_changed"})
    count = 0
    for index, (left, right) in enumerate(zip(before["sheets"], after["sheets"]), 1):
        a, b = ({c["address"]: c for c in sheet["cells"]} for sheet in [left, right])
        if len(a) != len(left["cells"]) or len(b) != len(right["cells"]):
            raise ValueError("Duplicate audit cell addresses.")
        for address in sorted(a.keys() | b.keys()):
            count += 1
            if (
                address not in a
                or address not in b
                or not equal_value(a[address]["value"], b[address]["value"])
            ):
                changes.append(
                    {
                        "kind": "cell_value_changed",
                        "sheet_number": index,
                        "cell": address,
                    }
                )
            elif formulas and any(
                a[address].get(k) != b[address].get(k)
                for k in ["formula", "number_format"]
            ):
                changes.append(
                    {
                        "kind": "formula_or_number_format_changed",
                        "sheet_number": index,
                        "cell": address,
                    }
                )
    return {
        "status": "failed" if changes else "checked",
        "cells_compared": count,
        "changes": changes,
        "numeric_tolerance": {"relative": 1e-12, "absolute": 1e-12},
    }


def convert_workbook(workspace, source, output, reviewer, reason):
    if os.name != "nt":
        raise ValueError(
            "Controlled XLS conversion currently requires installed Microsoft Excel on Windows."
        )
    source, output = Path(source), private_path(output)
    if (
        source.suffix.lower() != ".xls"
        or output.exists()
        or not reviewer.strip()
        or not reason.strip()
    ):
        raise ValueError("Select XLS, a new output directory, reviewer and reason.")
    admit_file(workspace, source)
    original = file_receipt(source)
    cached = inspect_xls(source)
    output.mkdir(parents=True)
    preserved = output / "original.xls"
    shutil.copyfile(source, preserved)
    converted, audit = output / "converted.xlsx", output / "excel-audit.json"
    script = Path(__file__).resolve().parents[1] / "tools" / "convert_workbook.ps1"
    try:
        process = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(script),
                "-Source",
                str(preserved),
                "-Destination",
                str(converted),
                "-Audit",
                str(audit),
            ],
            capture_output=True,
            timeout=180,
        )
        if process.returncode or not converted.is_file() or not audit.is_file():
            raise ValueError(
                "Excel conversion failed; inspect the retained private output directory."
            )
        capture = json.loads(audit.read_text(encoding="utf-8-sig"))
        opening = compare_workbooks(cached, capture["before"], formulas=False)
        comparison = compare_workbooks(capture["before"], capture["after"])
        if not current_file(original) or digest(preserved) != original["sha256"]:
            raise ValueError("Original changed during conversion.")
        report = {
            "opening_cache_check": opening,
            "conversion_check": comparison,
            "status": "failed"
            if opening["changes"] or comparison["changes"]
            else "checked_cells_only",
            "visual_review_required": True,
            "scope": "Cell values, formulas, number formats, sheet order/names/visibility and date system. Layout, charts, names and scientific interpretation require review.",
        }
        write_json(output / "comparison.json", report)
        if report["status"] == "failed":
            raise ValueError(
                "Conversion changed cells, formulas or sheets; it cannot be indexed as verified evidence."
            )
        record = {
            "source": original,
            "preserved_original": file_receipt(preserved),
            "converted": file_receipt(converted),
            "audit": file_receipt(audit),
            "comparison": file_receipt(output / "comparison.json"),
            "engine": capture["engine"],
            "version": capture["version"],
            "controls": capture["controls"],
            "reviewer": reviewer,
            "reason": reason,
            "status": report["status"],
            "author_approval": False,
        }
        write_json(output / "conversion-receipt.json", record)

        def apply(data):
            data.setdefault("legacy_conversions", []).append(record)
            register_derived(
                data, [output / "conversion-receipt.json"], "legacy_conversion"
            )

        update_project(workspace, apply)
        return record
    except Exception:
        write_json(
            output / "conversion-failure.json", {"status": "failed_not_admissible"}
        )
        raise
    finally:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-File",
                str(script.with_name("stop_workbook.ps1")),
                "-Receipt",
                str(audit) + ".process.json",
            ],
            capture_output=True,
            timeout=30,
            check=True,
        )


def verified_conversion(data, source):
    records = [
        r
        for r in data.get("legacy_conversions", [])
        if r["source"]["sha256"] == source["sha256"]
    ]
    if not records:
        raise ValueError("Run controlled XLS conversion first.")
    record = records[-1]
    if record.get("status") != "checked_cells_only" or not all(
        current_file(record[k])
        for k in ["source", "preserved_original", "converted", "audit", "comparison"]
    ):
        raise ValueError("Legacy conversion receipts are stale or incomplete.")
    return record["converted"]
