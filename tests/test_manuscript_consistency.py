from copy import deepcopy

import pytest

from utils.project_store import create_project, load_project, update_project
from utils.project_results import approve_results
from utils.manuscript_consistency import audit_consistency, save_claim, review_finding


def setup(tmp_path):
    create_project(tmp_path)
    rows = [
        {
            "id": k,
            "label": k,
            "count": count,
            "denominator": 20,
            "definition": "Specificity",
            "source": "Synthetic",
            "method": "Count",
            "participants": 10,
        }
        for k, count in [("a", 14), ("b", 15)]
    ]
    approve_results(rows, "Reviewer", "Synthetic check")
    update_project(tmp_path, lambda d: d.update(results=rows))
    return {
        "id": "rank",
        "kind": "ranking",
        "quote": "Group A had the highest specificity.",
        "result_id": "a",
        "result_ids": ["a", "b"],
        "direction": "highest",
    }


def test_contradictory_ranking_cannot_be_dismissed(tmp_path):
    claim = setup(tmp_path)
    save_claim(tmp_path, claim)
    report = audit_consistency(load_project(tmp_path), claim["quote"])
    row = next(
        r for r in report["findings"] if r["kind"] == "ranking_contradicts_results"
    )
    assert row["leaders"] == ["b"] and row["severity"] == "error"
    with pytest.raises(ValueError, match="Correct contradictory"):
        review_finding(tmp_path, claim["quote"], row["id"], "Reviewer", "Ignore")
    claim["quote"] = "Group B had the highest specificity."
    claim["result_id"] = "b"
    save_claim(tmp_path, claim)
    assert (
        audit_consistency(load_project(tmp_path), claim["quote"])["status"] == "checked"
    )


@pytest.mark.parametrize(
    "field,value,kind",
    [
        ("participants", 1, "single_participant_group_ranking"),
        ("count", 15, "ranking_tie_needs_qualification"),
        ("definition", "Sensitivity", "ranking_metrics_not_comparable"),
    ],
)
def test_rankings_flag_design_limits(tmp_path, field, value, kind):
    claim = setup(tmp_path)
    claim.update(result_id="b", quote="B had the highest specificity.")

    def alter(d):
        d["results"][0][field] = value
        approve_results(d["results"], "Reviewer", "Updated")

    update_project(tmp_path, alter)
    save_claim(tmp_path, claim)
    assert kind in {
        r["kind"]
        for r in audit_consistency(load_project(tmp_path), claim["quote"])["findings"]
    }


def test_proposed_uses_kept_and_reviews_invalidated_on_wording_change(tmp_path):
    setup(tmp_path)
    quote = "Communication effectiveness remains to be tested in a future study."
    claim = {
        "id": "future",
        "kind": "outcome",
        "classification": "proposed",
        "quote": quote,
        "qualification": "remains to be tested",
    }
    save_claim(tmp_path, claim)
    assert audit_consistency(load_project(tmp_path), quote)["status"] == "checked"
    with pytest.raises(ValueError, match="qualification"):
        save_claim(tmp_path, dict(claim, qualification="unseen qualification"))
    text = "The model is validated for communication."
    report = audit_consistency(load_project(tmp_path), text)
    row = next(
        r for r in report["findings"] if r["kind"] == "unmapped_interpretive_claim"
    )
    review_finding(tmp_path, text, row["id"], "Reviewer", "Checked outcome and scope")
    assert row["id"] in {
        r["id"]
        for r in audit_consistency(load_project(tmp_path), text)["reviewed_findings"]
    }
    assert not audit_consistency(load_project(tmp_path), text + " Updated.")[
        "reviewed_findings"
    ]


def test_figure_markers_use_recovered_labels_not_inferred_pixels(tmp_path):
    setup(tmp_path)
    data = load_project(tmp_path)
    data["figures"] = [
        {
            "id": "Figure 1",
            "caption": "Figure 1. Red circles mark the finding.",
            "panels": [{"source_label": "black asterisks"}],
        }
    ]
    report = audit_consistency(data, "Caption")
    assert report["findings"][0]["kind"] == "figure_marker_label_mismatch"
    data["figures"][0]["caption"] = "Figure 1. Black asterisks mark the finding."
    assert audit_consistency(data, "Caption")["status"] == "checked"


def test_consistency_cli_fails_for_detected_issue(tmp_path, capsys):
    from research_project_cli import main

    setup(tmp_path)
    manuscript = tmp_path / "draft.txt"
    manuscript.write_text("A has the highest specificity.")
    output = tmp_path / "report.json"
    with pytest.raises(SystemExit) as error:
        main(
            [
                "--workspace",
                str(tmp_path),
                "consistency-check",
                str(manuscript),
                "--output",
                str(output),
            ]
        )
    assert error.value.code == 1 and output.exists()
    assert "highest" not in capsys.readouterr().out


def test_consistency_errors_block_pack(tmp_path, monkeypatch):
    from test_project_workflow import pack_fixture
    from utils.project_pack import prepare_pack

    w = tmp_path / "project"
    create_project(w)
    spec = pack_fixture(w, tmp_path, monkeypatch)
    # A mapped comparison with an unapproved result is a computational failure.
    d = load_project(w)
    a = deepcopy(d["results"][0])
    a["id"] = "other"
    a.pop("approval", None)
    update_project(w, lambda d: d["results"].append(a))
    save_claim(
        w,
        {
            "id": "r",
            "kind": "ranking",
            "quote": "Synthetic region: 13 (65.0%).",
            "result_ids": ["region", "other"],
            "result_id": "region",
            "direction": "highest",
        },
    )
    report = prepare_pack(w, spec, tmp_path / "pack")
    assert report["status"] == "failed"
    assert any(
        r["kind"] == "ranking_result_unapproved_or_stale" for r in report["problems"]
    )
