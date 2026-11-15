from pathlib import Path
from tools.check_build_pins import findings


def test_real_repository_pins():
    assert not findings(Path(__file__).resolve().parents[1])


def test_unpinned_fixture_is_rejected(tmp_path):
    (tmp_path / "requirements-lock.txt").write_text("example>=1\n")
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "test.yml").write_text(
        "jobs:\n  check:\n    steps:\n      - uses: actions/checkout@v4\n"
    )
    assert len(findings(tmp_path)) == 2


def test_floating_reusable_workflow_in_yaml_is_rejected(tmp_path):
    (tmp_path / "requirements-lock.txt").write_text("example==1.0\n")
    folder = tmp_path / ".github" / "workflows"
    folder.mkdir(parents=True)
    (folder / "test.yaml").write_text(
        "jobs:\n  check:\n    uses: example/repo/.github/workflows/check.yml@main\n"
    )
    assert findings(tmp_path) == ["Unpinned action in test.yaml"]
