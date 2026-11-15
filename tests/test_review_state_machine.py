"""Generated sequences check approvals across imports and source changes."""

import tempfile
from pathlib import Path
from hypothesis import settings, strategies as st
from hypothesis.stateful import RuleBasedStateMachine, rule, invariant
from utils.project_store import create_project, load_project
from utils.project_review import import_host, decide_query, query_status
from utils.project_results import approve_results, approved, render_results
from utils.research_quality import fingerprint


class ReviewSequence(RuleBasedStateMachine):
    def __init__(self):
        super().__init__()
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        create_project(self.path)
        self.source_version = 0
        self.query_version = 0
        self.confirmed_at = None
        self.row = None
        self._source()
        self._query()

    def _source(self):
        self.sha = fingerprint(self.source_version)
        import_host(
            self.path,
            {
                "schema": 1,
                "mode": "host_assisted",
                "host": "Synthetic",
                "sources": [
                    {
                        "id": "source",
                        "sha256": self.sha,
                        "origin": "fixture",
                        "status": "read",
                        "blocks": [{"locator": "page:1", "text": "Verified phrase"}],
                    }
                ],
            },
        )

    def _query(self):
        import_host(
            self.path,
            {
                "schema": 1,
                "mode": "host_assisted",
                "host": "Synthetic",
                "queries": [
                    {
                        "id": "q",
                        "owner": "Reviewer",
                        "target": "manuscript",
                        "question": "Confirm " + str(self.query_version),
                        "quote": "Verified phrase",
                        "evidence": [
                            {
                                "source_id": "source",
                                "source_sha256": self.sha,
                                "locator": "page:1",
                                "quote": "Verified phrase",
                            }
                        ],
                    }
                ],
            },
        )

    @rule()
    def confirm(self):
        decide_query(self.path, "q", "Reviewer", "Confirmed fixture")
        # A stale question cannot be cleared by clicking confirm again.
        data = load_project(self.path)
        if data["queries"][0]["evidence"][0]["source_sha256"] == self.sha:
            self.confirmed_at = (self.source_version, self.query_version)

    @rule()
    def change_source(self):
        self.source_version += 1
        self._source()

    @rule()
    def change_question(self):
        self.query_version += 1
        self._query()
        self.confirmed_at = None

    @rule()
    def flag(self):
        decide_query(self.path, "q", "Reviewer", "Needs review", "flag")
        self.confirmed_at = None

    @rule(count=st.integers(min_value=0, max_value=20))
    def change_result(self, count):
        if self.row is None:
            self.row = {
                "id": "r",
                "label": "Synthetic",
                "definition": "Test",
                "source": "Fixture",
                "method": "Count",
                "count": count,
                "denominator": 20,
            }
        else:
            self.row["count"] = count

    @rule()
    def approve_result(self):
        if self.row:
            approve_results([self.row], "Reviewer", "Checked")

    @invariant()
    def approvals_never_survive_changed_evidence(self):
        data = load_project(self.path)
        status = query_status(data["queries"][0], data["sources"])
        if status == "resolved":
            assert self.confirmed_at == (self.source_version, self.query_version)
        if self.row:
            if approved(self.row):
                assert render_results("{{result:r:count}}", [self.row]) == str(
                    self.row["count"]
                )
            else:
                try:
                    render_results("{{result:r:count}}", [self.row])
                except ValueError:
                    pass
                else:
                    raise AssertionError("Unapproved result rendered")

    def teardown(self):
        self.temp.cleanup()


TestReviewSequence = ReviewSequence.TestCase
TestReviewSequence.settings = settings(
    max_examples=30, stateful_step_count=35, deadline=None, derandomize=True
)


class PackSequence(RuleBasedStateMachine):
    """Release, edit, recheck and rebuild sequences preserve the approval boundary."""

    def __init__(self):
        import pytest
        from test_project_workflow import pack_fixture
        from utils.project_pack import prepare_pack

        super().__init__()
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "workspace"
        create_project(self.workspace)
        self.patch = pytest.MonkeyPatch()
        self.spec = pack_fixture(self.workspace, self.root, self.patch)
        self.version = 0
        self.exports = 0
        self.reviewed = False
        self.changed = False
        self.pack = self.root / "pack0"
        prepare_pack(self.workspace, self.spec, self.pack)

    @rule()
    def review(self):
        from utils.project_pack import record_visual_review

        if not self.changed:
            record_visual_review(
                self.workspace,
                self.pack,
                "Reviewer",
                "Synthetic rendered fixture checked",
            )
            self.reviewed = True

    @rule()
    def change_title(self):
        from docx import Document

        doc = Document(self.pack / "title.docx")
        doc.paragraphs[0].text = "Changed author"
        doc.save(self.pack / "title.docx")
        self.changed = True

    @rule()
    def rebuild(self):
        from utils.project_pack import prepare_pack

        self.version += 1
        self.pack = self.root / ("pack" + str(self.version))
        prepare_pack(self.workspace, self.spec, self.pack)
        self.reviewed = False
        self.changed = False

    @rule()
    def release(self):
        import pytest
        import zipfile
        from utils.project_pack import release_pack

        self.exports += 1
        dest = self.root / ("review" + str(self.exports) + ".zip")
        if self.reviewed and not self.changed:
            receipt = release_pack(self.workspace, self.pack, dest)
            assert receipt["sent"] is False
            with zipfile.ZipFile(dest) as z:
                assert z.testzip() is None
        else:
            with pytest.raises((ValueError, FileNotFoundError)):
                release_pack(self.workspace, self.pack, dest)
            assert not dest.exists()

    def teardown(self):
        self.patch.undo()
        self.temp.cleanup()


TestPackSequence = PackSequence.TestCase
TestPackSequence.settings = settings(
    max_examples=12, stateful_step_count=12, deadline=None, derandomize=True
)
