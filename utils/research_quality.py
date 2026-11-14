"""Deterministic research checks. Findings require interpretation, never silent repair."""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def numeric_audit(text, *, denominator=None, facts=None):
    """Check count/percentage pairs and exact quotes linked to approved aggregate facts.

    A supplied denominator is a hypothesis for screening, not evidence of the true N.
    Facts use id, approved_by, source, value, unit, optional ci and occurrences (quote,
    value, unit, ci). Occurrences must be verbatim and are never inferred by a model.
    """
    findings, checked = [], 0
    if denominator is not None:
        if (
            isinstance(denominator, bool)
            or int(denominator) != denominator
            or denominator <= 0
        ):
            raise ValueError("Denominator must be a positive integer.")
        for match in re.finditer(r"\b(\d+)\s*\((\d+(?:\.\d+)?)\s*%\)", text):
            count, percentage = int(match[1]), Decimal(match[2])
            expected = Decimal(count) * 100 / Decimal(denominator)
            tolerance = Decimal(5) * (
                Decimal(10) ** (-len(match[2].partition(".")[2]) - 1)
            )
            checked += 1
            if count > denominator or abs(percentage - expected) > tolerance:
                findings.append(
                    dict(
                        kind="count_percentage_conflict",
                        quote=match[0],
                        offset=match.start(),
                        denominator_hypothesis=denominator,
                        expected_percent=str(expected.quantize(Decimal(".01"))),
                    )
                )
    for fact in facts or []:
        if not fact.get("approved_by") or not fact.get("source"):
            findings.append(dict(kind="unapproved_fact", fact_id=fact.get("id")))
            continue
        occurrences = fact.get("occurrences", [])
        if not occurrences:
            findings.append(dict(kind="fact_not_mapped", fact_id=fact.get("id")))
        for occurrence in occurrences:
            checked += 1
            quote = occurrence.get("quote", "")
            if not quote or quote not in text:
                findings.append(
                    dict(kind="stale_occurrence", fact_id=fact.get("id"), quote=quote)
                )
                continue
            for field in ("value", "unit", "ci"):
                if field in fact and fact[field] != occurrence.get(field):
                    findings.append(
                        dict(
                            kind=field + "_conflict",
                            fact_id=fact.get("id"),
                            quote=quote,
                            expected=fact[field],
                            observed=occurrence.get(field),
                        )
                    )
    return dict(
        status="needs_review" if findings else "no_conflicts_in_checked_items" if checked else "not_checked",
        checked_items=checked,
        findings=findings,
        scope="Count/percentage pairs and explicitly mapped facts only; unrecognised prose is not certified.",
    )


def aggregate_constraints(facts):
    """Check approved aggregate relationships without accepting patient rows."""
    findings = []
    by_id = {f["id"]: f for f in facts}
    if len(by_id) != len(facts):
        raise ValueError("Fact IDs must be unique.")
    for fact in facts:
        try:
            value = Decimal(str(fact["value"]))
            if not value.is_finite():
                raise ValueError("Values must be finite.")
            parent = fact.get("subset_of")
            if parent and value > Decimal(str(by_id[parent]["value"])):
                findings.append(
                    dict(
                        kind="subset_exceeds_parent", fact_id=fact["id"], parent=parent
                    )
                )
            parts = fact.get("sum_of")
            if parts and value != sum(Decimal(str(by_id[p]["value"])) for p in parts):
                findings.append(
                    dict(kind="sum_conflict", fact_id=fact["id"], parts=parts)
                )
            ci = fact.get("ci")
            if ci and not Decimal(str(ci[0])) <= value <= Decimal(str(ci[1])):
                findings.append(dict(kind="invalid_interval", fact_id=fact["id"]))
        except (KeyError, InvalidOperation, TypeError, IndexError) as exc:
            raise ValueError("Invalid aggregate fact or reference.") from exc
    return findings


def assess_claims(claims, references):
    """Score explicitly linked claims; existence and lexical overlap are not entailment."""
    findings = []
    for claim in claims:
        links = claim.get("references", [])
        if not links:
            findings.append(dict(kind="unsupported_claim", claim_id=claim["id"]))
        for key in links:
            ref = references.get(key)
            if ref is None:
                findings.append(
                    dict(kind="unknown_reference", claim_id=claim["id"], reference=key)
                )
            elif ref.get("status") in {"retracted", "withdrawn"}:
                findings.append(
                    dict(kind="retracted_evidence", claim_id=claim["id"], reference=key)
                )
            elif not ref.get("passage"):
                findings.append(
                    dict(kind="missing_passage", claim_id=claim["id"], reference=key)
                )
    return findings
