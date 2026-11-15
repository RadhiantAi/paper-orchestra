"""Content-minimised workbook inspection before a researcher allocates sources."""

from collections import Counter, defaultdict
from pathlib import Path
import posixpath
import re

from lxml import etree as E
from utils.project_sources import package, XML
from utils.project_store import file_receipt, current_file, update_project
from utils.research_quality import fingerprint
from utils.workbook_sources import S, R, MAX_PART, MAX_CELLS

ROLES = (
    "candidate_primary",
    "trial_input",
    "withheld_reference",
    "uncertain",
    "excluded",
)


def inspect_structure(path):
    """Read cell types and occupancy, never return cell values, formulas or labels."""
    path = Path(path)
    receipt = file_receipt(path)
    result = {
        "schema": 1,
        "source": receipt,
        "sheets": [],
        "status": "needs_review",
        "content_exposure": "Package structure, row occupancy and cell types inspected; no values or labels emitted.",
        "scope": "Heuristics cannot establish primary status, chronology, independence or completeness.",
    }
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        result["status"] = "unsupported_preserve_and_convert"
        return result
    with package(path) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError("Duplicate workbook package entries.")

        def xml(name):
            if z.getinfo(name).file_size > MAX_PART:
                raise ValueError("Workbook part limit exceeded.")
            tree = E.fromstring(z.read(name), XML)
            if tree.getroottree().docinfo.doctype:
                raise ValueError("Workbook document types are unsupported.")
            return tree

        links = {}
        external = 0
        for rel in xml("xl/_rels/workbook.xml.rels"):
            if rel.get("TargetMode") == "External":
                external += 1
                continue
            target = rel.get("Target", "")
            name = posixpath.normpath(
                target.lstrip("/")
                if target.startswith("/")
                else posixpath.join("xl", target)
            )
            if not name.startswith("xl/") or "\\" in name or ":" in name:
                raise ValueError("Unsafe workbook relationship.")
            links[rel.get("Id")] = name
        total = 0
        for index, sheet in enumerate(
            xml("xl/workbook.xml").findall(S + "sheets/" + S + "sheet"), 1
        ):
            part = links.get(sheet.get(R + "id"))
            if not part:
                raise ValueError("Missing or external worksheet relationship.")
            rows, types, seen = defaultdict(int), Counter(), set()
            for cell in xml(part).iter(S + "c"):
                total += 1
                if total > MAX_CELLS:
                    raise ValueError("Workbook cell limit exceeded.")
                address = cell.get("r", "")
                match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", address)
                if not match or address in seen:
                    raise ValueError("Invalid or duplicate cell address.")
                seen.add(address)
                if cell.find(S + "f") is not None:
                    types["formula"] += 1
                elif cell.get("t", "n") == "n" and cell.findtext(S + "v") not in {
                    None,
                    "",
                }:
                    types["literal_numeric"] += 1
                    rows[int(match[2])] += 1
                elif cell.get("t") in {"s", "inlineStr", "str"}:
                    types["text"] += 1
                elif cell.get("t") == "e":
                    types["error"] += 1
            # Multiple numeric columns repeated across rows merit primary-data review,
            # even in a file labelled statistics. Summary tables can trigger this too.
            repeated = sum(n >= 2 for n in rows.values())
            cues = []
            if repeated >= 5:
                cues.append("possible_row_level_data_review_required")
            if types["formula"]:
                cues.append("formula_or_summary_content_present")
            if not types["literal_numeric"]:
                cues.append("possible_empty_template_or_text_only_sheet")
            result["sheets"].append(
                {
                    "sheet_number": index,
                    "state": sheet.get("state", "visible"),
                    "cell_types": dict(types),
                    "rows_with_multiple_numeric_literals": repeated,
                    "cues": cues,
                }
            )
        result["external_workbook_links_not_followed"] = external
    if not current_file(receipt):
        raise ValueError("Workbook changed during structural inspection.")
    result["report_identity"] = fingerprint(result)
    return result


def allocate_source(workspace, path, role, reviewer, reason):
    if role not in ROLES or not reviewer.strip() or not reason.strip():
        raise ValueError("Choose a source role and provide reviewer and reason.")
    if role in {"withheld_reference", "excluded", "uncertain"} and Path(
        path
    ).resolve().is_relative_to(Path(workspace).resolve()):
        raise ValueError(
            "Keep withheld, excluded and uncertain originals outside the trial workspace and its backups."
        )
    report = inspect_structure(path)
    row = {
        "id": fingerprint(report["source"]["path"]),
        "source": report["source"],
        "role": role,
        "reviewer": reviewer,
        "reason": reason,
        "structure": report,
        "author_approval": False,
    }

    def apply(data):
        if role != "trial_input" and any(
            s.get("sha256") == report["source"]["sha256"] for s in data["sources"]
        ):
            raise ValueError(
                "Source already indexed: do not label exposed content as withheld. Start a separate blind workspace."
            )
        data["source_allocations"] = [
            r for r in data.get("source_allocations", []) if r["id"] != row["id"]
        ] + [row]

    return update_project(workspace, apply)


def allocation_findings(data):
    findings = []
    for row in data.get("source_allocations", []):
        if not current_file(row["source"]):
            findings.append({"kind": "source_allocation_stale", "id": row["id"]})
        if row["role"] in {"uncertain", "candidate_primary"}:
            findings.append(
                {"kind": "source_allocation_needs_decision", "id": row["id"]}
            )
        if row["role"] in {"withheld_reference", "excluded"} and any(
            s.get("sha256") == row["source"]["sha256"] for s in data["sources"]
        ):
            findings.append(
                {"kind": "withheld_or_excluded_source_indexed", "id": row["id"]}
            )
    return findings
