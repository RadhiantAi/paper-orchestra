"""Offline research-quality harness; accepts candidate outputs from any model/host."""

import argparse
import json
from pathlib import Path

from utils.research_quality import assess_claims, numeric_audit


def evaluate(case, candidate):
    required = set(case["required_evidence"])
    retrieved = set(candidate.get("retrieved_evidence", []))
    numeric = numeric_audit(candidate["text"], denominator=case["denominator"])
    evidence = assess_claims(candidate["claims"], case["references"])
    expected = set(case.get("expected_claims", []))
    actual = {c["id"] for c in candidate["claims"]}
    return {
        "missed_evidence": sorted(required - retrieved),
        "evidence_recall": len(required & retrieved) / len(required) if required else 1,
        "invented_claims": sorted(actual - expected),
        "numerical_errors": len(numeric["findings"]),
        "unsafe_or_missing_evidence": evidence,
        "passes": not (
            required - retrieved or actual - expected or numeric["findings"] or evidence
        ),
    }


def run_suite(path, candidates=None):
    cases = json.loads(Path(path).read_text(encoding="utf-8"))
    results = []
    for case in cases:
        before = evaluate(case, (candidates or {}).get(case["id"], case["flawed"]))
        after = evaluate(case, case["corrected"])
        results.append(
            {
                "id": case["id"],
                "before": before,
                "after": after,
                "correction_success": not before["passes"] and after["passes"],
            }
        )
    return {
        "scope": "Deterministic synthetic acceptance checks; this does not measure live model performance.",
        "cases": results,
        "passed": all(
            r["after"]["passes"]
            and (
                r["before"]["passes"]
                if candidates is not None
                else not r["before"]["passes"]
            )
            for r in results
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite", default=str(Path(__file__).parent / "benchmarks/synthetic.json")
    )
    parser.add_argument(
        "--candidates",
        help="Optional JSON mapping case IDs to externally generated candidate outputs.",
    )
    parser.add_argument("--output")
    args = parser.parse_args()
    candidates = (
        json.loads(Path(args.candidates).read_text(encoding="utf-8"))
        if args.candidates
        else None
    )
    result = run_suite(args.suite, candidates)
    payload = json.dumps(result, indent=2)
    if args.output:
        Path(args.output).write_text(payload, encoding="utf-8")
    print(payload)
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
