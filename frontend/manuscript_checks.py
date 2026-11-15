"""Researcher-defined completeness and panel location controls."""

import streamlit as st


def pack_quality_controls(data):
    profile, mappings = None, []
    with st.expander("Manuscript completeness expectations"):
        st.caption(
            "Choose expectations for this article type. Word counts and covered passages do not certify scientific quality. Unselected expectations remain a pending check."
        )
        enabled = st.checkbox("Apply agreed manuscript expectations")
        minimum = st.number_input(
            "Minimum discussion words", min_value=0, max_value=100000, value=0
        )
        references = st.number_input(
            "Minimum numbered references", min_value=0, max_value=10000, value=0
        )
        who = st.text_input("Expectations reviewer")
        reason = st.text_input("Reason for these article expectations")
        passages = st.text_area(
            "Expected discussion passages (topic | exact passage per line)"
        )
        if enabled:
            profile = {
                "schema": 1,
                "reviewer": who,
                "reason": reason,
                "section_min_words": {"Discussion": int(minimum)},
                "minimum_references": int(references),
                "discussion_passages": [
                    {
                        "topic": line.partition("|")[0].strip(),
                        "quote": line.partition("|")[2].strip(),
                    }
                    for line in passages.splitlines()
                    if line.strip()
                ],
            }
    with st.expander("Check each panel in its Word document and PDF"):
        st.caption(
            "Use the image-locations report to identify Word paragraph numbers, including table paragraphs. Use zero to leave a location unresolved. Review the rendered pages as well."
        )
        for figure in data["figures"]:
            for panel in figure["panels"]:
                key = figure["id"] + ":" + panel["label"]
                document = st.selectbox(
                    "Document for " + key,
                    ["Manuscript", "Figures"],
                    key="placement_doc_" + key,
                )
                paragraph = st.number_input(
                    "Word paragraph for " + key,
                    min_value=0,
                    value=0,
                    key="placement_word_" + key,
                )
                page = st.number_input(
                    "PDF page for " + key,
                    min_value=0,
                    value=0,
                    key="placement_pdf_" + key,
                )
                for suffix, value, location in [
                    ("docx", paragraph, f"body:paragraph:{int(paragraph)}"),
                    ("pdf", page, f"page:{int(page)}"),
                ]:
                    if value:
                        mappings.append(
                            {
                                "figure_id": figure["id"],
                                "panel": panel["label"],
                                "document": document + "." + suffix,
                                "location": location,
                            }
                        )
    return profile, mappings
