"""Explicit document history; text equality never proves issuance or approval."""

from pathlib import Path
import shutil
from difflib import SequenceMatcher

from utils.project_store import (
    current_file,
    file_receipt,
    private_path,
    update_project,
    require_text,
)

KINDS = {"unknown", "confirmed_issued", "reconstructed", "published", "working_draft"}


def make_provenance(workspace, kind, reviewer, reason, evidence_file=None):
    if kind not in KINDS:
        raise ValueError("Unknown version provenance.")
    row = {
        "kind": kind,
        "reviewer": reviewer,
        "reason": reason,
        "author_approval": False,
    }
    if kind != "unknown":
        require_text(row, "reviewer", "reason")
    if kind in {"confirmed_issued", "reconstructed", "published"} and not evidence_file:
        raise ValueError(
            "Supply the supporting sent record, tracked return or publication."
        )
    if evidence_file:
        receipt = file_receipt(evidence_file)
        if receipt["bytes"] > 200 * 1024**2:
            raise ValueError("Evidence file exceeds the size budget.")
        suffix = Path(evidence_file).suffix.lower()
        if suffix not in {".docx", ".pdf", ".eml", ".txt", ".md"}:
            raise ValueError("Use a document, email or text evidence file.")
        target = (
            private_path(workspace) / "version-evidence" / (receipt["sha256"] + suffix)
        )
        target.parent.mkdir(exist_ok=True)
        if not target.exists():
            shutil.copyfile(evidence_file, target)
        if file_receipt(target)["sha256"] != receipt["sha256"]:
            raise ValueError("Version evidence changed while copying.")
        row["evidence"] = file_receipt(target)
    return row


def provenance_status(record):
    provenance = record.get("provenance", {})
    if not provenance:
        return "unknown"
    if (
        (
            provenance.get("source_sha256")
            and provenance["source_sha256"] != record.get("sha256")
        )
        or (record.get("path") and not current_file(record))
        or (record.get("file") and not current_file(record["file"]))
    ):
        return "stale_source"
    if provenance.get("evidence") and not current_file(provenance["evidence"]):
        return "stale_evidence"
    return provenance.get("kind", "unknown")


def set_source_provenance(
    workspace, source_id, kind, reviewer, reason, evidence_file=None
):
    provenance = make_provenance(workspace, kind, reviewer, reason, evidence_file)

    def apply(data):
        source = next(s for s in data["sources"] if s["id"] == source_id)
        if source.get("path") and not current_file(source):
            raise ValueError("Source changed; reindex before recording its history.")
        if kind == "reconstructed":
            from utils.coauthor_review import _paragraphs

            if (
                Path(source.get("path", "")).suffix.lower() != ".docx"
                or Path(evidence_file).suffix.lower() != ".docx"
                or _paragraphs(source["path"]) != _paragraphs(evidence_file, True)
            ):
                raise ValueError(
                    "Reconstructed source must match the tracked return's original-text view."
                )
        source["provenance"] = dict(provenance, source_sha256=source["sha256"])

    return update_project(workspace, apply)


def set_baseline_provenance(
    workspace, issued_id, kind, reviewer, reason, evidence_file=None
):
    provenance = make_provenance(workspace, kind, reviewer, reason, evidence_file)

    def apply(data):
        record = next(
            r for r in data.get("issued_versions", []) if r["id"] == issued_id
        )
        if not current_file(record["file"]):
            raise ValueError("Baseline changed; preserve and reconcile it first.")
        if kind == "reconstructed":
            from utils.coauthor_review import _paragraphs

            if Path(evidence_file).suffix.lower() != ".docx" or _paragraphs(
                record["file"]["path"]
            ) != _paragraphs(evidence_file, True):
                raise ValueError(
                    "Reconstructed baseline must match the tracked return's original-text view."
                )
        record.setdefault("provenance_history", []).append(
            record.get("provenance", {"kind": "unknown"})
        )
        record["provenance"] = provenance

    return update_project(workspace, apply)


def change_report(before, after):
    a = [b["text"] for b in before.get("blocks", [])]
    b = [b["text"] for b in after.get("blocks", [])]
    rows = []
    for op, i, j, k, l in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op != "equal":
            rows.append(
                {
                    "operation": op,
                    "before": a[i:j],
                    "after": b[k:l],
                    "before_locators": [
                        x.get("locator", "unrecorded") for x in before["blocks"][i:j]
                    ],
                    "after_locators": [
                        x.get("locator", "unrecorded") for x in after["blocks"][k:l]
                    ],
                }
            )
    return {
        "before_sha256": before["sha256"],
        "after_sha256": after["sha256"],
        "before_provenance": provenance_status(before),
        "after_provenance": provenance_status(after),
        "sources_current": all(
            not r.get("path") or current_file(r) for r in (before, after)
        ),
        "changes": rows,
        "author_approval": False,
        "scope": "Source passages and captions changed between these exact files. Historical ancestry and author approval are not inferred.",
    }
