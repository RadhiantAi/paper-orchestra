import json

from streamlit.testing.v1 import AppTest


def test_evidence_and_revision_controls_persist(tmp_path):
    (tmp_path / "evidence_review.json").write_text(json.dumps({"claims": [{"claim_context": "20 (40%)", "candidate_passage": "20 of 80", "source_url": "https://example.org/study"}]}))
    (tmp_path / "manuscript_sections.json").write_text(json.dumps({"Results": {"text": "20 (40%).", "approval": None}, "Introduction": {"text": "Keep this section.", "approval": "Reviewer"}}))
    app = AppTest.from_string(
        "from frontend.research_review import render_review\nrender_review(" + repr(str(tmp_path)) + ")"
    ).run()
    assert not app.exception
    next(x for x in app.text_input if x.label == "Reviewer").set_value("Researcher")
    next(x for x in app.text_area if x.label == "Reason").set_value("Incorrect denominator")
    next(x for x in app.button if x.label == "Save decision").click().run()
    assert json.loads((tmp_path / "review_decisions.json").read_text())[0]["decision"] == "flag"
    next(x for x in app.text_area if x.label == "Proposed replacement").set_value("20 (25%).")
    next(x for x in app.text_input if x.label == "Reason for revision").set_value("Correct denominator")
    next(x for x in app.text_input if x.label == "Reviewer accepting this revision").set_value("Researcher")
    next(x for x in app.button if x.label == "Preview revision").click().run()
    next(x for x in app.button if x.label == "Accept this revision").click().run()
    assert not app.exception
    sections = json.loads((tmp_path / "manuscript_sections.json").read_text())
    assert sections["Results"]["text"] == "20 (25%)."
    assert sections["Introduction"]["approval"] == "Reviewer"
