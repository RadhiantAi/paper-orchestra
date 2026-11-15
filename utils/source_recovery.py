"""Local OCR and explicit source coverage; recovered text needs human review."""

from collections import defaultdict
from pathlib import Path
import csv
import io
import subprocess
import uuid

from utils.project_store import (
    load_project,
    update_project,
    private_path,
    current_file,
    file_receipt,
)
from utils.research_quality import fingerprint


def source_inventory(data):
    groups = defaultdict(list)
    for source in data["sources"]:
        if source.get("sha256"):
            groups[source["sha256"]].append(source["id"])
    text_groups = defaultdict(list)
    for source in data["sources"]:
        body = " ".join(" ".join(b["text"].split()) for b in source.get("blocks", []))
        if body:
            text_groups[fingerprint(body)].append(source["id"])
    return {
        "sources": len(data["sources"]),
        "unreadable": [s["id"] for s in data["sources"] if s["status"] == "unreadable"],
        "partial": [s["id"] for s in data["sources"] if s["status"] == "partial"],
        "missing_files": [
            s["id"] for s in data["sources"] if s.get("path") and not current_file(s)
        ],
        "missing_roots": sorted(
            {
                p
                for search in data["searches"]
                for p in search.get("missing_roots", [])
                if not Path(p).exists()
            }
        ),
        "identical_files": [ids for ids in groups.values() if len(ids) > 1],
        "same_text_candidates": [ids for ids in text_groups.values() if len(ids) > 1],
        "ocr_needing_review": sum(
            bool(b.get("review_required"))
            for s in data["sources"]
            for b in s.get("blocks", [])
        ),
        "scope": "Indexed sources and declared roots only. Same text does not prove the same figures or edits.",
    }


def _ocr_image(path, executable):
    result = subprocess.run(
        [str(Path(executable).resolve()), str(path), "stdout", "tsv"],
        capture_output=True,
        timeout=90,
    )
    if result.returncode:
        raise ValueError("Local OCR failed; source coverage remains incomplete.")
    if len(result.stdout) > 8 * 1024**2:
        raise ValueError("OCR output exceeds the extraction limit.")
    rows = list(
        csv.DictReader(
            io.StringIO(result.stdout.decode("utf-8", errors="replace")), delimiter="\t"
        )
    )
    words = [r for r in rows if r.get("text", "").strip()]
    confidences = [float(r["conf"]) for r in words if float(r.get("conf", -1)) >= 0]
    return " ".join(r["text"] for r in words), sum(confidences) / len(
        confidences
    ) if confidences else None


def retain_ocr(old, record):
    """Reindexing an unchanged source preserves reviewed OCR and its provenance."""
    from copy import deepcopy

    if old.get("sha256") != record.get("sha256"):
        return
    blocks = [
        deepcopy(b)
        for b in old.get("blocks", [])
        if b.get("method") == "local_ocr" and current_file(b.get("preview", {}))
    ]
    for block in blocks:
        review = block.get("review", {})
        if (
            not review.get("reviewer")
            or not review.get("reason")
            or review.get("identity")
            != fingerprint([record["sha256"], block["text"], block["preview"]])
        ):
            block["review_required"] = True
    record["blocks"].extend(blocks)
    if blocks:
        record["ocr_engine"] = old.get("ocr_engine")
        reviewed = {
            b["locator"].removesuffix(":ocr")
            for b in blocks
            if not b.get("review_required")
        }
        record["warnings"] = [
            w
            for w in record["warnings"]
            if not (
                w.endswith(":no_extractable_text_ocr_required")
                and w.split(":no_extractable")[0] in reviewed
            )
        ]
        if any(b.get("review_required") for b in blocks):
            record["warnings"].append("ocr_requires_review")


def recover_ocr(workspace, source_id, executable, max_pages=30):
    if type(max_pages) is not int or not 1 <= max_pages <= 100:
        raise ValueError("Choose an OCR page limit between 1 and 100.")
    engine = file_receipt(executable)
    data = load_project(workspace)
    source = next(s for s in data["sources"] if s["id"] == source_id)
    if not source.get("path") or not current_file(source):
        raise ValueError("Index a current local source before OCR.")
    path = Path(source["path"])
    from utils.strict_trial import admit_file
    admit_file(workspace, path)
    directory = private_path(workspace) / "ocr" / uuid.uuid4().hex
    directory.mkdir(parents=True)
    recovered = []

    def failed():
        def mark(data):
            s = next(s for s in data["sources"] if s["id"] == source_id)
            s["status"] = "partial"
            s["warnings"] = sorted(set(s.get("warnings", []) + ["ocr_failed"]))

        update_project(workspace, mark)

    def extract(image, locator):
        try:
            body, confidence = _ocr_image(image, executable)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            failed()
            raise ValueError("Local OCR failed. Coverage remains incomplete.") from None
        if body.strip():
            recovered.append(
                {
                    "locator": locator,
                    "text": body,
                    "ocr_text": body,
                    "method": "local_ocr",
                    "review_required": True,
                    "confidence": confidence,
                    "preview": file_receipt(image),
                }
            )

    if path.suffix.lower() == ".pdf":
        import pymupdf as fitz

        with fitz.open(path) as pdf:
            if len(pdf) > 1000:
                raise ValueError("PDF exceeds the OCR page budget.")
            missing = [n for n, p in enumerate(pdf) if not p.get_text().strip()]
            for n in missing[:max_pages]:
                image = directory / f"page-{n + 1}.png"
                pdf[n].get_pixmap(dpi=150).save(image)
                extract(image, f"page:{n + 1}:ocr")
    elif path.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        from PIL import Image

        image = directory / "image.png"
        with Image.open(path) as original:
            original.convert("RGB").save(image)
        extract(image, "image:ocr")
    else:
        raise ValueError("OCR supports PDF and image files.")
    if not recovered:
        failed()
        raise ValueError("No text recovered; source coverage remains incomplete.")

    def apply(current):
        s = next(s for s in current["sources"] if s["id"] == source_id)
        if s.get("sha256") != source["sha256"] or not current_file(s):
            raise ValueError("Source changed during OCR.")
        locators = {b["locator"] for b in recovered}
        s["blocks"] = [
            b for b in s["blocks"] if b["locator"] not in locators
        ] + recovered
        s["ocr_engine"] = engine
        s["status"] = "partial"
        s["warnings"] = sorted(
            set(
                [w for w in s.get("warnings", []) if w != "ocr_failed"]
                + ["ocr_requires_review"]
            )
        )

    update_project(workspace, apply)
    return {"pages_recovered": len(recovered), "status": "needs_review"}


def confirm_ocr(workspace, source_id, locator, reviewer, reason, correction=None):
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Reviewer and reason required.")

    def apply(data):
        s = next(s for s in data["sources"] if s["id"] == source_id)
        if not current_file(s):
            raise ValueError("Source changed since OCR.")
        b = next(
            b
            for b in s["blocks"]
            if b["locator"] == locator and b.get("method") == "local_ocr"
        )
        if not current_file(b["preview"]):
            raise ValueError("OCR preview changed or disappeared.")
        if correction is not None:
            if not correction.strip():
                raise ValueError("Corrected text cannot be empty.")
            b["text"] = correction
        b["review_required"] = False
        b["review"] = {
            "reviewer": reviewer,
            "reason": reason,
            "identity": fingerprint([s["sha256"], b["text"], b["preview"]]),
        }
        pending = any(x.get("review_required") for x in s["blocks"])
        reviewed = {
            x["locator"].removesuffix(":ocr")
            for x in s["blocks"]
            if x.get("method") == "local_ocr" and not x.get("review_required")
        }
        s["warnings"] = [
            w
            for w in s.get("warnings", [])
            if not (
                w.endswith(":no_extractable_text_ocr_required")
                and w.split(":no_extractable")[0] in reviewed
            )
            and not (w == "ocr_requires_review" and not pending)
        ]
        s["status"] = "partial" if s["warnings"] or pending else "read"

    return update_project(workspace, apply)
