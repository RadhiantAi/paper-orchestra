import json
import time
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from PIL import Image

from methods import paper_writer
from methods.agents import literature_review_agent as literature
from utils import pdf_utils, provider_backend
from utils.draft_output import DRAFT_LABEL


def test_synthetic_workflow_with_mixed_providers(tmp_path, monkeypatch):
    """Run real agents and PDF handling; replace only external APIs and TeX binaries."""
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-openai-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-anthropic-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    raw = tmp_path / "raw_materials"
    figures = raw / "figures"
    figures.mkdir(parents=True)
    (raw / "idea_sparse.md").write_text(
        "Synthetic educational study.", encoding="utf-8"
    )
    (raw / "experimental_log.md").write_text(
        "Synthetic result: 4 of 10.", encoding="utf-8"
    )
    Image.new("RGB", (100, 100), "white").save(figures / "checked.png")
    (figures / "info.json").write_text(
        json.dumps([{"name": "checked.png", "caption": "Synthetic figure."}])
    )
    template = tmp_path / "template"
    template.mkdir()
    (template / "guidelines.md").write_text("Synthetic test guidelines.")
    tex = "\\documentclass{article}\n\\begin{document}Synthetic result: 4 of 10.\\end{document}"
    (template / "template.tex").write_text(tex)
    record = {
        "title": "Synthetic reference",
        "year": 2020,
        "publicationDate": "2020-01-01",
        "authors": [{"name": "Synthetic Author"}],
        "abstract": "Synthetic abstract.",
        "venue": "Test Journal",
    }
    monkeypatch.setattr(literature, "s2_search", lambda query: [record])
    monkeypatch.setattr(literature, "s2_title_search", lambda *args: record)
    monkeypatch.setattr(time, "sleep", lambda _: None)
    outline = {
        "intro_related_work_plan": {
            "introduction_strategy": {"search_directions": ["synthetic"]}
        },
        "section_plan": [],
    }
    review = {"Overall": 5, "Confidence": 3, "Quality": 2, "Clarity": 2}
    response_texts = [json.dumps(outline), '{"selected_ids": [0]}', tex, tex]
    response_texts += [json.dumps(review)] * 4
    response_texts += ["```json\n{}\n```\n```latex\n" + tex + "\n```"]
    response_texts += [json.dumps(review)] * 4
    response_texts += ['{"figure_and_tables": {}, "other_issues": []}']
    requests = []

    def model_response(provider, model, parts, *args):
        requests.append((provider, model, parts))
        assert response_texts, "Unexpected extra model request"
        return response_texts.pop(0)

    monkeypatch.setattr(provider_backend, "_request", model_response)
    original_init = paper_writer.ContentRefinementAgent.__init__

    def one_reflection(self, *args, **kwargs):
        kwargs["max_reflections"] = 1
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(paper_writer.ContentRefinementAgent, "__init__", one_reflection)

    def synthetic_tex(command, cwd, **kwargs):
        if command[0] == "pdflatex":
            path = Path(cwd) / Path(command[-1]).with_suffix(".pdf")
            with pymupdf.open() as document:
                document.new_page().insert_text(
                    (50, 50), "Synthetic result: 4 of 10.\n" * 6
                )
                document.save(path)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(pdf_utils.subprocess, "run", synthetic_tex)
    assert (
        paper_writer.write_single_paper(
            str(tmp_path),
            str(template),
            idea_filename="idea_sparse.md",
            writer_model_name="openai:writer",
            reflection_model_name="anthropic:reviewer",
            search_model_name="compatible:ranker",
            research_cutoff="2026-01",
        )
        is True
    )
    assert not response_texts
    assert [(p, m) for p, m, _ in requests[:4]] == [
        ("openai", "writer"),
        ("compatible", "ranker"),
        ("openai", "writer"),
        ("openai", "writer"),
    ]
    assert all(p == "anthropic" and m == "reviewer" for p, m, _ in requests[4:])
    assert any("data" in part for part in requests[3][2])
    assert any("data" in part for part in requests[8][2])
    with pymupdf.open(tmp_path / "final_paper.pdf") as document:
        assert DRAFT_LABEL in document[0].get_text()
        assert "Synthetic result: 4 of 10." in document[0].get_text()
    assert (tmp_path / "literature_agent_output" / "references.bib").exists()
    assert (
        tmp_path / "content_refinement_workdir" / "final_refined_paper.tex"
    ).exists()
