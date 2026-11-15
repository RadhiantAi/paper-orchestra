"""Versioned journal requirements, supplied and confirmed by the researcher."""

from datetime import date
from pathlib import Path
import re
from PIL import Image
from utils.research_quality import fingerprint


def validate_profile(profile):
    if profile.get("schema") != 1:
        raise ValueError("Unsupported journal profile schema.")
    for k in ["name", "source", "verified_on", "confirmed_by"]:
        if not isinstance(profile.get(k), str) or not profile[k].strip():
            raise ValueError("Journal profile requires " + k)
    date.fromisoformat(profile["verified_on"])
    if profile.get("reference_style") not in {"numeric", "author_year", "manual"}:
        raise ValueError("Choose a reference style.")
    for k in [
        "max_words",
        "max_abstract_words",
        "max_references",
        "max_figures",
        "figure_min_width_px",
        "figure_min_dpi",
    ]:
        if type(profile.get(k)) is not int or profile[k] < 0:
            raise ValueError("Journal limits must be non-negative integers: " + k)
    for k in [
        "required_sections",
        "required_declarations",
        "checklist_items",
        "exclude_from_main_count",
        "figure_formats",
    ]:
        if not isinstance(profile.get(k), list) or any(
            not isinstance(v, str) or not v.strip() for v in profile[k]
        ):
            raise ValueError("Journal profile requires a list: " + k)


def journal_word_counts(profile, manuscript):
    """Exclude a named section together with its child headings."""
    excluded = {k.casefold() for k in profile["exclude_from_main_count"]} | {
        "references",
        "bibliography",
    }
    stack = []
    headings = set()
    total = 0
    abstract = 0
    for line in manuscript.splitlines():
        match = re.match(r"^(#{1,9})\s+(.+)", line)
        if match:
            level, name = len(match[1]), match[2].strip().casefold()
            stack = [(n, title) for n, title in stack if n < level] + [(level, name)]
            headings.add(name)
            continue
        words = len(re.findall(r"\b\w+(?:['’\-]\w+)*\b", line))
        parents = {name for _, name in stack}
        if not parents & excluded:
            total += words
        if "abstract" in parents:
            abstract += words
    return total, abstract if "abstract" in headings else None, headings


def check_journal(profile, manuscript, figures, reviews=None):
    validate_profile(profile)
    findings = []
    total, abstract, headings = journal_word_counts(profile, manuscript)
    if total > profile["max_words"]:
        findings.append(
            {
                "kind": "journal_word_limit",
                "actual": total,
                "limit": profile["max_words"],
            }
        )
    if abstract is None:
        findings.append({"kind": "abstract_heading_not_recognised"})
    elif abstract > profile["max_abstract_words"]:
        findings.append({"kind": "abstract_word_limit", "actual": abstract})
    for section in profile["required_sections"]:
        if section.casefold() not in headings:
            findings.append({"kind": "missing_required_section", "item": section})
    for declaration in profile["required_declarations"]:
        if declaration.casefold() not in manuscript.casefold():
            findings.append({"kind": "missing_declaration_label", "item": declaration})
    pieces = re.split(
        r"^#{1,3}\s+(?:References|Bibliography)\s*$", manuscript, flags=re.M | re.I
    )
    body = pieces[0]
    references = pieces[1] if len(pieces) > 1 else ""
    numbered = re.findall(r"^\s*(\d+)[.)]\s+", references, re.M)
    if profile["reference_style"] == "numeric":
        if not numbered:
            findings.append({"kind": "numbered_references_not_recognised"})
        cited = set()
        for match in re.findall(r"\[([\d,;\s\-–]+)\]", body):
            for a, b in re.findall(r"(\d+)(?:\s*[-–]\s*(\d+))?", match):
                if b and (int(b) < int(a) or int(b) - int(a) > 1000):
                    findings.append({"kind": "invalid_reference_range"})
                    continue
                cited.update(range(int(a), int(b or a) + 1))
        ids = {int(n) for n in numbered}
        if cited - ids:
            findings.append(
                {"kind": "missing_cited_references", "numbers": sorted(cited - ids)}
            )
        if not cited:
            findings.append({"kind": "numeric_citations_not_recognised"})
        if len(ids) != len(numbered):
            findings.append({"kind": "duplicate_reference_numbers"})
    elif profile["reference_style"] == "author_year" and not re.search(
        r"\([^)]*\b(?:19|20)\d{2}[a-z]?[^)]*\)", body
    ):
        findings.append({"kind": "author_year_citations_not_recognised"})
    ref_count = (
        len(numbered)
        if numbered
        else len([p for p in references.splitlines() if p.strip()])
    )
    if ref_count > profile["max_references"]:
        findings.append({"kind": "reference_count_limit"})
    if len(figures) > profile["max_figures"]:
        findings.append({"kind": "figure_count_limit"})
    for fig in figures:
        for panel in fig["panels"]:
            path = Path(panel["display"]["path"])
            if path.suffix.lower().lstrip(".") not in profile["figure_formats"]:
                findings.append({"kind": "figure_format", "id": fig["id"]})
            try:
                image = Image.open(path)
            except (OSError, ValueError):
                findings.append({"kind": "figure_unreadable", "id": fig["id"]})
                continue
            with image:
                if image.width < profile["figure_min_width_px"]:
                    findings.append({"kind": "figure_width", "id": fig["id"]})
                if min(image.info.get("dpi", (0, 0))) < profile["figure_min_dpi"]:
                    findings.append(
                        {"kind": "figure_dpi_missing_or_low", "id": fig["id"]}
                    )
    identity = fingerprint([profile, manuscript])
    for item in profile["checklist_items"] + ["Reference formatting reviewed"]:
        if not any(
            r.get("item") == item
            and r.get("identity") == identity
            and r.get("reviewer")
            and r.get("reason")
            and r.get("quote")
            and r["quote"] in manuscript
            for r in reviews or []
        ):
            findings.append({"kind": "journal_item_needs_review", "item": item})
    age = (date.today() - date.fromisoformat(profile["verified_on"])).days
    if age < 0 or age > 365:
        findings.append({"kind": "journal_profile_date_needs_review"})
    return {
        "status": "needs_review" if findings else "checked",
        "findings": findings,
        "main_word_count": total,
        "profile_fingerprint": fingerprint(profile),
        "scope": "Declared journal requirements and literal formatting checks. Scientific checklist compliance requires recorded human review. Unnumbered reference counts use non-empty paragraphs.",
    }
