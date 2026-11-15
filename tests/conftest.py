import socket

import pytest


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch, request):
    # Positive adapter fixtures exercise the online branch against mocks only.
    # The socket denial below still prevents all external network access.
    monkeypatch.setenv("PAPER_NETWORK_MODE", "online")
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "SEMANTIC_SCHOLAR_API_KEY",
        "NCBI_API_KEY",
        "OPENALEX_API_KEY",
        "LITERATURE_CONTACT_EMAIL",
        "LITERATURE_SOURCES",
        "LITERATURE_RESULTS_PER_SOURCE",
        "LITERATURE_MAX_REQUESTS",
        "LITERATURE_MAX_SECONDS",
        "LITERATURE_REQUEST_TIMEOUT",
        "LITERATURE_REQUIRE_ALL_SOURCES",
        "LITERATURE_COLLECTION_PATH",
        "VERTEX_AI_PROJECT",
        "VERTEX_AI_LOCATION",
        "LLM_API_KEY",
        "LLM_BASE_URL",
        "PAPER_WRITER_MODEL",
        "PAPER_REVIEW_MODEL",
        "PAPER_SEARCH_MODEL",
        "PAPER_MAX_OUTPUT_TOKENS",
        "PAPER_MODEL_POLICY",
        "PAPER_MAX_COST_USD",
        "PAPER_MAX_MODEL_CALLS",
        "PAPER_PROBE_MODE",
        "PAPER_TEX_IMAGE",
        "SMTP_EMAIL",
        "SMTP_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    original_connect = socket.socket.connect

    def no_network(sock, address):
        # Windows asyncio creates a loopback socket pair for AppTest's event loop.
        if request.node.path.name in {
            "test_frontend.py",
            "test_research_review_ui.py",
            "test_project_review_ui.py",
        } and address[0] in {
            "127.0.0.1",
            "::1",
        }:
            return original_connect(sock, address)
        raise AssertionError("Tests must not make network requests")

    def no_connection(*args, **kwargs):
        raise AssertionError("Tests must not make network requests")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_connection)
