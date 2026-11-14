from streamlit.testing.v1 import AppTest
from pathlib import Path


def test_demo_opens_without_provider_credentials_and_blocks_unconfigured_run():
    app = AppTest.from_file(
        Path(__file__).resolve().parents[1] / "frontend/app.py"
    ).run(timeout=30)
    assert not app.exception
    labels = {item.label for item in app.sidebar.text_input}
    assert "Writer model" in labels
    assert "Review model (blank uses writer)" in labels
    assert "Literature ranking model (blank uses writer)" in labels
    assert "Email" not in labels
    plotting = next(
        item
        for item in app.sidebar.selectbox
        if item.label == "Enable Figure Generation"
    )
    assert plotting.options == ["No"]
    assert plotting.disabled
    next(
        button for button in app.button if "Begin Writing" in button.label
    ).click().run()
    assert not app.exception
    assert any("PAPER_WRITER_MODEL" in error.value for error in app.error)
