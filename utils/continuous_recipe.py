"""Prespecified descriptive and OLS analyses of independent continuous measurements."""

import math
import re
import numpy as np


def calculate_continuous(recipe, rows):
    allowed = {
        "name",
        "sampling_unit",
        "independent_units_confirmed",
        "units",
        "groups",
        "group_definition",
        "missingness_reason",
        "outcomes",
        "predictors",
        "confidence",
        "seed",
        "bootstrap_iterations",
    }
    if set(recipe) - allowed:
        raise ValueError("Unknown continuous-measurement recipe options.")
    for field in ("sampling_unit", "group_definition", "missingness_reason"):
        if not isinstance(recipe.get(field), str) or not recipe[field].strip():
            raise ValueError(
                "Describe "
                + field
                + " explicitly (unknown is allowed for missingness)."
            )
    if recipe.get("independent_units_confirmed") is not True:
        raise ValueError(
            "Confirm independent units; repeated or clustered records need another method."
        )
    units, groups = recipe.get("units"), recipe.get("groups")
    if (
        not isinstance(units, dict)
        or not 1 <= len(units) <= 20
        or any(
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,49}", k)
            or k in {"unit_id", "group"}
            or not isinstance(v, str)
            or not v.strip()
            for k, v in units.items()
        )
    ):
        raise ValueError("Name 1 to 20 measurement columns and their units.")
    if (
        not isinstance(groups, dict)
        or not 1 <= len(groups) <= 20
        or any(
            not isinstance(k, str)
            or not k.strip()
            or not isinstance(v, str)
            or not v.strip()
            for k, v in groups.items()
        )
    ):
        raise ValueError(
            "Define each literal group code; use one code for an ungrouped sample."
        )
    predictors, outcomes = recipe.get("predictors", []), recipe.get("outcomes", [])
    if any(
        not isinstance(v, list)
        or any(not isinstance(c, str) for c in v)
        or len(set(v)) != len(v)
        for v in [predictors, outcomes]
    ):
        raise ValueError("Predictors and outcomes must be distinct lists.")
    if (set(predictors) | set(outcomes)) - set(units) or set(predictors) & set(
        outcomes
    ):
        raise ValueError("Use known, separate predictor and outcome columns.")
    if bool(predictors) != bool(outcomes) or len(predictors) > 5 or len(outcomes) > 6:
        raise ValueError(
            "Select both predictors and outcomes, with at most five and six respectively."
        )
    confidence = recipe.get("confidence", 0.95)
    seed, iterations = recipe.get("seed", 0), recipe.get("bootstrap_iterations", 2000)
    if type(confidence) not in {float, int} or not 0.5 < confidence < 1:
        raise ValueError("Confidence must be between 0.5 and 1.")
    if (
        type(seed) is not int
        or not 0 <= seed < 2**32
        or type(iterations) is not int
        or not 100 <= iterations <= 20000
    ):
        raise ValueError("Use an unsigned seed and 100 to 20,000 bootstrap samples.")
    if (
        not rows
        or len(rows) > 10000
        or len(rows) * iterations * (len(units) + len(outcomes) * 2) > 100_000_000
    ):
        raise ValueError(
            "Continuous analysis exceeds the bounded row/resampling budget."
        )
    seen = set()
    expected = set(units) | {"unit_id", "group"}
    parsed = []
    for row in rows:
        if set(row) != expected or any(v is None for v in row.values()):
            raise ValueError(
                "CSV must contain exactly unit_id, group and the declared measurement columns."
            )
        uid = str(row["unit_id"]).strip()
        group = str(row["group"]).strip()
        if not uid or uid in seen or group not in groups:
            raise ValueError(
                "Supply unique anonymous unit IDs and defined group codes."
            )
        seen.add(uid)
        values = {}
        for column in units:
            value = row[column]
            if isinstance(value, bool):
                raise ValueError("Boolean measurement is invalid.")
            if str(value).strip() == "":
                values[column] = None
            else:
                number = float(value)
                if not math.isfinite(number) or abs(number) > 1e12:
                    raise ValueError(
                        "Measurements must be finite and within the numeric limit; only blanks mean missing."
                    )
                values[column] = number
        parsed.append((uid, group, values))
    parsed.sort(key=lambda r: r[0])
    rng = np.random.default_rng(seed)
    quantiles = [(1 - confidence) / 2, (1 + confidence) / 2]
    summaries, models, warnings = [], [], []
    sets = [(None, parsed)] + [
        (g, [r for r in parsed if r[1] == g]) for g in sorted(groups)
    ]
    for group, subset in sets:
        if not subset:
            warnings.append({"kind": "empty_defined_group", "group": group})
        for column in sorted(units):
            values = np.array(
                [r[2][column] for r in subset if r[2][column] is not None], dtype=float
            )
            n = len(values)
            row = {
                "group": group,
                "variable": column,
                "unit": units[column],
                "total": len(subset),
                "available": n,
                "missing": len(subset) - n,
                "mean": None,
                "sd": None,
                "min": None,
                "max": None,
                "ci": None,
            }
            if n:
                row.update(
                    mean=float(values.mean()),
                    min=float(values.min()),
                    max=float(values.max()),
                )
            if n >= 2:
                row["sd"] = float(values.std(ddof=1))
                estimates = []
                for start in range(0, iterations, 100):
                    estimates.extend(
                        rng.choice(values, size=(min(100, iterations - start), n))
                        .mean(axis=1)
                        .tolist()
                    )
                row["ci"] = np.quantile(estimates, quantiles).tolist()
            if n < 20 or (n and np.ptp(values) == 0):
                warnings.append(
                    {
                        "kind": "small_or_constant_sample",
                        "group": group,
                        "variable": column,
                    }
                )
            summaries.append(row)
        for outcome in outcomes:
            complete = [
                r
                for r in subset
                if all(r[2][c] is not None for c in predictors + [outcome])
            ]
            n = len(complete)
            model = {
                "group": group,
                "outcome": outcome,
                "predictors": predictors,
                "complete_cases": n,
                "excluded_missing": len(subset) - n,
                "status": "not_estimable",
            }
            models.append(model)
            if n <= len(predictors) + 2:
                warnings.append(
                    {
                        "kind": "insufficient_model_cases",
                        "group": group,
                        "outcome": outcome,
                    }
                )
                continue
            x = np.array([[1.0] + [r[2][c] for c in predictors] for r in complete])
            y = np.array([r[2][outcome] for r in complete])
            # Standardise for rank/conditioning and LOOCV diagnostics, while returning
            # coefficients in the declared original measurement units.
            scales = x[:, 1:].std(axis=0)
            if np.any(scales == 0) or np.ptp(y) == 0:
                warnings.append(
                    {
                        "kind": "constant_model_column",
                        "group": group,
                        "outcome": outcome,
                    }
                )
                continue
            means = x[:, 1:].mean(axis=0)
            z = np.column_stack([np.ones(n), (x[:, 1:] - means) / scales])
            if np.linalg.matrix_rank(z) < z.shape[1] or np.linalg.cond(z) > 1e8:
                warnings.append(
                    {
                        "kind": "rank_deficient_or_unstable_model",
                        "group": group,
                        "outcome": outcome,
                    }
                )
                continue
            beta = np.linalg.lstsq(z, y, rcond=None)[0]
            coefficients = np.r_[
                beta[0] - np.dot(beta[1:] / scales, means), beta[1:] / scales
            ]
            residual = y - z @ beta
            leverage = np.sum(z * np.linalg.pinv(z).T, axis=1)
            valid_loo = np.all(1 - leverage > 1e-8)
            draws = []
            for _ in range(iterations):
                ix = rng.integers(0, n, size=n)
                sample = z[ix]
                if (
                    np.linalg.matrix_rank(sample) == sample.shape[1]
                    and np.linalg.cond(sample) <= 1e8
                ):
                    b = np.linalg.lstsq(sample, y[ix], rcond=None)[0]
                    draws.append(
                        np.r_[b[0] - np.dot(b[1:] / scales, means), b[1:] / scales]
                    )
            model.update(
                status="estimated",
                coefficients=dict(
                    zip(["intercept"] + predictors, coefficients.tolist())
                ),
                r_squared=float(1 - np.sum(residual**2) / np.sum((y - y.mean()) ** 2)),
                loo_rmse=float(np.sqrt(np.mean((residual / (1 - leverage)) ** 2)))
                if valid_loo
                else None,
                mean_only_loo_rmse=float(
                    np.sqrt(np.mean(((y - y.mean()) * n / (n - 1)) ** 2))
                ),
                coefficient_ci=np.quantile(draws, quantiles, axis=0).T.tolist()
                if len(draws) >= 0.95 * iterations
                else None,
                coefficient_order=["intercept"] + predictors,
                undefined_bootstrap_samples=iterations - len(draws),
            )
            if not valid_loo or model["coefficient_ci"] is None or n < 20:
                warnings.append(
                    {
                        "kind": "model_uncertainty_needs_review",
                        "group": group,
                        "outcome": outcome,
                    }
                )
    if any(r["missing"] for r in summaries):
        warnings.append({"kind": "missing_data_assumptions_require_review"})
    warnings.append(
        {"kind": "exploratory_method_and_clinical_interpretation_require_review"}
    )
    return {
        "recipe_version": "1",
        "recipe": recipe,
        "numpy_version": np.__version__,
        "results": summaries,
        "models": models,
        "warnings": warnings,
        "scope": "Independent units; available-case summaries and outcome-specific complete-case OLS with intercept. Percentile row-bootstrap intervals; analytic leave-one-out prediction errors. No imputation, causal claims, multiplicity correction or clinical approval. No unit IDs or measurement rows emitted.",
    }
