# Reviewed evidence and blinded trial evaluation

Live model calls are unnecessary for these controls. The project remains private and outside the repository. These are workflow and integrity checks, not clinical approval or protection against a person editing project files deliberately.

## Completing a human check

The review interface now provides workbook visual and calculation interpretation decisions. A named reviewer records a reason, every required checkbox and either `accepted` or `unresolved`. Acceptance of a calculation interpretation also requires an exact passage in a current manuscript describing its interpretation and limitations. The final pack must retain that passage.

The decision binds to the calculation, input, output and conversion receipts. Changes reopen the decision. Workbook acceptance clears only `legacy_workbook_visual_review_required`; missing cells, changed formulas, other source gaps and failed calculations cannot be waived. Recovered copies with unchanged bytes retain these decisions. Author approval remains separate.

CLI: `review-check KIND TARGET checks.json --decision accepted --reviewer NAME --reason REASON`, adding `--manuscript FILE --quote PASSAGE` for interpretation. Required checkbox names are shown in the interface and `utils/reviewer_checks.py`.

## Freeze before revealing a reference

1. Create a new project and enable strict trial mode. Allocate all primary inputs and at least one withheld reference. Keep reference originals outside the project. Structural inspection emits no workbook values or labels. Record any previous exposure honestly.
2. Freeze the protocol with `trial-protocol protocol.json --reviewer NAME --reason REASON`. Supply exactly `question`, `analysis_plan`, `success_criteria`, `exposure_statement` and `recipes`. Recipes contain the complete exact JSON configurations, or an empty list for a declared manual/descriptive workflow. Freeze before registering analyses. Inputs and recipes cannot be added afterwards; amendments need a separately identified trial.
3. Produce the candidate from admitted evidence. `trial-draft FILE --reviewer NAME --reason REASON` declares a newly produced draft or derived input. It is an operator attestation, not independent proof of what a chat or researcher has seen. A byte-identical withheld reference is rejected. External calculation imports are disabled after protocol freeze; use the declared local recipes or retain manual calculations as explicitly declared supporting evidence.
4. Build and visually inspect the review pack. `trial-freeze PACK_FOLDER --reviewer NAME --reason REASON` seals its released ZIP, exact manuscript and project/check snapshots. Any pending author checks remain recorded. This is a review candidate, not submission approval.
5. Only then use `trial-unblind --hashes SHA256 ... --reviewer NAME --reason REASON`. This unlocks the dedicated comparison only. It does not admit references to the original analysis or permit changing the frozen project.
6. `trial-compare REFERENCE --output REPORT.json` reports number-token differences, unmatched reference passages and exact image matches. Dates and citations may appear as numeric differences; paraphrases and image conversions may appear unmatched. The report needs a human review of numerical discrepancies, omissions, unsupported claims and figure meaning. A reference is a comparator, not automatic ground truth.

Every CLI command also takes `--workspace PRIVATE_FOLDER`. UI controls follow the same phase sequence. Code outside this project cannot be prevented from reading a reference; the exposure declaration is part of interpreting the trial. Do not call a previously exposed study independently blinded.

Backup excludes withheld originals and unregistered stray files in strict mode. The sealed evidence travels in the recovery archive. Restoring changes location, not its identity. Changed original inputs, missing evidence or altered candidate files block validation. A restored editable review pack still needs a fresh build and visual review if its path-bearing metadata changed; the sealed ZIP remains byte-identical.

## Continuous statistical figures

Register and technically review continuous results first. Generate a point/interval plot with `continuous-figure spec.json --output NEW_FOLDER`. A spec has `id`, `title`, `axis_label` and `items`; each item has `result_id`, `label` and optional `interval_id`. Only a mean with its own confidence interval or a coefficient with its own coefficient interval can be paired. Groups, variables, calculation, units and confidence level must agree.

The output contains PNG, PDF, plotted numbers and provenance receipts. Labels use the same rounding as prose and tables; confidence levels appear on the chart. Select plot IDs in the pack interface, or set `continuous_figures` in the pack spec. The pack receives PNG/PDF assets under `StatisticalFigures`. This does not automatically place a plot inside Word or write a scientifically valid legend. Use existing figure placement controls for embedding and check the final layout.

The checker rejects stale inputs, changed result precision or reviews, altered plot assets and missing pack copies. It cannot prove the suitability of an analysis or its labels for a particular study. Those require the recorded methodological and author reviews.
