"""Host exchange, conditional author queries and discussion coverage."""

from copy import deepcopy
import difflib
import re

from utils.literature_sources import utc_now
from utils.project_store import (
    current_file,
    identity,
    require_text,
    unique,
    update_project,
    upsert,
)
from utils.research_quality import fingerprint

KINDS = {"finding", "interpretation", "hypothesis", "proposed_study"}


def evidence_valid(evidence, sources):
    by_id = {s["id"]: s for s in sources}
    return bool(evidence) and all(
        e.get("source_id") in by_id
        and e.get("source_sha256") == by_id[e["source_id"]]["sha256"]
        and ("path" not in by_id[e["source_id"]] or current_file(by_id[e["source_id"]]))
        and any(
            b["locator"] == e.get("locator")
            and e.get("quote")
            and e["quote"] in b["text"]
            for b in by_id[e["source_id"]].get("blocks", [])
        )
        for e in evidence
    )


def validate_query(q):
    require_text(q, "id", "owner", "question", "target", "quote")
    if not isinstance(q.get("evidence", []), list) or not isinstance(
        q.get("conditions", []), list
    ):
        raise ValueError("Evidence and conditions must be lists.")
    for c in q.get("conditions", []):
        require_text(c, "id", "description")
        if c.get("kind") not in {"exact_text_match", "source_evidence"}:
            raise ValueError(
                "Condition kind must be exact_text_match or source_evidence."
            )
    unique(q.get("conditions", []))


def query_status(q, sources):
    d = next(
        (d for d in reversed(q.get("decisions", [])) if d["identity"] == identity(q)),
        None,
    )
    if d is None:
        return "open"
    if q.get("evidence") and not evidence_valid(q["evidence"], sources):
        return "stale_evidence"
    if d["action"] == "flag":
        return "open"
    proofs = {c["id"]: c for c in d.get("condition_proofs", [])}
    if any(
        c["id"] not in proofs
        or not evidence_valid(proofs[c["id"]].get("evidence"), sources)
        for c in q.get("conditions", [])
    ):
        return "conditional_pending"
    for condition in q.get("conditions", []):
        if condition["kind"] == "exact_text_match":
            # Conditional agreement with an original requires the whole anchored text.
            norm = lambda s: re.sub(r"\s+", " ", s).strip()
            if not any(
                norm(e["quote"]) == norm(q["quote"])
                for e in proofs[condition["id"]]["evidence"]
            ):
                return "conditional_pending"
    return "resolved"


def decide_query(
    workspace, query_id, reviewer, reason, action="confirm", condition_proofs=None
):
    require_text({"reviewer": reviewer, "reason": reason}, "reviewer", "reason")
    if action not in {"confirm", "flag"}:
        raise ValueError("Unknown query action.")

    def apply(data):
        q = next(q for q in data["queries"] if q["id"] == query_id)
        proofs = condition_proofs or []
        unique(proofs)
        if any(not evidence_valid(p.get("evidence"), data["sources"]) for p in proofs):
            raise ValueError("Condition proof must cite current exact source text.")
        q.setdefault("decisions", []).append(
            {
                "identity": identity(q),
                "action": action,
                "reviewer": reviewer,
                "reason": reason,
                "condition_proofs": proofs,
                "at": utc_now(),
            }
        )

    return update_project(workspace, apply)


def compare_versions(before, after, decisions=None):
    """Surface removed proposals; similarity is a candidate, never acceptance."""
    decisions = decisions or []
    rows = []
    after_text = "\n".join(b["text"] for b in after.get("blocks", []))
    for edit in before.get("edits", []):
        key = fingerprint(
            {"source": before["sha256"], "edit": edit, "after": after["sha256"]}
        )
        decision = next((d for d in decisions if d.get("fingerprint") == key), None)
        if (
            decision
            and decision.get("reviewer")
            and decision.get("reason")
            and decision.get("status") in {"retained", "rejected", "superseded"}
        ):
            status = decision["status"]
        elif edit.get("kind") == "ins" and edit["text"] and edit["text"] in after_text:
            status = "present_needs_review"
        else:
            status = "unresolved"
        rows.append({"fingerprint": key, "edit": edit, "status": status})
    return {
        "before": before["id"],
        "after": after["id"],
        "edits": rows,
        "diff": "".join(
            difflib.unified_diff(
                "\n".join(b["text"] for b in before.get("blocks", [])).splitlines(True),
                after_text.splitlines(True),
                fromfile="earlier",
                tofile="current",
            )
        ),
    }


def discussion_coverage(data, manuscript):
    findings = []
    for t in data["topics"]:
        require_text(t, "id", "kind", "text", "source_id")
        if t["kind"] not in KINDS:
            raise ValueError("Unknown scientific statement kind.")
        disposition = t.get("disposition", "include")
        if disposition in {"exclude", "superseded"}:
            if not t.get("reviewer") or not t.get("reason"):
                findings.append({"id": t["id"], "kind": "unexplained_omission"})
            continue
        quote = t.get("manuscript_quote", "")
        if not quote or quote not in manuscript:
            findings.append({"id": t["id"], "kind": "missing_topic"})
        if t["kind"] in {"hypothesis", "proposed_study"}:
            qualification = t.get("qualification", "")
            if not qualification or qualification not in quote:
                findings.append({"id": t["id"], "kind": "unqualified_proposal"})
        if t["kind"] == "finding" and not evidence_valid(
            t.get("evidence"), data["sources"]
        ):
            findings.append({"id": t["id"], "kind": "finding_without_current_evidence"})
    return {
        "status": "needs_review"
        if findings
        else "checked"
        if data["topics"]
        else "not_checked",
        "findings": findings,
        "word_counts": section_word_counts(manuscript),
        "scope": "Explicit topic mappings only; qualification wording still needs scientific review.",
    }


def section_word_counts(text):
    sections, title = {}, "Preamble"
    for line in text.splitlines():
        heading = re.match(r"^#{1,3}\s+(.+)", line)
        if heading:
            title = heading[1].strip()
            sections.setdefault(title, 0)
        else:
            sections[title] = sections.get(title, 0) + len(
                re.findall(r"\b\w+(?:['’\-]\w+)*\b", line)
            )
    total = sum(
        n
        for title, n in sections.items()
        if not re.match(r"^(references|bibliography)\b", title, re.I)
    )
    return {
        "by_section": sections,
        "excluding_references": total,
        "rule": "Markdown headings excluded; references/bibliography sections excluded; tables and captions included.",
    }


def import_host(workspace, payload):
    """Atomic, provider-independent exchange. Never executes actions from source content."""
    if payload.get("schema") != 1 or payload.get("mode") != "host_assisted":
        raise ValueError("Unsupported host exchange schema or execution mode.")
    allowed = {
        "schema",
        "mode",
        "host",
        "sources",
        "searches",
        "queries",
        "topics",
        "results",
        "figures",
        "calculations",
        "edit_decisions",
    }
    if set(payload) - allowed:
        raise ValueError("Unknown exchange fields.")
    require_text(payload, "host")
    for name in [
        "sources",
        "searches",
        "queries",
        "topics",
        "results",
        "figures",
        "calculations",
        "edit_decisions",
    ]:
        if not isinstance(payload.get(name, []), list):
            raise ValueError("Exchange collections must be lists.")

    def apply(data):
        draft = deepcopy(data)
        unique(payload.get("sources", []))
        for r in payload.get("sources", []):
            require_text(r, "id", "sha256", "origin", "status")
            if not re.fullmatch(r"[a-f0-9]{64}", r["sha256"]):
                raise ValueError("Source content hash required.")
            if r["status"] not in {"read", "partial", "unreadable", "excluded"}:
                raise ValueError("Invalid source state.")
            if "path" in r:
                raise ValueError(
                    "Host sources use origin URLs; local files use the indexer."
                )
            for b in r.get("blocks", []):
                require_text(b, "locator", "text")
            upsert(draft["sources"], deepcopy(r))
        ids = {s["id"] for s in draft["sources"]}
        for name in ["queries", "topics", "results", "figures", "calculations"]:
            rows = payload.get(name, [])
            unique(rows)
            for r in rows:
                require_text(r, "id")
                if name == "queries":
                    validate_query(r)
                    if "decisions" in r:
                        raise ValueError(
                            "Confirmations use the explicit decision operation."
                        )
                    previous = next((q for q in draft[name] if q["id"] == r["id"]), {})
                    r = dict(r, decisions=previous.get("decisions", []))
                if name == "topics" and (
                    r.get("source_id") not in ids or r.get("kind") not in KINDS
                ):
                    raise ValueError(
                        "Topics require a known source and scientific statement kind."
                    )
                if name == "results":
                    from utils.project_results import validate_result

                    validate_result(r)
                if name == "figures":
                    from utils.project_figures import validate_figure

                    validate_figure(r)
                    if any(p["source_id"] not in ids for p in r["panels"]):
                        raise ValueError("Figure panels require known sources.")
                if name == "calculations":
                    require_text(
                        r, "method", "code_sha256", "output_sha256", "reviewer"
                    )
                    if any(
                        not re.fullmatch(r"[a-f0-9]{64}", r[k])
                        for k in ["code_sha256", "output_sha256"]
                    ):
                        raise ValueError("Calculation receipts require SHA256 hashes.")
                upsert(draft[name], deepcopy(r))
        for search in payload.get("searches", []):
            require_text(search, "source", "query", "status")
            if search["status"] not in {"complete", "partial", "failed"}:
                raise ValueError("Invalid search state.")
            draft["searches"].append(deepcopy(search))
        if "edit_decisions" in payload:
            for d in payload["edit_decisions"]:
                require_text(d, "fingerprint", "reviewer", "reason", "status")
                if d["status"] not in {"retained", "rejected", "superseded"}:
                    raise ValueError("Invalid edit disposition.")
            draft.setdefault("edit_decisions", []).extend(payload["edit_decisions"])
        draft["events"].append(
            {
                "kind": "host_import",
                "host": payload["host"],
                "payload_fingerprint": fingerprint(payload),
                "at": utc_now(),
                "local_model_calls": 0,
            }
        )
        data.clear()
        data.update(draft)

    return update_project(workspace, apply)
