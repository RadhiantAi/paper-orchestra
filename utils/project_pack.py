"""Checked co-author packs with explicit review status and file-bound receipts."""

from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import zipfile

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Inches

from utils.project_store import (
    dependency_status,
    load_project,
    private_path,
    require_text,
)
from utils.project_review import discussion_coverage, query_status
from utils.project_results import audit_occurrences, render_results
from utils.project_figures import figure_issues
from utils.research_quality import fingerprint
from utils.run_control import digest, write_json


def paragraph_replace(p, old, new, yellow=False):
    """Replace one exact span while retaining the formatting of surrounding runs."""
    if p.text.count(old) != 1:
        raise ValueError("Review anchor must identify one exact occurrence.")
    start = p.text.index(old)
    end = start + len(old)
    position = 0
    selected = []
    for run in list(p.runs):
        length = len(run.text)
        left, right = position, position + length
        position = right
        if right <= start or left >= end:
            continue
        before = run.text[: max(0, start - left)]
        after = run.text[max(0, end - left) :] if right > end else ""
        original = deepcopy(run._r)
        run.text = before
        anchor = run._r
        if left <= start < right:
            nr = deepcopy(original)
            for child in list(nr):
                if child.tag.endswith("}t"):
                    nr.remove(child)
            from docx.text.run import Run

            anchor.addnext(nr)
            r = Run(nr, p)
            r.text = new
            if yellow:
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
            selected.append(r)
            anchor = nr
        if after:
            ar = deepcopy(original)
            anchor.addnext(ar)
            from docx.text.run import Run

            Run(ar, p).text = after
    if not selected:
        raise ValueError("Cannot anchor empty or unsupported Word content.")
    return selected


def all_paragraphs(doc):
    yield from doc.paragraphs
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                yield from cell.paragraphs


def reviewed_span(paragraph, quote):
    """Check the requested text itself, rather than a neighbouring yellow run."""
    if paragraph.text.count(quote) != 1:
        return False, False
    start = paragraph.text.index(quote)
    end = start + len(quote)
    colours = [
        r.font.highlight_color == WD_COLOR_INDEX.YELLOW
        for r in paragraph.runs
        for _ in r.text
    ]
    yellow = len(colours) >= end and all(colours[start:end])
    from docx.oxml.ns import qn

    offset, starts, ranges = 0, {}, []
    for node in paragraph._p:
        if node.tag == qn("w:commentRangeStart"):
            starts[node.get(qn("w:id"))] = offset
        elif node.tag == qn("w:commentRangeEnd"):
            key = node.get(qn("w:id"))
            if key in starts:
                ranges.append((starts[key], offset))
        elif node.tag == qn("w:r"):
            from docx.text.run import Run

            offset += len(Run(node, paragraph).text)
    return yellow, any(left <= start and right >= end for left, right in ranges)


def clear_owned_review(doc, query, protected_quotes):
    """Remove this workflow's resolved annotations; leave unrelated comments intact."""
    from docx.oxml.ns import qn

    owned = [c for c in doc.comments if c.text.startswith("[" + query["id"] + "] ")]
    if not owned:
        return
    anchors = [p for p in all_paragraphs(doc) if query["quote"] in p.text]
    if len(anchors) != 1 or anchors[0].text.count(query["quote"]) != 1:
        raise ValueError("Resolved query anchor missing or ambiguous: " + query["id"])
    p = anchors[0]
    left = p.text.index(query["quote"])
    right = left + len(query["quote"])
    overlap = False
    for quote in protected_quotes:
        for match in re.finditer(re.escape(quote), p.text):
            overlap |= match.start() < right and match.end() > left
    for comment in owned:
        cid = str(comment.comment_id)
        for node in doc._element.xpath(
            ".//w:commentRangeStart | .//w:commentRangeEnd | .//w:commentReference"
        ):
            if node.get(qn("w:id")) == cid:
                node.getparent().remove(node)
        comment._element.getparent().remove(comment._element)
    if not overlap:
        for run in paragraph_replace(p, query["quote"], query["quote"]):
            run.font.highlight_color = None


def image_pixel_hash(blob):
    """Identify known originals even when Office/PDF changes their container bytes."""
    from io import BytesIO
    from PIL import Image
    import hashlib

    try:
        with Image.open(BytesIO(blob)) as im:
            rgb = im.convert("RGB")
            return hashlib.sha256(str(rgb.size).encode() + rgb.tobytes()).hexdigest()
    except (OSError, ValueError):
        return None


def doc_text(path):
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return "\n".join(
            ("# " if p.style.name.startswith("Heading") else "") + p.text
            for p in all_paragraphs(Document(path))
        )
    if path.suffix.lower() == ".pdf":
        import pymupdf as fitz
        from collections import Counter

        with fitz.open(path) as d:
            pages = [(p.rect.height, p.get_text("blocks")) for p in d]
            repeated = Counter(
                b[4].strip()
                for h, blocks in pages
                for b in blocks
                if b[1] < 60 or b[3] > h - 45
            )
            return "\n".join(
                b[4]
                for h, blocks in pages
                for b in blocks
                if not ((b[1] < 60 or b[3] > h - 45) and repeated[b[4].strip()] > 1)
                and not (b[1] > h - 80 and b[4].strip().isdigit())
            )
    return path.read_text(encoding="utf-8-sig")


def normalise(text):
    return re.sub(r"\s+", "", text).replace("’", "'")


def render_word(source, destination, libreoffice=None):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("PDF destination already exists.")
    if libreoffice:
        with tempfile.TemporaryDirectory() as tmp:
            profile = (Path(tmp) / "profile").as_uri()
            r = subprocess.run(
                [
                    str(Path(libreoffice).resolve()),
                    "-env:UserInstallation=" + profile,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp,
                    str(source),
                ],
                capture_output=True,
                timeout=120,
            )
            pdf = Path(tmp) / (source.stem + ".pdf")
            if r.returncode or not pdf.exists():
                raise RuntimeError("Word rendering failed.")
            shutil.copy2(pdf, destination)
    elif __import__("os").name == "nt":
        quote = lambda p: "'" + str(p).replace("'", "''") + "'"
        script = (
            "$ErrorActionPreference='Stop'\n$w=New-Object -ComObject Word.Application\n$w.Visible=$false\n$w.DisplayAlerts=0\n$w.AutomationSecurity=3\ntry {$d=$w.Documents.Open("
            + quote(source)
            + ",$false,$true)\ntry {$d.ActiveWindow.View.ShowRevisionsAndComments=$false;$d.Repaginate();$d.ExportAsFixedFormat("
            + quote(destination)
            + ",17,$false,0,0,1,1,0)}finally{$d.Close(0)}}finally{$w.Quit()}"
        )
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=120,
        )
        if r.returncode or not destination.exists():
            raise RuntimeError("Word rendering failed.")
    else:
        raise ValueError("Select a local LibreOffice executable for PDF rendering.")


def figures_document(figures, destination):
    doc = Document()
    for index, fig in enumerate(figures):
        if index:
            doc.add_page_break()
        doc.add_heading(fig["id"], 1)
        table = doc.add_table(rows=2, cols=len(fig["panels"]))
        for cell, panel in zip(table.rows[0].cells, fig["panels"]):
            cell.text = panel["label"]
        for cell, panel in zip(table.rows[1].cells, fig["panels"]):
            cell.paragraphs[0].add_run().add_picture(
                panel["display"]["path"], width=Inches(6 / len(fig["panels"]))
            )
        p = doc.add_paragraph(fig["caption"])
        if figure_issues(fig):
            for r in p.runs:
                r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    doc.save(destination)


def prepare_pack(workspace, spec, output, libreoffice=None):
    spec = deepcopy(spec)
    spec.setdefault("stage", "coauthor_review")
    data = load_project(workspace)
    output = private_path(output)
    if output.exists():
        raise ValueError("Never overwrite a previous pack.")
    if dependency_status(data):
        raise ValueError("Source files changed or disappeared; reindex and review.")
    if spec.get("stage", "coauthor_review") not in {"coauthor_review", "submission"}:
        raise ValueError("Unknown pack stage.")
    roles = [f["role"] for f in spec["files"]]
    if roles.count("manuscript") != 1 or roles.count("title_page") != 1:
        raise ValueError("One manuscript and one title page are required.")
    names = [f["name"] for f in spec["files"]]
    if len({n.casefold() for n in names}) != len(names):
        raise ValueError("Duplicate output names.")
    for f in spec["files"]:
        require_text(f, "role", "name", "path", "sha256")
        if f["role"] == "title_page" and not f.get("preserve"):
            raise ValueError("Supply the approved title page with preserve=true.")
        if (
            f["role"] in {"title_page", "manuscript"}
            and Path(f["name"]).suffix.lower() != ".docx"
        ):
            raise ValueError(
                "The manuscript and approved title page must be Word documents."
            )
        p = PurePosixPath(f["name"])
        if p.is_absolute() or ".." in p.parts or "\\" in f["name"] or ":" in f["name"]:
            raise ValueError("Unsafe pack filename.")
        if p.name.casefold() in {
            "pack_spec.json",
            "pack_check.json",
            "visual_review.json",
            "release_receipt.json",
            "build_failure.json",
        }:
            raise ValueError("Reserved pack metadata filename.")
        if digest(f["path"]) != f["sha256"]:
            raise ValueError("Pack input changed.")
    for fig in data["figures"]:
        issues = figure_issues(fig)
        if any(
            i["kind"]
            in {
                "privacy_needs_confirmation",
                "display_changed_or_missing",
                "original_changed_or_missing",
                "invalid_mask",
            }
            for i in issues
        ):
            raise ValueError(
                "Figure privacy or integrity requires review before packaging."
            )
    output.mkdir(parents=True)
    try:
        for f in spec["files"]:
            dst = output / f["name"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f["path"], dst)
        if spec.get("apply_reviews", True):
            for f in spec["files"]:
                if f.get("preserve") or Path(f["name"]).suffix.lower() != ".docx":
                    continue
                dest = output / f["name"]
                doc = Document(dest)
                for p in all_paragraphs(doc):
                    tokens = re.findall(r"\{\{result:[^}]+\}\}", p.text)
                    for token in tokens:
                        paragraph_replace(
                            p, token, render_results(token, data["results"])
                        )
                for fig in data["figures"]:
                    if f["role"] == "manuscript":
                        anchors = [
                            p
                            for p in all_paragraphs(doc)
                            if p.text.startswith(fig["id"] + ".")
                        ]
                        if len(anchors) != 1:
                            raise ValueError(
                                "Figure caption must have one Word anchor."
                            )
                        paragraph_replace(
                            anchors[0],
                            anchors[0].text,
                            fig["caption"],
                            bool(figure_issues(fig)),
                        )
                for q in data["queries"]:
                    if q["target"] not in {f["name"], f["role"]}:
                        continue
                    if query_status(q, data["sources"]) == "resolved":
                        protected = [
                            other["quote"]
                            for other in data["queries"]
                            if other["target"] in {f["name"], f["role"]}
                            and query_status(other, data["sources"]) != "resolved"
                        ]
                        protected += [
                            fig["caption"]
                            for fig in data["figures"]
                            if figure_issues(fig)
                        ]
                        clear_owned_review(doc, q, protected)
                        continue
                    anchors = [p for p in all_paragraphs(doc) if q["quote"] in p.text]
                    if len(anchors) != 1:
                        raise ValueError(
                            "Author query anchor missing or ambiguous: " + q["id"]
                        )
                    runs = paragraph_replace(anchors[0], q["quote"], q["quote"], True)
                    doc.add_comment(
                        runs,
                        text=f"[{q['id']}] {q['owner']}: {q['question']}",
                        author="Author review",
                        initials="AR",
                    )
                doc.save(dest)
        if spec.get("generate_figures"):
            if not data["figures"]:
                raise ValueError("No figures registered.")
            if (output / "Figures.docx").exists() or (output / "Figures.pdf").exists():
                raise ValueError(
                    "Generated figures would overwrite a supplied artifact."
                )
            figures_document(data["figures"], output / "Figures.docx")
        if spec.get("render", True):
            for file in output.rglob("*.docx"):
                pdf = file.with_suffix(".pdf")
                if pdf.exists():
                    # Supplied PDFs only accepted for explicitly preserved documents.
                    entry = next(
                        (
                            f
                            for f in spec["files"]
                            if f["name"] == file.relative_to(output).as_posix()
                        ),
                        {},
                    )
                    if not entry.get("preserve"):
                        raise ValueError(
                            "A supplied PDF could be stale; omit it and render the revised Word file."
                        )
                else:
                    render_word(file, pdf, libreoffice)
        write_json(output / "pack_spec.json", spec)
        report = check_pack(workspace, output)
        if not any(f["name"] == "AuthorQuestions.txt" for f in spec["files"]):
            lines = [
                "CONFIDENTIAL CO-AUTHOR REVIEW",
                "",
                "Outstanding confirmations",
                "",
            ]
            for q in data["queries"]:
                if query_status(q, data["sources"]) != "resolved":
                    lines.append(f"{q['id']} | {q['owner']}: {q['question']}")
            for fig in data["figures"]:
                issues = figure_issues(fig)
                if issues:
                    lines.append(
                        fig["id"]
                        + ": "
                        + ", ".join(i["kind"].replace("_", " ") for i in issues)
                    )
            (output / "AuthorQuestions.txt").write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
            report = check_pack(workspace, output)
        write_json(output / "pack_check.json", report)
        return report
    except Exception:
        # Retain the failed build for inspection; never promote it or delete source material.
        write_json(output / "build_failure.json", {"status": "failed_not_releasable"})
        raise


def check_pack(workspace, directory):
    data = load_project(workspace)
    directory = private_path(directory)
    spec = json.loads((directory / "pack_spec.json").read_text(encoding="utf-8"))
    problems, pending = [], []
    if (directory / "build_failure.json").exists():
        problems.append({"kind": "failed_build_requires_new_output"})
    if any(p.is_symlink() for p in directory.rglob("*")):
        problems.append({"kind": "symlink_in_pack"})
    problems.extend(dependency_status(data))
    text_by_role = {}
    for f in spec["files"]:
        dest = directory / f["name"]
        if not dest.exists():
            problems.append({"kind": "missing_artifact", "name": f["name"]})
            continue
        if f.get("preserve") and digest(dest) != f["sha256"]:
            problems.append({"kind": "preserved_file_changed", "name": f["name"]})
        if dest.suffix.lower() in {".docx", ".md", ".txt"}:
            text_by_role[f["role"]] = doc_text(dest)
        if dest.suffix.lower() == ".docx":
            doc = Document(dest)
            starts = doc._element.xpath(".//w:commentRangeStart/@w:id")
            ends = doc._element.xpath(".//w:commentRangeEnd/@w:id")
            refs = doc._element.xpath(".//w:commentReference/@w:id")
            comment_ids = [str(c.comment_id) for c in doc.comments]
            if (
                not sorted(starts)
                == sorted(ends)
                == sorted(refs)
                == sorted(comment_ids)
            ):
                problems.append({"kind": "broken_comment_anchors", "name": f["name"]})
            pdf = dest.with_suffix(".pdf")
            if not pdf.exists():
                problems.append({"kind": "missing_pdf", "name": f["name"]})
            else:
                content = normalise(doc_text(pdf))
                for p in all_paragraphs(Document(dest)):
                    if p.text.strip() and normalise(p.text) not in content:
                        problems.append(
                            {"kind": "word_pdf_text_mismatch", "name": f["name"]}
                        )
                        break
    manuscript = text_by_role.get("manuscript", "")
    if data["results"]:
        audit = audit_occurrences(
            manuscript, data["results"], spec.get("result_mappings", [])
        )
        problems.extend(audit["findings"])
    else:
        audit = {"status": "not_checked"}
    for item in spec.get("result_assets", []):
        receipt = json.loads(Path(item["receipt"]).read_text(encoding="utf-8"))
        if receipt["results_fingerprint"] != fingerprint(data["results"]):
            problems.append({"kind": "stale_result_plot_or_table"})
        for original, target in item["files"].items():
            if (
                original not in receipt["files"]
                or not (directory / target).is_file()
                or digest(directory / target) != receipt["files"][original]
            ):
                problems.append({"kind": "changed_result_asset", "name": target})
    if data["results"] and not spec.get("result_assets"):
        pending.append({"kind": "statistical_plot_derivation_not_checked"})
    # Include embedded Office image bytes when looking for known unmasked originals.
    asset_hashes, pixel_hashes = set(), set()
    import hashlib

    for f in directory.rglob("*"):
        if f.is_file():
            asset_hashes.add(digest(f))
            if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
                pixel_hashes.add(image_pixel_hash(f.read_bytes()))
            if f.suffix.lower() in {".docx", ".pptx"}:
                with zipfile.ZipFile(f) as z:
                    for n in z.namelist():
                        if "/media/" in n:
                            asset_hashes.add(hashlib.sha256(z.read(n)).hexdigest())
                            pixel_hashes.add(image_pixel_hash(z.read(n)))
            if f.suffix.lower() == ".pdf":
                import pymupdf as fitz

                with fitz.open(f) as pdf:
                    for xref in {im[0] for page in pdf for im in page.get_images()}:
                        blob = pdf.extract_image(xref)["image"]
                        asset_hashes.add(hashlib.sha256(blob).hexdigest())
                        pixel_hashes.add(image_pixel_hash(blob))
    for fig in data["figures"]:
        if manuscript.count(fig["caption"]) != 1:
            problems.append({"kind": "caption_mismatch", "id": fig["id"]})
        if figure_issues(fig):
            entry = next(f for f in spec["files"] if f["role"] == "manuscript")
            if Path(entry["name"]).suffix == ".docx":
                doc = Document(directory / entry["name"])
                anchors = [p for p in all_paragraphs(doc) if p.text == fig["caption"]]
                if anchors and not all(
                    r.font.highlight_color == WD_COLOR_INDEX.YELLOW
                    for r in anchors[0].runs
                    if r.text
                ):
                    problems.append(
                        {"kind": "unconfirmed_caption_not_yellow", "id": fig["id"]}
                    )
        for issue in figure_issues(fig):
            (
                problems
                if issue["kind"]
                in {
                    "privacy_needs_confirmation",
                    "display_changed_or_missing",
                    "original_changed_or_missing",
                    "invalid_mask",
                }
                else pending
            ).append({"id": fig["id"], **issue})
        for p in fig["panels"]:
            display = Path(p["display"]["path"])
            display_pixels = (
                image_pixel_hash(display.read_bytes()) if display.is_file() else None
            )
            if p["display"]["sha256"] not in asset_hashes and not (
                display_pixels and display_pixels in pixel_hashes
            ):
                problems.append(
                    {
                        "kind": "registered_figure_image_missing",
                        "id": fig["id"],
                        "panel": p["label"],
                    }
                )
            # Any copy of an unmasked original is forbidden when a distinct approved display exists.
            if p["original"]["sha256"] != p["display"]["sha256"]:
                original = Path(p["original"]["path"])
                pixel_hash = (
                    image_pixel_hash(original.read_bytes())
                    if original.is_file()
                    else None
                )
                if p["original"]["sha256"] in asset_hashes or (
                    pixel_hash and pixel_hash in pixel_hashes
                ):
                    problems.append(
                        {"kind": "unmasked_original_in_pack", "id": fig["id"]}
                    )
    figure_docs = [
        p
        for p in directory.glob("*")
        if p.stem.startswith("Figures") and p.suffix in {".docx", ".pdf"}
    ]
    figure_docs += [
        directory / f["name"] for f in spec["files"] if f["role"] == "figures"
    ]
    for f in figure_docs:
        content = normalise(doc_text(f))
        for fig in data["figures"]:
            if normalise(fig["caption"]) not in content:
                problems.append(
                    {"kind": "figure_document_caption_mismatch", "id": fig["id"]}
                )
    for q in data["queries"]:
        status = query_status(q, data["sources"])
        if status != "resolved":
            pending.append(
                {
                    "id": q["id"],
                    "kind": status,
                    "owner": q["owner"],
                    "question": q["question"],
                }
            )
            target = next(
                (f for f in spec["files"] if q["target"] in {f["name"], f["role"]}),
                None,
            )
            if target is None or Path(target["name"]).suffix != ".docx":
                problems.append({"kind": "query_target_missing", "id": q["id"]})
                continue
            doc = Document(directory / target["name"])
            anchors = [p for p in all_paragraphs(doc) if q["quote"] in p.text]
            if len(anchors) != 1:
                problems.append(
                    {"kind": "query_anchor_missing_or_ambiguous", "id": q["id"]}
                )
            else:
                yellow, comment = reviewed_span(anchors[0], q["quote"])
                if not yellow:
                    problems.append({"kind": "query_highlight_missing", "id": q["id"]})
                if not comment:
                    problems.append({"kind": "query_comment_missing", "id": q["id"]})
    coverage = discussion_coverage(data, manuscript)
    pending.extend(coverage["findings"])
    if coverage["status"] == "not_checked":
        pending.append({"kind": "discussion_coverage_not_checked"})
    latest_searches = {}
    for search in data["searches"]:
        key = fingerprint(
            {
                "kind": search.get("kind"),
                "roots": sorted(search.get("roots", [])),
                "source": search.get("source"),
                "query": search.get("query"),
            }
        )
        latest_searches[key] = search
    if any(
        s.get("complete") is False or s.get("status") in {"partial", "failed"}
        for s in latest_searches.values()
    ) or any(s["status"] in {"partial", "unreadable"} for s in data["sources"]):
        pending.append({"kind": "incomplete_source_coverage"})
    if not data["sources"]:
        pending.append({"kind": "source_coverage_not_checked"})
    for calc in data["calculations"]:
        # Host receipts describe an external calculation; they do not rerun it.
        pending.append(
            {"kind": "external_calculation_not_reproduced", "id": calc["id"]}
        )
    if spec.get("stage") == "submission" and pending:
        problems.append({"kind": "unresolved_submission_checks"})
    files = {
        p.relative_to(directory).as_posix(): digest(p)
        for p in directory.rglob("*")
        if p.is_file()
        and p.name
        not in {"pack_check.json", "visual_review.json", "release_receipt.json"}
    }
    return {
        "schema": 1,
        "status": "failed" if problems else "ready_for_visual_review",
        "project_fingerprint": fingerprint(data),
        "files": files,
        "problems": problems,
        "pending": pending,
        "numeric_status": audit["status"],
        "coverage": coverage,
    }


def record_visual_review(workspace, directory, reviewer, notes):
    if not reviewer.strip() or not notes.strip():
        raise ValueError("Reviewer and visual review notes required.")
    directory = Path(directory)
    report = check_pack(workspace, directory)
    if report["problems"]:
        raise ValueError("Resolve failed pack checks before recording visual review.")
    receipt = {
        "reviewer": reviewer,
        "notes": notes,
        "files": report["files"],
        "project_fingerprint": report["project_fingerprint"],
    }
    write_json(directory / "pack_check.json", report)
    write_json(directory / "visual_review.json", receipt)
    return receipt


def release_pack(workspace, directory, destination):
    directory = Path(directory)
    destination = private_path(destination)
    if destination.is_relative_to(directory.resolve()):
        raise ValueError("Release ZIP must be outside its source folder.")
    if destination.exists():
        raise ValueError("Never overwrite a released ZIP.")
    report = check_pack(workspace, directory)
    visual = json.loads((directory / "visual_review.json").read_text(encoding="utf-8"))
    if (
        report["problems"]
        or visual["files"] != report["files"]
        or visual["project_fingerprint"] != report["project_fingerprint"]
    ):
        raise ValueError("Changed files or review decisions invalidate release checks.")
    # Internal provenance/paths never travel in the recipient ZIP.
    excluded = {
        "pack_spec.json",
        "pack_check.json",
        "visual_review.json",
        "release_receipt.json",
        "build_failure.json",
    }
    candidates = [
        p for p in directory.rglob("*") if p.is_file() and p.name not in excluded
    ]
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as z:
        for f in candidates:
            z.write(f, f.relative_to(directory).as_posix())
    with zipfile.ZipFile(destination) as z:
        if z.testzip() is not None:
            raise ValueError("ZIP corruption detected.")
        for f in candidates:
            if z.read(f.relative_to(directory).as_posix()) != f.read_bytes():
                raise ValueError("ZIP contents differ from checked artifacts.")
    receipt = {
        "zip_sha256": digest(destination),
        "files": len(candidates),
        "stage": json.loads((directory / "pack_spec.json").read_text())["stage"],
        "pending_checks": len(report["pending"]),
        "sent": False,
    }
    write_json(directory / "release_receipt.json", receipt)
    return receipt
