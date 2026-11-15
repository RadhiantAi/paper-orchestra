from unittest.mock import Mock

import pytest

from utils.provider_backend import model_file_label


def test_model_labels_allow_vendor_paths_and_avoid_collisions(tmp_path):
    labels = [
        model_file_label("compatible:vendor/model:tag"),
        model_file_label("compatible:vendor_model_tag"),
    ]
    assert labels[0] != labels[1]
    for label in labels:
        path = tmp_path / f"evaluation_{label}.json"
        path.write_text("{}", encoding="utf-8")
        assert path.is_file()


@pytest.mark.parametrize(
    "model", ["anthropic:example", "compatible:vendor/model", None]
)
def test_literature_comparison_uses_shared_adapter(monkeypatch, model):
    from autoraters import sxs_lit_review_quality as evaluation

    request = Mock(return_value={"parsed_response": {"winner": "paper1"}})
    monkeypatch.setattr(evaluation, "call_llm_with_text_prompt", request)
    assert evaluation.rate_sxs_lit_review("A", "B", model) == {"winner": "paper1"}
    assert request.call_args.kwargs["model_name"] == model
    request.assert_called_once()


@pytest.mark.parametrize("review", [{}, {"Overall": 0}, {"Overall": "bad"}])
def test_invalid_peer_review_cannot_count_as_complete(monkeypatch, tmp_path, review):
    from methods.agents import content_refinement_agent as module

    agent = module.ContentRefinementAgent(
        "unused", "unused", "unused", work_dir=str(tmp_path)
    )
    monkeypatch.setattr(module, "load_paper", lambda **kw: "Synthetic paper")
    monkeypatch.setattr(module, "perform_review_agentreview", lambda **kw: review)
    with pytest.raises(RuntimeError, match="has not completed review"):
        agent._get_peer_review("unused.pdf", "initial")


def test_invalid_format_review_cannot_count_as_complete(monkeypatch, tmp_path):
    from methods.agents import content_refinement_agent as module

    agent = module.ContentRefinementAgent(
        "unused", "unused", "unused", work_dir=str(tmp_path)
    )
    monkeypatch.setattr(module, "pdf_to_grid_images", lambda *args: [])
    monkeypatch.setattr(
        module, "call_llm_with_images", lambda **kw: {"parsed_response": {}}
    )
    with pytest.raises(RuntimeError, match="has not completed review"):
        agent._get_formatting_review("unused.pdf", "initial")
