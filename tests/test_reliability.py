import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest
from docx import Document

from utils.model_policy import RunPolicy, ModelPolicyError, use_policy
from utils import provider_backend, safe_compile
from utils.run_control import RunWorkspace
from utils.research_exports import evidence_ledger, export_word
from utils.literature_adapters import CollectionSource
from utils.literature_sources import SourceError


def profiles():
    return {
        "openai:test": dict(
            text=True,
            json=True,
            images=True,
            max_image_tokens=4096,
            max_input_tokens=16000,
            max_output_tokens=16384,
            input_usd_per_million=1,
            output_usd_per_million=2,
        )
    }


def test_reservations_prevent_overspending_and_count_failed_calls(tmp_path):
    policy = RunPolicy(profiles(), max_cost=0.02, max_calls=2)
    policy.attach(tmp_path)
    index = policy.reserve("openai:test", [{"text": "test"}], None, 1000)
    policy.finish(index, status="failed_unknown_usage")
    with pytest.raises(ModelPolicyError, match="spending limit"):
        policy.reserve("openai:test", [{"text": "test"}], None, 1000)
    assert len(policy.attempts) == 1
    resumed = RunPolicy(profiles(), max_cost=0.02)
    resumed.attach(tmp_path)
    with pytest.raises(ModelPolicyError):
        resumed.reserve("openai:test", [{"text": "test"}], None, 1000)


def test_reported_tokens_replace_conservative_reservation():
    policy = RunPolicy(profiles(), max_cost=1)
    index = policy.reserve("openai:test", [{"text": "test"}], None, 1000)
    policy.finish(index, {"input_tokens": 100, "output_tokens": 20})
    assert policy.attempts[0]["accounted_usd"] == pytest.approx(0.00014)


def test_policy_blocks_image_incompatible_model_before_request(monkeypatch):
    profile = profiles()
    profile["openai:test"]["images"] = False
    policy = RunPolicy(profile, max_cost=1)
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic")
    request = Mock()
    monkeypatch.setattr(provider_backend, "_request", request)
    with use_policy(policy), pytest.raises(ModelPolicyError, match="image support"):
        provider_backend.call_llm_with_contents(
            [{"mime_type": "image/png", "data": b"fixture"}], "openai:test"
        )
    request.assert_not_called()


def test_context_and_call_limits_are_enforced():
    policy = RunPolicy(profiles(), max_cost=1, max_calls=1)
    with pytest.raises(ModelPolicyError, match="context"):
        policy.reserve("openai:test", [{"text": "x" * 17000}], None, 10)
    policy.reserve("openai:test", [{"text": "test"}], None, 10)
    with pytest.raises(ModelPolicyError, match="model-call"):
        policy.reserve("openai:test", [{"text": "test"}], None, 10)


def workspace_inputs(tmp_path):
    raw, template = tmp_path / "raw_materials", tmp_path / "template"
    raw.mkdir()
    template.mkdir()
    (raw / "input.md").write_text("original")
    (template / "template.tex").write_text("template")
    return template


def test_new_runs_preserve_existing_drafts_and_resume_skips_completed_stage(tmp_path):
    template = workspace_inputs(tmp_path)
    previous = tmp_path / "final_paper.pdf"
    previous.write_bytes(b"keep")
    first = RunWorkspace(tmp_path, template, {})
    action = Mock(side_effect=lambda: (first.path / "draft.txt").write_text("saved"))
    first.stage("draft", action, ["draft.txt"])
    resumed = RunWorkspace(tmp_path, template, {}, resume=first.path)
    resumed.stage("draft", action, ["draft.txt"])
    action.assert_called_once()
    second = RunWorkspace(tmp_path, template, {})
    assert first.path != second.path and previous.read_bytes() == b"keep"


def test_resume_rejects_edits_and_changed_inputs(tmp_path):
    template = workspace_inputs(tmp_path)
    run = RunWorkspace(tmp_path, template, {})
    run.stage(
        "draft", lambda: (run.path / "draft.txt").write_text("saved"), ["draft.txt"]
    )
    (run.path / "draft.txt").write_text("human edits")
    with pytest.raises(ValueError, match="edited"):
        RunWorkspace(tmp_path, template, {}, resume=run.path)
    (tmp_path / "raw_materials" / "input.md").write_text("new input")
    with pytest.raises(ValueError, match="changed"):
        RunWorkspace(tmp_path, template, {}, resume=run.path)
    assert (run.path / "draft.txt").read_text() == "human edits"


def test_compiler_rejects_nonzero_exit_even_if_old_pdf_exists(tmp_path, monkeypatch):
    (tmp_path / "draft.tex").write_text("bad TeX")
    target = tmp_path / "old.pdf"
    target.write_bytes(b"old draft preserved")
    calls = []

    def command(args, **kw):
        calls.append(args)
        return SimpleNamespace(
            returncode=1 if "run" in args else 0, stdout="error", stderr=""
        )

    monkeypatch.setattr(safe_compile.subprocess, "run", command)
    with pytest.raises(safe_compile.CompilationError):
        safe_compile.compile_latex(tmp_path, target, "draft")
    assert target.read_bytes() == b"old draft preserved"
    run = calls[1]
    assert "--network=none" in run and "--read-only" in run
    assert "--cap-drop=ALL" in run and "-no-shell-escape" in run
    assert "--pull=never" in run
    assert not any("API_KEY" in item for item in run)


def test_unresolved_references_reject_compilation(tmp_path, monkeypatch):
    (tmp_path / "draft.tex").write_text("test")

    def command(args, **kw):
        if "run" in args:
            mount = args[args.index("--mount") + 1]
            work = Path(mount.split("source=", 1)[1].split(",target=", 1)[0])
            (work / "draft.log").write_text(
                "LaTeX Warning: There were undefined references."
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(safe_compile.subprocess, "run", command)
    with pytest.raises(safe_compile.CompilationError, match="unresolved"):
        safe_compile.compile_latex(tmp_path, tmp_path / "output.pdf", "draft")
    assert not (tmp_path / "output.pdf").exists()


def test_compilation_only_copies_approved_file_types(tmp_path):
    inputs, outputs = tmp_path / "in", tmp_path / "out"
    inputs.mkdir()
    outputs.mkdir()
    (inputs / "draft.tex").write_text("test")
    (inputs / ".env").write_text("synthetic-secret")
    safe_compile.copy_build_inputs(inputs, outputs)
    assert (outputs / "draft.tex").exists() and not (outputs / ".env").exists()


def test_real_word_export_contains_text_and_draft_header(tmp_path):
    tex = tmp_path / "draft.tex"
    tex.write_text(
        r"\documentclass{article}\begin{document}\section{Methods}Synthetic aggregate results.\end{document}"
    )
    export_word(tex, tmp_path / "draft.docx")
    doc = Document(tmp_path / "draft.docx")
    assert "Synthetic aggregate results." in " ".join(p.text for p in doc.paragraphs)
    assert "DRAFT" in doc.sections[0].header.paragraphs[0].text


def test_evidence_does_not_confuse_abstracts_with_full_text_or_verify_support(tmp_path):
    tex, refs = tmp_path / "draft.tex", tmp_path / "refs.json"
    tex.write_text(
        "Screening evidence matters \\cite{abstract}.\n\nScreening evidence matters \\cite{full}.\n\nUnknown \\cite{missing}."
    )
    refs.write_text(
        json.dumps(
            {
                "abstract": {"abstract": "Screening evidence matters."},
                "full": {
                    "full_text": "Screening evidence matters.",
                    "doi": "10.1/example",
                },
            }
        )
    )
    rows = evidence_ledger(tex, refs, tmp_path)
    assert [r["status"] for r in rows] == [
        "needs_full_text",
        "candidate_passage_needs_review",
        "unknown_reference",
    ]
    assert rows[1]["candidate_passage"] == "Screening evidence matters."


def test_selected_pdf_collection_preserves_page_labels_and_rejects_escape(tmp_path):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((50, 50), "Synthetic screening evidence.")
        doc.save(tmp_path / "selected.pdf")
    record = dict(
        title="Synthetic screening",
        source="selected",
        source_id="1",
        url="https://example.invalid/1",
        pdf_path="selected.pdf",
        rights="Synthetic test document",
    )
    path = tmp_path / "collection.json"
    path.write_text(json.dumps([record]))
    assert (
        "[Page 1]"
        in CollectionSource(path)
        .search("screening", 2, None, None)
        .records[0]
        .full_text
    )
    record["pdf_path"] = "../outside.pdf"
    path.write_text(json.dumps([record]))
    with pytest.raises(SourceError, match="outside"):
        CollectionSource(path).search("screening", 2, None, None)


@pytest.mark.skipif(
    os.getenv("RUN_TEX_INTEGRATION") != "1",
    reason="Requires a running Docker engine and a prebuilt TeX image",
)
def test_real_isolated_tex_compilation(tmp_path):
    (tmp_path / "draft.tex").write_text(
        r"\documentclass{article}\begin{document}Synthetic offline compilation.\end{document}"
    )
    safe_compile.compile_latex(tmp_path, tmp_path / "draft-output.pdf", "draft")
    with pymupdf.open(tmp_path / "draft-output.pdf") as doc:
        assert "Synthetic offline compilation." in doc[0].get_text()
        assert "DRAFT" in doc[0].get_text()
