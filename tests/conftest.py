import socket

import pytest


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch, request):
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "SEMANTIC_SCHOLAR_API_KEY",
        "VERTEX_AI_PROJECT",
        "VERTEX_AI_LOCATION",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "PAPER_WRITER_MODEL",
        "PAPER_REVIEW_MODEL",
        "PAPER_SEARCH_MODEL",
        "PAPER_MAX_OUTPUT_TOKENS",
        "SMTP_EMAIL",
        "SMTP_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    original_connect = socket.socket.connect

    def no_network(sock, address):
        # Windows asyncio creates a loopback socket pair for AppTest's event loop.
        if request.node.path.name == "test_frontend.py" and address[0] in {
            "127.0.0.1",
            "::1",
        }:
            return original_connect(sock, address)
        raise AssertionError("Tests must not make network requests")

    def no_connection(*args, **kwargs):
        raise AssertionError("Tests must not make network requests")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_connection)
