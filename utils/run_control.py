"""Versioned workspaces and hash-checked stage checkpoints."""

from datetime import datetime, timezone
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import shutil
import uuid


def write_json(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    temporary.replace(path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree_hash(root):
    root = Path(root)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("Input symlinks are not supported.")
        if path.is_file():
            result[str(path.relative_to(root))] = digest(path)
    return result


class RunWorkspace:
    def __init__(self, base, template, settings, resume=None, raw_source=None):
        base = Path(base).resolve()
        raw = Path(raw_source).resolve() if raw_source else base / "raw_materials"
        if not raw.is_dir() or not Path(template).is_dir():
            raise ValueError("Raw materials and template directories must exist.")
        identity = {
            "version": 2,
            "inputs": tree_hash(raw),
            "template": tree_hash(template),
            "settings": settings,
        }
        # A source edit invalidates checkpoints even before a new Git commit.
        repo = Path(__file__).resolve().parents[1]
        identity["code"] = {
            str(p.relative_to(repo)): digest(p)
            for folder in ("utils", "methods", "autoraters")
            for p in sorted((repo / folder).rglob("*.py"))
        }
        fingerprint = hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode()
        ).hexdigest()
        if resume:
            self.path = Path(resume).resolve()
            if not self.path.is_relative_to(base / "runs"):
                raise ValueError(
                    "Resume path must be inside this project's runs directory."
                )
            self.manifest = json.loads(
                (self.path / "run_manifest.json").read_text(encoding="utf-8")
            )
            if self.manifest["fingerprint"] != fingerprint:
                raise ValueError(
                    "Inputs, configuration or code changed. Start a new run; the previous draft is preserved."
                )
        else:
            name = (
                datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                + "-"
                + uuid.uuid4().hex[:8]
            )
            self.path = base / "runs" / name
            self.path.mkdir(parents=True)
            shutil.copytree(raw, self.path / "raw_materials")
            shutil.copytree(template, self.path / "template_inputs")
            self.manifest = {
                "fingerprint": fingerprint,
                "identity": identity,
                "stages": {},
                "status": "created",
            }
            self.save()
        self.verify()
        write_json(base / "latest_run.json", {"run_directory": str(self.path)})

    def save(self):
        write_json(self.path / "run_manifest.json", self.manifest)

    def verify(self):
        for folder, expected in (
            ("raw_materials", self.manifest["identity"]["inputs"]),
            ("template_inputs", self.manifest["identity"]["template"]),
        ):
            if tree_hash(self.path / folder) != expected:
                raise ValueError(
                    "The saved run inputs were edited. Start a new run to preserve edits."
                )
        for stage, receipt in self.manifest["stages"].items():
            for name, expected in receipt.items():
                path = self.path / name
                if not path.is_file() or digest(path) != expected:
                    raise ValueError(
                        f"Completed stage '{stage}' was edited or is incomplete. Start a new run to preserve edits."
                    )

    @contextmanager
    def lock(self):
        import os

        with (self.path / ".execution.lock").open("a+b") as stream:
            stream.write(b"0")
            stream.flush()
            stream.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise RuntimeError(
                    "This run is already executing in another process."
                ) from None
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def stage(self, name, action, outputs):
        if name in self.manifest["stages"]:
            self.verify()
            return
        self.manifest.update(status="running", current_stage=name)
        self.save()
        action()
        receipt = {}
        for relative in outputs:
            target = self.path / relative
            paths = sorted(target.rglob("*")) if target.is_dir() else [target]
            for path in paths:
                if path.is_file():
                    receipt[str(path.relative_to(self.path))] = digest(path)
            if not target.exists():
                raise RuntimeError(
                    f"Stage '{name}' did not produce its required output."
                )
        self.manifest["stages"][name] = receipt
        self.save()


def artifact_root(base):
    """Resolve the latest output for UI display, without accepting external paths."""
    base = Path(base).resolve()
    pointer = base / "latest_run.json"
    if pointer.is_file():
        path = Path(
            json.loads(pointer.read_text(encoding="utf-8"))["run_directory"]
        ).resolve()
        if path.is_relative_to(base / "runs"):
            return path
    return base
