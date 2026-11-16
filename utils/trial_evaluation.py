"""Prespecified blind protocols, sealed candidate packs and explicit unblinding."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile

from utils.project_store import (
    load_project,
    update_project,
    file_receipt,
    current_file,
    private_path,
    require_text,
)
from utils.research_quality import fingerprint
from utils.literature_sources import utc_now
from utils.run_control import write_json


def strict_unexposed(data):
    if not data.get("strict_trial", {}).get("enabled") or data["strict_trial"].get(
        "unblinded_at"
    ):
        raise ValueError("A strict project with no recorded unblinding is required.")


def freeze_protocol(workspace, protocol, reviewer, reason):
    require_text(
        protocol, "question", "analysis_plan", "success_criteria", "exposure_statement"
    )
    require_text({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")
    recipes = protocol.get("recipes", [])
    if not isinstance(recipes, list) or any(
        not isinstance(r, dict) or not r.get("name") for r in recipes
    ):
        raise ValueError(
            "Supply the exact planned local recipes, or an empty list for descriptive/manual analysis."
        )
    if set(protocol) != {
        "question",
        "analysis_plan",
        "success_criteria",
        "exposure_statement",
        "recipes",
    }:
        raise ValueError("Unknown or missing protocol fields.")

    def apply(data):
        strict_unexposed(data)
        if (
            data.get("trial_protocol")
            or data.get("calculations")
            or data.get("results")
            or data.get("continuous_results")
        ):
            raise ValueError(
                "Freeze one protocol before analysis. Amendments require a new trial project."
            )
        inputs = [
            a
            for a in data.get("source_allocations", [])
            if a["role"] == "trial_input"
            and not a["source"].get("origin", "").startswith("host-exchange:")
        ]
        refs = [
            a
            for a in data.get("source_allocations", [])
            if a["role"] == "withheld_reference"
        ]
        if not inputs or not refs:
            raise ValueError(
                "Allocate the trial inputs and at least one withheld reference first."
            )
        if any(
            a["source"].get("path") and not current_file(a["source"])
            for a in inputs + refs
        ):
            raise ValueError("Allocated inputs or withheld references changed.")
        row = {
            "protocol": deepcopy(protocol),
            "reviewer": reviewer,
            "reason": reason,
            "at": utc_now(),
            "inputs": [deepcopy(a["source"]) for a in inputs],
            "reference_hashes": sorted({a["source"]["sha256"] for a in refs}),
            "recipe_hashes": [fingerprint(r) for r in recipes],
        }
        row["identity"] = protocol_identity(row)
        data["trial_protocol"] = row

    return update_project(workspace, apply)


def protocol_identity(row):
    from utils.reviewer_checks import content_identity

    return fingerprint(
        content_identity({k: v for k, v in row.items() if k != "identity"})
    )


def validate_protocol(data):
    row = data.get("trial_protocol")
    if not row or row.get("identity") != protocol_identity(row):
        raise ValueError("Trial protocol is missing or changed.")
    if any(r.get("path") and not current_file(r) for r in row["inputs"]):
        raise ValueError("Prespecified trial input changed.")
    return row


def check_recipe(data, recipe):
    if data.get("trial_protocol"):
        protocol = validate_protocol(data)
        if fingerprint(recipe) not in protocol["recipe_hashes"]:
            raise ValueError(
                "This analysis was not prespecified in the frozen trial protocol."
            )


def register_draft(workspace, path, reviewer, reason):
    """Record an operator-produced draft without pretending its provenance is independently proved."""
    require_text({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")
    receipt = file_receipt(path)

    def apply(data):
        protocol = validate_protocol(data)
        strict_unexposed(data)
        if receipt["sha256"] in protocol["reference_hashes"] or not current_file(
            receipt
        ):
            raise ValueError(
                "A withheld reference or changed file cannot be declared a candidate draft."
            )
        from utils.strict_trial import register_derived

        register_derived(data, [path], "operator_declared_trial_draft")
        data["events"].append(
            {
                "kind": "trial_draft_declaration",
                "file": receipt,
                "reviewer": reviewer,
                "reason": reason,
                "at": utc_now(),
                "scope": "Operator attestation; external exposure is not independently verified.",
            }
        )

    return update_project(workspace, apply)


def freeze_candidate(workspace, directory, reviewer, reason):
    from utils.project_pack import release_pack, check_pack

    require_text({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")
    data = load_project(workspace)
    strict_unexposed(data)
    protocol = validate_protocol(data)
    if data.get("trial_freeze"):
        raise ValueError(
            "A candidate is already frozen. Start a new trial for another attempt."
        )
    directory = Path(directory)
    report = check_pack(workspace, directory)
    output = private_path(workspace) / "sealed-trial"
    if output.exists():
        raise ValueError(
            "A previous sealing attempt exists; preserve it and use a new trial."
        )
    output.mkdir()
    release_pack(workspace, directory, output / "candidate.zip")
    spec = json.loads((directory / "pack_spec.json").read_text(encoding="utf-8"))
    manuscript = next(f for f in spec["files"] if f["role"] == "manuscript")
    shutil.copyfile(directory / manuscript["name"], output / "candidate.docx")
    with zipfile.ZipFile(output / "candidate.zip") as archive:
        sealed_bytes = archive.read(manuscript["name"])
    if (
        hashlib.sha256(sealed_bytes).hexdigest() != report["files"][manuscript["name"]]
        or sealed_bytes != (output / "candidate.docx").read_bytes()
    ):
        raise ValueError(
            "Candidate changed while sealing; the preserved attempt cannot be promoted."
        )
    write_json(output / "project-at-freeze.json", data)
    write_json(output / "checks-at-freeze.json", report)
    row = {
        "zip": file_receipt(output / "candidate.zip"),
        "manuscript": file_receipt(output / "candidate.docx"),
        "project": file_receipt(output / "project-at-freeze.json"),
        "checks": file_receipt(output / "checks-at-freeze.json"),
        "protocol_identity": protocol["identity"],
        "reviewer": reviewer,
        "reason": reason,
        "at": utc_now(),
        "pending_checks": report["pending"],
        "author_approval": False,
    }
    row["identity"] = freeze_identity(row)

    def apply(current):
        if fingerprint(current) != fingerprint(data):
            raise ValueError(
                "Project changed while sealing. Candidate cannot be promoted."
            )
        current["trial_freeze"] = row

    update_project(workspace, apply)
    return row


def freeze_identity(row):
    from utils.reviewer_checks import content_identity

    return fingerprint(
        content_identity({k: v for k, v in row.items() if k != "identity"})
    )


def validate_freeze(data):
    protocol = validate_protocol(data)
    row = data.get("trial_freeze")
    if (
        not row
        or row.get("identity") != freeze_identity(row)
        or row.get("protocol_identity") != protocol["identity"]
    ):
        raise ValueError("Candidate freeze is missing or changed.")
    if not all(
        current_file(row[k]) for k in ["zip", "manuscript", "project", "checks"]
    ):
        raise ValueError("Frozen candidate evidence changed or disappeared.")
    return row


def unblind(workspace, reference_hashes, reviewer, reason):
    require_text({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")

    def apply(data):
        validate_freeze(data)
        if data.get("trial_unblinding"):
            raise ValueError("Unblinding is already recorded.")
        hashes = set(reference_hashes)
        if not hashes or not hashes.issubset(
            data["trial_protocol"]["reference_hashes"]
        ):
            raise ValueError("Select only references withheld in the frozen protocol.")
        for sha in hashes:
            allocations = [
                a
                for a in data.get("source_allocations", [])
                if a["source"]["sha256"] == sha
            ]
            if not allocations or any(
                a["role"] != "withheld_reference"
                or (a["source"].get("path") and not current_file(a["source"]))
                for a in allocations
            ):
                raise ValueError(
                    "A withheld reference changed or its allocation is invalid."
                )
        data["trial_unblinding"] = {
            "reference_hashes": sorted(hashes),
            "reviewer": reviewer,
            "reason": reason,
            "at": utc_now(),
            "freeze_identity": data["trial_freeze"]["identity"],
        }
        data["strict_trial"]["unblinded_at"] = data["trial_unblinding"]["at"]

    return update_project(workspace, apply, trial_operation="unblind")


def compare_reference(workspace, reference, output):
    from utils.project_pack import doc_text
    from utils.figure_presence import image_occurrences

    data = load_project(workspace)
    frozen = validate_freeze(data)
    receipt = file_receipt(reference)
    reveal = data.get("trial_unblinding", {})
    if reveal.get("freeze_identity") != frozen["identity"] or receipt[
        "sha256"
    ] not in reveal.get("reference_hashes", []):
        raise ValueError(
            "Explicitly unblind this reference after freezing the candidate."
        )
    reference = Path(reference)
    if reference.suffix.lower() not in {".docx", ".pdf", ".md", ".txt"}:
        raise ValueError("Compare a Word, PDF or text reference.")
    candidate = Path(frozen["manuscript"]["path"])

    def comparison_text(path):
        if path.suffix.lower() != ".docx":
            return doc_text(path), 0
        # python-docx paragraph.text can omit inserted runs. Compare the current
        # visible view, but retain the fact that changes have not been approved.
        from utils.project_sources import package, XML, W, NS
        from lxml import etree

        with package(path) as archive:
            root = etree.fromstring(archive.read("word/document.xml"), XML)
        paragraphs = [
            "".join(p.xpath(".//w:t[not(ancestor::w:del)]/text()", namespaces=NS))
            for p in root.iter(W + "p")
        ]
        return "\n".join(paragraphs), len(
            root.xpath("//w:ins | //w:del", namespaces=NS)
        )

    left, left_edits = comparison_text(candidate)
    right, right_edits = comparison_text(reference)
    number = r"(?<![\w.])-?\d+(?:\.\d+)?%?(?![\w.])"
    left_numbers, right_numbers = (
        set(re.findall(number, left)),
        set(re.findall(number, right)),
    )
    left_paragraphs = {
        re.sub(r"\s+", " ", p).strip() for p in left.splitlines() if p.strip()
    }
    missing = [
        p
        for p in right.splitlines()
        if p.strip() and re.sub(r"\s+", " ", p).strip() not in left_paragraphs
    ]

    def images(path):
        if path.suffix.lower() not in {".docx", ".pdf"}:
            return set()
        return {hashlib.sha256(blob).hexdigest() for blob, _ in image_occurrences(path)}

    a, b = images(candidate), images(reference)
    report = {
        "schema": 1,
        "status": "needs_human_review",
        "candidate": frozen["manuscript"],
        "reference": receipt,
        "freeze_identity": frozen["identity"],
        "protocol_identity": frozen["protocol_identity"],
        "tracked_changes": {
            "candidate": left_edits,
            "reference": right_edits,
            "view": "Inserted text included; deleted text excluded. This does not accept or approve changes.",
        },
        "numeric_candidates": {
            "only_in_candidate": sorted(left_numbers - right_numbers),
            "only_in_reference": sorted(right_numbers - left_numbers),
        },
        "reference_passages_not_exactly_matched": missing,
        "figures": {
            "candidate_unique": len(a),
            "reference_unique": len(b),
            "exact_matches": len(a & b),
        },
        "unsupported_claims": {
            "status": "not_automatically_assessed",
            "instruction": "Trace candidate claims to admitted source evidence; disagreement with the reference is not proof of error.",
        },
        "scope": "Literal comparison only. Number tokens include dates, citations and counts. Paraphrases, figure conversion and scientific validity require review.",
        "at": utc_now(),
    }
    if not current_file(receipt) or not current_file(frozen["manuscript"]):
        raise ValueError("Comparison files changed while being read.")
    out = private_path(output)
    if out.exists():
        raise ValueError("Never overwrite a trial comparison.")
    write_json(out, report)

    def record(current):
        if fingerprint(current) != fingerprint(data) or not current_file(receipt):
            raise ValueError("Trial or reference changed during comparison.")
        validate_freeze(current)
        current.setdefault("trial_comparisons", []).append(file_receipt(out))

    update_project(workspace, record, trial_operation="compare")
    return report
