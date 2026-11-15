# Recovery and co-author workflow

Updated 15 November 2026. All examples are synthetic. Live model testing remains off.

## Open the workbench

After installing the locked requirements into `.venv`, double-click **Launch Review.cmd**
on Windows. It forces offline mode and opens the local review interface. Choose an
existing private project, create one, or restore a recovery ZIP into a new folder.
`streamlit run review_app.py` also opens the chooser. The optional `-- --workspace`
argument still opens a specific project. Keep research files outside this checkout.

Word and analysis file controls accept a browser file picker, an indexed source,
or a typed local path. Saved decisions automatically refresh the screen. The
readiness panel identifies the next outstanding project check; it does not replace
the full pack check or certify scientific correctness. Reviewer names are records
of decisions, not authenticated identities. This remains a single-user local tool.

## Private backups and recovery

Every saved project update snapshots the state before and after the change. File
content is stored once by hash under `.recovery/objects`; snapshot manifests retain
the associated project state. These snapshots are on the same disk and do not
protect against loss of that disk. Export a private recovery ZIP to a separate
protected storage location using the Recovery tab or:

```powershell
python research_project_cli.py --workspace C:\private\study backup --output D:\private-backups\study-v1.zip
python research_project_cli.py --workspace C:\private\restored-study restore D:\private-backups\study-v1.zip
```

Select an older snapshot to recover an earlier state. Backups include workspace
files and external files referenced by hash receipts. Known credential/configuration
files, tool executables, caches, the Git checkout and older snapshot history are
excluded. This is a named-file exclusion policy, not a general secret detector.
Never place credentials in research files. A recovery ZIP can contain unmasked
original images and private source documents. It is **not** the co-author review ZIP.
For encrypted exports, select **Encrypt the recovery export**, enter and repeat a
long, unique passphrase, and save a `.porx` archive. The CLI prompts privately with
`backup --encrypt --output D:\private-backups\study-v1.porx`. Restore detects the
encrypted format and prompts for the passphrase. Never put it in command arguments,
project notes, emails or chat. Keep it separately in a password manager; there is no
passphrase recovery service.

The entire ZIP, including file names and the manifest, is protected using the
existing pinned `cryptography` library: standard Fernet authenticated encryption and
Argon2id key derivation (64 MiB, three passes, four lanes, random 16-byte salt).
The envelope version, approximate size and Fernet creation time remain visible.
Passphrases are not written into project records or logs. Encryption/decryption
uses memory, without creating a temporary plaintext ZIP. Authentication completes
before restore creates any project folder. This does not encrypt the source
workspace, snapshots, restored files, OS swap or separately exported review packs.

Encrypted exports accept up to 127 MiB of source content and a 128 MiB ZIP payload;
the bounds keep memory use predictable. Plain ZIP export retains its existing 2 GB
limit and is explicitly unencrypted. Larger projects need protected storage or a
separately reviewed large-file encryption approach. The format is versioned and
uses fixed KDF settings; unsupported envelopes, incorrect passphrases and damaged
data fail closed. Cryptographic primitives come from the library, but this wrapper
has not received an independent security certification.

The checker reads every object back and verifies hashes, sizes, schema and safe
destinations. Missing referenced files produce an explicit incomplete result and
a non-zero backup CLI exit. A backup cannot recover a file that was already missing.
Unregistered external files are outside its scope. Limits are 10,000 restored files
and 2 GB of uncompressed data for plain exports.

The **Storage warnings and retention preview** panel reports workspace size, free
disk space, recovery-object size and a proposed retention list. Defaults keep the
20 newest snapshots plus all snapshots from the last 30 days; either condition
protects a snapshot. Shared objects and current project receipts remain protected.
The default warning threshold is 5 GiB of workspace storage and less than 1 GiB
free disk space. These are operational thresholds, not automatic limits.

The preview performs no deletion. It gives candidate snapshot names, content hashes,
estimated reclaimable bytes and an inventory fingerprint. External sources and
backup archives outside the workspace are excluded from the totals. Missing or
malformed snapshot records block a cleanup estimate. Legacy manifests use file
modification time when no creation timestamp is available. Recalculate immediately
before any separately authorised cleanup, and verify an independent backup first.
There is no cleanup/apply command in this release. Export a private JSON preview with:

```powershell
python research_project_cli.py --workspace C:\private\study retention-preview --keep-latest 20 --keep-days 30 --output C:\private\retention-review.json
```

Restore uses a temporary sibling folder and only exposes the new project after
successful validation. It never replaces an existing project. External source
receipts relocate into the new folder; source IDs and prior decisions remain.
The original project record is retained in `recovery-original`. OCR previews,
figure identity and pack visual checks require fresh review after relocation.
Historical pack specifications and receipts are preserved as evidence, not rewritten
into newly approved packs. Rebuild the review pack in a new output folder. The
implementation supports project/recovery schema 1 and rejects unsupported schemas;
it does not claim automatic migration of future schemas.

## Returned Word documents

1. Register the exact clean Word version issued to co-authors. This stores a copy;
   it sends nothing. Resolve tracked text changes in the baseline first.
2. Import each returned DOCX against that baseline and assign an owner. Paragraph
   differences, tracked edits and comments retain their source and author context.
3. Accept, reject or mark each item for discussion with a reviewer and reason.
   Overlapping, different edits from different returns require reconciliation.
4. Create a new Word draft from accepted changes. Automatic application supports
   simple one-paragraph text replacements against a verified original text view.
   Images, fields, equations, footnotes, comments, insertions/deletions of paragraphs
   and ambiguous mappings require manual Word reconciliation. Source files remain
   unchanged. Text matching does not prove formatting or document ancestry.
5. For manual reconciliation, select the accepted items and the revised Word file,
   then record who checked it and why. The record binds to that file's current hash.
   Accepted replacement text must be present; an accepted deletion must be absent.
6. Export an unsent response document if useful. Build and visually review a fresh
   manuscript pack. Pending decisions, changed returns, unresolved conflicts,
   unreconciled accepted edits, missing accepted text and detectable rejected text
   block a submission pack. Co-author packs may disclose pending review items.

These checks do not determine editorial intent. Identical wording elsewhere may
make a deletion or rejected-text check ambiguous; resolve the wording and review
record explicitly.

## Explicit review rounds

When registering a later issued version, select its parent round and record a
reviewer and reason. The same clean document may be issued again as a distinct
round. Existing projects remain readable; older issued versions are independent
first rounds unless linked through a new later version.

Registering a round clears nothing. To replace an earlier decision, select an item
from an ancestor round, an accepted replacement in the current round, and the
checked manuscript. Add the reviewer and reason. Text items link to text items;
comments link to comments. A stored copy of the checked document binds the decision
to its hash. The later wording must be present and obsolete replacement wording
must be absent or the operation stops for manual review.

The old item becomes `superseded`; its text, author, previous decisions and the new
link remain in the history. Three or more rounds can form a chain. Submission
checks follow the chain, require the current accepted wording and flag obsolete
wording reintroduced into the pack. Changes to supporting documents, missing
evidence, invalid ancestry or withdrawal/revision of the replacement decision
invalidate the supersession. To revise a supersession, reopen the earlier item with
an explicit decision and reason, then link it again. No authorship or editorial
intent is inferred from text similarity alone. Unrelated items remain active.

## Additional statistical recipes

The original Wilson proportion and paired binary agreement recipes remain.

| New recipe | Input columns | Estimate and resampling |
|---|---|---|
| `clustered_proportion` | `cluster_id,count,denominator,missing_count` | Explicit observation-weighted or equal-cluster proportion; resample whole clusters |
| `clustered_binary_agreement` | `cluster_id,n00,n01,n10,n11,missing_count` | Pooled unweighted Cohen kappa; resample whole clusters |
| `multirater_fleiss` | `unit_id,n0,...,n(K-1),missing_count` | Fleiss kappa with interchangeable raters; resample independent units |

IDs must be anonymous. `missing_count` is optional, reported separately and never
imputed. Each row describes complete observed counts for one independent cluster
or unit. Fleiss requires the same 2 to 100 observed ratings per unit and 2 to 20
categories. Confirm independence and name the sampling unit. Fixed-rater inference,
clustered multi-rater inference, weighted agreement and arbitrary mixed models
remain outside these recipes. Fleiss is not a substitute for a fixed-reader design.

Intervals are percentile bootstrap intervals with a recorded seed and sample count.
Fewer than 20 independent units raises a conservative method-review flag, not a
universal statistical cut-off. Undefined estimates, too many undefined resamples
or degenerate intervals are flagged. Warnings remain submission blockers; the
workbench does not silently waive them after calculation. Use an independently
reviewed method where the recipe does not fit. New estimates are available in
analysis receipts; only the original simple proportion recipe automatically feeds
the count/denominator result register. No calculated result is automatically approved.

Formula reference: [statsmodels Fleiss kappa documentation](https://www.statsmodels.org/stable/generated/statsmodels.stats.inter_rater.fleiss_kappa.html)
and its [implementation](https://www.statsmodels.org/stable/_modules/statsmodels/stats/inter_rater.html).
Validation uses hand-derived examples, deterministic resampling, known pooled
counts, permutations, invalid designs and receipt recomputation. This verifies
computation within the declared design, not clinical validity for a particular study.

## Rendering and dependency maintenance

The synthetic real-Office fixture includes nested tables, an equation, a footnote,
an embedded figure, a caption, a page break and an internal comment. The PDF checks
detect lost content and leaked comments while verifying that conversion leaves the
source DOCX unchanged. Separate negative fixtures test missing features. These are
content/layout regressions, not a pixel-perfect guarantee for arbitrary manuscripts.
Final manuscript visual inspection remains required.

Run the dedicated test with `RUN_OFFICE_INTEGRATION=1`. LibreOffice is the default;
set `LIBREOFFICE_EXECUTABLE` when it is not on PATH. On Windows, set
`OFFICE_TEST_ENGINE=word` to exercise installed Microsoft Word. CI exercises
LibreOffice; Word testing requires a licensed local installation.

Dependabot proposes weekly Python, GitHub Actions and Docker updates for review
after this configuration is merged. It does not auto-merge. Python requirements
are exactly pinned and external workflow actions use full commit hashes. The
offline build-pin check rejects floating pins. Existing Docker image digest
pinning remains. OS packages installed by CI are distribution-managed, not frozen
to historical snapshots. Dependency installation and update discovery require
network access; application and model tests remain offline.

The repository's `main` branch now requires all five jobs: Windows and Linux Python,
TeX, OCR and Office. The Office requirement was applied and read back on
15 November 2026, preserving strict checks, administrator enforcement and the
existing GitHub Actions app bindings. This is a hosting setting, so a clone alone
cannot enforce it; recheck the branch settings before future releases.

References: [Dependabot configuration](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
and [GitHub Actions security](https://docs.github.com/en/actions/reference/security/secure-use).

Encryption reference: [cryptography 50 Fernet documentation](https://cryptography.io/en/50.0.0/fernet/),
including its password derivation guidance and in-memory size limitation, accessed
15 November 2026.
