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
    ).run()
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
