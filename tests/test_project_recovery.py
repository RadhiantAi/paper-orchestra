import json
import zipfile
import pytest
from utils.project_store import (
    create_project,
    load_project,
    update_project,
    current_file,
)
from utils.project_sources import index_sources
from utils.project_recovery import backup_project, restore_project


def test_portable_recovery_preserves_files_decisions_and_detects_changes(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    source = tmp_path / "source.txt"
    source.write_text("Synthetic original")
    index_sources(w, [source])
    update_project(w, lambda d: d.update(test_decision="Retain original"))
    (w / "result.txt").write_text("Synthetic output")
    backup = tmp_path / "private.zip"
    assert backup_project(w, backup)["status"] == "complete"
    source.unlink()
    restored = tmp_path / "restored"
    restore_project(backup, restored)
    data = load_project(restored)
    assert data["test_decision"] == "Retain original" and current_file(
        data["sources"][0]
    )
    assert (restored / "result.txt").read_text() == "Synthetic output"
    assert (restored / "recovery-original" / "project.json").exists()
    assert list((w / ".recovery" / "snapshots").glob("*.json"))
    assert (
        backup_project(restored, tmp_path / "second-backup.zip")["status"] == "complete"
    )
    restore_project(tmp_path / "second-backup.zip", tmp_path / "second-restore")
    assert current_file(load_project(tmp_path / "second-restore")["sources"][0])
    with pytest.raises(ValueError):
        restore_project(backup, restored)


def test_snapshot_can_recover_previous_state_and_missing_inputs_are_explicit(tmp_path):
    w = tmp_path / "project"
    create_project(w)
    source = tmp_path / "source.txt"
    source.write_text("Synthetic")
    index_sources(w, [source])
    update_project(w, lambda d: d.update(marker="previous"))
    update_project(w, lambda d: d.update(marker="changed"))
    snapshots = list((w / ".recovery" / "snapshots").glob("*.json"))
    previous = next(
        p
        for p in snapshots
        if any(
            f["relative"] == "project.json"
            and json.loads((w / ".recovery" / "objects" / f["sha256"]).read_text()).get(
                "marker"
            )
            == "previous"
            for f in json.loads(p.read_text())["files"]
        )
    )
    backup_project(w, tmp_path / "previous.zip", previous)
    restore_project(tmp_path / "previous.zip", tmp_path / "previous")
    assert load_project(tmp_path / "previous")["marker"] == "previous"
    source.unlink()
    assert backup_project(w, tmp_path / "missing.zip")["status"] == "incomplete"


@pytest.mark.parametrize(
    "change", ["hash", "traversal", "extra", "schema", "alias", "reserved"]
)
def test_hostile_backups_fail_before_restore(tmp_path, change):
    w = tmp_path / "project"
    create_project(w)
    backup_project(w, tmp_path / "good.zip")
    with zipfile.ZipFile(tmp_path / "good.zip") as z:
        members = {n: z.read(n) for n in z.namelist()}
    m = json.loads(members["manifest.json"])
    if change == "hash":
        members[next(n for n in members if n.startswith("objects/"))] = b"corrupt"
    if change == "traversal":
        m["files"][0]["relative"] = "../escape.json"
    if change == "alias":
        m["files"].append(
            dict(m["files"][0], original="alias", relative="folder//alias.json")
        )
    if change == "reserved":
        m["files"].append(dict(m["files"][0], original="alias", relative="CON.txt"))
    if change == "schema":
        m["schema"] = 99
    if change == "extra":
        members["unexpected.txt"] = b"bad"
    members["manifest.json"] = json.dumps(m).encode()
    with zipfile.ZipFile(tmp_path / "bad.zip", "w") as z:
        for n, b in members.items():
            z.writestr(n, b)
    with pytest.raises(ValueError):
        restore_project(tmp_path / "bad.zip", tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_unsupported_project_schema_and_corrupt_store_preserve_live_data(tmp_path):
    from utils.project_recovery import snapshot

    w = tmp_path / "project"
    create_project(w)
    manifest_path = snapshot(w, load_project(w))
    manifest = json.loads(manifest_path.read_text())
    entry = next(f for f in manifest["files"] if f["relative"] == "project.json")
    (w / ".recovery" / "objects" / entry["sha256"]).write_bytes(b"corrupt")
    before = (w / "project.json").read_bytes()
    with pytest.raises(ValueError, match="corrupt"):
        update_project(w, lambda d: d.update(marker="bad"))
    assert (w / "project.json").read_bytes() == before


def test_failed_staged_restore_leaves_no_project(tmp_path, monkeypatch):
    import utils.project_recovery as recovery

    w = tmp_path / "project"
    create_project(w)
    backup_project(w, tmp_path / "good.zip")

    def fail_write(*args):
        raise OSError("Synthetic interrupted write")

    monkeypatch.setattr(recovery, "write_json", fail_write)
    with pytest.raises(OSError, match="interrupted"):
        restore_project(tmp_path / "good.zip", tmp_path / "restored")
    assert not (tmp_path / "restored").exists()
    assert not list(tmp_path.glob(".recovery-*"))
