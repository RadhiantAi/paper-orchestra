import json
from pathlib import Path

import pytest

from research_benchmark import run_suite
from research_review_cli import export_sections, import_manuscript
from utils.research_quality import aggregate_constraints, numeric_audit
from utils.review_workspace import (
    accept_revision,
    current_decision,
    propose_revision,
    save_decision,
    save_revision,
)


def test_numeric_fail_then_pass():
    assert numeric_audit("20 (40%)", denominator=80)["findings"]
    assert not numeric_audit("20 (25.0%)", denominator=80)["findings"]
    assert numeric_audit("81 (101%)", denominator=80)["findings"]
    with pytest.raises(ValueError):
        numeric_audit("", denominator=0)


def test_fact_units_intervals_and_stale_quotes():
    facts = [
        dict(
            id="a",
            source="approved aggregate table",
            approved_by="Reviewer",
            value=2,
            unit="mm",
            ci=[1, 3],
            occurrences=[
                dict(quote="size 2 cm", value=2, unit="cm", ci=[0, 3]),
                dict(quote="absent", value=2),
            ],
        )
    ]
    kinds = {x["kind"] for x in numeric_audit("size 2 cm", facts=facts)["findings"]}
    assert kinds == {"unit_conflict", "ci_conflict", "stale_occurrence"}
    facts[0]["approved_by"] = ""
    assert (
        numeric_audit("size 2 cm", facts=facts)["findings"][0]["kind"]
        == "unapproved_fact"
    )


def test_aggregate_subsets_and_sums():
    facts = [
        dict(id="all", value=10, sum_of=["a", "b"]),
        dict(id="a", value=11, subset_of="all"),
        dict(id="b", value=1),
    ]
    assert {x["kind"] for x in aggregate_constraints(facts)} == {
        "sum_conflict",
        "subset_exceeds_parent",
    }


def test_evidence_decision_invalidated_by_claim_or_source(tmp_path):
    claim = {"claim_context": "A finding", "candidate_passage": "Original source"}
    decision = save_decision(tmp_path, claim, "accept", "Researcher", "Read the source")
    assert current_decision(claim, [decision]) == decision
    assert (
        current_decision({**claim, "candidate_passage": "Changed source"}, [decision])
        is None
    )
    assert (
        current_decision({**claim, "claim_context": "A different finding"}, [decision])
        is None
    )
    with pytest.raises(ValueError):
        save_decision(tmp_path, claim, "accept", "", "Reason")


def test_revision_preserves_approved_sections_and_rejects_stale():
    sections = {
        "intro": {"text": "Approved intro", "approval": "Dr A"},
        "results": {"text": "20 (40%) [1]", "approval": "Dr B"},
    }
    proposal = propose_revision(
        sections, "results", "20 (25%) [2]", "Corrected denominator and source"
    )
    assert proposal["numbers_changed"] and proposal["citations_changed"]
    result = accept_revision(sections, proposal, "Dr B")
    assert result["intro"] == sections["intro"]
    assert result["results"]["approval"] is None
    with pytest.raises(ValueError):
        accept_revision(result, proposal, "Dr B")


def test_offline_exchange_and_revision_export(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Title\n\n## Results\n20 (40%).", encoding="utf-8")
    root = tmp_path / "review"
    assert import_manuscript(source, root, denominator=80)["findings"]
    sections = json.loads((root / "manuscript_sections.json").read_text())
    key = next(k for k in sections if "Results" in k)
    proposal = propose_revision(sections, key, "## Results\n20 (25%).", "Correction")
    save_revision(root, proposal, "Reviewer")
    export_sections(root, tmp_path / "new.md")
    assert "20 (25%)" in (tmp_path / "new.md").read_text()
    with pytest.raises(ValueError):
        import_manuscript(source, root)


def test_benchmark_detects_faults_and_corrected_versions_pass():
    result = run_suite(Path(__file__).parents[1] / "benchmarks/synthetic.json")
    assert result["passed"] and len(result["cases"]) == 3
    assert all(
        c["after"]["passes"] and not c["before"]["passes"] for c in result["cases"]
    )


def test_aggregate_conflict_sets_exchange_status(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Results\nTotal 10. Subset 11.", encoding="utf-8")
    facts = [
        dict(id="total", value=10, source="source", approved_by="Reviewer", occurrences=[dict(quote="Total 10", value=10)]),
        dict(id="subset", value=11, subset_of="total", source="source", approved_by="Reviewer", occurrences=[dict(quote="Subset 11", value=11)]),
    ]
    result = import_manuscript(source, tmp_path / "review", facts=facts)
    assert not result["findings"]
    assert result["aggregate_constraints"]
    assert result["status"] == "needs_review"


def test_revision_marks_derived_reports_stale(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("# Results\n20 (40%).", encoding="utf-8")
    root = tmp_path / "review"
    import_manuscript(source, root, denominator=80)
    (root / "evidence_review.json").write_text('{"claims": []}')
    sections = json.loads((root / "manuscript_sections.json").read_text())
    proposal = propose_revision(sections, next(iter(sections)), "# Results\n20 (25%).", "Correction")
    save_revision(root, proposal, "Reviewer")
    for name in ("numeric_audit.json", "evidence_review.json"):
        assert json.loads((root / name).read_text())["status"] == "stale_after_revision"
