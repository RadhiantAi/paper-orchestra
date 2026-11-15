from unittest.mock import MagicMock

import pytest

from methods.agents import literature_review_agent as literature
from utils.literature_sources import LiteratureRecord


def records_from_dicts(records):
    return [
        LiteratureRecord(source="pubmed", source_id=str(i), **r)
        for i, r in enumerate(records)
    ]


@pytest.fixture
def agent(tmp_path):
    return literature.HybridLiteratureAgent(
        "missing",
        "missing",
        "missing",
        "missing",
        str(tmp_path),
        model_name="openai:writer",
        search_model_name="anthropic:ranker",
    )


def test_ranker_can_only_select_retrieved_records(agent, monkeypatch):
    records = [
        {
            "title": "Synthetic real record",
            "abstract": "Synthetic abstract",
            "year": 2020,
        }
    ]
    monkeypatch.setattr(
        agent.discovery, "search", lambda *args: records_from_dicts(records)
    )
    model = MagicMock(return_value={"parsed_response": {"selected_ids": [0, 0]}})
    monkeypatch.setattr(literature, "call_llm_with_contents", model)
    result = agent._discover_candidates({"focus": "test"}, {}, "2026-01")
    assert [item["title"] for item in result] == ["Synthetic real record"]
    assert model.call_args.kwargs["model_name"] == "anthropic:ranker"


@pytest.mark.parametrize("ids", [[1], [-1], [True], ["0"], None])
def test_invented_or_malformed_candidate_ids_fail(agent, monkeypatch, ids):
    monkeypatch.setattr(
        agent.discovery,
        "search",
        lambda *args: records_from_dicts(
            [{"title": "Synthetic", "abstract": "Abstract", "year": 2020}]
        ),
    )
    monkeypatch.setattr(
        literature,
        "call_llm_with_contents",
        lambda *args, **kwargs: {"parsed_response": {"selected_ids": ids}},
    )
    with pytest.raises(ValueError, match="invalid candidate"):
        agent._discover_candidates({"focus": "test"}, {}, "2026-01")


def test_empty_search_is_not_retried_as_failure(agent, monkeypatch):
    discover = MagicMock(return_value=[])
    monkeypatch.setattr(agent, "_discover_candidates", discover)
    assert (
        agent._process_search_task({"focus": "test", "section": "test"}, {}, "2026-01")
        == []
    )
    discover.assert_called_once()


def test_search_failure_is_not_silent_success(agent, monkeypatch):
    monkeypatch.setattr(
        agent,
        "_discover_candidates",
        MagicMock(side_effect=RuntimeError("offline fixture")),
    )
    with pytest.raises(RuntimeError, match="three attempts"):
        agent._process_search_task({"focus": "test", "section": "test"}, {}, "2026-01")


def test_full_abstract_is_available_to_ranker(agent, monkeypatch):
    abstract = "a" * 2000 + "critical limitation"
    monkeypatch.setattr(
        agent.discovery,
        "search",
        lambda *args: records_from_dicts(
            [{"title": "Synthetic", "abstract": abstract, "year": 2020}]
        ),
    )
    model = MagicMock(return_value={"parsed_response": {"selected_ids": []}})
    monkeypatch.setattr(literature, "call_llm_with_contents", model)
    agent._discover_candidates({"focus": "test"}, {}, "2026-01")
    assert "critical limitation" in model.call_args.args[0][0]
