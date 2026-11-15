"""Locate referenced panels in a specific document; visual review remains required."""

from pathlib import Path
import hashlib
import posixpath

from docx import Document
from docx.oxml.ns import qn


def image_occurrences(path):
    path = Path(path)
    if path.suffix.lower() == ".docx":
        doc = Document(path)
        parts = [(doc.part, "body")]
        for node in doc._element.xpath(".//w:headerReference | .//w:footerReference"):
            part = doc.part.related_parts.get(node.get(qn("r:id")))
            if part is not None:
                parts.append((part, str(part.partname)))
        for part, section in parts:
            for number, paragraph in enumerate(part.element.iter(qn("w:p")), 1):
                for node in paragraph.iter():
                    rid = (
                        node.get(qn("r:embed"))
                        if node.tag == qn("a:blip")
                        else node.get(qn("r:id"))
                        if node.tag == "{urn:schemas-microsoft-com:vml}imagedata"
                        else None
                    )
                    if not rid or any(
                        a.tag in {qn("w:del"), qn("w:moveFrom")}
                        for a in node.iterancestors()
                    ):
                        continue
                    run = next(
                        (a for a in node.iterancestors() if a.tag == qn("w:r")), None
                    )
                    if run is not None and run.xpath(
                        "./w:rPr/w:vanish[not(@w:val) or not(@w:val='0' or @w:val='false' or @w:val='off')]"
                    ):
                        continue
                    image = part.related_parts.get(rid)
                    if image is not None and image.content_type.startswith("image/"):
                        yield image.blob, f"{section}:paragraph:{number}"
    elif path.suffix.lower() == ".pptx":
        from lxml import etree as E
        from utils.project_sources import package, XML

        with package(path) as z:

            def xml(name):
                root = E.fromstring(z.read(name), XML)
                if root.getroottree().docinfo.doctype:
                    raise ValueError("PowerPoint document types are unsupported.")
                return root

            def relationships(part):
                name = posixpath.join(
                    posixpath.dirname(part), "_rels", posixpath.basename(part) + ".rels"
                )
                if name not in z.namelist():
                    return {}
                result = {}
                for rel in xml(name):
                    if rel.get("TargetMode") == "External":
                        continue
                    target = rel.get("Target", "")
                    resolved = posixpath.normpath(
                        target.lstrip("/")
                        if target.startswith("/")
                        else posixpath.join(posixpath.dirname(part), target)
                    )
                    if (
                        not resolved.startswith("ppt/")
                        or "\\" in resolved
                        or ":" in resolved
                    ):
                        raise ValueError("Unsafe slide relationship.")
                    result[rel.get("Id")] = resolved
                return result

            refs = relationships("ppt/presentation.xml")
            ns = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
            for number, slide_ref in enumerate(
                xml("ppt/presentation.xml").findall(ns + "sldIdLst/" + ns + "sldId"), 1
            ):
                part = refs[slide_ref.get(qn("r:id"))]
                slide = xml(part)
                if slide.get("show", "1") in {"0", "false"}:
                    continue
                images = relationships(part)
                for node in slide.iter(qn("a:blip")):
                    media = images.get(node.get(qn("r:embed")))
                    if media and media.startswith("ppt/media/"):
                        yield z.read(media), f"slide:{number}"
    elif path.suffix.lower() == ".pdf":
        import pymupdf as fitz

        with fitz.open(path) as pdf:
            for number, page in enumerate(pdf, 1):
                for xref in {im[0] for im in page.get_images()}:
                    if any(
                        rect.intersects(page.rect) and not rect.is_empty
                        for rect in page.get_image_rects(xref)
                    ):
                        yield pdf.extract_image(xref)["image"], f"page:{number}"


def check_placements(directory, figures, mappings):
    from utils.project_pack import image_pixel_hash

    directory = Path(directory).resolve()
    if not isinstance(mappings, list) or any(
        not isinstance(row, dict) for row in mappings
    ):
        raise ValueError("Figure placements must be a list of mappings.")
    panels = {(f["id"], p["label"]): p for f in figures for p in f["panels"]}
    problems, covered, cache = [], set(), {}
    for row in mappings:
        if any(
            not isinstance(row.get(k), str) or not row[k].strip()
            for k in ("figure_id", "panel", "document", "location")
        ):
            raise ValueError(
                "A figure placement needs figure_id, panel, document and location."
            )
        key = (row.get("figure_id"), row.get("panel"))
        relative = Path(row.get("document", ""))
        path = (directory / relative).resolve()
        location = row.get("location")
        if (
            key not in panels
            or not location
            or relative.is_absolute()
            or not path.is_relative_to(directory)
            or not path.is_file()
            or path.suffix.lower() not in {".docx", ".pdf", ".pptx"}
        ):
            problems.append({"kind": "invalid_figure_placement", "mapping": row})
            continue
        covered.add(key)
        if path not in cache:
            cache[path] = [
                (hashlib.sha256(blob).hexdigest(), image_pixel_hash(blob), loc)
                for blob, loc in image_occurrences(path)
            ]
        panel = panels[key]
        display = Path(panel["display"]["path"])
        pixel = image_pixel_hash(display.read_bytes()) if display.is_file() else None
        if not any(
            loc == location
            and (
                sha == panel["display"]["sha256"]
                or (pixel is not None and pixel == pixels)
            )
            for sha, pixels, loc in cache[path]
        ):
            problems.append({"kind": "figure_missing_at_declared_location", **row})
    pending = [
        {"kind": "figure_placement_not_mapped", "id": fid, "panel": label}
        for fid, label in sorted(set(panels) - covered)
    ]
    # A document mapping does not establish its rendered PDF counterpart.
    for fid, label in sorted(covered):
        rows = [
            r for r in mappings if (r.get("figure_id"), r.get("panel")) == (fid, label)
        ]
        for row in rows:
            if Path(row.get("document", "")).suffix.lower() == ".docx":
                pdf = str(Path(row["document"]).with_suffix(".pdf")).replace("\\", "/")
                if not any(
                    r.get("document", "").replace("\\", "/") == pdf for r in rows
                ):
                    pending.append(
                        {
                            "kind": "rendered_panel_not_mapped",
                            "id": fid,
                            "panel": label,
                            "document": pdf,
                        }
                    )
    return {
        "problems": problems,
        "pending": pending,
        "scope": "Exact image identity at declared content locations. Cropping, occlusion, labels and clinical meaning still need visual review.",
    }
