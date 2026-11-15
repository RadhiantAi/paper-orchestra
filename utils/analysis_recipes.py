"""Fixed aggregate-data recipes. No generated code or automatic result approval."""

from pathlib import Path
import csv
import json
import math
from statistics import NormalDist
import numpy as np

from utils.project_store import (
    private_path,
    file_receipt,
    current_file,
    update_project,
)
from utils.research_quality import fingerprint
from utils.run_control import digest, write_json

VERSION = "2"


def recipe_code_hash():
    return fingerprint(
        [digest(__file__), digest(Path(__file__).with_name("design_recipes.py")),
         digest(Path(__file__).with_name("continuous_recipe.py"))]
    )


def _integer(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Counts must be non-negative integers.")
    n = int(value)
    if str(n) != str(value).strip() or n < 0:
        raise ValueError("Counts must be non-negative integers.")
    return n


def wilson(count, denominator, confidence=0.95):
    if not 0 <= count <= denominator or not 0 < denominator <= 10**8:
        raise ValueError("Invalid count or denominator.")
    z = NormalDist().inv_cdf((1 + confidence) / 2)
    p = count / denominator
    a = 1 + z * z / denominator
    centre = (p + z * z / (2 * denominator)) / a
    half = z * math.sqrt(p * (1 - p) / denominator + z * z / (4 * denominator**2)) / a
    return [max(0, centre - half), min(1, centre + half)]


def kappa(cells):
    a, b, c, d = cells
    n = sum(cells)
    if n <= 0:
        return None
    expected = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    return (float((a + d) / n) - expected) / (1 - expected) if expected < 1 else None


def calculate(recipe, rows):
    from utils.design_recipes import NAMES, calculate_design

    if recipe.get("name") == "continuous_measurements":
        from utils.continuous_recipe import calculate_continuous
        return calculate_continuous(recipe, rows)
    if recipe.get("name") in NAMES:
        return calculate_design(recipe, rows)
    if set(recipe) - {
        "name",
        "sampling_unit",
        "independent_units_confirmed",
        "confidence",
        "seed",
        "bootstrap_iterations",
    }:
        raise ValueError(
            "Unknown recipe options. Clustered analyses are not supported by these recipes."
        )
    if recipe.get("name") not in {"binary_proportion", "paired_binary_agreement"}:
        raise ValueError("Select a registered aggregate recipe.")
    if (
        recipe.get("independent_units_confirmed") is not True
        or not recipe.get("sampling_unit", "").strip()
    ):
        raise ValueError(
            "Confirm independent sampling units. Clustered data need a separate reviewed recipe."
        )
    confidence = recipe.get("confidence", 0.95)
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0.5 < confidence < 1
    ):
        raise ValueError("Confidence level must be between 0.5 and 1.")
    if not rows or len(rows) > 1000:
        raise ValueError("Supply between 1 and 1,000 aggregate rows.")
    seen = set()
    output = []
    seed = recipe.get("seed", 0)
    iterations = recipe.get("bootstrap_iterations", 2000)
    if type(seed) is not int or not 0 <= seed < 2**32:
        raise ValueError("Seed must be an unsigned 32-bit integer.")
    if type(iterations) is not int or not 100 <= iterations <= 20000:
        raise ValueError("Use 100 to 20,000 bootstrap iterations.")
    rng = np.random.default_rng(seed)
    for row in rows:
        allowed = (
            {"id", "label", "count", "denominator", "missing_count"}
            if recipe["name"] == "binary_proportion"
            else {"id", "label", "n00", "n01", "n10", "n11", "missing_count"}
        )
        if set(row) - allowed:
            raise ValueError(
                "Unexpected columns. These recipes accept aggregate counts only."
            )
        if not row.get("id") or not row.get("label") or row["id"] in seen:
            raise ValueError("Unique IDs and labels required.")
        seen.add(row["id"])
        result = {
            "id": row["id"],
            "label": row["label"],
            "missing_count": _integer(row.get("missing_count", "0")),
        }
        if recipe["name"] == "binary_proportion":
            n = _integer(row["denominator"])
            count = _integer(row["count"])
            result.update(
                count=count,
                denominator=n,
                proportion=count / n if n else None,
                ci=wilson(count, n, confidence),
                method="Wilson score interval",
            )
        else:
            cells = [_integer(row[k]) for k in ["n00", "n01", "n10", "n11"]]
            n = sum(cells)
            if n <= 0 or n > 10**8:
                raise ValueError("Invalid paired observation count.")
            point = kappa(cells)
            estimates = [
                kappa(x.tolist())
                for x in rng.multinomial(n, np.asarray(cells) / n, size=iterations)
            ]
            valid = [x for x in estimates if x is not None]
            ci = (
                np.quantile(
                    valid, [(1 - confidence) / 2, (1 + confidence) / 2]
                ).tolist()
                if len(valid) >= 0.95 * iterations
                else None
            )
            result.update(
                denominator=n,
                cells=cells,
                kappa=point,
                agreement=(cells[0] + cells[3]) / n,
                ci=ci,
                undefined_bootstrap_samples=iterations - len(valid),
                method="Unweighted Cohen kappa; percentile bootstrap of independent paired units",
            )
        output.append(result)
    return {
        "recipe_version": VERSION,
        "recipe": recipe,
        "numpy_version": np.__version__,
        "results": output,
        "warnings": [
            "undefined_or_unstable_agreement"
            for r in output
            if recipe["name"] == "paired_binary_agreement"
            and (r["kappa"] is None or r["ci"] is None)
        ],
        "scope": "Aggregate counts only. Missing observations are reported separately and excluded from observed denominators. No clustered inference.",
    }


def run_recipe(workspace, recipe, source, output, reviewer, reason):
    from utils.trial_evaluation import check_recipe
    from utils.project_store import load_project
    check_recipe(load_project(workspace), recipe)
    from utils.strict_trial import admit_file
    admit_file(workspace, source)
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Reviewer and reason required for a calculation run.")
    source = Path(source)
    if source.stat().st_size > 2 * 1024**2:
        raise ValueError("Analysis CSV exceeds 2 MB.")
    original = file_receipt(source)
    with source.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(
            reader.fieldnames
        ):
            raise ValueError("CSV columns must be named and unique.")
        rows = list(reader)
    result = calculate(recipe, rows)
    destination = private_path(output)
    if destination.exists():
        raise ValueError("Choose a new analysis folder.")
    destination.mkdir(parents=True)
    snapshot = destination / ("measurement-input.csv" if recipe["name"] == "continuous_measurements" else "aggregate-input.csv")
    snapshot.write_bytes(source.read_bytes())
    if digest(snapshot) != original["sha256"]:
        raise ValueError("Input changed during calculation.")
    write_json(destination / "analysis.json", result)
    record = {
        "id": fingerprint([recipe, original["sha256"]]),
        "kind": "local_recipe",
        "method": recipe["name"],
        "recipe": recipe,
        "recipe_version": VERSION,
        "numpy_version": np.__version__,
        "input": file_receipt(snapshot),
        "original_input": original,
        "output": file_receipt(destination / "analysis.json"),
        "code_sha256": recipe_code_hash(),
        "output_sha256": digest(destination / "analysis.json"),
        "reviewer": reviewer,
        "reason": reason,
    }
    write_json(destination / "analysis_receipt.json", record)

    def apply(data):
        data["calculations"] = [
            c for c in data["calculations"] if c["id"] != record["id"]
        ] + [record]

    update_project(workspace, apply)
    return record


def verify_calculation(record):
    if record.get("kind") != "local_recipe":
        return False
    if (
        record.get("code_sha256") != recipe_code_hash()
        or record.get("numpy_version") != np.__version__
    ):
        return False
    if not all(
        current_file(record.get(k, {})) for k in ["input", "original_input", "output"]
    ):
        return False
    try:
        with Path(record["input"]["path"]).open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        actual = json.loads(Path(record["output"]["path"]).read_text())
        return fingerprint(calculate(record["recipe"], rows)) == fingerprint(actual)
    except (ValueError, KeyError, OSError):
        return False


def calculated_result_current(result, calculation):
    if calculation is None or not verify_calculation(calculation):
        return False
    if result.get("calculation_output_sha256") != calculation.get("output_sha256"):
        return False
    output = json.loads(Path(calculation["output"]["path"]).read_text())
    row = next((r for r in output["results"] if r["id"] == result["id"]), None)
    return row is not None and all(
        result.get(k) == row.get(k) for k in ["count", "denominator"]
    )


def register_proportions(workspace, calculation_id, definition):
    if not definition.strip():
        raise ValueError("Provide a scientific definition before registering results.")

    def apply(data):
        calc = next(c for c in data["calculations"] if c["id"] == calculation_id)
        if not verify_calculation(calc) or calc["method"] != "binary_proportion":
            raise ValueError(
                "Only current proportion calculations can populate the count register."
            )
        output = json.loads(Path(calc["output"]["path"]).read_text())
        for r in output["results"]:
            if any(old["id"] == r["id"] for old in data["results"]):
                raise ValueError(
                    "Result ID already exists; preserve it or use a distinct ID."
                )
            data["results"].append(
                {k: r[k] for k in ["id", "label", "count", "denominator"]}
                | {
                    "definition": definition,
                    "source": calc["input"]["sha256"],
                    "method": r["method"],
                    "precision": 1,
                    "calculation_id": calc["id"],
                    "calculation_output_sha256": calc["output_sha256"],
                }
            )

    return update_project(workspace, apply)
