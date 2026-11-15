"""Content-addressed private snapshots and checked portable recovery archives."""

from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath
import hashlib
import json
import os
import re
import uuid
import zipfile
import tempfile
import io
from datetime import datetime, timezone

from utils.run_control import digest, write_json

MAX_BYTES = 2 * 1024**3
MAX_FILES = 10000
SKIP = {
    ".recovery",
    ".git",
    ".venv",
    "__pycache__",
    ".review.lock",
    ".env",
    "recovery-original",
    "credentials.json",
    "secrets.json",
    "connectors.json",
}


def _receipts(value, key=""):
    # Allocation is an inventory, not permission to ingest withheld originals.
    if key == "source_allocations":
        return
    if isinstance(value, dict):
        if (
            key != "ocr_engine"
            and isinstance(value.get("path"), str)
            and "sha256" in value
        ):
            yield value
        for k, child in value.items():
            if k != "ocr_engine":
                yield from _receipts(child, k)
    elif isinstance(value, list):
        for child in value:
            yield from _receipts(child, key)


def snapshot(workspace, data):
    """Caller holds the project lock. Missing inputs remain explicit in the snapshot."""
    root = Path(workspace).resolve()
    recovery = root / ".recovery"
    objects = recovery / "objects"
    manifests = recovery / "snapshots"
    objects.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(exist_ok=True)
    paths = set()
    for folder, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [
            n
            for n in dirs
            if n not in SKIP
            and not (Path(folder) / n).is_symlink()
            and not (Path(folder) / n).is_junction()
        ]
        paths.update(
            Path(folder) / name
            for name in names
            if name not in SKIP and not name.startswith(".env.")
        )
    missing = []
    for receipt in _receipts(data):
        path = Path(receipt["path"])
        if path.is_file():
            paths.add(path)
        else:
            missing.append(receipt["path"])
    if len(paths) > MAX_FILES:
        raise ValueError("Project exceeds the recovery file budget.")
    entries, total = [], 0
    for path in sorted(paths):
        if path.is_symlink():
            raise ValueError("Recovery does not follow file symlinks.")
        path = path.resolve()
        if path.name in SKIP or path.name.startswith(".env."):
            raise ValueError(
                "A referenced credential/configuration file cannot enter a research backup."
            )
        size = path.stat().st_size
        total += size
        if total > MAX_BYTES:
            raise ValueError("Project exceeds the 2 GB recovery budget.")
        blob = (
            json.dumps(data, ensure_ascii=False, indent=2).encode()
            if path == root / "project.json"
            else path.read_bytes()
        )
        sha = hashlib.sha256(blob).hexdigest()
        target = objects / sha
        if target.exists():
            if digest(target) != sha:
                raise ValueError(
                    "Recovery object is corrupt. Preserve and repair the recovery store."
                )
        else:
            with target.open("xb") as stream:
                stream.write(blob)
        relative = (
            path.relative_to(root).as_posix() if path.is_relative_to(root) else None
        )
        entries.append(
            {
                "original": str(path),
                "relative": relative,
                "sha256": sha,
                "bytes": len(blob),
            }
        )
    manifest = {
        "schema": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_schema": data["schema"],
        "workspace": str(root),
        "files": entries,
        "missing": sorted(set(missing)),
        "complete": not missing,
        "scope": "Private recovery archive. Tool executables, secrets and earlier snapshot history are excluded.",
    }
    name = uuid.uuid4().hex + ".json"
    write_json(manifests / name, manifest)
    return manifests / name


def backup_project(workspace, destination, snapshot_file=None, password=None):
    from utils.project_store import private_path, load_project
    from utils.review_workspace import review_lock

    root, destination = private_path(workspace), private_path(destination)
    if password is not None and destination.suffix.lower() != ".porx":
        raise ValueError("Use .porx for an encrypted recovery archive.")
    if password is None and destination.suffix.lower() != ".zip":
        raise ValueError(
            "Use .zip for an unencrypted backup, or supply a passphrase for .porx."
        )
    if destination.exists() or destination.is_relative_to(root):
        raise ValueError("Use a new backup ZIP outside the project folder.")
    with review_lock(root):
        if snapshot_file:
            manifest_path = Path(snapshot_file).resolve()
            if manifest_path.parent != root / ".recovery" / "snapshots":
                raise ValueError(
                    "Choose a snapshot from this project's recovery store."
                )
        else:
            manifest_path = snapshot(root, load_project(root))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Validate all objects before creating the archive.
        hashes = {f["sha256"] for f in manifest["files"]}
        for sha in hashes:
            if (
                not re.fullmatch("[a-f0-9]{64}", sha)
                or digest(root / ".recovery" / "objects" / sha) != sha
            ):
                raise ValueError("Snapshot data is corrupt.")
        from utils.recovery_crypto import MAX_PLAINTEXT, encrypt_archive

        if (
            password is not None
            and sum(f["bytes"] for f in manifest["files"]) > MAX_PLAINTEXT - 1024**2
        ):
            raise ValueError(
                "Encrypted exports support up to 127 MiB of source content. Use protected storage for larger projects."
            )
        buffer = io.BytesIO() if password is not None else None
        with zipfile.ZipFile(
            buffer if buffer is not None else destination,
            "w" if buffer is not None else "x",
            zipfile.ZIP_DEFLATED,
        ) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
            for sha in sorted(hashes):
                archive.write(root / ".recovery" / "objects" / sha, "objects/" + sha)
        if buffer is not None:
            envelope = encrypt_archive(buffer.getvalue(), password)
            # Authenticate and inspect the encrypted representation before writing it.
            from utils.recovery_crypto import decrypt_archive

            inspect_backup(io.BytesIO(decrypt_archive(envelope, password)))
            with destination.open("xb") as stream:
                stream.write(envelope)
    inspect_backup(destination, password)
    return {
        "status": "complete" if manifest["complete"] else "incomplete",
        "files": len(manifest["files"]),
        "missing": len(manifest["missing"]),
        "sha256": digest(destination),
        "encrypted": password is not None,
    }


def _archive_source(path, password=None):
    from utils.recovery_crypto import MAGIC, MAX_ENVELOPE, decrypt_archive

    if hasattr(path, "read"):
        path.seek(0)
        return path
    path = Path(path)
    with path.open("rb") as stream:
        encrypted = stream.read(len(MAGIC)) == MAGIC
    if encrypted:
        if password is None:
            raise ValueError("This archive requires a passphrase.")
        if path.stat().st_size > MAX_ENVELOPE:
            raise ValueError("Encrypted archive exceeds the size limit.")
        return io.BytesIO(decrypt_archive(path.read_bytes(), password))
    if password is not None or path.suffix.lower() == ".porx":
        raise ValueError("This is not a recognised encrypted recovery archive.")
    return path


def inspect_backup(path, password=None):
    try:
        return _inspect_backup(path, password)
    except (
        zipfile.BadZipFile,
        KeyError,
        TypeError,
        UnicodeError,
        OverflowError,
    ) as exc:
        raise ValueError(
            "Invalid recovery archive structure or damaged content."
        ) from exc


def _inspect_backup(path, password=None):
    with zipfile.ZipFile(_archive_source(path, password)) as archive:
        infos = archive.infolist()
        names = [i.filename for i in infos]
        if (
            len(infos) > MAX_FILES + 1
            or len(names) != len(set(names))
            or sum(i.file_size for i in infos) > MAX_BYTES
        ):
            raise ValueError("Invalid or oversized recovery archive.")
        if (
            "manifest.json" not in names
            or archive.getinfo("manifest.json").file_size > 20 * 1024**2
        ):
            raise ValueError("Recovery manifest is missing or oversized.")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("schema") != 1 or manifest.get("project_schema") != 1:
            raise ValueError("Unsupported recovery schema. Original archive retained.")
        entries = manifest["files"]
        if len(entries) > MAX_FILES or sum(f["bytes"] for f in entries) > MAX_BYTES:
            raise ValueError("Recovery expansion exceeds the file or byte budget.")
        originals = [f["original"] for f in entries]
        relatives = [
            f["relative"].casefold() for f in entries if f["relative"] is not None
        ]
        if len(originals) != len(set(originals)) or len(relatives) != len(
            set(relatives)
        ):
            raise ValueError("Duplicate recovery destinations.")
        if sum(f.get("relative") == "project.json" for f in entries) != 1:
            raise ValueError("Exactly one project record is required.")
        expected = {"manifest.json"}
        for f in entries:
            sha = f["sha256"]
            if not re.fullmatch("[a-f0-9]{64}", sha):
                raise ValueError("Invalid content hash.")
            relative = f["relative"]
            if relative is not None:
                p = PurePosixPath(relative)
                if (
                    p.is_absolute()
                    or ".." in p.parts
                    or "\\" in relative
                    or ":" in relative
                    or not p.parts
                    or str(p) != relative
                    or p.parts[0] in SKIP
                ):
                    raise ValueError("Unsafe recovery path.")
                if any(
                    part.endswith((" ", "."))
                    or re.fullmatch(
                        r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part
                    )
                    for part in p.parts
                ):
                    raise ValueError("Unsafe platform-specific recovery path.")
            member = "objects/" + sha
            expected.add(member)
            blob = archive.read(member)
            if len(blob) != f["bytes"] or hashlib.sha256(blob).hexdigest() != sha:
                raise ValueError("Recovery content hash mismatch.")
        if set(names) != expected:
            raise ValueError("Unexpected recovery archive members.")
        project_entry = next(f for f in entries if f["relative"] == "project.json")
        project = json.loads(archive.read("objects/" + project_entry["sha256"]))
        if (
            project.get("schema") != manifest["project_schema"]
            or project.get("mode") != "host_assisted"
            or any(
                not isinstance(project.get(k), list)
                for k in [
                    "sources",
                    "queries",
                    "results",
                    "figures",
                    "events",
                    "searches",
                    "calculations",
                    "topics",
                ]
            )
        ):
            raise ValueError("Invalid project record in recovery archive.")
        return manifest


def restore_project(archive_path, destination, password=None):
    from utils.project_store import private_path

    destination = private_path(destination)
    if destination.exists():
        raise ValueError(
            "Restore requires a new folder; existing projects are preserved."
        )
    manifest = inspect_backup(archive_path, password)
    mapping = {}
    for n, f in enumerate(manifest["files"]):
        # Parse Windows source names consistently when restoring on Linux.
        suffix = PureWindowsPath(f["original"]).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
            suffix = ""
        name = f["relative"] or ("recovered-external/" + str(n) + suffix)
        mapping[f["original"]] = str(destination / name)
    if len({p.casefold() for p in mapping.values()}) != len(mapping):
        raise ValueError("Recovery paths collide.")

    def relocate(value):
        if isinstance(value, dict):
            return {mapping.get(k, k): relocate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [relocate(v) for v in value]
        return mapping.get(value, value) if isinstance(value, str) else value

    archive_hash = digest(archive_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage beside the destination. A failed restore cannot appear as a usable project.
    with tempfile.TemporaryDirectory(
        prefix=".recovery-", dir=destination.parent
    ) as temp:
        stage = Path(temp) / "project"
        stage.mkdir()
        with zipfile.ZipFile(_archive_source(archive_path, password)) as archive:
            for f in manifest["files"]:
                target = stage / Path(mapping[f["original"]]).relative_to(destination)
                blob = archive.read("objects/" + f["sha256"])
                if (
                    len(blob) != f["bytes"]
                    or hashlib.sha256(blob).hexdigest() != f["sha256"]
                ):
                    raise ValueError("Recovery archive changed during restore.")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(blob)
        original = json.loads((stage / "project.json").read_text(encoding="utf-8"))
        data = relocate(deepcopy(original))
        for source in data.get("sources", []):
            for block in source.get("blocks", []):
                if block.get("method") == "local_ocr":
                    block["review_required"] = True
                    source["status"] = "partial"
                    source["warnings"] = sorted(
                        set(source.get("warnings", []) + ["ocr_requires_review"])
                    )
        history = stage / "recovery-original"
        history.mkdir()
        write_json(history / "project.json", original)
        write_json(history / "manifest.json", manifest)
        data.setdefault("events", []).append(
            {
                "kind": "restored",
                "archive_sha256": archive_hash,
                "missing_files": len(manifest["missing"]),
                "note": "Original decisions retained. Location-bound reviews and released-pack checks need fresh review.",
            }
        )
        write_json(stage / "project.json", data)
        if digest(archive_path) != archive_hash or destination.exists():
            raise ValueError("Recovery archive or destination changed during restore.")
        stage.rename(destination)
    return {
        "status": "restored",
        "files": len(manifest["files"]),
        "missing": len(manifest["missing"]),
        "review_required": "Check relocated figures, OCR previews and pack visual reviews.",
    }
