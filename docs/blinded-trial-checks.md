# Offline trial review

These additions address source selection, continuous measurements and manuscript
checks. They make no model calls. Use the existing private project and review
interface; keep research inputs outside the public checkout.

## Figure identity and placement

Word presence checks follow referenced document, header and footer pictures.
Orphaned media, tracked deletions/moves and directly hidden runs do not establish
presence. PowerPoint checks follow active slide references and exclude hidden
slides and unused media. PDF checks require an image occurrence on the page.
Privacy checks still inspect packaged media, including unused images.

Pack specifications accept `figure_placements`, one entry per expected occurrence:

```json
[
  {"figure_id": "Figure 1", "panel": "A", "document": "Manuscript.docx", "location": "body:paragraph:12"},
  {"figure_id": "Figure 1", "panel": "A", "document": "Manuscript.pdf", "location": "page:3"}
]
```

`image-locations DOCUMENT --output REPORT.json` lists locations and image hashes.
Word paragraph numbers include table paragraphs. Headers and footers use their
part name instead of `body`. PowerPoint locations use `slide:1`. The pack screen
provides Word paragraph and PDF page controls for each panel. More complex packs
can supply mappings in the specification. A wrong document, page or paragraph is
an error; unmapped panels or Word panels without a PDF mapping remain pending.
Changed mappings or output files invalidate the existing visual review.

This is an identity/location check, not proof of correct rendering. Cropping,
overlays, off-page shapes, inherited visibility, panel arrangement, vector-only
PDF illustrations and clinical meaning still need visual review. Exact image
identity can also need manual reconciliation after image conversion. An image
must not receive an automatic clinical or author approval.

## Inspect structure before allocating sources

Use **Review workbook structure before choosing trial sources**, or:

```text
python research_project_cli.py --workspace PRIVATE_PROJECT source-structure WORKBOOK --output PRIVATE_REPORT.json
python research_project_cli.py --workspace PRIVATE_PROJECT allocate-source WORKBOOK --role candidate_primary --reviewer "Technical reviewer" --reason "Repeated numeric rows need source review"
```

The bounded XML inspection reports sheet numbers, visibility, numeric-cell
occupancy and formula counts. It emits no measurement values, formula text,
sheet labels or images. This is still a recorded structural exposure, not a claim
that the file was never inspected. No formulas, macros or external links run.
Legacy XLS is reported as unsupported and requires a preserved separate conversion.

Repeated numeric rows trigger a candidate-data clue irrespective of the filename.
Summary tables can trigger it too. The reviewer must establish provenance and
choose `trial_input`, `withheld_reference`, `uncertain`, `excluded` or
`candidate_primary`. Only an explicit `trial_input` allocation allows the native
indexer to ingest a source already in this allocation register. Matching copies
are checked by hash as well as path. Previously indexed content cannot be relabelled
as withheld; a new blind workspace is needed. Unregistered inputs retain the
existing indexing behaviour. Host-imported evidence needs a separate exposure log.

Allocation records are metadata and do not cause external originals to enter
backups. Keep withheld, excluded and uncertain originals outside the project.
Backups include files physically inside the project, so copying a withheld file
there would expose it. Selected sources enter recovery through normal indexing.
Changed files invalidate their allocation, and unresolved allocations remain pack
review items. A source role is neither scientific approval nor proof of completeness.

## Continuous measurements

Select `continuous_measurements` in the analysis screen or use the existing
`analyse` CLI with `examples/continuous-measurements.example.json`. Supply CSV
columns `unit_id,group` followed by every declared measurement column. IDs must be
anonymous and unique across the whole sample. Define literal group codes and
measurement units, identify the sampling unit and explicitly confirm independence.
Describe missingness, including when its reason is unknown. Only blank cells mean
missing. Invalid numbers, unknown groups and duplicate units are rejected.

Available-case summaries report total, available and missing counts, mean, sample
standard deviation, range and percentile bootstrap intervals, pooled and within
each defined group. Optional prespecified OLS models include an intercept and use
complete cases separately for each outcome and its predictors. Outputs include
original-unit coefficients, bootstrap coefficient intervals, in-sample R squared
and leave-one-out RMSE alongside a leave-one-out mean-only comparator. Whole
independent rows are resampled. The seed, method configuration, source and code
hashes are retained in the existing replayable calculation receipt.

Rank deficiency, small samples, empty groups, missingness and unstable model
uncertainty remain explicit warnings. Missing measurements are never imputed.
The small-sample threshold is a conservative review clue, not a universal cutoff.
This recipe does not support repeated/clustered observations, weighted fits,
causal inference or automatic model selection. Analysis output contains aggregate
results, not unit IDs; the private input snapshot and recovery archive contain
the supplied measurements and need appropriate protection. The recipe does not
populate the count/denominator register or approve scientific conclusions.

The new code fingerprint intentionally invalidates older local calculation
receipts; rerun them with their recorded input and method in a new output folder.

The implementation follows the least-squares criterion documented by
[NIST](https://www.itl.nist.gov/div898/handbook/pmd/section4/pmd431.htm) and uses
[NumPy's least-squares solver](https://numpy.org/doc/stable/reference/generated/numpy.linalg.lstsq.html).
Tests compare coefficients with closed-form formulae and analytic leave-one-out
errors with independent omitted-row fits. Sources checked 15 November 2026.

## Manuscript completeness

The pack screen accepts researcher-defined discussion length, minimum numbered
references and exact expected discussion passages. The specification field is
`manuscript_expectations`; see the synthetic example. There are no universal
minimums and no quality score. An unselected profile remains pending.

`completeness-check MANUSCRIPT --profile PROFILE.json --output REPORT.json`
reports recognised section word counts and editorial findings. It exits non-zero
when checks are unresolved. Word Heading styles or Markdown headings are required;
manually formatted headings need conversion. Child headings count towards their
parent section. Reference counts currently recognise numbered entries only.

Administrative wording such as author details requiring confirmation is flagged
even when yellow. Move questions into comments anchored to the relevant text.
Some legitimate scientific uncertainty can match these clues: review the wording
without turning uncertainty into a supported conclusion. Discussion-topic evidence
and qualification checks continue to use the existing coverage register. Literal
passages, length and citation counts cannot establish scientific completeness or
full-text support. Unresolved items may be disclosed in a co-author pack and block
submission clearance. Technical reviewer labels never authenticate author approval.
