"""Review returned Word files against an explicitly registered issued version."""

from difflib import SequenceMatcher
from pathlib import Path
import shutil
from lxml import etree as E
from docx import Document

from utils.project_store import (
    load_project,
    update_project,
    private_path,
    file_receipt,
    current_file,
)
from utils.project_sources import package, word_records, W, NS, XML
from utils.project_pack import all_paragraphs, paragraph_replace
from utils.research_quality import fingerprint
from utils.review_rounds import (
    ancestors,
    decision_identity,
    supersession_valid,
    latest_item,
)


def _paragraphs(path, original=False):
    with package(path) as archive:
        root = E.fromstring(archive.read("word/document.xml"), XML)
        result = []
        for p in root.iter(W + "p"):
            query = (
                ".//w:t[not(ancestor::w:ins)]/text() | .//w:delText/text()"
                if original
                else ".//w:t[not(ancestor::w:del)]/text()"
            )
            result.append("".join(p.xpath(query, namespaces=NS)))
        return result


def _copy(workspace, source, folder):
    source = Path(source)
    if source.suffix.lower() != ".docx":
        raise ValueError("Select a Word document.")
    receipt = file_receipt(source)
    target = private_path(workspace) / folder / (receipt["sha256"] + ".docx")
    target.parent.mkdir(exist_ok=True)
    if target.exists():
        if file_receipt(target)["sha256"] != receipt["sha256"]:
            raise ValueError("Stored review document changed.")
    else:
        shutil.copyfile(source, target)
    return file_receipt(target)


def register_issued(
    workspace, manuscript, label, parent_issued_id=None, reviewer="", reason=""
):
    if not label.strip():
        raise ValueError("Name the issued version.")
    if _paragraphs(manuscript, True) != _paragraphs(manuscript):
        raise ValueError(
            "The issued baseline must have its tracked text changes resolved first."
        )
    receipt = _copy(workspace, manuscript, "issued")
    record = {"id": receipt["sha256"], "label": label, "file": receipt}

    def apply(data):
        if parent_issued_id is not None:
            parent = next(
                r
                for r in data.get("issued_versions", [])
                if r["id"] == parent_issued_id
            )
            if (
                not reviewer.strip()
                or not reason.strip()
                or not current_file(parent["file"])
            ):
                raise ValueError(
                    "A later round needs a current parent baseline, reviewer and reason."
                )
            ancestors(data, parent_issued_id)
            record.update(
                id=fingerprint([receipt["sha256"], parent_issued_id, label]),
                parent_issued_id=parent_issued_id,
                round=len(ancestors(data, parent_issued_id)) + 2,
                reviewer=reviewer,
                reason=reason,
            )
        else:
            record["round"] = 1
        if any(r["id"] == record["id"] for r in data.get("issued_versions", [])):
            raise ValueError("This issued version is already registered.")
        data.setdefault("issued_versions", []).append(record)

    update_project(workspace, apply)
    return record


def import_return(workspace, issued_id, returned, owner):
    if not owner.strip():
        raise ValueError("Assign the returned review to a named owner.")
    data = load_project(workspace)
    issued = next(r for r in data.get("issued_versions", []) if r["id"] == issued_id)
    if not current_file(issued["file"]):
        raise ValueError("Issued document changed or disappeared.")
    receipt = _copy(workspace, returned, "returned")
    before = _paragraphs(issued["file"]["path"])
    after = _paragraphs(returned)
    original = _paragraphs(returned, True)
    # Untracked changes cannot prove their parent; they are held for manual reconciliation.
    base_verified = original == before
    rid = fingerprint([issued_id, receipt["sha256"]])
    items = []
    for op, a, b, c, d in SequenceMatcher(
        a=before, b=after, autojunk=False
    ).get_opcodes():
        if op == "equal":
            continue
        items.append(
            {
                "kind": "text_change",
                "span": [a, b],
                "before": before[a:b],
                "after": after[c:d],
                "owner": owner,
                "status": "pending",
                "operation": op,
            }
        )
    assets = private_path(workspace) / "assets"
    assets.mkdir(exist_ok=True)
    _, edits, _ = word_records(returned, assets)
    for e in edits:
        if e["kind"] == "comment":
            items.append(
                {
                    "kind": "comment",
                    "text": e["text"],
                    "context": e["context"],
                    "recorded_author": e["author"],
                    "owner": owner,
                    "status": "pending",
                }
            )
    for index, item in enumerate(items):
        item["id"] = fingerprint([rid, index, item])
    review = {
        "id": rid,
        "issued_id": issued_id,
        "file": receipt,
        "owner": owner,
        "base_verified": base_verified,
        "tracked_edits": edits,
        "items": items,
    }

    def apply(data):
        if any(r["id"] == rid for r in data.get("coauthor_returns", [])):
            raise ValueError("Return already imported.")
        data.setdefault("coauthor_returns", []).append(review)

    update_project(workspace, apply)
    return review


def decide_return(workspace, return_id, item_id, status, owner, reviewer, reason):
    if status not in {"accepted", "rejected", "needs_discussion"} or not all(
        x.strip() for x in [owner, reviewer, reason]
    ):
        raise ValueError("Choose a decision, owner, reviewer and reason.")

    def apply(data):
        review = next(r for r in data["coauthor_returns"] if r["id"] == return_id)
        if not current_file(review["file"]):
            raise ValueError("Returned document changed.")
        item = next(i for i in review["items"] if i["id"] == item_id)
        item.pop("supersession", None)
        item.update(status=status, owner=owner, reviewer=reviewer, reason=reason)
        item.setdefault("decisions", []).append(
            {"status": status, "owner": owner, "reviewer": reviewer, "reason": reason}
        )

    return update_project(workspace, apply)


def return_conflicts(data, issued_id):
    changes = [
        (r, i)
        for r in data.get("coauthor_returns", [])
        if r["issued_id"] == issued_id
        for i in r["items"]
        if i["kind"] == "text_change" and i["status"] not in {"rejected", "superseded"}
    ]
    conflicts = []
    for n, (ra, a) in enumerate(changes):
        for rb, b in changes[n + 1 :]:
            if ra["id"] == rb["id"]:
                continue
            left = max(a["span"][0], b["span"][0])
            right = min(a["span"][1], b["span"][1])
            if (
                left < right
                or (
                    left == right
                    and (a["span"][0] == a["span"][1] or b["span"][0] == b["span"][1])
                )
            ) and (a["after"] != b["after"] or a["span"] != b["span"]):
                conflicts.append(
                    {"items": [a["id"], b["id"]], "kind": "overlapping_returned_edits"}
                )
    return conflicts


def apply_returned_edits(workspace, issued_id, destination):
    data = load_project(workspace)
    dest = private_path(destination)
    if dest.exists() or dest.suffix.lower() != ".docx":
        raise ValueError("Choose a new Word output file.")
    issued = next(r for r in data["issued_versions"] if r["id"] == issued_id)
    if not current_file(issued["file"]):
        raise ValueError("Issued baseline changed.")
    conflicts = return_conflicts(data, issued_id)
    accepted = [
        (r, i)
        for r in data.get("coauthor_returns", [])
        if r["issued_id"] == issued_id
        for i in r["items"]
        if i["kind"] == "text_change" and i["status"] == "accepted"
    ]
    if not accepted:
        raise ValueError("No accepted text changes to apply.")
    if any(i["id"] in c["items"] for _, i in accepted for c in conflicts):
        raise ValueError("Resolve conflicting returned edits first.")
    doc = Document(issued["file"]["path"])
    paragraphs = list(all_paragraphs(doc))
    if len(paragraphs) != len(_paragraphs(issued["file"]["path"])):
        raise ValueError(
            "Structured Word paragraph mapping needs manual reconciliation."
        )
    applied = set()
    for review, item in accepted:
        if not review["base_verified"] or not current_file(review["file"]):
            raise ValueError(
                "Returned version cannot be verified against this baseline."
            )
        if len(item["before"]) != 1 or len(item["after"]) != 1 or not item["before"][0]:
            raise ValueError(
                "Paragraph insertion/deletion needs manual Word reconciliation."
            )
        p = paragraphs[item["span"][0]]
        if any(
            E.QName(n).localname
            in {
                "drawing",
                "pict",
                "oMath",
                "oMathPara",
                "fldChar",
                "instrText",
                "footnoteReference",
                "hyperlink",
                "ins",
                "del",
                "commentRangeStart",
                "commentRangeEnd",
                "commentReference",
            }
            for n in p._p.iter()
        ):
            raise ValueError(
                "This paragraph contains structured Word content and needs manual reconciliation."
            )
        key = fingerprint([item["span"], item["after"]])
        if key in applied:
            continue
        if p.text != item["before"][0]:
            raise ValueError("Paragraph no longer matches its baseline.")
        paragraph_replace(p, item["before"][0], item["after"][0])
        applied.add(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(dest)
    update_project(
        workspace,
        lambda d: d.setdefault("events", []).append(
            {
                "kind": "coauthor_edits_applied",
                "issued_id": issued_id,
                "output": file_receipt(dest),
                "items": [i["id"] for _, i in accepted],
            }
        ),
    )
    return {"status": "draft_created", "applied": len(applied)}


def record_manual_reconciliation(
    workspace, issued_id, manuscript, item_ids, reviewer, reason
):
    if Path(manuscript).suffix.lower() != ".docx":
        raise ValueError("Select a reconciled Word document.")
    if not item_ids or not reviewer.strip() or not reason.strip():
        raise ValueError(
            "Select items and record the reviewer and reconciliation reason."
        )
    from utils.project_pack import doc_text

    text = doc_text(manuscript)
    receipt = file_receipt(manuscript)

    def apply(data):
        candidates = {
            i["id"]: i
            for r in data.get("coauthor_returns", [])
            if r["issued_id"] == issued_id
            for i in r["items"]
            if i["status"] == "accepted"
        }
        if set(item_ids) - set(candidates):
            raise ValueError("Only accepted items can be reconciled.")
        for key in item_ids:
            item = candidates[key]
            if item["kind"] == "text_change" and any(
                t and t not in text for t in item["after"]
            ):
                raise ValueError(
                    "Accepted replacement text is missing from the reconciled manuscript."
                )
            if (
                item["kind"] == "text_change"
                and not item["after"]
                and any(t and t in text for t in item["before"])
            ):
                raise ValueError("Accepted deletion is still present or ambiguous.")
        data.setdefault("events", []).append(
            {
                "kind": "coauthor_manual_reconciliation",
                "issued_id": issued_id,
                "output": receipt,
                "items": item_ids,
                "reviewer": reviewer,
                "reason": reason,
            }
        )

    return update_project(workspace, apply)


def coauthor_findings(data, manuscript=None):
    findings = []
    for issued in data.get("issued_versions", []):
        try:
            ancestors(data, issued["id"])
        except ValueError:
            findings.append(
                {"kind": "invalid_review_round_ancestry", "id": issued["id"]}
            )
        if not current_file(issued["file"]):
            findings.append({"kind": "issued_file_changed", "id": issued["id"]})
    applied = {
        i
        for event in data.get("events", [])
        if event.get("kind")
        in {"coauthor_edits_applied", "coauthor_manual_reconciliation"}
        and current_file(event.get("output", {}))
        for i in event.get("items", [])
    }
    for iid in {r["issued_id"] for r in data.get("coauthor_returns", [])}:
        findings.extend(return_conflicts(data, iid))
    for review in data.get("coauthor_returns", []):
        if not current_file(review["file"]):
            findings.append({"kind": "returned_file_changed", "id": review["id"]})
        for item in review["items"]:
            if item["status"] == "superseded":
                if not supersession_valid(data, item["id"]):
                    findings.append(
                        {"kind": "invalid_coauthor_supersession", "id": item["id"]}
                    )
                elif manuscript is not None and item["kind"] == "text_change":
                    final_item = latest_item(data, item["id"])
                    if any(
                        t and t in manuscript and t not in final_item["after"]
                        for t in item["after"]
                    ):
                        findings.append(
                            {
                                "kind": "superseded_coauthor_text_present_or_ambiguous",
                                "id": item["id"],
                            }
                        )
            elif item["status"] in {"pending", "needs_discussion"}:
                findings.append({"kind": "coauthor_item_pending", "id": item["id"]})
            elif (
                item["status"] == "rejected"
                and item["kind"] == "text_change"
                and manuscript is not None
                and any(
                    t and t in manuscript and t not in item["before"]
                    for t in item["after"]
                )
            ):
                findings.append(
                    {
                        "kind": "rejected_coauthor_text_present_or_ambiguous",
                        "id": item["id"],
                    }
                )
            elif item["status"] == "accepted" and item["kind"] == "text_change":
                if item["id"] not in applied:
                    findings.append(
                        {"kind": "coauthor_change_not_reconciled", "id": item["id"]}
                    )
                elif manuscript is not None:
                    if any(t and t not in manuscript for t in item["after"]) or (
                        not item["after"]
                        and any(t and t in manuscript for t in item["before"])
                    ):
                        findings.append(
                            {
                                "kind": "coauthor_change_missing_from_pack",
                                "id": item["id"],
                            }
                        )
    return findings


def supersede_item(
    workspace, earlier_item_id, later_item_id, manuscript, reviewer, reason
):
    """A human links a prior item to an accepted decision in a descendant round."""
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Record the supersession reviewer and reason.")
    from utils.project_pack import doc_text

    receipt = _copy(workspace, manuscript, "reconciled")
    text = doc_text(receipt["path"])

    def apply(data):
        items = {
            i["id"]: (r, i)
            for r in data.get("coauthor_returns", [])
            for i in r["items"]
        }
        old_review, old = items[earlier_item_id]
        new_review, new = items[later_item_id]
        if old["status"] == "superseded" or new["status"] != "accepted":
            raise ValueError(
                "Choose an active earlier item and an accepted later decision."
            )
        if old_review["issued_id"] not in ancestors(data, new_review["issued_id"]):
            raise ValueError(
                "The replacement decision must belong to a later descendant round."
            )
        issued = {r["id"]: r for r in data["issued_versions"]}
        if not all(
            current_file(r["file"])
            for r in [
                old_review,
                new_review,
                issued[old_review["issued_id"]],
                issued[new_review["issued_id"]],
            ]
        ):
            raise ValueError("A baseline or returned document changed.")
        if old["kind"] != new["kind"]:
            raise ValueError("Link text edits to text edits, or comments to comments.")
        if new["kind"] == "text_change":
            if any(t and t not in text for t in new["after"]) or (
                not new["after"] and any(t and t in text for t in new["before"])
            ):
                raise ValueError(
                    "The checked manuscript does not contain the later decision."
                )
            if any(t and t in text and t not in new["after"] for t in old["after"]):
                raise ValueError(
                    "Earlier replacement text is still present or ambiguous."
                )
        link = {
            "target_id": later_item_id,
            "target_decision": decision_identity(new),
            "output": receipt,
            "reviewer": reviewer,
            "reason": reason,
        }
        old["supersession"] = link
        old.setdefault("decisions", []).append(
            {"status": "superseded", "previous_status": old["status"], **link}
        )
        old["status"] = "superseded"
        data.setdefault("events", []).append(
            {
                "kind": "coauthor_manual_reconciliation",
                "issued_id": new_review["issued_id"],
                "output": receipt,
                "items": [later_item_id],
                "reviewer": reviewer,
                "reason": reason,
            }
        )

    return update_project(workspace, apply)


def export_response(workspace, issued_id, destination):
    dest = private_path(destination)
    if dest.exists() or dest.suffix.lower() != ".docx":
        raise ValueError("Choose a new response Word file.")
    doc = Document()
    doc.add_heading("Draft response to co-author comments", 0)
    data = load_project(workspace)
    for r in data.get("coauthor_returns", []):
        if r["issued_id"] != issued_id:
            continue
        for item in r["items"]:
            doc.add_heading(item["owner"] + " / " + item["status"].replace("_", " "), 2)
            doc.add_paragraph(
                item.get("text")
                or "\n".join(item["before"]) + " -> " + "\n".join(item["after"])
            )
            if item["status"] == "superseded":
                link = item.get("supersession", {})
                doc.add_paragraph(
                    "Reason for replacement: " + link.get("reason", "Needs review.")
                )
                doc.add_paragraph(
                    "Replacement reviewed by: "
                    + link.get("reviewer", "Needs confirmation.")
                )
                if not supersession_valid(data, item["id"]):
                    doc.add_paragraph(
                        "This replacement decision needs review because its evidence or later decision is no longer current."
                    )
                if item.get("reason"):
                    doc.add_paragraph("Earlier decision reason: " + item["reason"])
            else:
                doc.add_paragraph(item.get("reason", "Awaiting review."))
    dest.parent.mkdir(parents=True, exist_ok=True)
    doc.save(dest)
    return {"status": "draft_created", "sent": False}
