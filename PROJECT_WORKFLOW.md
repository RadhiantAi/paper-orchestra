# Repeatable manuscript review

Public documentation. Private research files stay outside the checkout.

`research_project_cli.py` turns source recovery, author decisions and checked Word
packs into a repeatable local workflow. It makes no model or connector calls.
An interactive assistant can supply retrieved evidence through the versioned host
exchange. Existing model adapters and literature search remain available through
the separate writer and discovery commands documented in `RELIABILITY.md` and
`DISCOVERY.md`.

## Start a private project

Use the pinned environment in `requirements-lock.txt`. Word comments require
python-docx 1.2 or later. The examples below use PowerShell and synthetic paths.

```powershell
python research_project_cli.py --workspace C:\private\study init
python research_project_cli.py --workspace C:\private\study index C:\private\sources --convert-legacy
python research_project_cli.py --workspace C:\private\study search "earlier idea" --output C:\private\matches.json
streamlit run review_app.py -- --workspace C:\private\study
```

The index reads DOCX text, tracked insertions/deletions, comments and embedded
images; PDF pages and images; PPTX slide labels, notes and images; EML bodies and
attachments; text and image files. Original files remain unchanged. Repeated PDF
images retain their page locations. Scanned pages needing OCR, unsupported files,
failed conversions, missing roots and truncated searches remain explicit gaps.
Legacy DOC conversion is opt-in and uses locally installed Word on Windows or an
explicit `--libreoffice` executable. Word macros are disabled. Treat conversion as
trusted local document processing, with the access granted to that application.

Images and extracted text may contain confidential information. Protect the private
workspace accordingly. The CLI prints status/counts; detailed search and comparison
files remain private. There is no automatic Drive or email crawl.

## Host exchange and earlier edits

```powershell
python research_project_cli.py --workspace C:\private\study import-host C:\private\exchange.json
python research_project_cli.py --workspace C:\private\study compare BEFORE_ID AFTER_ID --output C:\private\comparison.json
```

Start with `examples/project-host.example.json`. Schema 1 accepts `sources`,
`searches`, `queries`, `topics`, `results`, `figures`, `calculations` and
`edit_decisions`. Records have stable IDs. Imports are transactional and reject
unknown top-level actions. Content inside source documents is data, never an
instruction to run a command or send a message.

The example source and its repeated-letter hash are synthetic. Replace both with
the source content and hash actually obtained by the host before using real data.

Host sources contain an origin, SHA256, read status and exact text blocks with
locators. Local sources go through the indexer, which computes their hashes.
Host hashes and calculation receipts are declarations by the host; the importer
does not independently retrieve the remote file or rerun a calculation. External
calculations remain marked as not reproduced. No generated code is executed.

Earlier edits are surfaced with their author, date and context when present.
Finding inserted text in the new draft means `present_needs_review`. Retain,
reject or supersede an editorial point using an `edit_decisions` record containing
its comparison fingerprint, reviewer, reason and status. Those decisions apply
only to that source/draft pair. Text similarity never accepts an edit automatically.

## Author questions and discussion coverage

Questions specify an owner, document target, exact quote, supporting evidence and
any conditions. A confirmation is bound to that question and its current sources.

```powershell
python research_project_cli.py --workspace C:\private\study decide q1 --reviewer "Author" --reason "Verified against the source" --proofs C:\private\proofs.json
python research_project_cli.py --workspace C:\private\study coverage C:\private\manuscript.md --output C:\private\coverage.json
```

`source_evidence` conditions require a current exact source passage and reviewer
judgement. `exact_text_match` additionally requires the complete question quote to
match the cited source quote after whitespace normalisation. An answer such as
"yes, if unchanged" stays pending until its condition is proved. Changed local
source bytes invalidate the decision even before reindexing.

Discussion topics distinguish findings, interpretations, hypotheses and proposed
studies. Findings require source evidence. Hypotheses and proposed studies require
qualification in the mapped manuscript passage. Omitted topics require a reviewer
and reason. This is an explicit coverage register; it cannot decide whether a
scientific explanation is correct or whether an entire discussion is sufficient.
Word counts exclude Markdown headings and References/Bibliography sections, and
include tables and captions. Word Heading styles are converted to section markers
when checking a pack. Plain, manually formatted headings need explicit conversion.

The local screen records author questions and displays source/figure status.
Conditional proofs, result approvals and pack operations use the CLI. Reviewer
names are audit labels and do not authenticate a person's identity.

## Approved results and figures

Each result has its own definition, source, method, count, denominator and rounding
precision. Approved records supply placeholders such as `{{result:region:pair}}`
in Word paragraphs or table cells. Exact occurrence mappings check the resulting
text. Changing the value, denominator or definition invalidates its approval.

```powershell
python research_project_cli.py --workspace C:\private\study approve-results --ids region --reviewer "Author" --reason "Approved aggregate table"
python research_project_cli.py --workspace C:\private\study export-results --output C:\private\results-v1
```

The export produces CSV, Markdown, PNG and PDF assets from fixed plotting code,
plus a receipt linking them to the approved results. Include `result_assets` in
the pack specification to check those files. Unmapped numbers and other statistical
analyses are outside this test. Existing figures without these receipts remain
labelled as having unchecked derivation.

Figure panels record original/display file hashes, source locations, recovered
labels and any mask receipt. Image matching suggests candidates. It does not prove
diagnosis, cohort membership, caption accuracy or permission to reproduce an image.
These six checks remain separate: `image_identity`, `caption`, `clinical`,
`cohort`, `reproduction` and `privacy`.

```powershell
python research_project_cli.py --workspace C:\private\study mask C:\private\original.png --output C:\private\masked.png --rectangles C:\private\rectangles.json --reviewer "Author" --reason "Authorised margin masking"
python research_project_cli.py --workspace C:\private\study match C:\private\masked.png C:\private\candidate.png --output C:\private\matches.json
python research_project_cli.py --workspace C:\private\study confirm-figure "Figure 1" --check privacy --reviewer "Reviewer" --reason "Inspected the full masked image"
```

Rectangles are `[left, top, right, bottom]` pixel coordinates. Masking creates a new
PNG, removes metadata, paints only the authorised rectangles black, and verifies
every pixel outside them. It never uses image generation. Optional local Tesseract
scanning in `utils.project_figures.scan_identifiers` returns clue counts only and
always requires visual review. It does not certify anonymisation.

## Build, check and package

Prepare a private specification following `examples/project-pack.example.json`.
Use `file_receipt(path)` from `utils.project_store` to obtain real input hashes.
The title page must have `preserve: true`; its bytes are checked throughout.
Use a new directory for each build.

```powershell
python research_project_cli.py --workspace C:\private\study prepare C:\private\pack.json --output C:\private\pack-v1
python research_project_cli.py --workspace C:\private\study check C:\private\pack-v1
python research_project_cli.py --workspace C:\private\study visual-review C:\private\pack-v1 --reviewer "Reviewer" --notes "Opened the Word files and all PDF pages; checked tables, images, highlights and comments"
python research_project_cli.py --workspace C:\private\study release C:\private\pack-v1 --output C:\private\review-v1.zip
```

The builder preserves surrounding run formatting, inserts result values and
registered legends, and anchors unresolved questions to yellow text with Word
comments. It keeps the questions in a separate review note. Setting
`generate_figures: true` produces a figure document from registered panels.
Word/PDF rendering uses installed Word or selected LibreOffice. A supplied PDF is
accepted only with a preserved Word file; modified Word files must be rendered.

On a rebuild, resolved questions lose this workflow's generated comments and
yellow spans, unless another unresolved review overlaps the text. Legacy comments
remain intact. Preserved documents, including the approved title page, are never
edited automatically.

Checks cover exact query spans, comment range integrity, legend consistency,
mapped results, derived asset receipts, source changes, preserved files, missing
registered images and Word/PDF text. Known unmasked originals are checked by byte
and decoded pixel hashes in loose images, Office media and PDF images. Recompressed
or altered originals can evade exact matching; visual privacy review is still
required. Image checks do not prove correct panel placement or clinical content.

`coauthor_review` allows explicit outstanding clinical questions. `submission`
blocks unresolved checks, including unchecked coverage or calculation derivation.
Privacy/integrity failures block either stage. A visual-review record is mandatory
and bound to the exact project state and files. Any change invalidates it.

The release command writes and verifies a new local ZIP. It excludes internal
provenance files and absolute paths from those files. It does not scrub arbitrary
document text or Office metadata, send mail, upload files, merge code or submit a
paper. Failed builds remain available for inspection and cannot pass release.

## Validation

```powershell
python -m pytest -q
python research_benchmark.py
ruff check --select F821,F822,F823,E9 .
python -m pip check
```

Synthetic tests cover conditional approvals, source changes, stale plots,
misplaced yellow/comments, unmasked PDF images, missing OCR, lost edits, preserved
title pages and invalidated ZIP releases. CI runs offline tests on Windows and
Linux. The separately enabled Docker TeX integration requires its local image.
A private replay additionally exercised real legacy conversion and Word rendering.
No private manuscript, correspondence, clinical image or source dataset is part of
the public tests. Offline success does not establish live provider performance.
