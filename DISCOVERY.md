# Literature discovery

Public. Updated 14 November 2026.

Discovery is independent of the writing model. The default sources are PubMed,
OpenAlex, Semantic Scholar and Crossref. Each query searches one bounded page
from each enabled source. This is broad discovery, not an exhaustive search or
a systematic-review protocol.

## Configure and run

Set these optional values in `.env`:

```text
LITERATURE_SOURCES=pubmed,openalex,semantic_scholar,crossref
LITERATURE_RESULTS_PER_SOURCE=20
LITERATURE_MAX_REQUESTS=80
LITERATURE_MAX_SECONDS=180
LITERATURE_REQUEST_TIMEOUT=20
LITERATURE_REQUIRE_ALL_SOURCES=false
NCBI_API_KEY=
OPENALEX_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
LITERATURE_CONTACT_EMAIL=
```

Source keys and contact email are optional; provider access rules and rate limits
still apply. No registration, email, subscription or purchase is performed.
The request budget covers all source HTTP requests in one manuscript run,
including PubMed's separate search and record retrieval. The elapsed-time budget
starts with discovery. Existing requests have bounded timeouts; it is not an OS
process-kill deadline. Requests are paced per source within a process. Separate
processes do not share rate limits. Repeated queries use an in-memory cache.

The demo has a source selector. The manuscript CLI accepts
`--literature_sources pubmed,openalex,crossref`. For discovery without a model:

```text
python literature_search_cli.py "mammography screening" --output_dir paper_output_search --limit 5 --cutoff 2026-11-14
```

Use ordinary topic queries for multi-source discovery. Database-specific Boolean
syntax is not translated between services. A month cutoff includes the entire
month; unknown publication dates are retained with a warning.

The discovery-only CLI exits 0 when configured queries succeed with results,
1 when no eligible records are returned, and 2 for partial source access.
Result caps are always reported, including on exit 0. Strict mode rejects any
source failure. Otherwise drafting can continue with available records that have
an abstract or full text. Metadata-only records remain in the retrieval report.

## Evidence and coverage

Each manuscript's `literature_agent_output` contains:

- `discovery_report.json`: enabled sources, queries, timestamps, limits, totals,
  exclusions, failures and model selections.
- `retrieved_records.json`: original normalised records, including metadata-only
  records and records excluded after the cutoff.
- `citation_map.json`: selected evidence, DOI/PMID identifiers, provenance and
  any conflicting metadata carried into the manuscript.

The standalone CLI also saves `merged_records.json`. Duplicate records are
matched by DOI or PMID, then exact normalised title and year. Conflicting
identifiers remain separate. Metadata conflicts are recorded. No fuzzy match
is treated as proof that two papers are identical.

An abstract is kept in full. A full-text URL does not mean its content was
retrieved. Evidence is labelled `metadata`, `abstract` or `full_text`; neither
source existence nor this label establishes support for a manuscript claim.

## Connected collections and new adapters

Chat connectors are not automatically available to a standalone Python process.
For an explicitly selected export, add `collection` to `LITERATURE_SOURCES` and
set `LITERATURE_COLLECTION_PATH` to a JSON file containing a list of
`LiteratureRecord` objects. For example:

```json
[
  {
    "title": "Synthetic demonstration record",
    "source": "selected_reference_library",
    "source_id": "demo-1",
    "url": "https://example.invalid/demo-1",
    "year": 2026,
    "abstract": "Synthetic text for testing only.",
    "authors": []
  }
]
```

This adapter searches the supplied export by word overlap. It never scans folders,
follows URLs or connects to a cloud account. Full text can be supplied in
`full_text` with a `rights` note. Selecting a collection permits its retained text
to enter the chosen model's ranking and drafting requests. Use only material
authorised for that endpoint.

Applications can register a web, repository or connector adapter through
`DiscoveryEngine(config, extra_sources=[adapter])`, then pass the engine to
`write_single_paper(discovery_engine=engine)`. Implement `LiteratureSource.search`
and return `SearchPage` with normalised records, total/cap information and fixed
warning codes. Use the supplied transport for network calls so the request and
time budgets apply. Adapters are trusted application code, not dynamically loaded
from documents. A live MCP or web-search integration still needs its own adapter
and configured access; the extension interface does not grant credentials.

## Verification

An unauthenticated, five-request check on 14 November 2026 retrieved two records
each from PubMed, OpenAlex and Crossref. Semantic Scholar returned HTTP 429.
The report correctly marked partial coverage. Later validation is offline only,
as requested. No live model calls were made.

API references checked on 14 November 2026:
[NCBI E-utilities](https://eutilities.github.io/site/Quick_Start/eu_quick/),
[OpenAlex](https://help.openalex.org/api/),
[Semantic Scholar](https://api.semanticscholar.org/api-docs/graph),
[Crossref](https://www.crossref.org/documentation/retrieve-metadata/rest-api/).
