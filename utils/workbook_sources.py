"""Read XLSX evidence without running formulas, macros or external links."""

from decimal import Decimal, InvalidOperation
from pathlib import Path
import posixpath
import struct

from lxml import etree as E

from utils.project_sources import XML, package, asset

S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MAX_CELLS = 100000
MAX_TEXT = 8 * 1024**2
MAX_PART = 32 * 1024**2


def vector_text(raw, suffix):
    """Recover bounded EMF/WMF text records; never render or execute a metafile."""
    chunks, offset = [], 0
    if suffix == ".emf":
        while offset + 8 <= len(raw):
            kind, size = struct.unpack_from("<II", raw, offset)
            if size < 8 or offset + size > len(raw):
                raise ValueError("Invalid EMF record length.")
            record = raw[offset : offset + size]
            if kind in {83, 84} and size >= 76:
                if struct.unpack_from("<I", record, 52)[0] & 0x10:
                    raise ValueError("EMF glyph indices require visual review.")
                count, start = struct.unpack_from("<II", record, 44)
                width = 2 if kind == 84 else 1
                if count > 100000 or start < 76 or start + count * width > size:
                    raise ValueError("Invalid EMF text bounds.")
                chunks.append(
                    record[start : start + count * width].decode(
                        "utf-16-le" if width == 2 else "cp1252", errors="replace"
                    )
                )
            offset += size
    else:
        offset = 22 if raw[:4] == b"\xd7\xcd\xc6\x9a" else 0
        if len(raw) < offset + 18:
            raise ValueError("Invalid WMF header.")
        offset += 18
        while offset + 6 <= len(raw):
            words, kind = struct.unpack_from("<IH", raw, offset)
            size = words * 2
            if size < 6 or offset + size > len(raw):
                raise ValueError("Invalid WMF record length.")
            record = raw[offset : offset + size]
            start, count = 0, 0
            if kind == 0x0521 and size >= 8:  # META_TEXTOUT
                count = struct.unpack_from("<H", record, 6)[0]
                start = 8
            elif kind == 0x0A32 and size >= 14:  # META_EXTTEXTOUT
                count, options = struct.unpack_from("<HH", record, 10)
                start = 22 if options & 6 else 14
            if count:
                if start + count > size:
                    raise ValueError("Invalid WMF text bounds.")
                chunks.append(
                    record[start : start + count].decode("cp1252", errors="replace")
                )
            offset += size
    return "\n".join(c for c in chunks if c.strip())


def workbook_records(path, assets):
    blocks, images, warnings = [], [], []
    used = 0

    def add(row):
        nonlocal used
        used += len(row["text"].encode("utf-8"))
        if used > MAX_TEXT:
            raise ValueError("Workbook text budget exceeded.")
        blocks.append(row)

    with package(path) as z:
        if len(set(z.namelist())) != len(z.namelist()):
            raise ValueError("Duplicate workbook package entries.")

        def read(name):
            if z.getinfo(name).file_size > MAX_PART:
                raise ValueError("Workbook part budget exceeded.")
            return z.read(name)

        def xml(name):
            root = E.fromstring(read(name), XML)
            if root.getroottree().docinfo.doctype:
                raise ValueError("Workbook XML document types are unsupported.")
            return root

        def relationships(name):
            relpath = posixpath.join(
                posixpath.dirname(name), "_rels", posixpath.basename(name) + ".rels"
            )
            found = {}
            if relpath not in z.namelist():
                return found
            for rel in xml(relpath):
                if rel.get("TargetMode") == "External":
                    warnings.append("external_link_not_followed:" + name)
                    continue
                target = rel.get("Target", "")
                resolved = posixpath.normpath(
                    posixpath.join(posixpath.dirname(name), target)
                ).lstrip("/")
                if resolved.startswith("../") or "\\" in resolved or ":" in resolved:
                    raise ValueError("Unsafe workbook relationship.")
                found[rel.get("Id")] = resolved
            return found

        strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            strings = [
                "".join(n.itertext())
                for n in xml("xl/sharedStrings.xml").findall(S + "si")
            ]
        book = xml("xl/workbook.xml")
        links = relationships("xl/workbook.xml")
        count, formula_count = 0, 0
        seen_cells = set()
        contexts = {}
        for sheet in book.findall(S + "sheets/" + S + "sheet"):
            name = sheet.get("name", "")
            part = links[sheet.get(R + "id")]
            tree = xml(part)
            for cell in tree.iter(S + "c"):
                count += 1
                if count > MAX_CELLS:
                    raise ValueError("Workbook cell budget exceeded.")
                address = cell.get("r", "")
                import re

                if (
                    not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", address)
                    or (name, address) in seen_cells
                ):
                    raise ValueError(
                        "Missing, duplicate or invalid workbook cell address."
                    )
                seen_cells.add((name, address))
                kind = cell.get("t", "n")
                value = cell.findtext(S + "v")
                formula = cell.find(S + "f")
                if kind == "s" and value is not None:
                    if not 0 <= int(value) < len(strings):
                        raise ValueError("Invalid shared-string index.")
                    value = strings[int(value)]
                elif kind == "inlineStr":
                    value = "".join(cell.find(S + "is").itertext())
                row = {
                    "locator": f"sheet:{name}!{address}",
                    "kind": "workbook_cell",
                    "sheet": name,
                    "cell": address,
                    "cell_type": kind,
                    "saved_value": value,
                    "style_index": cell.get("s", "0"),
                    "sheet_state": sheet.get("state", "visible"),
                    "text": f"{name}!{address}: {value if value is not None else '[no saved value]'}",
                }
                if formula is not None:
                    formula_count += 1
                    row.update(
                        formula=formula.text or "",
                        formula_attributes=dict(formula.attrib),
                        review_required=True,
                    )
                    row["text"] += (
                        " | formula: "
                        + (formula.text or "[shared/array formula]")
                        + " | saved value is not recalculated"
                    )
                if kind == "e":
                    row["review_required"] = True
                    warnings.append("cell_error:" + row["locator"])
                add(row)
            for target in relationships(part).values():
                if "/drawings/" not in target or target not in z.namelist():
                    continue
                drawing = xml(target)
                refs = relationships(target)
                for anchor in drawing:
                    label = f"sheet:{name}/drawing:{target}"
                    for node in anchor.iter():
                        for attr in (R + "embed", R + "id"):
                            media = refs.get(node.get(attr))
                            if media:
                                contexts.setdefault(media, []).append(
                                    {"locator": label, "context": name}
                                )
                    words = " ".join(
                        t.text or ""
                        for t in anchor.iter()
                        if E.QName(t).localname == "t"
                    )
                    if words:
                        add(
                            {
                                "locator": label + f":{len(blocks)}",
                                "kind": "drawing_text",
                                "text": words,
                            }
                        )
        for node in book.findall(S + "definedNames/" + S + "definedName"):
            add(
                {
                    "locator": "defined_name:"
                    + node.get("name", "")
                    + ":"
                    + node.get("localSheetId", "global"),
                    "kind": "named_range",
                    "text": node.text or "",
                    "attributes": dict(node.attrib),
                }
            )
        for part in z.namelist():
            if part.startswith("xl/charts/") and part.endswith(".xml"):
                tree = xml(part)
                values = [
                    n.text
                    for n in tree.iter()
                    if E.QName(n).localname in {"v", "t", "f"} and n.text
                ]
                add(
                    {
                        "locator": part,
                        "kind": "chart_cache",
                        "text": "\n".join(values),
                        "review_required": True,
                        "occurrences": contexts.get(part, []),
                    }
                )
                warnings.append("chart_cache_not_recalculated:" + part)
            if part.startswith("xl/media/") and not part.endswith("/"):
                raw = read(part)
                suffix = Path(part).suffix.lower()
                image = asset(raw, suffix, assets, part)
                image["occurrences"] = contexts.get(part, [])
                images.append(image)
                if suffix in {".emf", ".wmf"}:
                    try:
                        body = vector_text(raw, suffix)
                        if body:
                            add(
                                {
                                    "locator": part + ":text",
                                    "kind": "vector_text",
                                    "text": body,
                                    "review_required": True,
                                    "image_sha256": image["sha256"],
                                }
                            )
                        warnings.append("vector_visual_review_required:" + part)
                    except (ValueError, struct.error):
                        warnings.append("vector_text_unreadable:" + part)
                else:
                    warnings.append("embedded_image_text_not_extracted:" + part)
            if part.startswith("xl/embeddings/") or part.endswith("vbaProject.bin"):
                warnings.append("embedded_object_not_executed:" + part)
            if part.startswith("xl/externalLinks/"):
                warnings.append("external_workbook_not_read")
        if formula_count:
            warnings.append("formula_saved_values_not_recalculated")
        add(
            {
                "locator": "workbook_summary",
                "kind": "workbook_summary",
                "text": f"Stored cells: {count}; formula cells: {formula_count}. Raw saved values; date/number formatting is not applied. No formulas or external links executed.",
            }
        )
    return blocks, [], images, sorted(set(warnings))


def register_workbook_result(
    workspace,
    source_id,
    count_locator,
    denominator_locator,
    result_id,
    label,
    definition,
):
    """Register literal aggregate counts; formula caches require independent analysis."""
    from utils.project_store import update_project, current_file, upsert, require_text
    from utils.project_results import validate_result

    def apply(data):
        source = next(s for s in data["sources"] if s["id"] == source_id)
        if not current_file(source):
            raise ValueError("Workbook changed; reindex it first.")
        cells = {
            b["locator"]: b
            for b in source["blocks"]
            if b.get("kind") == "workbook_cell"
        }
        values = []
        for locator in (count_locator, denominator_locator):
            cell = cells[locator]
            if (
                "formula" in cell
                or cell["cell_type"] != "n"
                or cell["saved_value"] is None
            ):
                raise ValueError(
                    "Choose literal numeric aggregate cells; formula caches are not verified calculations."
                )
            try:
                value = Decimal(cell["saved_value"])
                if not value.is_finite() or value != value.to_integral_value():
                    raise ValueError("Aggregate counts must be finite integers.")
                values.append(int(value))
            except InvalidOperation as exc:
                raise ValueError("Invalid numeric cell.") from exc
        row = {
            "id": result_id,
            "label": label,
            "definition": definition,
            "source": source_id,
            "method": "Literal workbook aggregate cells; interpretation needs review",
            "count": values[0],
            "denominator": values[1],
            "workbook_source": {k: source[k] for k in ("path", "sha256", "bytes")},
            "cell_locators": [count_locator, denominator_locator],
        }
        require_text(row, "id", "label", "definition")
        validate_result(row)
        upsert(data["results"], row)

    return update_project(workspace, apply)
