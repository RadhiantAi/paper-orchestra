import json
from datetime import datetime, timedelta, timezone

import pytest
from utils.project_store import create_project, load_project, update_project
from utils.project_recovery import backup_project, restore_project, inspect_backup
from utils.recovery_storage import retention_preview
from utils.run_control import digest

PASSWORD = "Synthetic test phrase only 123!"


def project(tmp_path):
    root = tmp_path / "project"
    create_project(root)
    (root / "private-source.txt").write_text(
        "Distinctive synthetic private manuscript content."
    )
    update_project(root, lambda d: d.update(marker="old"))
    update_project(root, lambda d: d.update(marker="new"))
    return root


def test_encrypted_roundtrip_hides_names_and_preserves_history(tmp_path):
    root = project(tmp_path)
    path = tmp_path / "private.porx"
    report = backup_project(root, path, password=PASSWORD)
    assert report["encrypted"] and report["status"] == "complete"
    blob = path.read_bytes()
    assert b"private-source.txt" not in blob and b"Distinctive synthetic" not in blob
    assert b"project.json" not in blob and PASSWORD.encode() not in blob
    assert not list(tmp_path.glob("*.zip"))
    assert inspect_backup(path, PASSWORD)["complete"]
    restored = tmp_path / "restored"
    restore_project(path, restored, PASSWORD)
    assert load_project(restored)["marker"] == "new"
    assert (restored / "private-source.txt").read_bytes() == (
        root / "private-source.txt"
    ).read_bytes()
    assert PASSWORD not in (restored / "project.json").read_text()
    second = tmp_path / "second.porx"
    backup_project(root, second, password=PASSWORD)
    assert second.read_bytes() != blob


@pytest.mark.parametrize(
    "defect",
    ["wrong_password", "missing_password", "header", "ciphertext", "truncated"],
)
def test_encrypted_damage_and_wrong_password_fail_before_restore(tmp_path, defect):
    root = project(tmp_path)
    path = tmp_path / "private.porx"
    backup_project(root, path, password=PASSWORD)
    password = PASSWORD
    if defect == "wrong_password":
        password = "Wrong synthetic passphrase"
    elif defect == "missing_password":
        password = None
    else:
        blob = bytearray(path.read_bytes())
        if defect == "truncated":
            blob = blob[:25]
        else:
            blob[0 if defect == "header" else -20] ^= 1
        path.write_bytes(blob)
    with pytest.raises(ValueError):
        restore_project(path, tmp_path / "bad", password)
    assert not (tmp_path / "bad").exists()
    assert not list(tmp_path.glob(".recovery-*"))


def test_encryption_rejects_weak_password_wrong_suffix_and_oversize(
    tmp_path, monkeypatch
):
    from utils import recovery_crypto

    root = project(tmp_path)
    with pytest.raises(ValueError, match="passphrase"):
        backup_project(root, tmp_path / "weak.porx", password="short")
    assert not (tmp_path / "weak.porx").exists()
    with pytest.raises(ValueError, match=".porx"):
        backup_project(root, tmp_path / "wrong.zip", password=PASSWORD)
    monkeypatch.setattr(recovery_crypto, "MAX_PLAINTEXT", 1024)
    with pytest.raises(ValueError, match="127 MiB"):
        backup_project(root, tmp_path / "large.porx", password=PASSWORD)
    assert not (tmp_path / "large.porx").exists()


def test_retention_preview_preserves_shared_objects_current_receipts_and_all_files(
    tmp_path,
):
    root = project(tmp_path)
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    for index, path in enumerate(sorted((root / ".recovery/snapshots").glob("*.json"))):
        manifest = json.loads(path.read_text())
        manifest["created_at"] = (now - timedelta(days=100 + index)).isoformat()
        path.write_text(json.dumps(manifest))
    before = {str(p): digest(p) for p in root.rglob("*") if p.is_file()}
    report = retention_preview(
        root, keep_latest=1, keep_days=0, budget_bytes=1, reserve_bytes=2**63, now=now
    )
    assert report["status"] == "preview_only" and not report["deletion_performed"]
    assert report["candidate_snapshots"] and report["estimated_reclaimable_bytes"] > 0
    assert len(report["storage"]["warnings"]) == 2
    manifests = [
        (p, json.loads(p.read_text()))
        for p in (root / ".recovery/snapshots").glob("*.json")
    ]
    retained = [
        m
        for p, m in manifests
        if p.name not in {s["name"] for s in report["candidate_snapshots"]}
    ]
    shared = {f["sha256"] for m in retained for f in m["files"]}
    assert not shared.intersection(report["candidate_objects"])
    assert before == {str(p): digest(p) for p in root.rglob("*") if p.is_file()}
    fresh = retention_preview(root, keep_latest=1, keep_days=365, now=now)
    assert not fresh["candidate_snapshots"] and not fresh["candidate_objects"]


def test_malformed_snapshot_blocks_cleanup_estimate_and_policy_is_bounded(tmp_path):
    root = project(tmp_path)
    (root / ".recovery/snapshots/broken.json").write_text("bad")
    report = retention_preview(root, keep_latest=1, keep_days=0)
    assert report["status"] == "blocked" and report["problems"]
    assert (
        not report["candidate_snapshots"] and report["estimated_reclaimable_bytes"] == 0
    )
    with pytest.raises(ValueError):
        retention_preview(root, keep_latest=0)


def test_damaged_plain_archive_has_a_controlled_error(tmp_path):
    path = tmp_path / "broken.zip"
    path.write_bytes(b"not a ZIP file")
    with pytest.raises(ValueError, match="Invalid recovery archive"):
        restore_project(path, tmp_path / "restored")
    assert not (tmp_path / "restored").exists()


def test_encrypted_cli_prompts_without_accepting_password_argument(
    tmp_path, monkeypatch, capsys
):
    import getpass
    from research_project_cli import main

    root = project(tmp_path)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: PASSWORD)
    path = tmp_path / "cli.porx"
    main(["--workspace", str(root), "backup", "--output", str(path), "--encrypt"])
    main(["--workspace", str(tmp_path / "restored"), "restore", str(path)])
    assert load_project(tmp_path / "restored")["marker"] == "new"
    assert PASSWORD not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(
            [
                "--workspace",
                str(root),
                "backup",
                "--output",
                str(path),
                "--password",
                PASSWORD,
            ]
        )
