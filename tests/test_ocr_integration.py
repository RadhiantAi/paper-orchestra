"""Real local OCR on generated text only, without model or retrieval calls."""

import os
import shutil

import pytest
from PIL import Image, ImageDraw, ImageFont
from utils.project_store import create_project, load_project
from utils.project_sources import index_sources
from utils.source_recovery import recover_ocr, confirm_ocr


@pytest.mark.skipif(
    os.getenv("RUN_OCR_INTEGRATION") != "1",
    reason="Real Tesseract integration runs in the OCR CI job",
)
def test_real_local_ocr(tmp_path, monkeypatch):
    monkeypatch.setenv("PAPER_NETWORK_MODE", "offline")
    executable = shutil.which("tesseract")
    assert executable, "The OCR integration job must install Tesseract"
    image = Image.new("RGB", (1500, 220), "white")
    ImageDraw.Draw(image).text(
        (30, 70),
        "SYNTHETIC RESEARCH 12345",
        fill="black",
        font=ImageFont.load_default(size=60),
    )
    scan = tmp_path / "synthetic.png"
    image.save(scan, dpi=(300, 300))
    workspace = tmp_path / "project"
    create_project(workspace)
    index_sources(workspace, [scan])
    sid = load_project(workspace)["sources"][0]["id"]
    recover_ocr(workspace, sid, executable)
    block = next(
        b
        for b in load_project(workspace)["sources"][0]["blocks"]
        if b.get("method") == "local_ocr"
    )
    assert "SYNTHETIC RESEARCH 12345" in block["text"]
    assert block["review_required"]
    confirm_ocr(
        workspace,
        sid,
        block["locator"],
        "Synthetic reviewer",
        "Compared generated image",
    )
    assert not next(
        b
        for b in load_project(workspace)["sources"][0]["blocks"]
        if b.get("method") == "local_ocr"
    )["review_required"]
