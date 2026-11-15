# Research trial fork

Public. Updated 14 November 2026.

This fork adds provider choice and local draft safeguards to Google Research's PaperOrchestra. It has not been validated for clinical research or journal submission. Upstream attribution and the Apache 2.0 licence are retained.

## Model configuration

The writing pipeline, including outline generation, literature writing, peer review and visual formatting review, uses one provider interface. The command line and demo accept separate models for writing, review and literature ranking.

| Prefix | Connection | Required configuration |
| --- | --- | --- |
| `openai:MODEL_ID` | OpenAI Chat Completions | `OPENAI_API_KEY` |
| `anthropic:MODEL_ID` | Anthropic Messages | `ANTHROPIC_API_KEY` |
| `gemini:MODEL_ID` | Gemini API or Vertex AI | `GEMINI_API_KEY`, or a Vertex project, location and application-default credentials |
| `compatible:MODEL_ID` | An OpenAI-compatible Chat Completions endpoint | `LLM_BASE_URL`; `LLM_API_KEY` where the server requires it |

Set `PAPER_WRITER_MODEL` in `.env`. `PAPER_REVIEW_MODEL` and `PAPER_SEARCH_MODEL` default to the writer when blank. Command-line arguments override these values. Model IDs are passed through; the application does not maintain a fixed model catalogue. Existing unprefixed Gemini, Claude and GPT model names remain recognised.

Credentials are checked only for selected providers. Selecting OpenAI does not require Gemini or Anthropic credentials. Compatible endpoints use their own key, never the OpenAI key. Remote endpoints require HTTPS; local HTTP endpoints are allowed. Select an endpoint whose data handling you have approved.

Writer models need image support when figures are supplied. Review models need image support for page-layout checks. The literature-ranking model only needs text and JSON output. A provider connection does not establish that every model it hosts has these capabilities. There is no silent switch to another provider or text-only review. Requests that are blocked, truncated or malformed fail.

PDF review sends extracted text and rendered page images through the selected provider. `PAPER_MAX_OUTPUT_TOKENS` controls the requested output limit and `PAPER_API_TIMEOUT` the request timeout in seconds. Adjust these to your selected model's limits. Costs and live model availability have not been tested.

## Literature discovery

Discovery queries PubMed, OpenAlex, Semantic Scholar and Crossref by default. Sources are configurable and independent of model choice. A common adapter interface supports additional sources, and an explicitly selected collection export can supply records and permitted full text. See [DISCOVERY.md](DISCOVERY.md) for limits, provenance and partial-coverage reporting.

On 14 November 2026, a small public-API check returned records from PubMed, OpenAlex and Crossref. Semantic Scholar returned HTTP 429, which was recorded as partial coverage. Subsequent validation is offline only. No live model calls were made.

Metadata matching does not verify that a cited claim is supported. The evidence-review table proposes passages for human checking, with abstract/full-text distinctions and missing-reference flags.

## Reliable runs and editable outputs

The pipeline saves separate run folders and hash-checked stage checkpoints. It can resume completed work, records model usage, checks declared capabilities and bounds calls and estimated spending. Generated TeX is compiled only in a restricted Docker container. A general medical template and editable Word export are included. Read [RELIABILITY.md](RELIABILITY.md) before starting a run.

## Draft safeguards

- The Semantic Scholar key is no longer printed. Lookup failures do not print raw request exceptions.
- Generated Python execution is removed. The CLI and plotting entry point reject automatic figure generation. Supply checked figures and `figures/info.json` containing their filenames and captions.
- The demo saves supplied figure captions. It supports launching the worker on Windows without a visible console.
- Automatic email delivery is disabled, including direct calls to the old helper.
- Every PDF compiled through the application receives a visible draft label. The LaTeX source remains editable and is not watermarked; recompiling it outside the application will not retain that label.
- The CLI returns a failure exit code when generation fails. Failed peer or formatting review is not counted as completed review.

For an initial trial, use public or synthetic material. No patient data, live model calls or email sends were used to validate these changes.

## Checks

Install the development requirements, then run:

```text
python -m pytest -q
ruff check --select F821,F822,F823,E9 .
git diff --check
```

Tests block external network calls. They cover all four provider adapters, mixed-provider orchestration, text/image/PDF requests, malformed and truncated responses, credential isolation, invalid literature IDs, plotting rejection, disabled email, draft labels and the Streamlit configuration screen. Windows AppTest permits its internal loopback socket pair.

The validation suite includes the mixed-provider workflow, source adapters, preserved runs, Word export and negative fixtures for the safety controls. See RELIABILITY.md for commands and the actual-compilation prerequisite.

The complete workflow test uses synthetic source material and real agent/PDF code, with model responses, literature sources and LaTeX executables replaced by fixtures. Passing it does not establish live API access, actual TeX compilation or manuscript quality. Those checks belong to the separately approved trial.

Provider API references checked on 14 November 2026: [OpenAI Chat Completions](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create), [Anthropic Messages](https://platform.claude.com/docs/en/api/messages) and [Google Gen AI Python SDK](https://googleapis.github.io/python-genai/).
