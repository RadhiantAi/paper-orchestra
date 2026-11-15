from streamlit.testing.v1 import AppTest
from utils.project_store import create_project, load_project
from utils.project_review import import_host, query_status


def test_project_queries_are_recorded_without_clearing_conditions(tmp_path):
    create_project(tmp_path)
    import_host(
        tmp_path,
        {
            "schema": 1,
            "mode": "host_assisted",
            "host": "Fixture",
            "queries": [
                {
                    "id": "caption",
                    "owner": "Author",
                    "target": "manuscript",
                    "quote": "A caption.",
                    "question": "Confirm only if unchanged.",
                    "conditions": [
                        {
                            "id": "same",
                            "kind": "exact_text_match",
                            "description": "Same as original.",
                        }
                    ],
                }
            ],
        },
    )
    app = AppTest.from_string(
        "from frontend.project_review import render_project\nrender_project("
        + repr(str(tmp_path))
        + ")"
    ).run(timeout=15)
    assert not app.exception
    next(x for x in app.text_input if x.label == "Reviewer").set_value("Author")
    next(x for x in app.text_area if x.label == "Reason").set_value(
        "Yes, if identical."
    )
    next(x for x in app.selectbox if x.label == "Decision").select("confirm")
    next(x for x in app.button if x.label == "Record author decision").click().run()
    assert not app.exception
    data = load_project(tmp_path)
    assert query_status(data["queries"][0], data["sources"]) == "conditional_pending"


def test_ui_resolves_exact_proof_and_approves_selected_result(tmp_path):
    from utils.project_results import approved

    create_project(tmp_path)
    import_host(
        tmp_path,
        {
            "schema": 1,
            "mode": "host_assisted",
            "host": "Fixture",
            "sources": [
                {
                    "id": "s",
                    "origin": "fixture",
                    "sha256": "a" * 64,
                    "status": "read",
                    "blocks": [{"locator": "page:1", "text": "Exact caption."}],
                }
            ],
            "queries": [
                {
                    "id": "q",
                    "owner": "Reviewer",
                    "target": "manuscript",
                    "question": "Confirm unchanged",
                    "quote": "Exact caption.",
                    "conditions": [
                        {
                            "id": "same",
                            "kind": "exact_text_match",
                            "description": "Exact match",
                        }
                    ],
                }
            ],
            "results": [
                {
                    "id": "r",
                    "label": "Synthetic",
                    "definition": "Test",
                    "source": "Fixture",
                    "method": "Count",
                    "count": 1,
                    "denominator": 2,
                }
            ],
        },
    )
    app = AppTest.from_string(
        "from frontend.project_review import render_project\nrender_project("
        + repr(str(tmp_path))
        + ")"
    ).run(timeout=15)
    assert not app.exception
    next(x for x in app.selectbox if x.label == "Supporting passage: same").select(
        0
    ).run(timeout=15)
    next(x for x in app.text_input if x.label == "Reviewer").set_value("Reviewer")
    next(x for x in app.text_area if x.label == "Reason").set_value(
        "Compared exact original"
    )
    next(x for x in app.selectbox if x.label == "Decision").select("confirm")
    next(x for x in app.button if x.label == "Record author decision").click().run(
        timeout=15
    )
    assert not app.exception
    data = load_project(tmp_path)
    assert query_status(data["queries"][0], data["sources"]) == "resolved"
    next(x for x in app.multiselect if x.label == "Results to approve").select("r")
    next(x for x in app.text_input if x.label == "Result reviewer").set_value(
        "Reviewer"
    )
    next(x for x in app.text_area if x.label == "Result approval reason").set_value(
        "Checked synthetic count"
    )
    next(x for x in app.button if x.label == "Approve selected results").click().run(
        timeout=15
    )
    assert not app.exception and approved(load_project(tmp_path)["results"][0])


def test_ui_builds_checks_and_releases_synthetic_pack(tmp_path, monkeypatch):
    from test_project_workflow import pack_fixture
    import zipfile

    workspace = tmp_path / "project"
    create_project(workspace)
    spec = pack_fixture(workspace, tmp_path, monkeypatch)
    app = AppTest.from_string(
        "from frontend.project_review import render_project\nrender_project("
        + repr(str(workspace))
        + ")"
    ).run(timeout=15)
    next(x for x in app.text_input if x.label == "Manuscript Word file").set_value(
        spec["files"][0]["path"]
    )
    next(
        x for x in app.text_input if x.label == "Approved title page Word file"
    ).set_value(spec["files"][1]["path"])
    next(
        x
        for x in app.text_input
        if x.label == "Exact sentence or table text for region"
    ).set_value("Synthetic region: {{result:region:pair}}.")
    next(x for x in app.button if x.label == "Build Word and PDF pack").click().run(
        timeout=20
    )
    assert not app.exception and not app.error
    next(x for x in app.button if x.label == "Create checked ZIP").click().run(
        timeout=15
    )
    assert app.error and not (workspace / "review-v1.zip").exists()
    next(x for x in app.text_input if x.label == "Visual reviewer").set_value(
        "Synthetic reviewer"
    )
    next(
        x
        for x in app.text_area
        if x.label == "What you inspected in the Word and PDF files"
    ).set_value("Compared synthetic fixture text and layout")
    next(x for x in app.button if x.label == "Record visual review").click().run(
        timeout=15
    )
    assert not app.exception and not app.error
    next(x for x in app.button if x.label == "Create checked ZIP").click().run(
        timeout=15
    )
    assert not app.exception and not app.error
    with zipfile.ZipFile(workspace / "review-v1.zip") as z:
        assert z.testzip() is None and "Manuscript.docx" in z.namelist()


def test_project_chooser_creates_and_opens_private_project(tmp_path):
    app = AppTest.from_string(
        "from frontend.project_home import project_home\nproject_home()"
    ).run(timeout=15)
    next(x for x in app.text_input if x.label == "Projects folder").set_value(
        str(tmp_path)
    )
    next(x for x in app.text_input if x.label == "New project name").set_value(
        "Synthetic project"
    )
    next(x for x in app.button if x.label == "Create and open project").click().run(
        timeout=15
    )
    assert (
        not app.exception and (tmp_path / "Synthetic project" / "project.json").exists()
    )
    assert app.session_state["workspace"] == str(tmp_path / "Synthetic project")


def test_file_picker_and_recovery_export_in_interface(tmp_path):
    from docx import Document
    from utils.project_sources import index_sources
    from utils.project_recovery import inspect_backup

    w = tmp_path / "project"
    create_project(w)
    doc = Document()
    doc.add_paragraph("Synthetic source")
    source = tmp_path / "source.docx"
    doc.save(source)
    index_sources(w, [source])
    app = AppTest.from_string(
        "from frontend.project_review import render_project\nrender_project("
        + repr(str(w))
        + ")"
    ).run(timeout=15)
    app.selectbox(key="pack_manuscript_choice").select(str(source)).run(timeout=15)
    app.button(key="pack_manuscript_use").click().run(timeout=15)
    assert not app.exception and app.text_input(key="pack_manuscript").value == str(
        source
    )
    next(x for x in app.button if x.label == "Create checked recovery ZIP").click().run(
        timeout=15
    )
    assert not app.exception and not app.error
    assert inspect_backup(tmp_path / "project-recovery.zip")["complete"]
