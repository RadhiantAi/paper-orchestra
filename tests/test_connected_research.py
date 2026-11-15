import json

import pytest

from utils.connected_sources import BraveSearchSource, MCPSource, ZoteroSource
from utils.literature_discovery import DiscoveryConfig, DiscoveryEngine
from utils.literature_enrichment import check_integrity, fetch_pmc
from utils.literature_sources import (
    BudgetExceeded,
    LiteratureRecord,
    SearchPage,
    SourceError,
)
from utils.search_plan import chase_citations, run_search_plan


def test_citation_chasing_preserves_success_before_budget_failure():
    transport = Transport([
        {"id": "https://openalex.org/W1", "referenced_works": ["https://openalex.org/W2", "https://openalex.org/W3"]},
        {"id": "https://openalex.org/W2", "title": "Recovered reference"},
        BudgetExceeded("budget_exhausted"),
    ])
    engine = DiscoveryEngine(transport=transport)
    results = chase_citations("10.1/seed", engine, 5)
    assert len(results) == 1
    assert results[0].title == "Recovered reference"
    assert engine.report["citation_chasing"][0]["status"] == "failed_or_budget_exhausted"


def test_connector_file_change_changes_resume_fingerprint(tmp_path):
    collection = tmp_path / "selected.json"
    collection.write_text("[]")
    first = DiscoveryEngine(DiscoveryConfig(collection_path=str(collection)))
    collection.write_text('[{"title":"Changed"}]')
    second = DiscoveryEngine(DiscoveryConfig(collection_path=str(collection)))
    assert first.input_fingerprints != second.input_fingerprints


class Transport:
    def __init__(self, responses):
        self.responses, self.calls, self.requests_used = list(responses), [], 0

    def remaining(self):
        return 100

    def get(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        self.requests_used += 1
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    request = get


def record(**kw):
    return LiteratureRecord(
        **dict(
            title="Synthetic study",
            source="fixture",
            source_id="1",
            doi="10.1/a",
            pmcid="PMC123",
            **kw,
        )
    )


def test_pagination_keeps_earlier_pages_on_failure(tmp_path):
    class Source:
        name = "pages"

        def search(self, query, limit, cutoff, transport, cursor=None):
            if cursor:
                raise BudgetExceeded("budget_exhausted")
            return SearchPage([record()], total=20, truncated=True, next_cursor="2")

    engine = DiscoveryEngine(
        DiscoveryConfig(sources=("pages",), max_pages=3), extra_sources=[Source()]
    )
    assert len(engine.search("query")) == 1
    assert engine.save_report(tmp_path)["status"] == "partial"


def test_search_variants_screening_and_dedup():
    class Source:
        name = "fixture"

        def search(self, *args):
            return SearchPage([record(abstract="Adult synthetic evidence")])

    engine = DiscoveryEngine(
        DiscoveryConfig(sources=("fixture",)), extra_sources=[Source()]
    )
    assert (
        len(run_search_plan(engine, ["query", "alternate"], required_terms=["adult"]))
        == 1
    )
    assert not run_search_plan(engine, ["third"], excluded_terms=["adult"])
    assert engine.report["screening"][-1]["reason"] == "excluded_terms: adult"


def test_pmc_requires_rights_and_preserves_location():
    xml = b'<OAI-PMH><GetRecord><record><metadata><article><front><article-meta><article-id pub-id-type="pmc">123</article-id><permissions><license>CC BY 4.0</license></permissions></article-meta></front><body><sec><title>Results</title><p>Five synthetic samples.</p></sec></body></article></metadata></record></GetRecord></OAI-PMH>'
    r = record()
    assert fetch_pmc(r, Transport([xml]))["status"] == "retrieved"
    assert r.passages[0]["section"] == "Body / Results"
    assert r.passages[0]["page"] is None
    no_rights = xml.replace(
        b"<permissions><license>CC BY 4.0</license></permissions>", b""
    )
    assert fetch_pmc(record(), Transport([no_rights]))["status"] == "unavailable"
    with pytest.raises(SourceError):
        fetch_pmc(record(), Transport([xml.replace(b">123<", b">456<")]))


def test_integrity_unknown_is_never_clean_and_relations_preserved():
    assert (
        check_integrity(record(), Transport([{"message": {"DOI": "10.1/a"}}]))["status"]
        == "unknown"
    )
    work = {
        "DOI": "10.1/a",
        "updated-by": [{"type": "retraction", "source": "retraction-watch"}],
        "relation": {"is-preprint-of": [{"id": "10.1/published", "id-type": "doi"}]},
    }
    report = check_integrity(record(), Transport([{"message": work}]))
    assert report["status"] == "retracted" and report["version_relations"]
    assert (
        check_integrity(record(), Transport([SourceError("http_503")]))["reason"]
        == "lookup_failed"
    )


def test_zotero_selected_library_only_and_web_snippets_not_evidence(monkeypatch):
    t = Transport(
        [
            [
                {
                    "key": "ABCDEFGH",
                    "data": {
                        "title": "Paper",
                        "date": "2020",
                        "itemType": "journalArticle",
                    },
                }
            ]
        ]
    )
    source = ZoteroSource("zotero", "groups/123", "ABCDEFGH")
    assert source.search("query", 10, None, t).records[0].year == 2020
    assert "/groups/123/collections/ABCDEFGH/items/top" in t.calls[0][0][1]
    with pytest.raises(ValueError):
        ZoteroSource("z", "users/../../private")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "fixture-key")
    t = Transport(
        [
            {
                "web": {
                    "results": [
                        {
                            "title": "Result",
                            "url": "https://example.org",
                            "description": "Misleading snippet",
                        }
                    ]
                }
            }
        ]
    )
    r = BraveSearchSource().search("query", 10, None, t).records[0]
    assert r.evidence_level == "metadata" and not r.abstract


def test_mcp_handshake_readonly_tool_and_structured_records():
    results = [
        dict(protocolVersion="2025-06-18"),
        {},
        dict(tools=[{"name": "search", "annotations": {"readOnlyHint": True}}]),
        dict(
            structuredContent={
                "records": [
                    {
                        "title": "Result",
                        "source": "mcp",
                        "source_id": "1",
                        "url": "https://example.org",
                    }
                ]
            }
        ),
    ]
    t = Transport(
        [
            (
                json.dumps({"jsonrpc": "2.0", "id": i + 1, "result": result}).encode(),
                {"Mcp-Session-Id": "fixture"},
            )
            for i, result in enumerate(results)
        ]
    )
    source = MCPSource("connector", "https://example.org/mcp", "search")
    assert len(source.search("query", 5, None, t).records) == 1
    assert [call[1]["body"]["method"] for call in t.calls] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert t.calls[-1][1]["body"]["params"]["name"] == "search"
    with pytest.raises(ValueError):
        MCPSource("bad", "https://user:secret@example.org/mcp", "search")


def test_mcp_refuses_mutating_tool():
    t = Transport(
        [
            (b'{"id":1,"result":{"protocolVersion":"2025-06-18"}}', {}),
            (b"", {}),
            (
                b'{"id":3,"result":{"tools":[{"name":"send","annotations":{"readOnlyHint":false}}]}}',
                {},
            ),
        ]
    )
    with pytest.raises(SourceError, match="readonly"):
        MCPSource("mcp", "https://example.org/mcp", "send").search("q", 1, None, t)
