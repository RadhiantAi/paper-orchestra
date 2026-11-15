"""Read-only storage accounting and conservative snapshot retention previews."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import json
import os
import re
import shutil

from utils.project_store import private_path, load_project
from utils.project_recovery import _receipts
from utils.research_quality import fingerprint
from utils.run_control import digest


def _linked(path):
    return path.is_symlink() or path.is_junction()


def retention_preview(
    workspace,
    keep_latest=20,
    keep_days=30,
    budget_bytes=5 * 1024**3,
    reserve_bytes=1024**3,
    now=None,
):
    if type(keep_latest) is not int or not 1 <= keep_latest <= 10000:
        raise ValueError("Retain at least one and at most 10,000 recent snapshots.")
    if type(keep_days) is not int or not 0 <= keep_days <= 36500:
        raise ValueError("Choose a valid age window.")
    if any(type(v) is not int or v < 0 for v in [budget_bytes, reserve_bytes]):
        raise ValueError("Storage thresholds must be non-negative byte counts.")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Use a timezone-aware preview time.")
    root = private_path(workspace)
    data = load_project(root)
    recovery = root / ".recovery"
    total = 0
    skipped_links = 0
    for folder, dirs, names in os.walk(root, followlinks=False):
        skipped_links += sum(_linked(Path(folder) / n) for n in dirs)
        dirs[:] = [n for n in dirs if not _linked(Path(folder) / n)]
        for name in names:
            path = Path(folder) / name
            if path.is_symlink():
                skipped_links += 1
            else:
                total += path.stat().st_size
    free = shutil.disk_usage(root).free
    warnings = []
    if total >= budget_bytes:
        warnings.append("project_storage_budget_reached")
    if free < reserve_bytes:
        warnings.append("disk_free_space_below_reserve")
    if skipped_links:
        warnings.append("linked_paths_excluded_from_estimate")
    summary = {
        "project_bytes": total,
        "disk_free_bytes": free,
        "budget_bytes": budget_bytes,
        "reserve_bytes": reserve_bytes,
        "warnings": warnings,
    }
    linked_recovery = any(
        _linked(p) for p in [recovery, recovery / "snapshots", recovery / "objects"]
    )
    paths = [] if linked_recovery else list((recovery / "snapshots").glob("*.json"))
    snapshots = []
    problems = ["linked_recovery_folder"] if linked_recovery else []
    if len(paths) > 10000:
        problems.append("snapshot_inventory_limit_exceeded")
        paths = []
    objects = {}
    for path in [] if linked_recovery else (recovery / "objects").glob("*"):
        if (
            path.is_symlink()
            or not path.is_file()
            or not re.fullmatch("[a-f0-9]{64}", path.name)
        ):
            problems.append("unexpected_recovery_object")
        else:
            objects[path.name] = path.stat().st_size
    for path in paths:
        try:
            if path.is_symlink() or path.stat().st_size > 20 * 1024**2:
                raise ValueError("Invalid manifest file")
            manifest = json.loads(path.read_text(encoding="utf-8"))
            if manifest["schema"] != 1:
                raise ValueError("Unknown manifest schema")
            created = (
                datetime.fromisoformat(manifest["created_at"])
                if manifest.get("created_at")
                else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            )
            if created.tzinfo is None:
                raise ValueError("Missing time zone")
            refs = {f["sha256"] for f in manifest["files"]}
            if any(
                not re.fullmatch("[a-f0-9]{64}", sha) or sha not in objects
                for sha in refs
            ):
                raise ValueError("Missing or invalid recovery object")
            snapshots.append(
                {
                    "name": path.name,
                    "created_at": created.isoformat(),
                    "time": created,
                    "sha256": digest(path),
                    "bytes": path.stat().st_size,
                    "objects": refs,
                }
            )
        except (OSError, ValueError, KeyError, TypeError):
            problems.append("unreadable_or_incomplete_snapshot:" + path.name)
    snapshots.sort(key=lambda s: (s["time"], s["name"]), reverse=True)
    retained = [
        s
        for i, s in enumerate(snapshots)
        if i < keep_latest or s["time"] >= now - timedelta(days=keep_days)
    ]
    candidates = [s for s in snapshots if s not in retained]
    protected = {r["sha256"] for r in _receipts(data)}
    protected.add(
        hashlib.sha256(
            json.dumps(data, ensure_ascii=False, indent=2).encode()
        ).hexdigest()
    )
    for s in retained:
        protected |= s["objects"]
    removable = set().union(*(s["objects"] for s in candidates)) - protected
    if problems:
        candidates, removable = [], set()
    plan = {
        "status": "blocked" if problems else "preview_only",
        "storage": summary,
        "policy": {"keep_latest": keep_latest, "keep_days": keep_days},
        "snapshot_count": len(snapshots),
        "recovery_object_bytes": sum(objects.values()),
        "candidate_snapshots": [
            {k: s[k] for k in ["name", "sha256", "bytes", "created_at"]}
            for s in candidates
        ],
        "candidate_objects": sorted(removable),
        "estimated_reclaimable_bytes": sum(objects[sha] for sha in removable)
        + sum(s["bytes"] for s in candidates),
        "problems": problems,
        "deletion_performed": False,
        "scope": "Preview only. External source files and backups outside the workspace are excluded from storage totals. Recalculate before any separately authorised cleanup; verify a separate backup first. This is not an integrity audit of object contents.",
    }
    plan["inventory_fingerprint"] = fingerprint(
        [[(s["name"], s["sha256"]) for s in snapshots], objects, data]
    )
    return plan
