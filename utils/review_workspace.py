"""Local human decisions and explicit section revisions, bound to exact content."""

import difflib
import json
import re
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from utils.literature_sources import utc_now
from utils.research_quality import fingerprint
from utils.run_control import write_json


@contextmanager
def review_lock(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".review.lock").open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        if __import__("os").name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if __import__("os").name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def save_decision(directory, claim, decision, reviewer, reason):
    if (
        decision not in {"accept", "reject", "flag"}
        or not reviewer.strip()
        or not reason.strip()
    ):
        raise ValueError("Decision, reviewer and reason are required.")
    with review_lock(directory):
        path = Path(directory) / "review_decisions.json"
        history = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        record = dict(
            fingerprint=fingerprint(claim),
            decision=decision,
            reviewer=reviewer.strip(),
            reason=reason.strip(),
            at=utc_now(),
        )
        history.append(record)
        write_json(path, history)
    return record


def current_decision(claim, decisions):
    key = fingerprint(claim)
    return next((d for d in reversed(decisions) if d["fingerprint"] == key), None)


def propose_revision(sections, section_id, replacement, reason):
    if section_id not in sections or not reason.strip() or not replacement.strip():
        raise ValueError("Select a section and supply replacement text and reason.")
    before = sections[section_id]["text"]
    numbers = lambda t: re.findall(r"\b\d+(?:\.\d+)?%?", t)
    citations = lambda t: re.findall(r"\\cite\w*\{[^}]+\}|\[[\d, -]+\]", t)
    return dict(
        base_fingerprint=fingerprint(sections),
        section_id=section_id,
        before=before,
        after=replacement,
        reason=reason,
        diff="".join(
            difflib.unified_diff(
                before.splitlines(True),
                replacement.splitlines(True),
                fromfile="current",
                tofile="proposed",
            )
        ),
        numbers_changed=numbers(before) != numbers(replacement),
        citations_changed=citations(before) != citations(replacement),
        conclusions_require_review=True,
        status="proposed",
    )


def accept_revision(sections, proposal, reviewer):
    if not reviewer.strip() or proposal["base_fingerprint"] != fingerprint(sections):
        raise ValueError(
            "Reviewer is required and proposal must match current manuscript."
        )
    if proposal.get("status") != "proposed":
        raise ValueError("Only pending proposals can be accepted.")
    result = deepcopy(sections)
    key = proposal["section_id"]
    if result[key]["text"] != proposal["before"]:
        raise ValueError("The section has changed.")
    result[key] = dict(
        text=proposal["after"], approval=None, revised_by=reviewer, revised_at=utc_now()
    )
    return result


def save_revision(directory, proposal, reviewer):
    with review_lock(directory):
        path = Path(directory) / "manuscript_sections.json"
        sections = json.loads(path.read_text(encoding="utf-8"))
        result = accept_revision(sections, proposal, reviewer)
        receipt = dict(
            proposal=proposal,
            accepted_by=reviewer,
            accepted_at=utc_now(),
            result_fingerprint=fingerprint(result),
        )
        receipt_path = Path(directory) / ("revision_" + fingerprint(receipt) + ".json")
        write_json(receipt_path, receipt)
        write_json(path, result)
        # A changed manuscript makes derived evidence and numerical reports stale.
        for name in ("evidence_review.json", "numeric_audit.json"):
            report_path = Path(directory) / name
            if report_path.exists():
                report = json.loads(report_path.read_text(encoding="utf-8"))
                report["status"] = "stale_after_revision"
                report["revision_receipt"] = receipt_path.name
                write_json(report_path, report)
    return result
