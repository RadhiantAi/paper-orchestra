"""Explicit calculation fields bound to manuscript occurrences and technical review."""

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
import math
import re
from pathlib import Path
from utils.project_store import update_project, require_text, upsert
from utils.research_quality import fingerprint
from utils.analysis_recipes import verify_calculation

TOKEN = re.compile(r"\{\{continuous:([\w.-]+):value\}\}")


def selected_value(calculation, selector):
    if calculation.get("method") != "continuous_measurements":
        raise ValueError("Select a continuous-measurement calculation.")
    result = json.loads(Path(calculation["output"]["path"]).read_text(encoding="utf-8"))
    kind, field = selector.get("kind"), selector.get("field")
    if set(selector) - {
        "kind",
        "group",
        "variable",
        "outcome",
        "predictors",
        "field",
        "coefficient",
    }:
        raise ValueError("Unknown continuous result selector fields.")
    if "group" not in selector:
        raise ValueError("Select a literal group code or null for the pooled analysis.")
    units = calculation["recipe"]["units"]
    if kind == "summary":
        if field not in {
            "mean",
            "sd",
            "min",
            "max",
            "ci",
            "available",
            "missing",
            "total",
        }:
            raise ValueError("Unsupported summary field.")
        matches = [
            r
            for r in result["results"]
            if r["group"] == selector["group"]
            and r["variable"] == selector.get("variable")
        ]
        unit = (
            "records"
            if field in {"available", "missing", "total"}
            else units.get(selector.get("variable"))
        )
    elif kind == "model":
        if field not in {
            "coefficients",
            "coefficient_ci",
            "r_squared",
            "loo_rmse",
            "mean_only_loo_rmse",
            "complete_cases",
            "excluded_missing",
        }:
            raise ValueError("Unsupported model field.")
        matches = [
            r
            for r in result["models"]
            if r["group"] == selector["group"]
            and r["outcome"] == selector.get("outcome")
            and r["predictors"] == selector.get("predictors")
        ]
        unit = (
            "records"
            if field in {"complete_cases", "excluded_missing"}
            else "unitless"
            if field == "r_squared"
            else units.get(selector.get("outcome"))
        )
    else:
        raise ValueError("Select a summary or model field.")
    if len(matches) != 1:
        raise ValueError("Selector must identify exactly one calculation row.")
    row = matches[0]
    value = row.get(field)
    if field in {"coefficients", "coefficient_ci"}:
        coefficient = selector.get("coefficient")
        order = row.get("coefficient_order", [])
        if coefficient not in order or value is None:
            raise ValueError("Coefficient or its interval is not estimable.")
        value = (
            value[coefficient]
            if field == "coefficients"
            else value[order.index(coefficient)]
        )
        if coefficient != "intercept":
            unit = f"{unit}/{units[coefficient]}"
    values = value if isinstance(value, list) else [value]
    if (isinstance(value, list) and len(value) != 2) or any(
        type(v) not in {int, float} or not math.isfinite(v) for v in values
    ):
        raise ValueError(
            "Only finite scalar values or two-bound intervals can be linked."
        )
    if isinstance(value, list) and value[0] > value[1]:
        raise ValueError("Interval bounds are reversed.")
    return value, unit


def register_continuous(
    workspace, result_id, calculation_id, selector, label, definition, precision=2
):
    require_text(
        {"id": result_id, "label": label, "definition": definition},
        "id",
        "label",
        "definition",
    )
    if (
        not re.fullmatch(r"[\w.-]+", result_id)
        or type(precision) is not int
        or not 0 <= precision <= 8
    ):
        raise ValueError("Use a simple result ID and zero to eight decimal places.")

    def apply(data):
        calc = next(c for c in data["calculations"] if c["id"] == calculation_id)
        if not verify_calculation(calc):
            raise ValueError(
                "Calculation must be reproduced before registering a result."
            )
        value, unit = selected_value(calc, selector)
        row = {
            "id": result_id,
            "calculation_id": calculation_id,
            "selector": deepcopy(selector),
            "label": label,
            "definition": definition,
            "precision": precision,
            "value": value,
            "unit": unit,
            "calculation_output_sha256": calc["output_sha256"],
            "author_approval": False,
        }
        upsert(data.setdefault("continuous_results", []), row)

    return update_project(workspace, apply)


def result_identity(row):
    return fingerprint({k: v for k, v in row.items() if k != "technical_review"})


def resolve_continuous(data, require_review=True):
    calculations = {c["id"]: c for c in data["calculations"]}
    verified, output = {}, {}
    for row in data.get("continuous_results", []):
        cid = row["calculation_id"]
        calc = calculations.get(cid)
        if cid not in verified:
            verified[cid] = bool(calc and verify_calculation(calc))
        if (
            not verified[cid]
            or row["calculation_output_sha256"] != calc["output_sha256"]
        ):
            raise ValueError("Continuous result calculation is stale: " + row["id"])
        value, unit = selected_value(calc, row["selector"])
        if value != row["value"] or unit != row["unit"]:
            raise ValueError(
                "Continuous result differs from its calculation: " + row["id"]
            )
        review = row.get("technical_review", {})
        if require_review and (
            not review.get("reviewer")
            or not review.get("reason")
            or review.get("identity") != result_identity(row)
        ):
            raise ValueError("Continuous result needs technical review: " + row["id"])
        if row["id"] in output:
            raise ValueError("Duplicate continuous result ID.")
        precision = row["precision"]
        if type(precision) is not int or not 0 <= precision <= 8:
            raise ValueError("Invalid result precision.")

        def number(v):
            rounded = Decimal(str(v)).quantize(
                Decimal(1).scaleb(-precision), rounding=ROUND_HALF_UP
            )
            return format(abs(rounded) if rounded == 0 else rounded, "f")

        output[row["id"]] = (
            " to ".join(number(v) for v in value)
            if isinstance(value, list)
            else number(value)
        )
    return output


def review_continuous(workspace, ids, reviewer, reason):
    require_text({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")

    def apply(data):
        resolve_continuous(data, require_review=False)
        rows = [r for r in data.get("continuous_results", []) if r["id"] in ids]
        if not ids or {r["id"] for r in rows} != set(ids):
            raise ValueError("Select known continuous results.")
        for row in rows:
            row["technical_review"] = {
                "reviewer": reviewer,
                "reason": reason,
                "identity": result_identity(row),
                "author_approval": False,
            }

    return update_project(workspace, apply)


def render_continuous(template, values):
    def replace(match):
        if match[1] not in values:
            raise ValueError("Unknown continuous result placeholder.")
        return values[match[1]]

    rendered = TOKEN.sub(replace, template)
    if "{{continuous:" in rendered:
        raise ValueError("Unrecognised continuous placeholder.")
    return rendered


def audit_continuous(data, documents, mappings):
    findings, checked = [], 0
    try:
        values = resolve_continuous(data)
    except (ValueError, KeyError, OSError, StopIteration) as exc:
        return {
            "status": "failed",
            "findings": [
                {"kind": "continuous_result_stale_or_unreviewed", "reason": str(exc)}
            ],
        }
    mapped = set()
    for mapping in mappings:
        rid, template = mapping.get("id"), mapping.get("template", "")
        document = mapping.get("document", "manuscript")
        count = mapping.get("occurrences", 1)
        if (
            rid not in values
            or set(TOKEN.findall(template)) != {rid}
            or type(count) is not int
            or count < 1
        ):
            raise ValueError(
                "Continuous mappings need a registered ID, its placeholder and a positive occurrence count."
            )
        expected = render_continuous(template, values)
        pattern = (
            (r"(?<![\d.])" if expected[:1] in "-+0123456789" else "")
            + re.escape(expected)
            + (r"(?![\d.])" if expected[-1:] in "0123456789" else "")
        )
        if (
            document not in documents
            or len(re.findall(pattern, documents[document])) != count
        ):
            findings.append(
                {
                    "kind": "continuous_result_occurrence_mismatch",
                    "id": rid,
                    "document": document,
                    "expected": expected,
                }
            )
        mapped.add(rid)
        checked += 1
    findings.extend(
        {"kind": "continuous_result_unmapped", "id": rid}
        for rid in values.keys() - mapped
    )
    return {
        "status": "failed" if findings else "checked" if checked else "not_checked",
        "checked": checked,
        "findings": findings,
        "scope": "Explicit scalar/interval occurrences only; unrelated numbers and scientific interpretation remain outside this check.",
    }
