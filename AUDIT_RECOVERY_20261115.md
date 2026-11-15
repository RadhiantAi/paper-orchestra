# Recovery and co-author workflow audit

15 November 2026. Synthetic data only; live models remained disabled.

## Implemented scope

1. Automatic before/after snapshots, content-addressed private backups, checked
   export and staged restore into a new project folder.
2. Windows launcher, project chooser, file pickers, automatic refresh and a next
   action/readiness panel.
3. Issued Word baselines, returned edits/comments, assignment and decisions,
   conflict checks, conservative application, manual reconciliation and draft responses.
4. Real Word/LibreOffice rendering regressions for complex synthetic documents.
5. Clustered proportion, clustered binary agreement and interchangeable-rater
   Fleiss kappa recipes with explicit assumptions and reproducible receipts.
6. Weekly reviewed dependency update configuration, exact action commits and an
   offline build-pin check alongside the existing exact Python lock.

## Findings fixed during implementation

- Damaged objects now block backup and project mutation without replacing live data.
- Restore rejects duplicate/unsafe destinations, unsupported schemas, extra members,
  corrupt hashes, expansion-budget violations and Windows reserved filenames.
- Interrupted restore leaves no partially restored project at the requested path.
- Missing input files make a backup incomplete; the CLI returns a non-zero exit.
- Restored OCR review remains pending and location-bound evidence needs fresh checks.
- Untracked returns cannot silently establish a verified baseline. Structured Word
  replacements and overlapping edits require explicit reconciliation.
- Accepted edits must have a current revised-file receipt; submission checks inspect
  the actual manuscript for accepted and detectable rejected text.
- Statistical options unrelated to the selected design are rejected. Fixed-rater
  designs cannot pass through the interchangeable-rater recipe.
- Word's mathematical italic Unicode is normalised for PDF content assertions,
  while missing equations still fail. Internal comments must not enter the PDF.
- Build-pin checks cover both workflow extensions and reusable workflow calls.
- Interface selection tests now include the rerender that a browser performs
  before enabling the selected-file button.

## Local evidence

- Full offline suite with real LibreOffice enabled: **197 passed, 2 skipped**.
  The two skips were the dedicated Docker/TeX and Tesseract integration tests.
- Real Microsoft Word rendering plus negative rendering fixtures: **6 passed**.
- Subsequent build-pin and interface checks: **8 passed**. Co-author checks,
  including the submission-gate regression: **5 passed**.
- All three deterministic synthetic research benchmark cases passed, including
  rejection of the seeded unsupported claims and numerical discrepancies.
- Installed dependency consistency, build pins, critical lint and whitespace checks passed.
- Project chooser, recovery and co-author screens inspected in a real browser.
  Both rendered Word PDF pages visually inspected; footnote, equation, image,
  caption and page break were present and internal comment text was absent.

CI runs the full final tree on Windows and Linux, plus dedicated TeX, OCR and
LibreOffice jobs. Use the PR's exact-commit checks for their current status.

## Remaining limits

No live provider performance or clinical validity is claimed. Backups are private,
unencrypted and bounded to 2 GB/10,000 files, with no automatic retention policy.
Same-disk snapshots do not protect against disk loss. Schema migration is not
implemented. Complex Word edits need manual reconciliation and final visual review.
Statistical warnings remain submission blockers. Dependency update PRs activate
after merge and still need review; this change does not authorise automatic merges.
