import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from utils.literature_adapters import (
    PubMedSource,
    OpenAlexSource,
    SemanticScholarSource,
    CrossrefSource,
    CollectionSource,
)
from utils.literature_discovery import DiscoveryConfig, DiscoveryEngine
from utils.literature_sources import (
    BudgetExceeded,
    LiteratureRecord,
    SearchPage,
    SearchTransport,
    SourceError,
    cutoff_end,
    merge_records,
)


PUBMED_XML = b"""<PubmedArticleSet><PubmedArticle>
<MedlineCitation><PMID>123</PMID><Article><ArticleTitle>Shared <i>study</i></ArticleTitle>
<Journal><Title>Test Journal</Title><JournalIssue><Volume>4</Volume><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
<Abstract><AbstractText Label="METHODS">A method.</AbstractText><AbstractText Label="RESULTS">A result.</AbstractText></Abstract>
<AuthorList><Author><ForeName>A</ForeName><LastName>Researcher</LastName></Author></AuthorList>
</Article></MedlineCitation><PubmedData><ArticleIdList>
<ArticleId IdType="doi">10.1234/shared</ArticleId><ArticleId IdType="pmc">PMC123</ArticleId>
</ArticleIdList></PubmedData></PubmedArticle></PubmedArticleSet>"""


class FixtureTransport:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.requests_used = 0
        self.calls = []

    def remaining(self):
        return 100

    def get(self, *args, **kwargs):
        self.requests_used += 1
        self.calls.append((args, kwargs))
        result = self.payloads.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def paper(**kwargs):
    return LiteratureRecord(
        **{
            "title": "Shared study",
            "source": "fixture",
            "source_id": "1",
            "year": 2020,
            "abstract": "Evidence",
            **kwargs,
        }
    )


class FixtureSource:
    def __init__(self, name, records=None, error=None, truncated=False):
        self.name, self.records, self.error, self.truncated = (
            name,
            records or [],
            error,
            truncated,
        )
        self.calls = 0

    def search(self, *args):
        self.calls += 1
        if self.error:
            raise self.error
        return SearchPage(
            self.records, total=len(self.records), truncated=self.truncated
        )


def engine_for(*sources, **config):
    return DiscoveryEngine(
        DiscoveryConfig(sources=tuple(s.name for s in sources), **config),
        extra_sources=sources,
    )


def test_pubmed_hydrates_ids_with_structured_abstract_and_provenance_fields():
    transport = FixtureTransport(
        [{"esearchresult": {"idlist": ["123"], "count": "5"}}, PUBMED_XML]
    )
    result = PubMedSource().search("test", 2, "2020-12-31", transport)
    record = result.records[0]
    assert record.title == "Shared study"
    assert record.pmid == "123" and record.pmcid == "PMC123"
    assert record.doi == "10.1234/shared"
    assert record.authors == ["A Researcher"]
    assert record.abstract == "METHODS: A method.\nRESULTS: A result."
    assert result.truncated and result.total == 5
    assert transport.calls[0][1]["params"]["maxdate"] == "2020/12/31"
    assert transport.calls[1][1]["params"]["id"] == "123"


def test_pubmed_zero_results_does_not_fetch_or_hide_query_warning():
    transport = FixtureTransport(
        [
            {
                "esearchresult": {
                    "idlist": [],
                    "count": "0",
                    "warninglist": {"outputmessages": ["No items found"]},
                }
            }
        ]
    )
    page = PubMedSource().search("test", 1, None, transport)
    assert page.records == [] and transport.requests_used == 1
    assert page.warnings == ["pubmed_query_warning"]


def test_openalex_reconstructs_abstract_without_claiming_pdf_retrieval():
    transport = FixtureTransport(
        [
            {
                "meta": {"count": 4},
                "results": [
                    {
                        "id": "https://openalex.org/W1",
                        "title": "Shared study",
                        "publication_year": 2020,
                        "doi": "https://doi.org/10.1234/SHARED",
                        "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/123"},
                        "abstract_inverted_index": {"Evidence": [0], "matters": [1]},
                        "primary_location": {
                            "pdf_url": "https://example.invalid/paper.pdf",
                            "license": "cc-by",
                        },
                    }
                ],
            }
        ]
    )
    result = OpenAlexSource().search("test", 2, "2020-12-31", transport)
    record = result.records[0]
    assert record.abstract == "Evidence matters" and record.evidence_level == "abstract"
    assert record.full_text == "" and record.full_text_url
    assert record.doi == "10.1234/shared" and record.pmid == "123"
    assert transport.calls[0][1]["params"]["filter"] == "to_publication_date:2020-12-31"


def test_crossref_metadata_is_preserved_even_without_abstract():
    transport = FixtureTransport(
        [
            {
                "message": {
                    "total-results": 1,
                    "items": [
                        {
                            "DOI": "10.1234/shared",
                            "title": ["Shared study"],
                            "published": {"date-parts": [[2020, 2, 29]]},
                        }
                    ],
                }
            }
        ]
    )
    record = CrossrefSource().search("test", 1, None, transport).records[0]
    assert record.evidence_level == "metadata" and record.year == 2020
    assert record.publication_date == "2020-02-29"


def test_semantic_scholar_external_ids_are_retained():
    transport = FixtureTransport(
        [
            {
                "total": 1,
                "data": [
                    {
                        "paperId": "abc",
                        "title": "Shared study",
                        "year": 2020,
                        "externalIds": {"DOI": "10.1234/shared", "PubMed": "123"},
                        "abstract": "Evidence",
                    }
                ],
            }
        ]
    )
    record = (
        SemanticScholarSource().search("test", 1, "2020-12-31", transport).records[0]
    )
    assert record.pmid == "123" and record.doi == "10.1234/shared"


def test_dedup_merges_ids_and_keeps_all_source_provenance():
    a = paper(doi="10.1234/shared", provenance=[{"source": "one"}])
    b = paper(
        source="two",
        doi="https://doi.org/10.1234/SHARED",
        pmid="123",
        abstract="Longer evidence",
        provenance=[{"source": "two"}],
    )
    result = merge_records([a, b])
    assert len(result) == 1
    assert result[0].pmid == "123" and result[0].abstract == "Longer evidence"
    assert len(result[0].provenance) == 2


def test_dedup_keeps_conflicting_identifiers_separate():
    assert len(merge_records([paper(doi="10.1/a"), paper(doi="10.1/b")])) == 2
    assert len(merge_records([paper(year=2020), paper(year=2021)])) == 2
    assert len(merge_records([paper(year=None), paper(year=None)])) == 2


def test_dedup_tracks_conflicting_metadata_instead_of_hiding_it():
    result = merge_records([paper(doi="10.1/a"), paper(doi="10.1/a", year=2021)])
    assert result[0].conflicts == [
        {"field": "year", "retained": 2020, "alternative": 2021, "source": "fixture"}
    ]


def test_partial_failure_remains_visible_and_does_not_require_semantic_scholar(
    tmp_path,
):
    good = FixtureSource("connected", [paper()])
    bad = FixtureSource("failed", error=RuntimeError("secret=must-not-log"))
    engine = engine_for(good, bad)
    assert len(engine.search("test")) == 1
    report = engine.save_report(tmp_path)
    assert report["status"] == "partial"
    assert report["coverage"][1]["status"] == "failed"
    assert "must-not-log" not in (tmp_path / "discovery_report.json").read_text()
    saved = json.loads((tmp_path / "retrieved_records.json").read_text())
    assert saved[0]["provenance"][0]["query"] == "test"


def test_complete_failure_and_empty_success_are_distinct(tmp_path):
    engine = engine_for(FixtureSource("down", error=SourceError("http_429")))
    assert engine.search("test") == []
    assert engine.save_report(tmp_path)["status"] == "partial"
    empty = engine_for(FixtureSource("empty"))
    assert empty.search("test") == []
    assert empty.save_report(tmp_path)["status"] == "completed_queries"


def test_strict_mode_rejects_missing_sources():
    engine = engine_for(
        FixtureSource("down", error=SourceError("http_503")), require_all_sources=True
    )
    with pytest.raises(RuntimeError, match="sources failed"):
        engine.search("test")


def test_repeated_query_uses_cache_without_sharing_mutable_records():
    source = FixtureSource("connected", [paper()])
    engine = engine_for(source)
    first = engine.search("test")
    first[0].title = "Changed by caller"
    assert engine.search("test")[0].title == "Shared study"
    assert source.calls == 1


def test_cutoff_includes_month_end_and_reports_exclusions(tmp_path):
    assert cutoff_end("2020-02") == "2020-02-29"
    source = FixtureSource(
        "connected",
        [
            paper(publication_date="2020-02-29"),
            paper(title="Later", publication_date="2020-03-01"),
        ],
    )
    engine = engine_for(source)
    assert len(engine.search("test", "2020-02")) == 1
    assert engine.save_report(tmp_path)["coverage"][0]["excluded_after_cutoff"] == 1


def test_capped_results_never_claim_exhaustive_coverage(tmp_path):
    engine = engine_for(FixtureSource("connected", [paper()], truncated=True))
    engine.search("test")
    assert engine.save_report(tmp_path)["status"] == "bounded"


def response_mock(payload=b"{}", status=200):
    return SimpleNamespace(
        __enter__=lambda self: self,
        __exit__=lambda *args: None,
        status_code=status,
        iter_content=lambda size: iter([payload]),
    )


def test_http_transport_enforces_budget_before_network(monkeypatch):
    request = Mock(side_effect=RuntimeError("synthetic-secret"))
    monkeypatch.setattr("utils.literature_sources.requests.get", request)
    transport = SearchTransport(max_requests=1)
    with pytest.raises(SourceError, match="request_or_response_failed"):
        transport.get("fixture", "https://example.invalid", interval=0)
    with pytest.raises(BudgetExceeded):
        transport.get("fixture", "https://example.invalid", interval=0)
    assert request.call_count == 1


def test_time_budget_prevents_new_requests(monkeypatch):
    transport = SearchTransport(max_seconds=1)
    monkeypatch.setattr(transport, "remaining", lambda: 0)
    request = Mock()
    monkeypatch.setattr("utils.literature_sources.requests.get", request)
    with pytest.raises(BudgetExceeded):
        transport.get("fixture", "https://example.invalid")
    request.assert_not_called()


def test_collection_requires_explicit_path_and_rights_for_full_text(tmp_path):
    with pytest.raises(SourceError, match="not_configured"):
        CollectionSource("").search("test", 1, None, None)
    path = tmp_path / "selected.json"
    record = paper(
        full_text="Allowed text", url="https://example.invalid/source"
    ).to_dict()
    path.write_text(json.dumps([record]))
    with pytest.raises(SourceError, match="rights"):
        CollectionSource(path).search("study", 1, None, None)
    record["rights"] = "User-approved text supplied for this project"
    path.write_text(json.dumps([record]))
    page = CollectionSource(path).search("study", 1, None, None)
    assert page.records[0].evidence_level == "full_text"


@pytest.mark.parametrize(
    "config",
    [
        {"sources": ()},
        {"sources": ("pubmed", "pubmed")},
        {"max_requests": 0},
        {"per_source_limit": 101},
    ],
)
def test_invalid_configuration_rejected(config):
    with pytest.raises(ValueError):
        DiscoveryConfig(**config)


def test_unknown_source_is_rejected_instead_of_silent_fallback():
    with pytest.raises(ValueError, match="Unknown literature"):
        DiscoveryEngine(DiscoveryConfig(sources=("not_registered",)))


def test_resumed_discovery_retains_request_budget(tmp_path):
    first = engine_for(FixtureSource("fixture", [paper()]), max_requests=2)
    first.search("test")
    first.transport.requests_used = 2
    first.save_report(tmp_path)
    resumed = engine_for(FixtureSource("fixture", [paper()]), max_requests=2)
    resumed.restore_report(tmp_path)
    with pytest.raises(BudgetExceeded):
        resumed.transport.get("fixture", "https://example.invalid")
    assert resumed.transport.requests_used == 2
