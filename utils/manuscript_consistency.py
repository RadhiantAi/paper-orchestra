"""Deterministic review clues and explicit claim-to-result checks, entirely local."""

from copy import deepcopy
from fractions import Fraction
import re

from utils.project_store import (
    update_project,
    require_text,
    upsert,
    unique,
)
from utils.project_results import approved, value_identity
from utils.project_review import evidence_valid
from utils.project_figures import figure_identity
from utils.research_quality import fingerprint

RISK_WORDS = re.compile(
    r"\b(highest|lowest|best|superior|validat\w*|proven|effectiveness)\b", re.I
)
MARKERS = re.compile(
    r"\b(red|green|black|white|blue|yellow)\s+(asterisks?|arrows?|circles?|stars?)\b",
    re.I,
)


def markers(text):
    return sorted(
        {
            colour.lower() + " " + shape.lower().rstrip("s")
            for colour, shape in MARKERS.findall(text)
        }
    )


def validate_claim(row):
    require_text(row, "id", "quote", "kind")
    if row["kind"] == "ranking":
        ids = row.get("result_ids", [])
        if (
            not isinstance(ids, list)
            or len(ids) < 2
            or len(set(ids)) != len(ids)
            or row.get("result_id") not in ids
            or row.get("direction") not in {"highest", "lowest"}
        ):
            raise ValueError(
                "Rankings need at least two distinct results, a target and highest/lowest direction."
            )
    elif row["kind"] == "outcome":
        if row.get("classification") not in {"measured", "proposed"}:
            raise ValueError("Classify an outcome as measured or proposed.")
        if row["classification"] == "proposed":
            require_text(row, "qualification")
            if row["qualification"] not in row["quote"]:
                raise ValueError("The qualification must appear in the quoted claim.")
        elif not row.get("evidence"):
            raise ValueError("A measured outcome needs exact source evidence.")
    else:
        raise ValueError("Unknown claim kind.")


def save_claim(workspace, row):
    row = deepcopy(row)
    row.pop("review", None)
    validate_claim(row)

    def apply(data):
        ids = {r["id"] for r in data["results"]}
        if set(row.get("result_ids", [])) - ids:
            raise ValueError("Claim refers to unknown results.")
        if row.get("evidence") and not evidence_valid(row["evidence"], data["sources"]):
            raise ValueError("Claim evidence must cite current source text.")
        upsert(data.setdefault("claims", []), row)

    return update_project(workspace, apply)


def audit_consistency(data, manuscript):
    findings, checked = [], 0
    by_id = {r["id"]: r for r in data["results"]}
    claims = data.get("claims", [])
    unique(claims)

    def add(kind, quote, subject="", severity="review", **extra):
        row = {
            "kind": kind,
            "quote": quote,
            "subject": subject,
            "severity": severity,
            **extra,
        }
        row["id"] = fingerprint(row)
        findings.append(row)

    for claim in claims:
        validate_claim(claim)
        quote, cid = claim["quote"], claim["id"]
        if manuscript.count(quote) != 1:
            add("claim_anchor_missing_or_ambiguous", quote, cid)
            continue
        checked += 1
        if claim["kind"] == "ranking":
            rows = [by_id.get(i) for i in claim["result_ids"]]
            if any(r is None or not approved(r) for r in rows):
                add("ranking_result_unapproved_or_stale", quote, cid, "error")
                continue
            if len({r.get("metric", r["definition"]) for r in rows}) != 1:
                add("ranking_metrics_not_comparable", quote, cid)
                continue
            values = {r["id"]: Fraction(r["count"], r["denominator"]) for r in rows}
            extreme = (max if claim["direction"] == "highest" else min)(values.values())
            if values[claim["result_id"]] != extreme:
                add(
                    "ranking_contradicts_results",
                    quote,
                    cid,
                    "error",
                    leaders=[k for k, v in values.items() if v == extreme],
                )
            elif sum(v == extreme for v in values.values()) > 1:
                add("ranking_tie_needs_qualification", quote, cid)
            if any(r.get("participants") == 1 for r in rows):
                add("single_participant_group_ranking", quote, cid)
            if any(r.get("participants") is None for r in rows):
                add("ranking_participant_counts_unknown", quote, cid)
        elif claim["classification"] == "measured":
            if not evidence_valid(claim["evidence"], data["sources"]):
                add("outcome_evidence_missing_or_stale", quote, cid, "error")
            add("measured_outcome_interpretation_review", quote, cid)
    # Candidate detection is deliberately not a claim that all scientific assertions were checked.
    for paragraph in manuscript.splitlines():
        if RISK_WORDS.search(paragraph) and not any(
            c["quote"] == paragraph.strip() for c in claims
        ):
            add("unmapped_interpretive_claim", paragraph.strip())
    for fig in data["figures"]:
        expected = set(markers(fig["caption"]))
        recovered = set(markers(" ".join(p["source_label"] for p in fig["panels"])))
        if expected or recovered:
            checked += 1
            if expected != recovered:
                add(
                    "figure_marker_label_mismatch",
                    fig["caption"],
                    fig["id"],
                    expected=sorted(expected),
                    recovered=sorted(recovered),
                )
    # Bind acknowledgements to complete checked wording and evidence, not only the warning label.
    context = fingerprint(
        [
            manuscript,
            [value_identity(r) for r in data["results"]],
            [figure_identity(f) for f in data["figures"]],
            [(s["id"], s["sha256"]) for s in data["sources"]],
            claims,
        ]
    )
    reviews = data.get("consistency_reviews", [])
    for row in findings:
        row["identity"] = fingerprint([context, row["id"]])
        row["reviewed"] = row["severity"] != "error" and any(
            r.get("identity") == row["identity"]
            and r.get("reviewer")
            and r.get("reason")
            for r in reviews
        )
    pending = [r for r in findings if not r["reviewed"]]
    return {
        "status": "needs_review"
        if pending
        else "checked"
        if checked or findings
        else "not_checked",
        "checked": checked,
        "findings": pending,
        "reviewed_findings": [r for r in findings if r["reviewed"]],
        "scope": "Explicit rankings and outcome mappings, selected risk words and recovered colour/shape labels only. No clinical approval, image interpretation or exhaustive semantic check.",
    }


def review_finding(workspace, manuscript, finding_id, reviewer, reason):
    require_text({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")

    def apply(data):
        report = audit_consistency(data, manuscript)
        row = next(r for r in report["findings"] if r["id"] == finding_id)
        if row["severity"] == "error":
            raise ValueError(
                "Correct contradictory or stale results/evidence before continuing."
            )
        data.setdefault("consistency_reviews", []).append(
            {"identity": row["identity"], "reviewer": reviewer, "reason": reason}
        )

    return update_project(workspace, apply)
