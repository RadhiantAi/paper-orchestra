"""Explicit, hash-bound admission at supported blinded-project intake boundaries."""

from pathlib import Path
import re
from utils.project_store import load_project, update_project, file_receipt
from utils.research_quality import fingerprint
from utils.literature_sources import utc_now


def enable_strict_trial(workspace, reviewer, reason):
    if not reviewer.strip() or not reason.strip():
        raise ValueError("Record a reviewer and reason for a new strict trial.")
    root = Path(workspace)

    def apply(data):
        if data.get("strict_trial") or any(
            data.get(k)
            for k in [
                "sources",
                "results",
                "figures",
                "queries",
                "topics",
                "calculations",
                "events",
                "issued_versions",
                "coauthor_returns",
                "continuous_results",
                "legacy_conversions",
            ]
        ):
            raise ValueError("Enable strict mode only on a new, unexposed project.")
        if any(
            p.is_file()
            and p.name not in {"project.json", ".review.lock"}
            and ".recovery" not in p.relative_to(root).parts
            for p in root.rglob("*")
        ):
            raise ValueError(
                "Strict mode requires a project without existing content files."
            )
        data["strict_trial"] = {
            "enabled": True,
            "reviewer": reviewer,
            "reason": reason,
            "started_at": utc_now(),
            "scope": "Supported application intake only; external tools and manual context exposure require a separate log.",
        }

    return update_project(workspace, apply)


def admit(data, sha256, *, path=None, origin=None):
    if not data.get("strict_trial", {}).get("enabled"):
        return
    if not re.fullmatch(r"[a-f0-9]{64}", sha256 or ""):
        raise ValueError("Strict trial admission requires an exact SHA256.")
    allocations = data.get("source_allocations", [])
    matched = [
        a
        for a in allocations
        if a["source"]["sha256"] == sha256
        or (
            path
            and a["source"].get("path")
            and Path(a["source"]["path"]).resolve() == Path(path).resolve()
        )
        or (origin and a["source"].get("origin") == origin)
    ]
    if any(a["role"] != "trial_input" for a in matched):
        raise ValueError(
            "Strict trial blocked a withheld, excluded or unclassified input."
        )
    if any(r["sha256"] == sha256 for r in data.get("trial_artifacts", [])):
        return
    if not any(
        a["role"] == "trial_input"
        and a["source"]["sha256"] == sha256
        and a.get("reviewer")
        and a.get("reason")
        for a in matched
    ):
        raise ValueError(
            "Strict trial requires an explicit trial-input allocation for these exact bytes."
        )


def admit_file(workspace, path):
    data = load_project(workspace)
    if data.get("strict_trial", {}).get("enabled"):
        receipt = file_receipt(path)
        admit(data, receipt["sha256"], path=path)


def allocate_host(workspace, origin, sha256, role, reviewer, reason):
    from utils.source_structure import ROLES

    if (
        role not in ROLES
        or not origin.strip()
        or not reviewer.strip()
        or not reason.strip()
        or not re.fullmatch(r"[a-f0-9]{64}", sha256)
    ):
        raise ValueError(
            "Host allocation needs origin, SHA256, role, reviewer and reason."
        )

    def apply(data):
        if role != "trial_input" and any(
            s.get("sha256") == sha256 for s in data["sources"]
        ):
            raise ValueError("Already exposed content cannot be labelled withheld.")
        row = {
            "id": fingerprint(["host", origin]),
            "source": {"origin": origin, "sha256": sha256},
            "role": role,
            "reviewer": reviewer,
            "reason": reason,
            "recorded_at": utc_now(),
            "author_approval": False,
            "verification": "Host-declared digest, not independent remote retrieval",
        }
        record_allocation_change(data, row)
        data["source_allocations"] = [
            a for a in data.get("source_allocations", []) if a["id"] != row["id"]
        ] + [row]

    return update_project(workspace, apply)


def admit_host(data, payload):
    if not data.get("strict_trial", {}).get("enabled"):
        return
    # Bind all imported text and derived assertions, not merely the source IDs.
    admit(data, fingerprint(payload), origin="host-exchange:" + payload["host"])
    for source in payload.get("sources", []):
        admit(data, source["sha256"], origin=source["origin"])
    from utils.project_recovery import _receipts

    for receipt in _receipts(payload):
        actual = file_receipt(receipt["path"])
        if actual["sha256"] != receipt["sha256"]:
            raise ValueError("Host-referenced file differs from its receipt.")
        admit(data, actual["sha256"], path=actual["path"])


def register_derived(data, paths, operation):
    if data.get("strict_trial", {}).get("enabled"):
        rows = data.setdefault("trial_artifacts", [])
        for path in paths:
            receipt = file_receipt(path)
            rows[:] = [r for r in rows if r["path"] != receipt["path"]]
            rows.append({**receipt, "operation": operation})


def record_allocation_change(data, row):
    from copy import deepcopy
    from utils.project_recovery import _receipts

    sha = row["source"]["sha256"]
    exposed = any(r.get("sha256") == sha for r in _receipts(data)) or any(
        event.get("payload_fingerprint") == sha for event in data.get("events", [])
    )
    if row["role"] != "trial_input" and exposed:
        raise ValueError(
            "Already exposed content cannot be relabelled as withheld or unclassified."
        )

    old = next(
        (a for a in data.get("source_allocations", []) if a["id"] == row["id"]), None
    )
    data.setdefault("allocation_history", []).append(
        {
            "decision": deepcopy(row),
            "previous_role": old["role"] if old else None,
            "at": utc_now(),
        }
    )
    if (
        old
        and old["role"] == "withheld_reference"
        and row["role"] == "trial_input"
        and data.get("strict_trial", {}).get("enabled")
    ):
        data["strict_trial"]["unblinded_at"] = utc_now()
