# Local manuscript review workbench

Public documentation. Updated 15 November 2026.

Open an existing private project with:

```powershell
streamlit run review_app.py -- --workspace C:\private\study
```

Double-click `Launch Review.cmd` on Windows, or omit `--workspace` to use the
project chooser. Create or restore private projects there. See
[Recovery and co-author workflow](RECOVERY_AND_COAUTHORS.md) for the new controls.
The server binds to localhost and disables usage telemetry. Keep the project and
all research files outside this public checkout. This is a single-user local tool;
reviewer names record decisions but do not authenticate identity.

## Review in the screen

1. **Sources and manuscript:** upload files or import a host evidence exchange,
   inspect original passages beside the current manuscript, and review coverage.
   Uploads keep their display names while using content hashes for storage. The
   inventory reports identical files, matching text, missing files and incomplete
   extraction. Matching text does not establish identical figures or tracked edits.
2. **Author questions:** select the exact source passage for each condition and
   record a reviewer, reason and decision. Conditional confirmation remains pending
   until the cited text proves the condition. Changed evidence invalidates it.
3. **Earlier edits:** compare two indexed sources and retain, reject or supersede
   each recovered tracked edit or comment. The latest decision applies to that
   exact comparison. A text diff does not interpret editorial intent.
4. **Results:** approve selected counts, export linked tables and plots, or run a
   fixed aggregate recipe. New calculated values require separate approval.
5. **Figures:** register panels and recovered labels, create authorised masked
   copies, inspect images and record identity, caption, clinical, cohort,
   reproduction and privacy checks. A changed panel or legend needs fresh checks.
6. **Journal and discussion:** inspect mapped topics, enter confirmed journal
   requirements and record checklist review against exact manuscript passages.
7. **Review pack:** select Word files, preserve the approved title page, map result
   occurrences and optionally include the exported results folder. Build Word/PDF
   files, check them, inspect the rendered documents and record visual review before
   creating a ZIP. Any subsequent file or project change invalidates that review.

Saved project changes automatically refresh the screen. The co-author tab reviews
returned Word documents; the recovery tab exports checked private backups.
Word/PDF conversion needs locally installed Word on Windows or the selected
LibreOffice executable. A ZIP stays local; no workflow sends it.

## Offline networking

`PAPER_NETWORK_MODE=offline` is the default even when the variable is absent.
Only `online` permits model or retrieval entry points. Empty or misspelt values
remain offline. This is independent of estimated spending limits, zero prices,
declared capabilities and compatible endpoints running on localhost.

Importing the application utilities installs a Python socket audit guard against
external connections and name resolution. Loopback remains available for the
review screen. This is an application guard, not an operating-system firewall:
separately launched programs, browsers, installation commands and another process
have their own access. Use OS controls when a fully disconnected machine is required.
The Word converter disables macros; TeX compilation uses its existing isolated
container with networking disabled. Live provider testing requires separate approval.

## Local OCR and coverage

Install Tesseract separately and select its executable. OCR runs locally on image
files or blank PDF text pages, with a declared page budget. Each recovered passage
retains a source hash, preview, recognised text, confidence and engine receipt.
Compare it against the preview and correct it before confirming. Unreviewed OCR
cannot support a resolved author question. Re-indexing unchanged sources retains
valid OCR decisions; changed text or previews invalidate them.

Failed OCR and pages beyond the limit remain coverage gaps. The inventory covers
indexed files and declared search roots only. It does not prove that every relevant
Drive file or email has been found. OCR is not an automatic patient-identifier
redaction tool. Privacy still requires the figure review and authorised masking.

## Reproducible aggregate analyses

Five fixed recipes are available. The original two are:

| Recipe | Required CSV columns | Output |
|---|---|---|
| `binary_proportion` | `id,label,count,denominator` | Proportion and Wilson interval |
| `paired_binary_agreement` | `id,label,n00,n01,n10,n11` | Observed agreement, unweighted Cohen kappa and percentile bootstrap interval |

Both accept optional `missing_count`, reported separately and excluded from
observed denominators. Counts must describe independent sampling units. Additional
recipes cover whole-cluster proportions, clustered binary agreement and Fleiss
multi-rater agreement under explicit design constraints. See the
[recipe table and limitations](RECOVERY_AND_COAUTHORS.md#additional-statistical-recipes).
Weighted kappa, adjudication and patient-level modelling need separate reviewed
recipes. These recipes do not reproduce arbitrary external analyses.

Every run records the sampling unit, independence confirmation, confidence level,
random seed, bootstrap count, input snapshot, original input hash, recipe code hash,
NumPy version, outputs and reviewer rationale. The checker recomputes the output.
Changed input, code, output or linked counts invalidates the calculation. Undefined
kappa or unstable intervals require review. This establishes computational
reproducibility; it does not establish that the selected method fits the study.

The CLI also exposes `analyse`, `register-analysis`, `inventory`, `ocr`,
`confirm-ocr` and `journal-check`; use each command's `--help` for arguments.
Detailed results stay in private files; terminal output contains status/counts.

## Journal profiles and submission checks

Enter a named article type, instructions source, date checked and reviewer, then
the word/reference/figure limits, section and declaration labels, reference style,
figure format/size requirements and reporting checklist items. Zero is a literal
zero limit. No journal rules or requirements are guessed or fetched automatically.

Checks cover recognised headings, counts, bracketed numeric citations, reference
numbers, image metadata and exact checklist evidence. Author-year recognition and
unnumbered reference counts are limited; full reference formatting always requires
human review. Profiles older than 365 days or dated in the future need review.
These checks cannot certify a scientific reporting guideline by themselves.

Main text counts exclude the configured sections plus References/Bibliography.
Use Word Heading styles or Markdown headings; manually styled headings may not be
recognised. Tables count in document order, including nested tables. Inspect the
reported section counts before relying on journal limits.

Record checklist review against the built manuscript if substitutions or legends
changed its text. The profile, manuscript and review must still match at release.
Co-author packs may carry explicitly pending checks. Submission packs cannot pass
with pending source, scientific, figure, journal or review checks.

## Verification and release controls

The offline suite includes known statistical answers, damaged files, stale inputs,
OCR edits, journal violations, UI interactions and generated sequences of review,
edit, rebuild and ZIP release. Negative fixtures must fail for the expected reason.
Tests remove provider credentials and deny network sockets; positive adapter tests
use mocks. No live model test is part of the suite.

GitHub Actions runs Python tests on Windows and Ubuntu, isolated TeX compilation,
real Tesseract against a generated synthetic image, and real LibreOffice rendering.
Local runs without enabled integration tools skip their dedicated tests; separate
CI jobs exercise them. Protect `main` with strict required passing checks, administrator enforcement,
resolved review conversations and no force pushes or deletion. Repository rules are
hosting settings, so check their current state before relying on them.
