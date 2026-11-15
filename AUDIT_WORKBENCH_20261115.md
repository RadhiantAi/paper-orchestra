# Review workbench audit, 15 November 2026

Public. Synthetic fixtures only; no private research files are included.

The local interface now supports evidence selection, tracked-edit decisions,
result approval, fixed analysis recipes, OCR review, figure registration and
confirmation, journal requirements and checked ZIP creation. The host-assisted
route remains independent of model and literature providers.

## Issues found and fixed

- Model and retrieval guards now default to offline independently of pricing and
  budget settings. This includes compatible localhost model endpoints. Python
  socket auditing adds a second check; it is not an operating-system firewall.
- Source uploads keep readable display names without trusting those names as
  output paths. Private data cannot be placed inside the public checkout through
  the project operations.
- OCR text cannot resolve a question before human review. Re-indexing retains
  valid decisions but invalidates changed text or previews. Failed and incomplete
  OCR remains an explicit coverage gap.
- Result tables and plots included by the screen are checked against the current
  approved register and export hashes. A stale calculation or changed linked count
  blocks approval and release.
- Duplicate CSV headings are rejected. Aggregate recipes record independent
  sampling units, missing counts, assumptions and reproducibility receipts.
  Undefined agreement estimates remain unresolved.
- Table text is traversed in document order, including nested tables. Journal
  counting preserves heading levels and excludes child sections with their parent,
  including structured abstracts and reference subsections.
- Missing figure files produce journal findings. Journal checklist decisions are
  bound to the exact profile and manuscript. Failed journal CLI checks return a
  nonzero exit status.
- A later decision about an earlier edit now takes precedence over the first.
- The inherited refinement prompt no longer suppresses limitations or requests
  for missing experiments. It preserves qualified hypotheses and proposed studies
  without implying that unsupported work has been completed. Invalid LaTeX string
  escapes were corrected.

## Validation scope

Final local run: 165 passed, 2 integration tests skipped, no warnings.

The full local offline suite includes UI interactions through a checked ZIP,
source and calculation changes, malformed documents, journal violations and
generated review/edit/rebuild/export sequences. The UI release test first proves
that release fails without visual review, then succeeds after recording review.
Stateful tests verify that subsequent edits invalidate release. These rendering
fixtures test workflow logic using a synthetic PDF renderer.

The review screen was also opened in a local browser and visually inspected.
Critical Ruff checks, dependency consistency and the three-case adversarial
benchmark passed. The benchmark's seeded defective outputs fail and its corrected
outputs pass. This does not establish live model performance.

Dedicated GitHub Actions jobs run real Tesseract on a generated image and real
isolated TeX compilation. The local suite skips these two integration tests when
the tools are unavailable. No live model calls, clinical dataset reanalysis or
external literature retrieval were performed for this implementation.

## Boundaries

The two statistical recipes cover independent aggregate proportions and paired
binary agreement. Clustered inference and arbitrary external scripts remain out
of scope. Journal rules must be supplied and confirmed by the researcher. Literal
format checks do not establish scientific checklist compliance. Reviewer names
are unauthenticated local audit labels. OCR confidence does not establish accuracy,
and duplicate detection does not select an authoritative manuscript version.

Clinical figure review, privacy inspection, scientific interpretation and final
submission approval remain human decisions. Co-author packs may carry unresolved
items; submission packs fail while required checks remain unresolved.
