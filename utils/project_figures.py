"""Image provenance and authorised local masking; no generative image path."""

import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image

from utils.project_store import current_file, file_receipt, private_path, require_text
from utils.research_quality import fingerprint


def validate_figure(r):
    require_text(r, "id", "caption")
    if not isinstance(r.get("panels"), list) or not r["panels"]:
        raise ValueError("A figure requires panels.")
    names = []
    for p in r["panels"]:
        require_text(p, "label", "source_id", "source_locator", "source_label")
        for kind in ["original", "display"]:
            require_text(p.get(kind, {}), "path", "sha256")
        names.append(p["label"])
    if len(set(names)) != len(names):
        raise ValueError("Duplicate panel labels.")


def figure_identity(r):
    return fingerprint({k: v for k, v in r.items() if k != "checks"})


def figure_issues(r):
    validate_figure(r)
    issues = []
    for p in r["panels"]:
        for kind in ["original", "display"]:
            if not current_file(p[kind]):
                issues.append(
                    {"panel": p["label"], "kind": kind + "_changed_or_missing"}
                )
        if p.get("mask_receipt"):
            try:
                verify_mask(p["mask_receipt"])
                receipt = p["mask_receipt"]
                if (
                    receipt["original"]["sha256"] != p["original"]["sha256"]
                    or receipt["display"]["sha256"] != p["display"]["sha256"]
                ):
                    raise ValueError("Mask belongs to another image.")
            except (ValueError, OSError):
                issues.append({"panel": p["label"], "kind": "invalid_mask"})
    for name in [
        "image_identity",
        "caption",
        "clinical",
        "cohort",
        "reproduction",
        "privacy",
    ]:
        check = r.get("checks", {}).get(name, {})
        if not (
            check.get("status") == "confirmed"
            and check.get("reviewer")
            and check.get("reason")
            and check.get("identity") == figure_identity(r)
        ):
            issues.append({"kind": name + "_needs_confirmation"})
    return issues


def mask_image(source, destination, rectangles, reviewer, reason):
    if not reviewer.strip() or not reason.strip() or not rectangles:
        raise ValueError("Explicit masking authorisation and rectangles required.")
    source, dest = Path(source).resolve(), private_path(destination)
    if dest == source or dest.exists() or dest.suffix.lower() != ".png":
        raise ValueError("Use a new PNG output; never overwrite an original.")
    pixels = np.asarray(Image.open(source).convert("RGB")).copy()
    h, w = pixels.shape[:2]
    mask = np.zeros((h, w), dtype=bool)
    for rect in rectangles:
        if len(rect) != 4 or any(type(x) is not int for x in rect):
            raise ValueError("Rectangles must contain four integer coordinates.")
        l, t, r, b = rect
        if not (0 <= l < r <= w and 0 <= t < b <= h):
            raise ValueError("Mask rectangle outside image.")
        mask[t:b, l:r] = True
    if mask.all():
        raise ValueError("Mask would remove the entire image.")
    original_roi = hashlib.sha256(pixels[~mask].tobytes()).hexdigest()
    pixels[mask] = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels).save(dest)  # new PNG omits original EXIF and text metadata
    receipt = {
        "original": file_receipt(source),
        "display": file_receipt(dest),
        "rectangles": rectangles,
        "unchanged_pixels_sha256": original_roi,
        "authorised_by": reviewer,
        "reason": reason,
        "privacy_status": "visual_confirmation_required",
    }
    verify_mask(receipt)
    dest.with_suffix(".mask.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    return receipt


def verify_mask(receipt):
    if not current_file(receipt["original"]) or not current_file(receipt["display"]):
        raise ValueError("Image changed since masking.")
    a = np.asarray(Image.open(receipt["original"]["path"]).convert("RGB"))
    b = np.asarray(Image.open(receipt["display"]["path"]).convert("RGB"))
    if a.shape != b.shape:
        raise ValueError("Image size changed.")
    mask = np.zeros(a.shape[:2], dtype=bool)
    if not receipt.get("rectangles"):
        raise ValueError("Mask receipt has no rectangles.")
    for rect in receipt["rectangles"]:
        if len(rect) != 4 or any(type(v) is not int for v in rect):
            raise ValueError("Invalid mask receipt coordinates.")
        l, t, r, bottom = rect
        h, w = a.shape[:2]
        if not (0 <= l < r <= w and 0 <= t < bottom <= h):
            raise ValueError("Mask receipt rectangle outside image.")
        mask[t:bottom, l:r] = True
    if mask.all():
        raise ValueError("Mask receipt removes entire image.")
    if not np.array_equal(a[~mask], b[~mask]) or np.any(b[mask]):
        raise ValueError(
            "Mask changed unapproved pixels or left masked pixels visible."
        )
    if (
        hashlib.sha256(a[~mask].tobytes()).hexdigest()
        != receipt["unchanged_pixels_sha256"]
    ):
        raise ValueError("Mask region receipt mismatch.")
    return True


def match_images(target, candidates, *, min_inliers=35):
    """Suggest matches using anatomical/central features, never approve captions."""
    import cv2

    def decode(p):
        im = Image.open(p).convert("L")
        im.thumbnail((1100, 1100))
        return np.asarray(im)

    a = decode(target)
    sift = cv2.SIFT_create(nfeatures=0)
    mask = np.zeros_like(a)
    h, w = a.shape
    mask[int(h * 0.16) : int(h * 0.84), int(w * 0.12) : int(w * 0.88)] = 255
    ka, da = sift.detectAndCompute(a, mask)
    matches = []
    for candidate in candidates:
        try:
            b = decode(candidate)
            if np.array_equal(a, b):
                matches.append(
                    {
                        "path": str(candidate),
                        "method": "decoded_pixels",
                        "candidate_only": True,
                    }
                )
                continue
            kb, db = sift.detectAndCompute(b, None)
            if da is None or db is None or len(db) < 2:
                continue
            good = [
                m
                for pair in cv2.BFMatcher().knnMatch(da, db, k=2)
                if len(pair) == 2
                for m, n in [pair]
                if m.distance < 0.7 * n.distance
            ]
            if len(good) < min_inliers:
                continue
            x = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
            y = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
            _, inliers = cv2.findHomography(x, y, cv2.RANSAC, 4)
            count = int(inliers.sum()) if inliers is not None else 0
            if count >= min_inliers and count / len(good) >= 0.5:
                matches.append(
                    {
                        "path": str(candidate),
                        "method": "geometric_features",
                        "inliers": count,
                        "candidate_only": True,
                    }
                )
        except (OSError, ValueError, cv2.error):
            continue
    return matches


def scan_identifiers(image, tesseract):
    """Optional local OCR clue scan. A clean scan never grants privacy approval."""
    import subprocess
    import re

    r = subprocess.run(
        [str(Path(tesseract).resolve()), str(Path(image).resolve()), "stdout"],
        capture_output=True,
        timeout=45,
    )
    if r.returncode:
        return {"status": "not_checked", "reason": "ocr_failed"}
    # Never return recognised identifiers, only counts and coarse categories.
    body = r.stdout.decode("utf-8", errors="replace")
    counts = {
        "identifier_labels": len(
            re.findall(r"patient|name|birth|accession|hospital|\bid\b", body, re.I)
        ),
        "date_patterns": len(re.findall(r"\b\d{1,4}[/.-]\d{1,2}[/.-]\d{1,4}\b", body)),
    }
    return {
        "status": "needs_visual_review",
        "counts": counts,
        "scope": "OCR can miss burned-in identifiers and does not certify anonymisation.",
    }
