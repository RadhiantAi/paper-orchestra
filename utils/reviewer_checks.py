"""Version-bound human decisions for warnings that code cannot resolve."""

import json
from pathlib import Path
from utils.project_store import (
    load_project,
    update_project,
    file_receipt,
    current_file,
    require_text,
)
from utils.research_quality import fingerprint
from utils.literature_sources import utc_now

CHECKS = {
    "workbook_visual": {"layout", "charts", "sheet_visibility", "labels_and_units"},
    "calculation_interpretation": {
        "assumptions",
        "missingness",
        "interpretation",
        "limitations",
    },
}


def content_identity(value):
    # Relocating byte-identical evidence during recovery does not change a decision.
    if isinstance(value, dict):
        return {k: content_identity(v) for k, v in value.items() if k != "path"}
    if isinstance(value, list):
        return [content_identity(v) for v in value]
    return value


def context(data, kind, target):
    if kind == "workbook_visual":
        from utils.legacy_workbooks import verified_conversion

        rows = [
            r
            for r in data.get("legacy_conversions", [])
            if r["source"]["sha256"] == target
        ]
        if not rows:
            raise ValueError("Unknown workbook conversion.")
        row = rows[-1]
        verified_conversion(data, row["source"])
        report = json.loads(Path(row["comparison"]["path"]).read_text(encoding="utf-8"))
        if report.get("status") != "checked_cells_only":
            raise ValueError(
                "Failed conversion checks cannot be waived by visual review."
            )
        return content_identity(row)
    if kind == "calculation_interpretation":
        from utils.analysis_recipes import verify_calculation

        row = next((c for c in data["calculations"] if c["id"] == target), None)
        if not row or not verify_calculation(row):
            raise ValueError(
                "Reproduce the calculation before reviewing its interpretation."
            )
        warnings = json.loads(
            Path(row["output"]["path"]).read_text(encoding="utf-8")
        ).get("warnings", [])
        return {"calculation": content_identity(row), "warnings": warnings}
    raise ValueError("Unknown human review check.")


def review_check(
    workspace,
    kind,
    target,
    reviewer,
    reason,
    decision,
    checks,
    manuscript=None,
    quote=None,
):
    require_text({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")
    if kind not in CHECKS or decision not in {"accepted", "unresolved"}:
        raise ValueError("Choose a known check and accepted or unresolved.")
    if (
        not isinstance(checks, dict)
        or set(checks) != CHECKS[kind]
        or any(type(v) is not bool for v in checks.values())
    ):
        raise ValueError("Record each required check explicitly.")
    if decision == "accepted" and not all(checks.values()):
        raise ValueError("All checks must be completed before acceptance.")
    evidence = None
    if kind == "calculation_interpretation" and decision == "accepted":
        from utils.strict_trial import admit_file
        from utils.project_pack import doc_text

        if not manuscript or not isinstance(quote, str) or not quote.strip():
            raise ValueError(
                "Cite the manuscript passage addressing interpretation and limitations."
            )
        admit_file(workspace, manuscript)
        evidence = file_receipt(manuscript)
        if quote not in doc_text(manuscript) or not current_file(evidence):
            raise ValueError(
                "The cited passage must be present in unchanged manuscript evidence."
            )

    def apply(data):
        bound = context(data, kind, target)
        row = {
            "kind": kind,
            "target": target,
            "reviewer": reviewer,
            "reason": reason,
            "decision": decision,
            "checks": checks,
            "context_identity": fingerprint(bound),
            "manuscript": evidence,
            "quote": quote if evidence else None,
            "at": utc_now(),
            "author_approval": False,
        }
        row["identity"] = fingerprint(content_identity(row))
        data.setdefault("human_check_reviews", []).append(row)

    return update_project(workspace, apply)


def review_status(data, kind, target, manuscript_text=None):
    reviews = [
        r
        for r in data.get("human_check_reviews", [])
        if r["kind"] == kind and r["target"] == target
    ]
    if not reviews:
        return "needs_review"
    row = reviews[-1]
    try:
        if row["context_identity"] != fingerprint(context(data, kind, target)):
            return "stale"
        if row["identity"] != fingerprint(
            content_identity({k: v for k, v in row.items() if k != "identity"})
        ):
            return "stale"
        evidence = row.get("manuscript")
        if evidence and (
            not current_file(evidence)
            or (manuscript_text is not None and row["quote"] not in manuscript_text)
        ):
            return "stale"
        if (
            row["decision"] == "accepted"
            and set(row["checks"]) == CHECKS[kind]
            and all(v is True for v in row["checks"].values())
            and row.get("reviewer")
            and row.get("reason")
        ):
            return "accepted"
        return "unresolved"
    except (OSError, ValueError, KeyError, TypeError):
        return "stale"


def source_incomplete(data, source):
    if source["status"] == "read":
        return False
    if source["status"] != "partial":
        return source["status"] == "unreadable"
    warnings = source.get("warnings", [])
    return not (
        warnings
        and set(warnings) == {"legacy_workbook_visual_review_required"}
        and current_file(source)
        and review_status(data, "workbook_visual", source["sha256"]) == "accepted"
    )
