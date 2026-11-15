# Workbook evidence and manuscript consistency

This workflow is local and makes no model calls. Keep private workspaces outside
the public repository. Source files remain unchanged.

## Workbook extraction

Index `.xlsx` and `.xlsm` through **Sources and manuscript** or the existing
`research_project_cli.py index` command. The browser retains sheet names, cell
addresses, hidden-sheet state, raw stored values, formulas, shared-formula
attributes, named ranges, chart caches, drawing text and original embedded images.
Supported EMF/WMF text records become searchable passages linked to the image.

Formula and chart values are saved caches, not recalculated results. Those
passages and vector text remain marked for review and cannot silently satisfy
exact-source evidence checks. Number/date formatting is not applied. Macros,
external links and embedded executable objects are never run. Embedded
workbooks/OLE objects are reported as unprocessed. Legacy `.xls` needs a separately
preserved conversion. Unsupported vector records, font-dependent ANSI decoding,
glyph indices and raster-only text still need visual inspection.

Package, part, cell and text limits fail closed. A failed extraction is never
reported as complete. Malformed vector text retains its original graphic with a
warning. Existing extracted assets are checked for alteration before reuse.

**Workbook cells and aggregate results** registers a count and denominator from
two literal integer cells. Results retain the workbook receipt and both locators
and still need approval. Formula caches cannot use this shortcut; independently
reproduce the analysis instead. Changed workbooks invalidate derived results,
including after reindexing. Register and review the new values before export.

```text
python research_project_cli.py --workspace PRIVATE_PROJECT workbook-result SOURCE_ID --count-cell "sheet:Counts!A1" --denominator-cell "sheet:Counts!B1" --id detection --label "Group A" --definition "Correct abnormal classifications"
```

## Claims and figure labels

Open **Claims and figure-label checks** under **Results**. Link an exact manuscript
paragraph to a ranking or outcome. Rankings use an explicit comparison set and
target result. Record a shared measure and independent participant counts, then
approve the updated results. The checker compares exact fractions and flags ties,
single-participant groups, unknown group sizes and incompatible measures. It
does not test statistical significance.

Contradictory rankings and stale/unapproved results are pack errors that cannot
be dismissed. Interpretation questions allow named review with a reason. Reviews
are bound to the manuscript, sources, results, figures and mappings, so changes
require fresh review. Measured outcomes need current source passages plus
interpretation review. Proposed applications retain an exact qualification.

Selected risk words flag unmapped claims. Caption colour/shape markers are
compared with recovered panel labels. This checks recorded labels, not pixels or
clinical meaning. The report states its limited scope; it is neither exhaustive
semantic review nor author approval. Unresolved findings enter the pack report
and prevent submission clearance. Existing image/privacy and Office checks remain.

CLI operations: `claim MAPPING.json`, `consistency-check MANUSCRIPT --output
REPORT.json`, and `consistency-review MANUSCRIPT FINDING_ID --reviewer NAME
--reason REASON`. The check exits non-zero for findings or no checked mappings.
See `examples/claim-ranking.example.json` for a synthetic mapping.

## Version history

**Document history** records unknown, confirmed issued, reconstructed, published
or working draft. Confirmed issuance requires a named reviewer, reason and sent
record. This records a person's attestation, not automated authentication or
approval by every author. Reconstruction requires text equality with a tracked
return's original-text view. Publication and reconstruction retain supporting
files. The co-author screen can also clarify existing baselines.

Old records default to unknown. Compatibility field `base_verified` means text
equality only; `base_text_matches`, provenance and `author_approval: false` expose
that limit. **Earlier edits** includes a downloadable report with exact hashes,
origins, changed passages and locations. Similarity never establishes ancestry.
Changed sources reset their classification on reindexing; altered supporting
evidence is flagged. Backup and restore retain classifications and source files.

## Parser references

Supported layouts follow Microsoft's
[EMR_EXTTEXTOUTW example](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-emf/624eb005-7ca7-49a9-a170-37be301e0424)
and [META_EXTTEXTOUT specification](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmf/7d07c44a-a828-4b82-9af0-e0a81cced5a8).
Font-dependent decoding remains a review limitation.
