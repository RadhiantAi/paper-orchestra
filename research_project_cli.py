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
    if getattr(args, "output", None):
        private_path(args.output)
    if c == "init":
        create_project(w)
        result = {"status": "created"}
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
        c == "journal-check" and result.get("status") != "checked"
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
