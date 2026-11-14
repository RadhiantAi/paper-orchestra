"""Mark generated PDFs as drafts without changing the LaTeX source."""

import pymupdf


DRAFT_LABEL = "DRAFT - Human review required"


def mark_pdf_as_draft(pdf_path):
    """Add a visible margin label on every page, preserving page content."""
    with pymupdf.open(pdf_path) as document:
        for page in document:
            page.insert_text((12, 12), DRAFT_LABEL, fontsize=8, color=(0.7, 0, 0))
        metadata = document.metadata
        metadata["subject"] = DRAFT_LABEL
        document.set_metadata(metadata)
        document.saveIncr()
