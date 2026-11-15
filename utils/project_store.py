"""Private, versioned project records for host-assisted manuscript work."""

import json
from pathlib import Path

from utils.research_quality import fingerprint
from utils.run_control import digest, write_json
from utils.review_workspace import review_lock

SCHEMA = 1
REPO = Path(__file__).resolve().parents[1]


def private_path(path):
    path = Path(path).resolve()
    if path == REPO or path.is_relative_to(REPO):
        raise ValueError("Research workspaces must be outside the public checkout.")
    return path


def create_project(path):
    path = private_path(path)
    path.mkdir(parents=True, exist_ok=True)
    with review_lock(path):
        if (path / "project.json").exists():
            raise ValueError("Project already exists; preserve its records.")
        data = {
            "schema": SCHEMA,
            "mode": "host_assisted",
            "sources": [],
            "searches": [],
            "queries": [],
            "topics": [],
            "results": [],
            "figures": [],
            "calculations": [],
            "events": [],
        }
        write_json(path / "project.json", data)
    return data


def load_project(path):
    data = json.loads((private_path(path) / "project.json").read_text(encoding="utf-8"))
    if data.get("schema") != SCHEMA:
        raise ValueError("Unsupported project schema.")
    return data


def update_project(path, transform):
    path = private_path(path)
    with review_lock(path):
        data = load_project(path)
        from utils.project_recovery import snapshot

        snapshot(path, data)
        transform(data)
        snapshot(path, data)
        write_json(path / "project.json", data)
    return data


def require_text(record, *fields):
    for field in fields:
        if not isinstance(record.get(field), str) or not record[field].strip():
            raise ValueError("Required non-empty field: " + field)


def unique(records):
    ids = [r["id"] for r in records]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate record IDs.")


def upsert(records, record):
    records[:] = [r for r in records if r["id"] != record["id"]] + [record]


def identity(record):
    return fingerprint(
        {k: v for k, v in record.items() if k not in {"decisions", "approval"}}
    )


def file_receipt(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": digest(path), "bytes": path.stat().st_size}


def current_file(record):
    try:
        return digest(record["path"]) == record["sha256"]
    except (OSError, KeyError):
        return False


def dependency_status(data):
    """A successful source lookup does not prove the retrieved file is still current."""
    problems = [
        {"id": s["id"], "status": "changed_or_missing"}
        for s in data["sources"]
        if s.get("path") and not current_file(s)
    ]
    problems += [
        {"id": s["id"], "status": "conversion_changed_or_missing"}
        for s in data["sources"]
        if s.get("conversion") and not current_file(s["conversion"])
    ]
    return problems
