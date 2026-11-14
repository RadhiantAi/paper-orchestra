import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

import pymupdf
import pytest

from utils import provider_backend as backend


@pytest.mark.parametrize(
    "name, expected",
    [
        ("openai:custom-model", ("openai", "custom-model")),
        ("anthropic:custom-model", ("anthropic", "custom-model")),
        ("gemini:custom-model", ("gemini", "custom-model")),
        ("compatible:vendor/model:tag", ("compatible", "vendor/model:tag")),
        ("gpt-4.1", ("openai", "gpt-4.1")),
        ("claude-sonnet-4-5", ("anthropic", "claude-sonnet-4-5")),
        ("gemini-2.5-pro", ("gemini", "gemini-2.5-pro")),
    ],
)
def test_model_routing(name, expected):
    assert backend.resolve_model(name) == expected


@pytest.mark.parametrize("name", [None, "unknown-model", "other:model", "openai:"])
def test_missing_or_invalid_model_rejected(name):
    with pytest.raises(backend.ModelConfigurationError):
        backend.resolve_model(name)


def test_imports_without_any_provider_sdk_or_credentials():
    code = """
import importlib.abc, sys
class BlockProviders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.startswith(("google.genai", "openai", "anthropic")):
            raise AssertionError("Unexpected provider import: " + fullname)
sys.meta_path.insert(0, BlockProviders())
import methods.paper_writer
import methods.paper_writer_with_plotting
import paper_writing_cli
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("provider", ["openai", "compatible", "anthropic", "gemini"])
def test_text_images_and_system_reach_only_selected_provider(monkeypatch, provider):
    monkeypatch.setenv(
        {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "compatible": "LLM_BASE_URL",
        }[provider],
        "http://127.0.0.1:1234/v1" if provider == "compatible" else "synthetic-key",
    )
    client = MagicMock()
    client.chat.completions.create.return_value = NS(
        choices=[NS(finish_reason="stop", message=NS(content='{"ok": true}'))]
    )
    client.messages.stream.return_value.__enter__.return_value.get_final_message.return_value = NS(
        stop_reason="end_turn", content=[NS(type="text", text='{"ok": true}')]
    )
    client.models.generate_content.return_value = NS(
        candidates=[NS(finish_reason="STOP")], text='{"ok": true}'
    )
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(backend, "_client", factory)
    answer = backend.call_llm_with_contents(
        ["hello", {"data": b"fake-image", "mime_type": "image/jpeg"}],
        model_name=provider + ":example-model",
        generation_configs={
            "system_instruction": "review carefully",
            "temperature": 0.3,
        },
    )
    assert answer["parsed_response"] == {"ok": True}
    factory.assert_called_once_with(provider)
    if provider in {"openai", "compatible"}:
        request = client.chat.completions.create.call_args.kwargs
        assert request["model"] == "example-model"
        assert request["messages"][0]["content"] == "review carefully"
        assert request["messages"][1]["content"][1]["image_url"]["url"].startswith(
            "data:image/jpeg;"
        )
        assert ("temperature" in request) == (provider == "compatible")
    elif provider == "anthropic":
        request = client.messages.stream.call_args.kwargs
        assert request["system"] == "review carefully"
        assert (
            request["messages"][0]["content"][1]["source"]["media_type"] == "image/jpeg"
        )
    else:
        request = client.models.generate_content.call_args.kwargs
        assert request["config"].system_instruction == "review carefully"
        assert request["contents"][1].inline_data.mime_type == "image/jpeg"


def test_compatible_credentials_do_not_reuse_openai_key(monkeypatch):
    import openai

    monkeypatch.setenv("OPENAI_API_KEY", "unrelated-synthetic-key")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:1234/v1")
    factory = MagicMock()
    monkeypatch.setattr(openai, "OpenAI", factory)
    backend._client("compatible")
    assert factory.call_args.kwargs["api_key"] == "local-no-key"
    assert factory.call_args.kwargs["base_url"] == "http://localhost:1234/v1"


@pytest.mark.parametrize(
    "url",
    ["file:///tmp/model", "https://user:secret@example.com", "http://example.com/v1"],
)
def test_invalid_compatible_endpoint_rejected(monkeypatch, url):
    monkeypatch.setenv("LLM_BASE_URL", url)
    with pytest.raises(backend.ModelConfigurationError):
        backend.validate_model_configuration("compatible:model")


def test_pdf_includes_text_and_every_page_image(tmp_path):
    pdf = tmp_path / "example.pdf"
    with pymupdf.open() as doc:
        for number in (1, 2):
            doc.new_page().insert_text((50, 50), f"Synthetic page {number}")
        doc.save(pdf)
    parts = backend._parts([{"data": pdf.read_bytes(), "mime_type": "application/pdf"}])
    assert "Synthetic page 2" in parts[0]["text"]
    assert len(parts) == 3
    assert all(p["data"].startswith(b"\x89PNG") for p in parts[1:])


@pytest.mark.parametrize("bad_output", ["", "not json", None])
def test_empty_or_malformed_output_is_not_success(monkeypatch, bad_output):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setattr(backend, "_request", lambda *args: bad_output)
    with pytest.raises(backend.ModelResponseError):
        backend.call_llm_with_text_prompt("test", "openai:model")


def test_truncated_response_is_rejected(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    client = MagicMock()
    client.chat.completions.create.return_value = NS(
        choices=[NS(finish_reason="length", message=NS(content='{"ok": true}'))]
    )
    monkeypatch.setattr(backend, "_client", lambda provider: client)
    with pytest.raises(backend.ModelResponseError, match="truncated"):
        backend.call_llm_with_text_prompt("test", "openai:model")


def test_provider_error_cannot_echo_secret_or_prompt(monkeypatch, capsys):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-secret")

    def failed(*args):
        raise RuntimeError("synthetic-secret private research text")

    monkeypatch.setattr(backend, "_request", failed)
    with pytest.raises(backend.ModelResponseError) as error:
        backend.call_llm_with_text_prompt("test", "openai:model")
    assert "synthetic-secret" not in str(error.value)
    assert "private research text" not in str(error.value)
    assert capsys.readouterr().out == ""
