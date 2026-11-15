from fractions import Fraction
import pytest
from utils.analysis_recipes import calculate, run_recipe, verify_calculation
from utils.design_recipes import fleiss
from utils.project_store import create_project


def recipe(name):
    return {
        "name": name,
        "sampling_unit": "Synthetic independent unit",
        (
            "independent_clusters_confirmed"
            if name.startswith("clustered_")
            else "independent_units_confirmed"
        ): True,
        "confidence": 0.95,
        "seed": 42,
        "bootstrap_iterations": 1000,
    }


def test_fleiss_matches_hand_derived_pair_agreement_and_permutations():
    # Four units, three ratings each: 8/12 agreeing ordered-pair proportions;
    # pooled category frequency 1/2 each gives kappa = (2/3-1/2)/(1-1/2).
    table = [[3, 0], [2, 1], [1, 2], [0, 3]]
    expected = float((Fraction(2, 3) - Fraction(1, 2)) / (1 - Fraction(1, 2)))
    assert fleiss(table) == pytest.approx(expected)
    assert fleiss([row[::-1] for row in table[::-1]]) == pytest.approx(expected)
    rows = [{"unit_id": str(n), "n0": a, "n1": b} for n, (a, b) in enumerate(table)]
    spec = recipe("multirater_fleiss") | {
        "categories": 2,
        "raters_design": "interchangeable",
    }
    output = calculate(spec, rows)
    assert output == calculate(spec, rows) and output["results"][0][
        "estimate"
    ] == pytest.approx(1 / 3)
    with pytest.raises(ValueError, match="Fixed-rater"):
        calculate(spec | {"raters_design": "fixed"}, rows)
    with pytest.raises(ValueError):
        calculate(spec, rows[:-1] + [{"unit_id": "3", "n0": 1, "n1": 1}])


def test_whole_cluster_resampling_and_weighting_known_answers():
    rows = [
        {"cluster_id": "a", "count": 1, "denominator": 1},
        {"cluster_id": "b", "count": 0, "denominator": 9},
    ]
    spec = recipe("clustered_proportion") | {"weighting": "observation"}
    output = calculate(spec, rows)["results"][0]
    assert output["estimate"] == 0.1 and output["ci"] == [0.0, 1.0]
    # Exhaustive two-cluster resampling yields 1, 0.1, 0.1, 0, not an independent-observation interval.
    assert (
        calculate(spec | {"weighting": "cluster_equal"}, rows)["results"][0]["estimate"]
        == 0.5
    )
    assert calculate(spec, rows) == calculate(spec, rows)
    with pytest.raises(ValueError, match="whole clusters"):
        calculate(spec | {"independent_clusters_confirmed": False}, rows)


def test_clustered_agreement_matches_known_total_and_receipt_recomputes(tmp_path):
    spec = recipe("clustered_binary_agreement")
    rows = [
        {"cluster_id": str(i), "n00": 20, "n01": 5, "n10": 5, "n11": 20}
        for i in range(2)
    ]
    assert calculate(spec, rows)["results"][0]["estimate"] == pytest.approx(0.6)
    assert "degenerate_bootstrap_interval" in calculate(spec, rows)["warnings"]
    w = tmp_path / "project"
    create_project(w)
    source = tmp_path / "clusters.csv"
    source.write_text("cluster_id,n00,n01,n10,n11\na,20,5,5,20\nb,20,5,5,20\n")
    record = run_recipe(
        w, spec, source, tmp_path / "analysis", "Reviewer", "Synthetic design checked"
    )
    assert verify_calculation(record)
    source.write_text("changed")
    assert not verify_calculation(record)


@pytest.mark.parametrize(
    "changes",
    [
        {"seed": -1},
        {"confidence": 1},
        {"bootstrap_iterations": 1},
        {"extra_option": True},
        {"raters_design": "interchangeable"},
    ],
)
def test_design_recipe_rejects_invalid_options(changes):
    with pytest.raises(ValueError):
        calculate(
            recipe("clustered_proportion") | {"weighting": "observation"} | changes,
            [{"cluster_id": str(i), "count": 1, "denominator": 2} for i in range(2)],
        )
