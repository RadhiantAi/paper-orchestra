# Running and reviewing research drafts

Public. Updated 14 November 2026.

## Setup

Use Python 3.14. `requirements-lock.txt` records the exact versions used for local
validation, including development tools. Install with:

```text
python -m pip install -r requirements-lock.txt
python -m pip check
docker build -f docker/tex.Dockerfile -t paper-orchestra-tex:local .
```

Docker must be running. Image building requires package downloads; manuscript
compilation uses the already built image, never pulls an image and has no network
access. For repeatable TeX environments, retain the built image and configure its
immutable image ID in `PAPER_TEX_IMAGE`. The Dockerfile's distribution packages
are not locked to a historical package snapshot.

Copy `.env.example` to `.env` and `model-policy.example.json` to `model-policy.json`.
Use actual model IDs, capabilities, context/output limits, a conservative image
token bound and current per-million-token prices for each selected model. The
example is illustrative, with zero prices for a local endpoint; it is not a
verified capability catalogue or a price list. Both local configuration files
are ignored by Git.

`PAPER_MAX_COST_USD` defaults to zero. Set an explicitly authorised estimate limit
before using a paid endpoint. `PAPER_MAX_MODEL_CALLS` defaults to 80. A request
reserves the configured maximum input charge plus its maximum output charge
before network access. Reported token usage replaces that reservation when
available. Failed or unknown outcomes retain it. Provider SDK retries are
disabled; agent retries count against the same run budget. Pricing, model-side
token accounting and endpoint behaviour remain external assumptions, so this is
an estimated spending control, not a billing guarantee. Use provider-side billing
limits as well where available.

The normal run first checks local compiler/Word tools and the declared model
roles, then performs small live text/JSON and image probes. Probe calls count
towards the budget. `PAPER_PROBE_MODE=declared` skips live probes and explicitly
records that capabilities have only been declared. It does not make subsequent
drafting offline. No live model calls were used during this implementation;
validation was kept offline at the user's request.

## Saved runs and resume

Every manuscript gets a new `output_dir/runs/<timestamp-id>` folder. Earlier
drafts are retained. `latest_run.json` points the demo to the current output.
Input and template snapshots are saved in the run. Stages are preflight, outline,
literature, draft, review and exports. Completed stages carry file hashes.

To resume, pass the same inputs, template and model configuration plus:

```text
--output_dir path/to/project --resume_run path/to/project/runs/RUN_ID
```

Changed inputs, templates, code, model settings or completed stage files reject
resume. Create a new run to preserve human edits. Spending and call ceilings can
be raised deliberately on resume; earlier usage remains in `model_usage.json`.
A process lock prevents simultaneous execution of the same run. Review attempts
are retained separately. If review fails, resume repeats that stage; it does not
re-run completed discovery or drafting. The demo launches new runs; resume is
currently a command-line function.

## Compilation

Generated TeX is compiled in a disposable Docker container with no network,
a read-only root filesystem, dropped capabilities, an unprivileged user and
CPU/memory/process limits. Only copied TeX, bibliography, style and figure files
are mounted. Environment credentials and arbitrary project files are not mounted.
Shell escape is explicitly disabled. A timeout removes only that named temporary
container. A nonzero command, missing log/PDF or unresolved references rejects
the build. A failed build does not replace an existing output PDF.

There is no automatic fallback to host compilation. Docker availability and a
compatible local image are prerequisites. Container isolation reduces exposure;
it does not certify arbitrary TeX or the host Docker installation as secure.

## Medical drafting and evidence review

Use `templates/medical` for a general medical manuscript, or select `medical` in
the demo. It includes structured abstract prompts, methods/results/discussion
sections and declarations. Missing ethics, consent, funding or authorship details
remain placeholders. It is not a journal-specific template or a certification of
clinical or reporting-checklist compliance.

Final outputs include `final_paper.pdf`, `reviewed/main.tex`, `manuscript.docx`,
`evidence_review.csv` and `evidence_review.json`. Word conversion uses Pandoc's
sandbox and adds a visible draft header. Inspect equations, tables, figures and
references against the PDF; conversion warnings are saved in
`word_export_report.json`.

The evidence table extracts citation-bearing paragraphs and some uncited numeric
statements. It links citation keys to DOI/PMID/source URLs and offers exact
candidate passages by lexical matching. It never marks a claim verified or
supported automatically. Abstract-only records need full-text review; absent
references and missing passages are flagged. Some uncited claims can remain
outside this heuristic report. Human review remains necessary.

An explicitly selected collection may supply full text or a `pdf_path` relative
to its JSON file. PDFs must stay inside that selected folder, carry a `rights`
note, be at most 25 MB/100 pages and contain extractable text. Page labels are
retained. The tool does not bypass publisher access controls or run OCR. See
[DISCOVERY.md](DISCOVERY.md) for source selection and coverage reporting.

## Validation

```text
python -m pytest -q
ruff check --select F821,F822,F823,E9 .
git diff --check
```

Tests use positive and negative fixtures for spending limits, missing model
capabilities, failed compilation, unresolved references, edited checkpoints,
source failures and evidence labels. The complete synthetic workflow runs real
agent code, PDF processing and Word conversion with model responses, search and
TeX executables replaced by fixtures. It also resumes without further model calls.

GitHub Actions defines Windows/Linux tests and a separate real containerised TeX
test. To run that TeX test locally after building the image, set
`RUN_TEX_INTEGRATION=1` and run `python -m pytest tests/test_reliability.py -k real_isolated_tex`.
On 14 November 2026, the local suite passed 86 tests with one real-TeX test skipped. Dependency checks and critical Python lint checks passed.

The local Docker engine was not running during implementation, so that real TeX
test was skipped locally. A passing fixture is not evidence of actual TeX execution.

Implementation references checked on 14 November 2026:
[Docker container controls](https://docs.docker.com/engine/containers/run/) and
[Pandoc sandbox](https://pandoc.org/MANUAL.html).
