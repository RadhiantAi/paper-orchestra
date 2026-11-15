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
as withheld; a new blind workspace is needed. Normal projects retain the existing
behaviour for unregistered inputs. Opt-in strict projects use the gates below.

Allocation records are metadata and do not cause external originals to enter
backups. Keep withheld, excluded and uncertain originals outside the project.
Normal-project backups include files physically inside the project, so copying a
withheld file there would expose it. Strict backups collect registered receipts
only and report excluded stray files. Selected sources enter recovery through indexing.
Changed files invalidate their allocation, and unresolved allocations remain pack
review items. A source role is neither scientific approval nor proof of completeness.

## Strict blinded-trial mode

Choose **Start a strict blinded trial** when creating a project, or run:

```text
python research_project_cli.py --workspace PRIVATE_PROJECT init
python research_project_cli.py --workspace PRIVATE_PROJECT strict-trial --reviewer "Trial reviewer" --reason "Approved blinded protocol"
python research_project_cli.py --workspace PRIVATE_PROJECT allocate-source INPUT --role trial_input --reviewer "Trial reviewer" --reason "Protocol input"
```

Enable strict mode before any content is imported or copied into the project.
There is no disable operation. Intake rejects unknown bytes, changed files and
renamed copies of withheld sources. Uploads, local indexing, analysis inputs,
co-author documents, provenance evidence, OCR and pack inputs use the gate.
Extracted media inherit their admitted container's provenance; email attachments
need their own allocation before extraction. Derived pack files are registered
and changed copies require a fresh allocation/build. Metadata-only structure
inspection and allocation remain available before admission.

Host imports need two decisions: each source's declared SHA256/origin and the
complete exchange's canonical fingerprint. The exchange origin is
`host-exchange:HOST`, where HOST exactly matches its `host` field. A coordinating
reviewer computes the fingerprint using `utils.research_quality.fingerprint` on
the parsed JSON, then supplies that digest without exposing withheld content to
the trial operator. Use **Record host allocation** or `allocate-host ORIGIN SHA256
--role trial_input --reviewer REVIEWER --reason REASON`. Nested local file receipts
are verified and admitted individually. Changing text while retaining a declared
source hash invalidates the exchange decision. Host digests remain declarations,
not independent proof that a remote source was retrieved faithfully.

Allocation history is retained as metadata and excluded from file collection.
Reclassifying a withheld source as an input records `unblinded_at`; strict intake
continues, but the project is no longer represented as never unblinded. Restores
retain the mode, history and roles. Strict snapshots exclude stray files and mark
changed registered files missing rather than copying unapproved replacement bytes.
This also means loose, unregistered drafts are not included in strict backups.

These are supported application intake controls, not an operating-system sandbox
or a guarantee about previous human/chat exposure. Keep a separate exposure log
for external tools, manual edits, literature searches and anything read outside
the project. Direct Python helpers, filesystem edits and source allocations made
by an operator do not establish an independently supervised blind trial.

## Controlled legacy Excel conversion

Use **Convert a legacy Excel workbook with checks**, or:

```text
python research_project_cli.py --workspace PRIVATE_PROJECT convert-workbook ORIGINAL.xls --output NEW_PRIVATE_FOLDER --reviewer REVIEWER --reason "Preserve and check legacy data"
```

This initial route requires installed Microsoft Excel on Windows. It accepts
bounded BIFF8/OLE workbooks with ordinary worksheets. Preflight rejects encryption,
VBA and Excel 4 macro sheets, defined names/named formulas, external supporting
books, query tables, connections and embedded objects. Unsupported files require
manual review; they are never silently converted by the indexer. Files are limited
to 32 MB and 100,000 inspected cells. No live models or external conversion service
are used.

The original is copied unchanged. Excel opens the copy read-only with links,
events, automatic calculation and VBA macros disabled. An independent XLS reader
captures stored values before Excel opens it. Checks compare that cache with the
opened workbook, then compare Excel's source and converted representations for
values, formulas, number formats, sheet names/order/visibility and date system.
Numeric tolerance is 1e-12 relative and absolute. Formula text is compared as Excel
interprets it; this is not a byte-level proof of identical BIFF formula tokens.
Excel 4 controls use preflight because Office's VBA automation setting alone does
not disable Excel 4 macros.

The private output contains the preserved XLS, XLSX, before/after audit, comparison
and hashed receipt with Excel version and settings. Errors and changed values
leave a failed output folder for inspection and do not register a verified
conversion. Cleanup targets only the new Excel process identified by its ID and
start time, leaving pre-existing Excel processes alone. Original inputs remain
untouched. This is a narrow conversion route, not a general malware sandbox.

After conversion, index the original XLS; the indexer follows its verified XLSX
receipt. Strict mode requires a separate allocation for the converted XLSX first.
Changed conversion artefacts invalidate the receipt. Backups preserve the original,
conversion and checks. Layout, charts, visual presentation and scientific meaning
remain human checks; the source retains a visual-review warning and cannot receive
automatic submission clearance. The private cell audit may contain research data.

Implementation references: [Excel automation security](https://learn.microsoft.com/en-us/office/vba/api/excel.application.automationsecurity),
[workbook opening controls](https://learn.microsoft.com/en-us/office/vba/api/excel.workbooks.open),
[BIFF sheet types](https://learn.microsoft.com/en-us/openspecs/office_file_formats/ms-xls/b9ec509a-235d-424e-871d-f8e721106501).

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

### Bind continuous values to prose and tables

Use **Link continuous calculations to manuscript values** to choose a group,
variable/model, field, coefficient and rounding precision. The CLI equivalent is
`continuous-result CALCULATION_ID SELECTOR.json --id ID --label LABEL --definition
DEFINITION --precision 2`. A pooled summary selector looks like:

```json
{"kind": "summary", "group": null, "variable": "x", "field": "mean"}
```

Model selectors also require `outcome` and the ordered `predictors`; coefficient
fields require `coefficient`, including `intercept`. Supported values include
means, SDs, ranges, bootstrap intervals, counts, coefficients and their intervals,
R squared and leave-one-out errors. Non-estimable/non-finite values are rejected.
The register retains the calculation, field, units and precision. A technical
reviewer must record their check with **Record continuous result technical review**
or `review-continuous --ids ID --reviewer REVIEWER --reason REASON`. This does not
grant author approval or endorse the scientific interpretation.

Use `{{continuous:ID:value}}` in Word prose or table cells. The pack replaces it
using fixed decimal places and half-up rounding. Intervals render as `lower to
upper`. Add an explicit `continuous_mappings` entry for each expected passage:

```json
{"id": "mean-x", "template": "Mean: {{continuous:mean-x:value}} mm", "document": "manuscript", "occurrences": 1}
```

The target can be a role or exact pack filename. Specify every repeated passage
and expected occurrence count. Missing mappings, wrong target documents, changed
numbers, stale calculations or missing technical reviews block pack release.
Re-registering a value clears its previous review. Changes to input, method,
calculation code or output require recalculation and renewed review. This checks
only mapped literal occurrences; unrelated numbers, chart labels and statistical
interpretation remain outside its scope. Existing count-result checks are unchanged.

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
