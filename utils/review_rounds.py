"""Explicit review-round ancestry and supersession validation."""

from utils.project_store import current_file
from utils.research_quality import fingerprint


def ancestors(data, issued_id):
    records = {r["id"]: r for r in data.get("issued_versions", [])}
    seen = {issued_id}
    result = []
    while issued_id in records:
        parent = records[issued_id].get("parent_issued_id")
        if parent is None:
            return result
        if parent in seen or parent not in records:
            raise ValueError("Review-round ancestry is invalid.")
        seen.add(parent)
        result.append(parent)
        issued_id = parent
    raise ValueError("Unknown issued review round.")


def decision_identity(item):
    # Later supersessions extend history without rewriting the underlying decision.
    decisions = [d for d in item.get("decisions", []) if d["status"] != "superseded"]
    return fingerprint(decisions)


def latest_item(data, item_id):
    items = {i["id"]: i for r in data.get("coauthor_returns", []) for i in r["items"]}
    seen = set()
    while item_id not in seen:
        seen.add(item_id)
        item = items[item_id]
        if item["status"] != "superseded":
            return item
        item_id = item["supersession"]["target_id"]
    raise ValueError("Cyclic supersession chain.")


def supersession_valid(data, item_id, seen=None):
    seen = set() if seen is None else set(seen)
    if item_id in seen:
        return False
    seen.add(item_id)
    items = {
        i["id"]: (r, i) for r in data.get("coauthor_returns", []) for i in r["items"]
    }
    issued = {r["id"]: r for r in data.get("issued_versions", [])}
    try:
        source_review, item = items[item_id]
        link = item["supersession"]
        target_review, target = items[link["target_id"]]
        if not all(
            current_file(r["file"])
            for r in [
                source_review,
                target_review,
                issued[source_review["issued_id"]],
                issued[target_review["issued_id"]],
            ]
        ):
            return False
        if source_review["issued_id"] not in ancestors(
            data, target_review["issued_id"]
        ):
            return False
        if decision_identity(target) != link["target_decision"] or not current_file(
            link["output"]
        ):
            return False
        return target["status"] == "accepted" or (
            target["status"] == "superseded"
            and supersession_valid(data, target["id"], seen)
        )
    except (KeyError, ValueError):
        return False
