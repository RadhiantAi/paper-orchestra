"""Explicit manuscript expectations and editorial clues, without a quality score."""

import re
from utils.research_quality import fingerprint

INTERNAL = re.compile(
    r"\b(?:requires?|needs?|awaits?)\s+(?:(?:author|clinical|current|further)\s+)?(?:confirmation|verification)\b"
    r"|\b(?:confirm|verify)\s+(?:the\s+)?(?:author|title page|ethics|sex.code|recruitment)"
    r"|\b(?:frozen snapshot|host.assisted|yellow highlight|source allocation|verification ZIP)\b",
    re.I,
)


def audit_completeness(manuscript, profile=None):
    sections, stack = {}, []
    findings = []
    for line_number, line in enumerate(manuscript.splitlines(), 1):
        match = re.match(r"^(#{1,9})\s+(.+?)\s*$", line)
        if match:
            level, name = len(match[1]), match[2].casefold()
            stack = [(n, title) for n, title in stack if n < level] + [(level, name)]
            sections.setdefault(name, [])
            continue
        for _, name in stack:
            sections[name].append(line)
        if INTERNAL.search(line):
            findings.append(
                {
                    "kind": "internal_review_wording_in_manuscript",
                    "line": line_number,
                    "quote": line.strip(),
                    "action": "Review the wording; put administrative questions in comments attached to highlighted relevant text.",
                }
            )
    counts = {
        key: len(re.findall(r"\b\w+(?:['’\-]\w+)*\b", "\n".join(lines)))
        for key, lines in sections.items()
    }
    reference_text = "\n".join(
        sections.get("references", sections.get("bibliography", []))
    )
    references = len(re.findall(r"^\s*\d+[.)]\s+", reference_text, re.M))
    if profile is None:
        findings.append({"kind": "manuscript_expectations_not_selected"})
    else:
        allowed = {
            "schema",
            "reviewer",
            "reason",
            "section_min_words",
            "minimum_references",
            "discussion_passages",
        }
        if (
            set(profile) - allowed
            or profile.get("schema") != 1
            or any(
                not isinstance(profile.get(k), str) or not profile[k].strip()
                for k in ["reviewer", "reason"]
            )
        ):
            raise ValueError(
                "Manuscript expectations need schema 1, reviewer and reason."
            )
        limits = profile.get("section_min_words", {})
        if not isinstance(limits, dict) or any(
            not isinstance(k, str)
            or not k.strip()
            or type(v) is not int
            or not 0 <= v <= 100000
            for k, v in limits.items()
        ):
            raise ValueError(
                "Section minimums must be named, non-negative word counts."
            )
        for name, minimum in limits.items():
            key = name.casefold().strip()
            if key not in counts:
                findings.append({"kind": "expected_section_missing", "section": name})
            elif counts[key] < minimum:
                findings.append(
                    {
                        "kind": "section_below_agreed_length",
                        "section": name,
                        "actual": counts[key],
                        "minimum": minimum,
                    }
                )
        minimum = profile.get("minimum_references", 0)
        if type(minimum) is not int or not 0 <= minimum <= 10000:
            raise ValueError("Reference minimum must be a non-negative integer.")
        if references < minimum:
            findings.append(
                {
                    "kind": "references_below_agreed_count",
                    "actual": references,
                    "minimum": minimum,
                }
            )
        passages = profile.get("discussion_passages", [])
        if not isinstance(passages, list):
            raise ValueError("Discussion passages must be a list.")
        discussion = " ".join(" ".join(sections.get("discussion", [])).split())
        for passage in passages:
            if not isinstance(passage, dict) or any(
                not isinstance(passage.get(k), str) or not passage[k].strip()
                for k in ["topic", "quote"]
            ):
                raise ValueError(
                    "Every expected discussion passage needs a topic and exact quote."
                )
            if " ".join(passage["quote"].split()) not in discussion:
                findings.append(
                    {
                        "kind": "expected_discussion_passage_missing",
                        "topic": passage["topic"],
                    }
                )
    return {
        "status": "needs_review" if findings else "checked",
        "section_word_counts": counts,
        "numbered_references": references,
        "findings": findings,
        "identity": fingerprint([manuscript, profile]),
        "scope": "Recognised Markdown/Word-style headings, numbered references and explicit editorial expectations. Length and exact passages do not establish scientific completeness or reference support. Review wording clues can include legitimate uncertainty.",
    }
