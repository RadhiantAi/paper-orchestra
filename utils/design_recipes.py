"""Reviewed study-design-specific estimators; bootstrap whole independent units."""

import numpy as np

NAMES = {"clustered_proportion", "clustered_binary_agreement", "multirater_fleiss"}


def fleiss(table):
    a = np.asarray(table, dtype=float)
    n = a.sum(axis=1)
    if a.ndim != 2 or np.any(n < 2) or np.any(n != n[0]):
        raise ValueError(
            "Fleiss kappa needs the same number of at least two ratings for every unit."
        )
    agreement = np.mean((np.square(a).sum(axis=1) - n) / (n * (n - 1)))
    expected = np.square(a.sum(axis=0) / a.sum()).sum()
    return float((agreement - expected) / (1 - expected)) if expected < 1 else None


def calculate_design(recipe, rows):
    from utils.analysis_recipes import _integer, kappa, VERSION

    name = recipe["name"]
    options = {
        "name",
        "sampling_unit",
        "confidence",
        "seed",
        "bootstrap_iterations",
    }
    options |= (
        {"independent_units_confirmed", "categories", "raters_design"}
        if name == "multirater_fleiss"
        else {"independent_clusters_confirmed"}
    )
    if name == "clustered_proportion":
        options.add("weighting")
    if set(recipe) - options:
        raise ValueError("Unknown design recipe options.")
    if not recipe.get("sampling_unit", "").strip():
        raise ValueError("Name the independent sampling unit.")
    if not 2 <= len(rows) <= 1000:
        raise ValueError("Use 2 to 1,000 independent units or clusters.")
    confidence = recipe.get("confidence", 0.95)
    seed = recipe.get("seed", 0)
    iterations = recipe.get("bootstrap_iterations", 2000)
    if type(confidence) not in {float, int} or not 0.5 < confidence < 1:
        raise ValueError("Invalid confidence level.")
    if (
        type(seed) is not int
        or not 0 <= seed < 2**32
        or type(iterations) is not int
        or not 100 <= iterations <= 20000
    ):
        raise ValueError("Invalid seed or bootstrap count.")
    cluster = name.startswith("clustered_")
    if cluster and recipe.get("independent_clusters_confirmed") is not True:
        raise ValueError("Confirm independence between whole clusters.")
    if not cluster and (
        recipe.get("independent_units_confirmed") is not True
        or recipe.get("raters_design") != "interchangeable"
    ):
        raise ValueError(
            "Fleiss requires independent units and explicitly interchangeable raters. Fixed-rater inference needs a different recipe."
        )
    categories = recipe.get("categories", 2)
    if not cluster and (type(categories) is not int or not 2 <= categories <= 20):
        raise ValueError("Use 2 to 20 categories.")
    columns = (
        ["count", "denominator"]
        if name == "clustered_proportion"
        else ["n00", "n01", "n10", "n11"]
        if cluster
        else ["n" + str(i) for i in range(categories)]
    )
    identifier = "cluster_id" if cluster else "unit_id"
    seen = set()
    values = []
    missing = 0
    for row in rows:
        if (
            set(row) - set(columns + [identifier, "missing_count"])
            or not row.get(identifier)
            or row[identifier] in seen
        ):
            raise ValueError(
                "Supply unique anonymous unit IDs and the exact recipe columns."
            )
        seen.add(row[identifier])
        numbers = [_integer(row[k]) for k in columns]
        missing += _integer(row.get("missing_count", "0"))
        if max(numbers, default=0) > 10**8:
            raise ValueError("Count exceeds the recipe budget.")
        if (
            name == "clustered_proportion"
            and not 0 <= numbers[0] <= numbers[1]
            or sum(numbers) == 0
        ):
            raise ValueError("Invalid or empty unit counts.")
        if name == "clustered_proportion" and numbers[1] == 0:
            raise ValueError("Each cluster needs observed units.")
        values.append(numbers)
    a = np.asarray(values, dtype=float)
    if name == "clustered_proportion":
        weighting = recipe.get("weighting")
        if weighting not in {"observation", "cluster_equal"}:
            raise ValueError(
                "Explicitly choose observation or equal-cluster weighting."
            )

        def estimate(x):
            return (
                float(x[:, 0].sum() / x[:, 1].sum())
                if weighting == "observation"
                else float(np.mean(x[:, 0] / x[:, 1]))
            )

        method = (
            "Whole-cluster percentile bootstrap; " + weighting + " weighted proportion"
        )
    elif name == "clustered_binary_agreement":

        def estimate(x):
            return kappa(x.sum(axis=0).tolist())

        method = "Unweighted Cohen kappa; whole-cluster percentile bootstrap"
    else:
        if (
            np.any(a.sum(axis=1) != a.sum(axis=1)[0])
            or np.any(a.sum(axis=1) < 2)
            or np.any(a.sum(axis=1) > 100)
        ):
            raise ValueError(
                "Use the same 2 to 100 complete ratings per independent unit."
            )
        estimate = fleiss
        method = "Fleiss kappa; independent-unit percentile bootstrap; interchangeable raters"
    point = estimate(a)
    rng = np.random.default_rng(seed)
    estimates = [
        estimate(a[rng.integers(0, len(a), size=len(a))]) for _ in range(iterations)
    ]
    valid = [x for x in estimates if x is not None and np.isfinite(x)]
    ci = (
        np.quantile(valid, [(1 - confidence) / 2, (1 + confidence) / 2]).tolist()
        if len(valid) >= 0.95 * iterations
        else None
    )
    warnings = []
    if len(a) < 20:
        warnings.append("small_number_of_independent_units_method_review_required")
    if point is None or ci is None:
        warnings.append("undefined_or_unstable_estimate")
    if ci is not None and ci[0] == ci[1]:
        warnings.append("degenerate_bootstrap_interval")
    return {
        "recipe_version": VERSION,
        "recipe": recipe,
        "numpy_version": np.__version__,
        "results": [
            {
                "id": name,
                "label": name.replace("_", " "),
                "estimate": point,
                "ci": ci,
                "independent_units": len(a),
                "missing_count": missing,
                "undefined_bootstrap_samples": iterations - len(valid),
                "method": method,
            }
        ],
        "warnings": warnings,
        "scope": "Design must be reviewed. Missing observations are excluded explicitly. No automatic clinical interpretation or manuscript approval.",
    }
