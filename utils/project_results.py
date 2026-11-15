"""Approved aggregate results drive prose, tables and deterministic plots."""

import csv
from decimal import Decimal, ROUND_HALF_UP
import json
import re

from utils.project_store import require_text, unique, private_path
from utils.research_quality import fingerprint


def value_identity(r):
    return fingerprint({k: v for k, v in r.items() if k != "approval"})


def validate_result(r):
    require_text(r, "id", "label", "definition", "source", "method")
    if any(
        isinstance(r.get(k), bool) or not isinstance(r.get(k), int)
        for k in ["count", "denominator"]
    ):
        raise ValueError("Counts and denominators must be integers.")
    if not 0 <= r["count"] <= r["denominator"] or r["denominator"] <= 0:
        raise ValueError("Invalid count or denominator.")
    precision = r.get("precision", 1)
    if type(precision) is not int or not 0 <= precision <= 4:
        raise ValueError("Precision must be between zero and four.")


def approved(r):
    validate_result(r)
    a = r.get("approval", {})
    return bool(
        a.get("reviewer") and a.get("reason") and a.get("identity") == value_identity(r)
    )


def approve_results(records, reviewer, reason):
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Named reviewer and approval reason required.")
    for r in records:
        validate_result(r)
        r["approval"] = {
            "identity": value_identity(r),
            "reviewer": reviewer,
            "reason": reason,
        }
    return records


def percentage(r):
    validate_result(r)
    return format(
        (Decimal(r["count"]) * 100 / r["denominator"]).quantize(
            Decimal(1).scaleb(-r.get("precision", 1)), rounding=ROUND_HALF_UP
        ),
        "f",
    )


def render_results(template, records):
    unique(records)
    by_id = {r["id"]: r for r in records}

    def replace(m):
        rid, field = m.groups()
        if rid not in by_id or not approved(by_id[rid]):
            raise ValueError("Unknown or unapproved result: " + rid)
        r = by_id[rid]
        return {
            "count": str(r["count"]),
            "denominator": str(r["denominator"]),
            "percent": percentage(r),
            "pair": f"{r['count']} ({percentage(r)}%)",
        }[field]

    result = re.sub(
        r"\{\{result:([\w.-]+):(count|denominator|percent|pair)\}\}", replace, template
    )
    if "{{result:" in result:
        raise ValueError("Unrecognised result placeholder.")
    return result


def audit_occurrences(text, records, mappings):
    findings, checked = [], 0
    by_id = {r["id"]: r for r in records}
    unique(records)
    for r in records:
        if not approved(r):
            findings.append({"id": r["id"], "kind": "unapproved_result"})
    for m in mappings:
        rid = m["id"]
        if rid not in by_id:
            raise ValueError("Unknown result mapping.")
        if not approved(by_id[rid]):
            continue
        expected = render_results(m["template"], [by_id[rid]])
        expected_count = m.get("occurrences", 1)
        if type(expected_count) is not int or expected_count < 1:
            raise ValueError("Occurrence count must be positive.")
        checked += 1
        if text.count(expected) != expected_count:
            findings.append(
                {"id": rid, "kind": "result_occurrence_mismatch", "expected": expected}
            )
    mapped = {m["id"] for m in mappings}
    findings += [
        {"id": r["id"], "kind": "unmapped_result"}
        for r in records
        if r["id"] not in mapped
    ]
    return {
        "status": "needs_review"
        if findings
        else "checked"
        if checked
        else "not_checked",
        "checked": checked,
        "findings": findings,
        "scope": "Explicit result mappings; unrelated or unmapped numbers are not certified.",
    }


def export_result_assets(records, destination):
    """Fixed reviewed plotting code, never generated Python."""
    unique(records)
    if not records or not all(approved(r) for r in records):
        raise ValueError("Only approved results may be exported.")
    dest = private_path(destination)
    if dest.exists():
        raise ValueError("Choose a new results export directory.")
    dest.mkdir(parents=True)
    rows = [
        {
            "id": r["id"],
            "label": r["label"],
            "count": r["count"],
            "denominator": r["denominator"],
            "percent": percentage(r),
            "definition": r["definition"],
        }
        for r in records
    ]
    with (dest / "results.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: "'" + v
                    if isinstance(v, str)
                    and v.lstrip().startswith(("=", "+", "-", "@"))
                    else v
                    for k, v in row.items()
                }
            )
    (dest / "results.md").write_text(
        "\n".join(
            f"{r['label']}: {r['count']}/{r['denominator']} ({percentage(r)}%)."
            for r in records
        ),
        encoding="utf-8",
    )
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(figsize=(8, max(3, len(records) * 0.5)))
    bars = ax.barh(
        [r["label"] for r in records], [float(percentage(r)) for r in records]
    )
    ax.set_xlim(0, 120)
    ax.set_xlabel("Percentage")
    ax.invert_yaxis()
    ax.bar_label(
        bars,
        labels=[f"{r['count']}/{r['denominator']} ({percentage(r)}%)" for r in records],
        padding=3,
    )
    fig.tight_layout()
    fig.savefig(dest / "results.png", dpi=200)
    fig.savefig(dest / "results.pdf")
    plt.close(fig)
    from utils.run_control import digest

    receipt = {
        "results_fingerprint": fingerprint(records),
        "files": {p.name: digest(p) for p in dest.iterdir()},
    }
    (dest / "results_receipt.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt
