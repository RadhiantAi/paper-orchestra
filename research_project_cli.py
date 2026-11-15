"""Private host-assisted projects: sources, review, results, figures and checked packs."""

import argparse
import json
from pathlib import Path

from utils.project_store import (
    create_project,
    load_project,
    update_project,
    private_path,
)
from utils.project_sources import index_sources, search_index
from utils.project_review import (
    import_host,
    decide_query,
    compare_versions,
    discussion_coverage,
)
from utils.project_results import export_result_assets
from utils.review_actions import approve_selected
from utils.source_recovery import source_inventory, recover_ocr, confirm_ocr
from utils.analysis_recipes import run_recipe, register_proportions
from utils.journal_checks import check_journal
from utils.project_figures import mask_image, match_images, figure_identity
from utils.project_pack import (
    prepare_pack,
    check_pack,
    record_visual_review,
    release_pack,
    doc_text,
)
from utils.run_control import write_json


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    a = sub.add_parser("review-check")
    a.add_argument("kind", choices=["workbook_visual", "calculation_interpretation"])
    a.add_argument("target")
    a.add_argument("checks", help="JSON object with each required checkbox explicitly recorded")
    a.add_argument("--decision", required=True, choices=["accepted", "unresolved"])
    a.add_argument("--manuscript")
    a.add_argument("--quote")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    for command, field in [("trial-protocol", "protocol"), ("trial-draft", "draft"), ("trial-freeze", "directory")]:
        a = sub.add_parser(command)
        a.add_argument(field)
        a.add_argument("--reviewer", required=True)
        a.add_argument("--reason", required=True)
    a = sub.add_parser("trial-unblind")
    a.add_argument("--hashes", nargs="+", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("trial-compare")
    a.add_argument("reference")
    a.add_argument("--output", required=True)
    a = sub.add_parser("continuous-figure")
    a.add_argument("spec")
    a.add_argument("--output", required=True)
    a = sub.add_parser("strict-trial")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("allocate-host")
    a.add_argument("origin")
    a.add_argument("sha256")
    a.add_argument("--role", required=True, choices=["candidate_primary", "trial_input", "withheld_reference", "uncertain", "excluded"])
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("convert-workbook")
    a.add_argument("source")
    a.add_argument("--output", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("continuous-result")
    a.add_argument("calculation_id")
    a.add_argument("selector", help="JSON selector file")
    a.add_argument("--id", required=True)
    a.add_argument("--label", required=True)
    a.add_argument("--definition", required=True)
    a.add_argument("--precision", type=int, default=2)
    a = sub.add_parser("review-continuous")
    a.add_argument("--ids", nargs="+", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("source-structure")
    a.add_argument("source")
    a.add_argument("--output", required=True)
    a = sub.add_parser("allocate-source")
    a.add_argument("source")
    a.add_argument("--role", required=True, choices=["candidate_primary", "trial_input", "withheld_reference", "uncertain", "excluded"])
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("completeness-check")
    a.add_argument("manuscript")
    a.add_argument("--profile")
    a.add_argument("--output", required=True)
    a = sub.add_parser("image-locations")
    a.add_argument("document")
    a.add_argument("--output", required=True)
    a = sub.add_parser("workbook-result")
    a.add_argument("source_id")
    a.add_argument("--count-cell", required=True)
    a.add_argument("--denominator-cell", required=True)
    a.add_argument("--id", required=True)
    a.add_argument("--label", required=True)
    a.add_argument("--definition", required=True)
    a = sub.add_parser("claim")
    a.add_argument("mapping")
    a = sub.add_parser("consistency-check")
    a.add_argument("manuscript")
    a.add_argument("--output", required=True)
    a = sub.add_parser("consistency-review")
    a.add_argument("manuscript")
    a.add_argument("finding_id")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("provenance")
    a.add_argument("source_id")
    a.add_argument(
        "--kind",
        choices=[
            "unknown",
            "confirmed_issued",
            "reconstructed",
            "published",
            "working_draft",
        ],
        required=True,
    )
    a.add_argument("--evidence-file")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("backup")
    a.add_argument("--output", required=True)
    a.add_argument("--snapshot")
    a.add_argument(
        "--encrypt",
        action="store_true",
        help="Prompt privately for an export passphrase; use a .porx output",
    )
    a = sub.add_parser("restore")
    a.add_argument("archive")
    a.add_argument(
        "--encrypted",
        action="store_true",
        help="Prompt privately for the restore passphrase",
    )
    a = sub.add_parser("retention-preview")
    a.add_argument("--keep-latest", type=int, default=20)
    a.add_argument("--keep-days", type=int, default=30)
    a.add_argument("--output", required=True)
    a = sub.add_parser("inventory")
    a.add_argument("--output", required=True)
    a = sub.add_parser("ocr")
    a.add_argument("source_id")
    a.add_argument("--executable", required=True)
    a.add_argument("--max-pages", type=int, default=30)
    a = sub.add_parser("confirm-ocr")
    a.add_argument("source_id")
    a.add_argument("locator")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a.add_argument("--correction-file")
    a = sub.add_parser("analyse")
    a.add_argument("recipe")
    a.add_argument("csv")
    a.add_argument("--output", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("register-analysis")
    a.add_argument("calculation_id")
    a.add_argument("--definition", required=True)
    a = sub.add_parser("journal-check")
    a.add_argument("profile")
    a.add_argument("manuscript")
    a.add_argument("--output", required=True)
    a = sub.add_parser("index")
    a.add_argument("roots", nargs="+")
    a.add_argument("--convert-legacy", action="store_true")
    a.add_argument("--libreoffice")
    a.add_argument("--max-files", type=int, default=2000)
    a = sub.add_parser("search")
    a.add_argument("terms", nargs="+")
    a.add_argument("--output", required=True)
    a = sub.add_parser("import-host")
    a.add_argument("payload")
    a = sub.add_parser("decide")
    a.add_argument("query_id")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a.add_argument("--action", choices=["confirm", "flag"], default="confirm")
    a.add_argument("--proofs")
    a = sub.add_parser("compare")
    a.add_argument("before")
    a.add_argument("after")
    a.add_argument("--output", required=True)
    a = sub.add_parser("coverage")
    a.add_argument("manuscript")
    a.add_argument("--output", required=True)
    a = sub.add_parser("approve-results")
    a.add_argument("--ids", nargs="+", required=True)
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("export-results")
    a.add_argument("--output", required=True)
    a = sub.add_parser("confirm-figure")
    a.add_argument("figure_id")
    a.add_argument(
        "--check",
        choices=[
            "image_identity",
            "caption",
            "clinical",
            "cohort",
            "reproduction",
            "privacy",
        ],
        required=True,
    )
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("mask")
    a.add_argument("image")
    a.add_argument("--output", required=True)
    a.add_argument(
        "--rectangles",
        required=True,
        help="JSON file of pixel rectangles [left,top,right,bottom]",
    )
    a.add_argument("--reviewer", required=True)
    a.add_argument("--reason", required=True)
    a = sub.add_parser("match")
    a.add_argument("image")
    a.add_argument("candidates", nargs="+")
    a.add_argument("--output", required=True)
    a = sub.add_parser("prepare")
    a.add_argument("spec")
    a.add_argument("--output", required=True)
    a.add_argument("--libreoffice")
    a = sub.add_parser("check")
    a.add_argument("directory")
    a = sub.add_parser("visual-review")
    a.add_argument("directory")
    a.add_argument("--reviewer", required=True)
    a.add_argument("--notes", required=True)
    a = sub.add_parser("release")
    a.add_argument("directory")
    a.add_argument("--output", required=True)
    args = p.parse_args(argv)
    w = args.workspace
    c = args.command
    from utils.strict_trial import admit_file
    # Structure/allocation inspect metadata only; all other direct evidence readers
    # must admit external files before opening their contents.
    if (Path(w) / "project.json").exists() and c not in {"init", "restore", "allocate-source", "source-structure"}:
        for field in ["manuscript", "document", "image", "correction_file"]:
            if getattr(args, field, None):
                admit_file(w, getattr(args, field))
        for path in getattr(args, "candidates", []):
            admit_file(w, path)
    if getattr(args, "output", None):
        private_path(args.output)
    if c == "init":
        create_project(w)
        result = {"status": "created"}
    elif c == "review-check":
        from utils.reviewer_checks import review_check
        review_check(w, args.kind, args.target, args.reviewer, args.reason, args.decision, read(args.checks), args.manuscript, args.quote)
        result = {"status": "human_check_recorded", "author_approval": False}
    elif c == "trial-protocol":
        from utils.trial_evaluation import freeze_protocol
        freeze_protocol(w, read(args.protocol), args.reviewer, args.reason)
        result = {"status": "protocol_frozen"}
    elif c == "trial-draft":
        from utils.trial_evaluation import register_draft
        register_draft(w, args.draft, args.reviewer, args.reason)
        result = {"status": "operator_draft_declaration_recorded"}
    elif c == "trial-freeze":
        from utils.trial_evaluation import freeze_candidate
        freeze_candidate(w, args.directory, args.reviewer, args.reason)
        result = {"status": "candidate_frozen_not_author_approved"}
    elif c == "trial-unblind":
        from utils.trial_evaluation import unblind
        unblind(w, args.hashes, args.reviewer, args.reason)
        result = {"status": "explicit_unblinding_recorded"}
    elif c == "trial-compare":
        from utils.trial_evaluation import compare_reference
        report = compare_reference(w, args.reference, args.output)
        result = {"status": report["status"], "scope": report["scope"]}
    elif c == "continuous-figure":
        from utils.continuous_figures import export_continuous_figure
        row = export_continuous_figure(w, read(args.spec), args.output)
        result = {"status": "figure_exported_not_author_approved", "id": row["id"]}
    elif c == "strict-trial":
        from utils.strict_trial import enable_strict_trial
        enable_strict_trial(w, args.reviewer, args.reason)
        result = {"status": "strict_trial_enabled"}
    elif c == "allocate-host":
        from utils.strict_trial import allocate_host
        allocate_host(w, args.origin, args.sha256, args.role, args.reviewer, args.reason)
        result = {"status": "host_allocation_recorded"}
    elif c == "convert-workbook":
        from utils.legacy_workbooks import convert_workbook
        record = convert_workbook(w, args.source, args.output, args.reviewer, args.reason)
        result = {"status": record["status"], "visual_review_required": True}
    elif c == "continuous-result":
        from utils.continuous_results import register_continuous
        register_continuous(w, args.id, args.calculation_id, read(args.selector), args.label, args.definition, args.precision)
        result = {"status": "registered_needs_technical_review"}
    elif c == "review-continuous":
        from utils.continuous_results import review_continuous
        review_continuous(w, args.ids, args.reviewer, args.reason)
        result = {"status": "technically_reviewed_not_author_approved"}
    elif c == "workbook-result":
        from utils.workbook_sources import register_workbook_result

        register_workbook_result(
            w,
            args.source_id,
            args.count_cell,
            args.denominator_cell,
            args.id,
            args.label,
            args.definition,
        )
        result = {"status": "registered_not_approved"}
    elif c == "claim":
        from utils.manuscript_consistency import save_claim

        save_claim(w, read(args.mapping))
        result = {"status": "claim_mapping_saved"}
    elif c == "consistency-check":
        from utils.manuscript_consistency import audit_consistency

        report = audit_consistency(load_project(w), doc_text(args.manuscript))
        write_json(args.output, report)
        result = {"status": report["status"], "findings": len(report["findings"])}
    elif c == "consistency-review":
        from utils.manuscript_consistency import review_finding

        review_finding(
            w, doc_text(args.manuscript), args.finding_id, args.reviewer, args.reason
        )
        result = {"status": "consistency_review_recorded"}
    elif c == "provenance":
        from utils.version_provenance import set_source_provenance

        set_source_provenance(
            w, args.source_id, args.kind, args.reviewer, args.reason, args.evidence_file
        )
        result = {"status": "version_provenance_recorded"}
    elif c == "backup":
        from utils.project_recovery import backup_project

        password = None
        if args.encrypt:
            from getpass import getpass

            password = getpass("Backup passphrase: ")
            if password != getpass("Repeat passphrase: "):
                raise ValueError("Passphrases do not match.")
        result = backup_project(w, args.output, args.snapshot, password)
    elif c == "restore":
        from utils.project_recovery import restore_project

        from utils.recovery_crypto import MAGIC

        with Path(args.archive).open("rb") as stream:
            encrypted = stream.read(len(MAGIC)) == MAGIC
        password = None
        if encrypted or args.encrypted:
            from getpass import getpass

            password = getpass("Recovery passphrase: ")
        result = restore_project(args.archive, w, password)
    elif c == "retention-preview":
        from utils.recovery_storage import retention_preview

        report = retention_preview(w, args.keep_latest, args.keep_days)
        destination = private_path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2)
        result = {
            "status": report["status"],
            "candidate_snapshots": len(report["candidate_snapshots"]),
            "deletion_performed": False,
        }
    elif c == "source-structure":
        from utils.source_structure import inspect_structure
        report = inspect_structure(args.source)
        write_json(private_path(args.output), report)
        result = {"status": report["status"], "sheets": len(report["sheets"])}
    elif c == "allocate-source":
        from utils.source_structure import allocate_source
        allocate_source(w, args.source, args.role, args.reviewer, args.reason)
        result = {"status": "allocation_recorded_not_author_approval"}
    elif c == "completeness-check":
        from utils.manuscript_completeness import audit_completeness
        report = audit_completeness(doc_text(args.manuscript), read(args.profile) if args.profile else None)
        write_json(private_path(args.output), report)
        result = {"status": report["status"], "findings": len(report["findings"])}
    elif c == "image-locations":
        import hashlib
        from utils.figure_presence import image_occurrences
        report = [{"location": loc, "sha256": hashlib.sha256(blob).hexdigest()} for blob, loc in image_occurrences(args.document)]
        write_json(private_path(args.output), report)
        result = {"status": "saved", "occurrences": len(report)}
    elif c == "inventory":
        report = source_inventory(load_project(w))
        write_json(args.output, report)
        result = {"sources": report["sources"], "status": "saved"}
    elif c == "ocr":
        result = recover_ocr(w, args.source_id, args.executable, args.max_pages)
    elif c == "confirm-ocr":
        confirm_ocr(
            w,
            args.source_id,
            args.locator,
            args.reviewer,
            args.reason,
            Path(args.correction_file).read_text(encoding="utf-8")
            if args.correction_file
            else None,
        )
        result = {"status": "ocr_review_recorded"}
    elif c == "analyse":
        record = run_recipe(
            w, read(args.recipe), args.csv, args.output, args.reviewer, args.reason
        )
        result = {"status": "calculated_not_approved", "id": record["id"]}
    elif c == "register-analysis":
        register_proportions(w, args.calculation_id, args.definition)
        result = {"status": "registered_not_approved"}
    elif c == "journal-check":
        data = load_project(w)
        report = check_journal(
            read(args.profile),
            doc_text(args.manuscript),
            data["figures"],
            data.get("journal_reviews"),
        )
        write_json(args.output, report)
        result = {"status": report["status"], "findings": len(report["findings"])}
    elif c == "index":
        if args.max_files < 1:
            p.error("--max-files must be positive")
        report = index_sources(
            w,
            args.roots,
            convert=args.convert_legacy,
            libreoffice=args.libreoffice,
            max_files=args.max_files,
        )
        result = {
            k: report[k] for k in ["discovered", "processed", "truncated", "complete"]
        }
    elif c == "import-host":
        import_host(w, read(args.payload))
        result = {"status": "imported", "local_model_calls": 0}
    elif c == "decide":
        decide_query(
            w,
            args.query_id,
            args.reviewer,
            args.reason,
            args.action,
            read(args.proofs) if args.proofs else None,
        )
        result = {"status": "recorded"}
    elif c == "search":
        matches = search_index(load_project(w), args.terms)
        write_json(args.output, matches)
        result = {"matches": len(matches)}
    elif c == "compare":
        data = load_project(w)
        sources = {s["id"]: s for s in data["sources"]}
        report = compare_versions(
            sources[args.before], sources[args.after], data.get("edit_decisions")
        )
        write_json(args.output, report)
        result = {
            "unresolved": sum(e["status"] == "unresolved" for e in report["edits"])
        }
    elif c == "coverage":
        report = discussion_coverage(
            load_project(w), Path(args.manuscript).read_text(encoding="utf-8")
        )
        write_json(args.output, report)
        result = {"status": report["status"], "findings": len(report["findings"])}
    elif c == "approve-results":
        approve_selected(w, args.ids, args.reviewer, args.reason)
        result = {"status": "approval_recorded"}
    elif c == "export-results":
        result = export_result_assets(load_project(w)["results"], args.output)
    elif c == "confirm-figure":
        if not args.reviewer.strip() or not args.reason.strip():
            p.error("Reviewer and reason cannot be blank")

        def apply(data):
            f = next(f for f in data["figures"] if f["id"] == args.figure_id)
            f.setdefault("checks", {})[args.check] = {
                "status": "confirmed",
                "identity": figure_identity(f),
                "reviewer": args.reviewer,
                "reason": args.reason,
            }

        update_project(w, apply)
        result = {"status": "confirmation_recorded"}
    elif c == "mask":
        mask_image(
            args.image, args.output, read(args.rectangles), args.reviewer, args.reason
        )
        result = {"status": "masked_copy_created", "privacy": "visual_review_required"}
    elif c == "match":
        matches = match_images(args.image, args.candidates)
        write_json(args.output, matches)
        result = {"candidates": len(matches), "clinical_approval": False}
    elif c == "prepare":
        report = prepare_pack(w, read(args.spec), args.output, args.libreoffice)
        result = {
            "status": report["status"],
            "problems": len(report["problems"]),
            "pending": len(report["pending"]),
        }
    elif c == "check":
        report = check_pack(w, args.directory)
        write_json(Path(args.directory) / "pack_check.json", report)
        result = {
            "status": report["status"],
            "problems": len(report["problems"]),
            "pending": len(report["pending"]),
        }
    elif c == "visual-review":
        record_visual_review(w, args.directory, args.reviewer, args.notes)
        result = {"status": "visual_review_recorded"}
    else:
        result = release_pack(w, args.directory, args.output)
    # Counts/status only. Never print source contents or recognised patient identifiers.
    print(json.dumps(result, indent=2))
    if result.get("status") in {"failed", "incomplete", "blocked"} or (
        c in {"journal-check", "consistency-check", "completeness-check"}
        and result.get("status") != "checked"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
