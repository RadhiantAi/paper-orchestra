import importlib
import os
from pathlib import Path
import runpy
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pymupdf
import pytest

from utils.draft_output import DRAFT_LABEL, mark_pdf_as_draft


def test_generated_code_never_executes(tmp_path):
    from utils.paper_banana_utils import (
        execute_plot_code_worker,
        generate_figure_visuals,
    )

    sentinel = tmp_path / "must-not-exist.txt"
    hostile = (
        f"from pathlib import Path; Path({str(sentinel)!r}).write_text('executed')"
    )
    with pytest.raises(RuntimeError, match="disabled"):
        execute_plot_code_worker(hostile)
    assert not sentinel.exists()
    with pytest.raises(RuntimeError, match="disabled"):
        generate_figure_visuals("plot", hostile)
    assert not sentinel.exists()


def test_plotting_pipeline_rejects_before_touching_output(tmp_path):
    from methods.paper_writer_with_plotting import write_single_paper

    sentinel = tmp_path / "final_paper.pdf"
    sentinel.write_bytes(b"preserve-existing-output")
    with pytest.raises(RuntimeError, match="disabled"):
        write_single_paper(str(tmp_path), "unused-template")
    assert sentinel.read_bytes() == b"preserve-existing-output"


def test_scholar_import_and_failure_do_not_log_credentials(monkeypatch, capsys):
    monkeypatch.setenv("SEMANTIC_SCHOLAR_API_KEY", "synthetic-secret")
    from utils import scholar_utils

    importlib.reload(scholar_utils)
    assert "synthetic-secret" not in capsys.readouterr().out

    def fail(*args, **kwargs):
        raise RuntimeError("synthetic-secret in a proxy error")

    monkeypatch.setattr(scholar_utils.requests, "get", fail)
    assert scholar_utils.s2_title_search("Synthetic Paper") is None
    assert "synthetic-secret" not in capsys.readouterr().out


def test_email_disabled_without_reading_attachment_or_connecting(tmp_path, monkeypatch):
    import smtplib
    from frontend.frontend_utils import send_notification_email

    transport = MagicMock(side_effect=AssertionError("Email must not connect"))
    monkeypatch.setattr(smtplib, "SMTP_SSL", transport)
    monkeypatch.setenv("SMTP_PASSWORD", "synthetic-password")
    assert (
        send_notification_email(
            "test@example.invalid", "draft", [tmp_path / "missing.pdf"]
        )[0]
        is False
    )
    transport.assert_not_called()


def test_draft_label_on_every_page_preserves_content(tmp_path):
    pdf = tmp_path / "draft.pdf"
    with pymupdf.open() as document:
        for n in range(2):
            document.new_page().insert_text((50, 50), f"Synthetic result {n}")
        document.save(pdf)
    mark_pdf_as_draft(pdf)
    with pymupdf.open(pdf) as document:
        assert len(document) == 2
        for n, page in enumerate(document):
            assert DRAFT_LABEL in page.get_text()
            assert f"Synthetic result {n}" in page.get_text()


def test_cli_rejects_plotting_without_credentials_or_writes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "paper_writing_cli.py",
            "--raw_materials_dir",
            "unused",
            "--latex_template_dir",
            "unused",
            "--output_dir",
            str(tmp_path / "output"),
            "--use_plotting",
            "true",
        ],
    )
    with pytest.raises(SystemExit) as error:
        runpy.run_path("paper_writing_cli.py", run_name="__main__")
    assert error.value.code == 2
    assert not (tmp_path / "output").exists()


def test_cli_propagates_failure_and_separate_models(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    raw = tmp_path / "raw"
    raw.mkdir()
    fake_pipeline = ModuleType("methods.paper_writer")
    fake_pipeline.write_single_paper = MagicMock(return_value=False)
    monkeypatch.setitem(sys.modules, "methods.paper_writer", fake_pipeline)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "paper_writing_cli.py",
            "--raw_materials_dir",
            str(raw),
            "--latex_template_dir",
            "unused",
            "--output_dir",
            str(tmp_path / "output"),
            "--writer_model_name",
            "openai:writer",
            "--reflection_model_name",
            "anthropic:reviewer",
            "--search_model_name",
            "openai:ranker",
        ],
    )
    with pytest.raises(SystemExit) as error:
        runpy.run_path("paper_writing_cli.py", run_name="__main__")
    assert error.value.code == 1
    values = fake_pipeline.write_single_paper.call_args.kwargs
    assert values["writer_model_name"] == "openai:writer"
    assert values["reflection_model_name"] == "anthropic:reviewer"
    assert values["search_model_name"] == "openai:ranker"
