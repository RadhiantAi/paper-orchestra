# Backup management and review-round audit

Public engineering record. 15 November 2026. Synthetic material only; live model
testing remained disabled.

## Implemented and verified

- `main` now requires the Office job alongside Windows, Linux, TeX and OCR. Readback
  confirmed strict checks and all five GitHub Actions app bindings. Administrator
  enforcement and the other existing protections were preserved. This hosting
  setting is active independently of the code PR.
- Encrypted `.porx` exports protect the complete ZIP, including file names and
  project history. Standard Fernet and Argon2id use the already pinned cryptography
  dependency. Export/restore passphrases use masked UI fields or private CLI prompts.
- Storage warnings and retention previews count shared objects once, protect retained
  snapshots and current receipts, and expose a reviewable candidate list. No cleanup
  operation or automatic deletion is implemented.
- Later review rounds explicitly name their parent, reviewer and reason. Supersession
  links an earlier item to an accepted later decision and a stored checked document.
  Earlier text and decisions remain in the history.

## Audit fixes and negative cases

- Wrong or missing passphrases, changed ciphertext/header, truncation, invalid file
  suffixes, short passphrases and oversized encrypted content are rejected. Failed
  authentication leaves no restored project. No temporary plaintext ZIP is created.
- Invalid plain ZIP files return a controlled recovery error.
- Malformed or incomplete snapshot records block cleanup estimates. Shared content
  and current project receipts are excluded from removable-object candidates.
- Symbolic links and Windows directory junctions are excluded from storage walks;
  linked recovery stores block the preview. Snapshot walks exclude directory junctions.
- Starting a new round does not clear outstanding items. Same-round/backward or
  unrelated supersession links are rejected, as are unsupported evidence and a
  changed/withdrawn replacement decision.
- Submission checks flag superseded wording reintroduced alongside the latest
  accepted wording. A three-round chain follows the final decision while preserving
  intermediate history. An encrypted restore retains those links and source hashes.
- UI controls show earlier and replacement wording side by side. Retention figures
  use readable storage units, and the preview explicitly records that nothing was deleted.

## Validation

- Final full local offline suite with real LibreOffice: **218 passed, 2 skipped**.
  Dedicated GitHub TeX and OCR jobs cover the two local integration skips.
- Targeted recovery, encryption, retention, review-round, pack and interface tests:
  **34 passed** during the final audit; these are included in the full suite.
- Three deterministic synthetic research benchmark cases passed.
- Installed dependency consistency, exact build pins, critical repository lint,
  additional F checks on changed implementation modules and whitespace checks passed.
- The encryption/retention and second-round supersession screens were inspected in
  a real browser after restarting the server on the final code.

The PR's Windows, Linux, TeX, OCR and Office jobs validate the pushed commit; inspect
their current results before merging. The new PR has not been authorised for merge.

## Limits and next trial

Encrypted exports are bounded to 127 MiB of source content and a 128 MiB ZIP payload.
Workspace files, snapshots, restored files and OS swap are outside that encryption
boundary. Archive size and creation time remain visible. Passphrase strength and
separate storage remain the operator's responsibility; this wrapper has no independent
security certification. Retention estimates omit external files and off-workspace
archives, and they are not an integrity audit or permission to delete.

Text checks cannot establish clinical correctness, editorial intent or author identity.
Ambiguous wording requires manual review. See `NEXT_MANUSCRIPT_TRIAL.md` for a proposed
offline trial against another manuscript with a trusted final reference version.
No second real manuscript was processed in this implementation task.
