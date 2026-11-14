# Research review and connected discovery

These additions support a researcher checking a draft. A passing numerical check,
source lookup or benchmark does not establish scientific validity or readiness for submission.

## Offline and chat-assisted work

Keep unpublished manuscripts and correspondence outside this public checkout.
Use this exchange route when an interactive host supplies the model and connectors:

```powershell
python research_review_cli.py import C:\private\manuscript.md --output C:\private\review --denominator 80
streamlit run review_app.py -- --workspace C:\private\review
python research_review_cli.py export C:\private\review --output C:\private\revision-2.md
python research_benchmark.py
```

The import records its source hash and `chat_assisted` execution mode. It makes no
model API calls. This is a separate review workflow, not a claim that the automatic
writer ran. Re-exporting sections does not automatically regenerate Word/PDF files.
Use a new output path for each draft. The optional `--facts aggregate-facts.json`
accepts a list of facts containing `id`, `source`, `approved_by`, `value`, `unit`,
optional `ci`, and `occurrences` (exact `quote`, `value`, `unit`, optional `ci`).
Optional `subset_of` and `sum_of` fields refer to other fact IDs. Never supply
patient rows. Empty approval/source fields are flagged. Quote mapping is explicit;
the tool does not infer which number belongs to which biological variable.

For a chat-assisted Markdown draft, `export_word(source, destination,
source_format="markdown")` from `utils.research_exports` converts directly to Word.
Both LaTeX and Markdown exports check recognised count/percentage pairs before
promoting the result. A failed preservation check stops the export; it does not
silently repair scientific content. Render and inspect the exported document.

Count/percentage checks use the supplied denominator as a hypothesis and allow
rounding at the printed precision. They never replace the study denominator.
Unrecognised prose, tables without count/percentage pairs and unmapped numerical
claims remain outside this check. No statistical analyses are invented or rerun.

The evidence screen displays claims, candidate passages, section/paragraph/page
locations when available, and source URLs. Accept/reject/flag requires a reviewer
and reason. Decisions are bound to the complete evidence row. Changed evidence
invalidates the decision. Revisions preserve other sections, show textual changes
and flag changed numbers/citations. Acceptance clears the changed section's approval
and marks derived evidence/numerical reports stale. Regenerate these before further
review. These are local audit records, not authenticated institutional signatures.

`research_benchmark.py` runs three synthetic adversarial cases, including incorrect
denominators, invented claims, missing evidence and a retracted source. It reports
evidence recall, numerical errors, invented claim IDs, evidence defects and
correction success. `--candidates file.json` evaluates externally generated outputs
using the same case schema. This deterministic harness is not a live model ranking
or an automated semantic entailment assessment.

## Deeper searches

```powershell
python literature_search_cli.py "topic" --alternate "synonym query" --pages 3 --limit 20 --require-term "term" --exclude-term "animal" --chase-doi "10.example/seed" --chase-limit 10 --enrich --output_dir C:\private\search
```

Pages, variants, reference lists and citing papers share the same request/time
budget. Citation chasing uses one generation through OpenAlex. Required/excluded
terms use literal case-insensitive matching, with an explicit reason per record.
This is screening for review, not a systematic-review eligibility decision. Missing
dates, truncated searches and failed later pages remain visible. Earlier successful
pages are retained. PubMed's 10,000-result window requires narrower queries.

## Connected sources

Copy `connectors.example.json` to ignored `connectors.json`, retain only sources
you have selected, and set `LITERATURE_CONNECTOR_CONFIG` to its absolute path (or
pass `--connectors`). Include the configured names in `--sources` or
`LITERATURE_SOURCES`. Configuration is operator-controlled, never model-generated.

- `web`: read-only Brave Search API, with `BRAVE_SEARCH_API_KEY`. Search snippets
  remain metadata, never automatically promoted to abstract or full-text evidence.
- `zotero`: an exact user/group library and optional collection, with optional
  `ZOTERO_API_KEY`. Reads metadata and abstracts; it does not import, alter or crawl
  attachments or the rest of a user's libraries.
- `mcp`: a selected HTTPS Streamable HTTP server and one explicitly selected search
  tool. It negotiates MCP 2025-06-18 and requires the tool's `readOnlyHint` annotation.
  The operator must independently trust that server/tool; annotations are not a
  security boundary. The host obtains/refreshes OAuth tokens and supplies them via
  the configured environment variable. The client does not discover or invoke other
  tools, run local servers, execute returned instructions or perform writes.
  The selected tool must return structured content with `records` in the
  `LiteratureRecord` schema and optional `total`/`next_cursor`. Other server schemas
  need a host-side mapping. JSON and bounded SSE responses are accepted. Stdio,
  OAuth login, automatic token refresh and paginated tool inventories are not
  implemented. Missing configuration/unsupported servers fail visibly.

Connector credentials may incur provider charges if the operator runs those
sources; the HTTP budget caps requests, not a provider invoice. Offline tests never
use these credentials. No connected search is enabled merely by installing a plugin
in an interactive assistant.

## Full text and publication status

`--enrich`, or `LITERATURE_ENRICH_SELECTED=true` in the automatic writer, retrieves
eligible PMC XML using the documented OAI-PMH API. It requires rights metadata,
checks returned identifiers, and stores section/paragraph anchors. XML has no PDF
page numbers: these are explicitly unavailable. Unavailable or restricted full text
is reported, with no paywall bypass or automatic publisher HTML scraping.

Crossref production `/works/{doi}` checks `updated-by`, `update-to`, Retraction Watch
source metadata and preprint/version relations. No updates or failed lookups mean
`unknown`, never 'not retracted'. Relations flag possible published versions but do
not silently substitute them. The automatic writer excludes records marked
retracted/withdrawn from selected evidence; the search report retains them for
inspection. Title/DOI conflicts remain visible. Status coverage depends on deposited
metadata and is not a complete research-integrity guarantee.

Primary documentation checked 14 November 2026:

- https://pmc.ncbi.nlm.nih.gov/tools/oai/
- https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/
- https://www.crossref.org/labs/retraction-watch/ (points to production services)
- https://www.zotero.org/support/dev/web_api/v3/basics
- https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- https://api-dashboard.search.brave.com/app/documentation/web-search/query
