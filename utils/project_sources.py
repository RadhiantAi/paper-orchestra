"""Bounded local source ingestion. Source text is data, never instructions."""

from email import policy
from email.parser import BytesParser
import hashlib
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile
from lxml import etree as E

from utils.project_store import (
    file_receipt,
    private_path,
    update_project,
    upsert,
    load_project,
    current_file,
)
from utils.research_quality import fingerprint

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
NS = {"w": W[1:-1]}
XML = E.XMLParser(resolve_entities=False, no_network=True)
FORMATS = {
    ".docx",
    ".doc",
    ".pptx",
    ".pdf",
    ".eml",
    ".txt",
    ".md",
    ".json",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
}


def text(node):
    return "".join(node.xpath(".//w:t/text() | .//w:delText/text()", namespaces=NS))


def package(path):
    z = zipfile.ZipFile(path)
    if (
        len(z.infolist()) > 5000
        or sum(x.file_size for x in z.infolist()) > 512 * 1024**2
    ):
        z.close()
        raise ValueError("Office package exceeds extraction budget.")
    return z


def asset(raw, suffix, target, locator):
    sha = hashlib.sha256(raw).hexdigest()
    dst = target / (sha + suffix.lower())
    if not dst.exists():
        dst.write_bytes(raw)
    return dict(file_receipt(dst), locator=locator)


def word_records(path, assets):
    blocks, edits, comments, images = [], [], [], []
    with package(path) as z:
        root = E.fromstring(z.read("word/document.xml"), XML)
        image_context = {}
        import posixpath

        rels = (
            E.fromstring(z.read("word/_rels/document.xml.rels"), XML)
            if "word/_rels/document.xml.rels" in z.namelist()
            else []
        )
        relmap = {
            r.get("Id"): posixpath.normpath(
                posixpath.join("word", r.get("Target", ""))
            ).lstrip("/")
            for r in rels
            if r.get("TargetMode") != "External"
        }
        for i, p in enumerate(root.iter(W + "p")):
            loc = f"paragraph:{i + 1}"
            # Retain current text and tracked deletions separately; never silently accept edits.
            current = "".join(
                p.xpath(".//w:t[not(ancestor::w:del)]/text()", namespaces=NS)
            )
            if current:
                blocks.append({"locator": loc, "text": current})
            for node in p.iter():
                for attr in [
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed",
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
                ]:
                    target = relmap.get(node.get(attr))
                    if target:
                        image_context.setdefault(target, []).append(
                            {"locator": loc, "context": current}
                        )
            for edit in p.xpath(".//w:ins | .//w:del", namespaces=NS):
                edits.append(
                    {
                        "id": f"{loc}:{E.QName(edit).localname}:{edit.get(W + 'id', '')}",
                        "kind": E.QName(edit).localname,
                        "text": text(edit),
                        "author": edit.get(W + "author", ""),
                        "date": edit.get(W + "date", ""),
                        "locator": loc,
                        "context": current,
                    }
                )
        if "word/comments.xml" in z.namelist():
            cr = E.fromstring(z.read("word/comments.xml"), XML)
            for c in cr:
                cid = c.get(W + "id")
                anchors = root.xpath(
                    "//w:p[w:commentRangeStart[@w:id=$id]]", namespaces=NS, id=cid
                )
                comments.append(
                    {
                        "id": "comment:" + cid,
                        "kind": "comment",
                        "text": text(c),
                        "author": c.get(W + "author", ""),
                        "date": c.get(W + "date", ""),
                        "locator": "comment:" + cid,
                        "context": "\n".join(text(a) for a in anchors),
                    }
                )
        for n in z.namelist():
            if n.startswith("word/media/") and not n.endswith("/"):
                images.append(
                    dict(
                        asset(z.read(n), Path(n).suffix, assets, n),
                        occurrences=image_context.get(n, []),
                    )
                )
    return blocks, edits + comments, images


def convert_legacy(source, destination, libreoffice=None):
    """Explicit conversion only; macros disabled in the Windows Word path."""
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("Never overwrite an earlier conversion.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if libreoffice:
        with tempfile.TemporaryDirectory() as tmp:
            profile = Path(tmp) / "profile"
            r = subprocess.run(
                [
                    str(Path(libreoffice).resolve()),
                    "-env:UserInstallation=" + profile.as_uri(),
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    tmp,
                    str(source),
                ],
                capture_output=True,
                timeout=120,
            )
            out = Path(tmp) / (source.stem + ".docx")
            if r.returncode or not out.exists():
                raise RuntimeError("Legacy conversion failed.")
            destination.write_bytes(out.read_bytes())
    elif __import__("os").name == "nt":
        quote = lambda p: "'" + str(p).replace("'", "''") + "'"
        code = (
            "$ErrorActionPreference='Stop'\n$w=New-Object -ComObject Word.Application\n$w.Visible=$false\n$w.DisplayAlerts=0\n$w.AutomationSecurity=3\ntry {\n$d=$w.Documents.Open("
            + quote(source)
            + ",$false,$true)\ntry {$d.SaveAs2("
            + quote(destination)
            + ",16)} finally {$d.Close(0)}\n} finally {$w.Quit()}"
        )
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", code],
            capture_output=True,
            timeout=120,
        )
        if r.returncode or not destination.exists():
            raise RuntimeError("Legacy conversion failed.")
    else:
        raise ValueError(
            "Select an installed LibreOffice executable for legacy conversion."
        )
    return file_receipt(destination)


def extract(path, assets, *, converted=None, depth=0):
    suffix = path.suffix.lower()
    if depth > 3:
        raise ValueError("Nested attachment depth exceeded.")
    if suffix == ".doc":
        if converted is None:
            return [], [], [], ["legacy_conversion_required"]
        b, e, i = word_records(converted, assets)
        return b, e, i, []
    if suffix == ".docx":
        return (*word_records(path, assets), [])
    if suffix == ".pptx":
        blocks, images = [], []
        with package(path) as z:
            contexts = {}
            for n in z.namelist():
                if re.match(r"ppt/(slides/slide|notesSlides/notesSlide)\d+\.xml$", n):
                    root = E.fromstring(z.read(n), XML)
                    blocks.append(
                        {
                            "locator": n,
                            "text": "\n".join(t.text or "" for t in root.iter(A + "t")),
                        }
                    )
                    relname = (
                        str(Path(n).parent.as_posix())
                        + "/_rels/"
                        + Path(n).name
                        + ".rels"
                    )
                    if relname in z.namelist():
                        import posixpath

                        for rel in E.fromstring(z.read(relname), XML):
                            target = posixpath.normpath(
                                posixpath.join(
                                    posixpath.dirname(n), rel.get("Target", "")
                                )
                            )
                            if target.startswith("ppt/media/"):
                                contexts.setdefault(target, []).append(
                                    {"locator": n, "context": blocks[-1]["text"]}
                                )
                if n.startswith("ppt/media/") and not n.endswith("/"):
                    images.append(asset(z.read(n), Path(n).suffix, assets, n))
            for image in images:
                image["occurrences"] = contexts.get(image["locator"], [])
        return blocks, [], images, []
    if suffix == ".pdf":
        import pymupdf as fitz

        blocks, images, warnings, seen = [], [], [], {}
        with fitz.open(path) as pdf:
            if pdf.page_count > 1000:
                raise ValueError("PDF exceeds 1,000-page extraction budget.")
            for n, page in enumerate(pdf, 1):
                body = page.get_text()
                blocks.append({"locator": f"page:{n}", "text": body})
                if not body.strip():
                    warnings.append(f"page:{n}:no_extractable_text_ocr_required")
                for im in page.get_images():
                    if im[0] in seen:
                        seen[im[0]]["occurrences"].append(
                            {"locator": f"page:{n}", "context": body}
                        )
                        continue
                    raw = pdf.extract_image(im[0])
                    if raw:
                        item = asset(
                            raw["image"],
                            "." + raw["ext"],
                            assets,
                            f"page:{n}:xref:{im[0]}",
                        )
                        item["occurrences"] = [
                            {"locator": f"page:{n}", "context": body}
                        ]
                        images.append(item)
                        seen[im[0]] = item
        return blocks, [], images, warnings
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        return [], [], [asset(path.read_bytes(), suffix, assets, "image")], []
    if suffix == ".eml":
        msg = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        blocks = [
            {
                "locator": "headers",
                "text": "\n".join(
                    f"{k}: {msg.get(k, '')}"
                    for k in ["From", "To", "Cc", "Date", "Subject"]
                ),
            }
        ]
        edits, images, warnings = [], [], []
        bodies = []
        for n, part in enumerate(msg.walk()):
            if part.is_multipart():
                continue
            raw = part.get_payload(decode=True) or b""
            name = part.get_filename()
            if name:
                suffix = Path(name).suffix.lower()
                dst = assets / (hashlib.sha256(raw).hexdigest() + suffix)
                dst.write_bytes(raw)
                if suffix not in FORMATS:
                    warnings.append(f"attachment:{n}:unsupported_format:{suffix}")
                    continue
                b, e, im, w = extract(dst, assets, depth=depth + 1)
                for item in b + e + im:
                    item["locator"] = f"attachment:{n}/" + item["locator"]
                blocks.extend(b)
                edits.extend(e)
                images.extend(im)
                warnings.extend(w)
            elif part.get_content_type() == "text/plain":
                bodies.append(
                    {
                        "locator": f"body:{n}",
                        "text": raw.decode(
                            part.get_content_charset() or "utf-8", errors="replace"
                        ),
                    }
                )
            elif part.get_content_type() == "text/html" and not any(
                b["locator"].startswith("body:") for b in bodies
            ):
                from lxml import html

                body = html.fromstring(
                    raw.decode(part.get_content_charset() or "utf-8", errors="replace")
                )
                for node in body.xpath("//script|//style"):
                    node.drop_tree()
                bodies.append(
                    {"locator": f"html_body:{n}", "text": body.text_content()}
                )
        plain = [b for b in bodies if b["locator"].startswith("body:")]
        blocks.extend(plain or bodies)
        if not bodies:
            warnings.append("no_extractable_email_body")
        return blocks, edits, images, warnings
    if suffix in {".txt", ".md", ".json"}:
        return (
            [{"locator": "text", "text": path.read_text(encoding="utf-8-sig")}],
            [],
            [],
            [],
        )
    return [], [], [], ["unsupported_format:" + suffix]


def index_sources(workspace, roots, *, max_files=2000, convert=False, libreoffice=None):
    if type(max_files) is not int or max_files < 1:
        raise ValueError("File budget must be a positive integer.")
    workspace = private_path(workspace)
    assets = workspace / "assets"
    assets.mkdir(exist_ok=True)
    roots = [Path(r).resolve() for r in roots]
    if any(r == workspace or workspace.is_relative_to(r) for r in roots):
        raise ValueError("Input roots must not contain the output workspace.")
    paths = sorted(
        {
            p
            for root in roots
            for p in ([root] if root.is_file() else root.rglob("*"))
            if p.is_file()
        }
    )
    records = []
    previous = {s["id"]: s for s in load_project(workspace)["sources"]}
    for p in paths[:max_files]:
        record = {
            "id": fingerprint(str(p)),
            "path": str(p),
            "status": "read",
            "blocks": [],
            "edits": [],
            "images": [],
            "warnings": [],
        }
        try:
            if p.is_symlink() or p.stat().st_size > 200 * 1024**2:
                raise ValueError("Symlink or file size budget exceeded.")
            record.update(file_receipt(p))
            converted = None
            if p.suffix.lower() == ".doc" and convert:
                converted = assets / (record["sha256"] + ".docx")
                if converted.exists():
                    old = previous.get(record["id"], {}).get("conversion")
                    if not old or not current_file(old):
                        raise ValueError(
                            "Unverified legacy conversion cache; use a new workspace."
                        )
                else:
                    convert_legacy(p, converted, libreoffice)
                record["conversion"] = file_receipt(converted)
            b, e, im, warnings = extract(p, assets, converted=converted)
            record.update(blocks=b, edits=e, images=im, warnings=warnings)
            if warnings:
                record["status"] = "partial" if b or im else "unreadable"
        except Exception as exc:
            record.update(status="unreadable", warnings=[type(exc).__name__])
        records.append(record)
    report = {
        "kind": "local_inventory",
        "roots": [str(r) for r in roots],
        "discovered": len(paths),
        "processed": len(records),
        "missing_roots": [str(r) for r in roots if not r.exists()],
        "truncated": len(paths) > max_files,
        "complete": len(paths) <= max_files
        and all(r.exists() for r in roots)
        and all(r["status"] == "read" for r in records),
    }

    def apply(data):
        for r in records:
            upsert(data["sources"], r)
        data["searches"].append(report)

    update_project(workspace, apply)
    return report


def search_index(data, terms):
    words = [w.casefold() for w in terms]
    return [
        {"source_id": s["id"], **b}
        for s in data["sources"]
        for b in s.get("blocks", [])
        if all(w in b["text"].casefold() for w in words)
    ]
