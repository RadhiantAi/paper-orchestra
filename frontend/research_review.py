"""Human evidence decisions and section revision controls, shared by both apps."""

import json
from pathlib import Path

import streamlit as st

from utils.review_workspace import (
    current_decision,
    propose_revision,
    save_decision,
    save_revision,
)


def render_review(directory):
    root = Path(directory)
    st.subheader("Evidence review")
    ledger = root / "evidence_review.json"
    if ledger.exists():
        ledger_data = json.loads(ledger.read_text(encoding="utf-8"))
        stale = ledger_data.get("status") == "stale_after_revision"
        if stale:
            st.warning(
                "The manuscript changed. Regenerate the evidence ledger before recording further decisions."
            )
        claims = [] if stale else ledger_data.get("claims", [])
        decisions_path = root / "review_decisions.json"
        decisions = (
            json.loads(decisions_path.read_text(encoding="utf-8"))
            if decisions_path.exists()
            else []
        )
        st.caption(
            "Accepting records your assessment of this exact claim and evidence. Any change makes the decision stale."
        )
        for index, claim in enumerate(claims):
            with st.expander(
                f"Claim {index + 1}: {claim.get('status', 'needs_review')}"
            ):
                st.text(claim.get("claim_context", ""))
                st.text(
                    claim.get("candidate_passage") or "No source passage available."
                )
                st.text("Location: " + str(claim.get("passage_origin", "unknown")))
                st.text("Source: " + str(claim.get("source_url", "unknown")))
                existing = current_decision(claim, decisions)
                if existing:
                    st.json(existing)
                with st.form(f"evidence_{index}"):
                    reviewer = st.text_input("Reviewer", key=f"reviewer_{index}")
                    decision = st.selectbox(
                        "Decision",
                        ["flag", "accept", "reject"],
                        key=f"decision_{index}",
                    )
                    reason = st.text_area("Reason", key=f"reason_{index}")
                    if st.form_submit_button("Save decision"):
                        try:
                            save_decision(root, claim, decision, reviewer, reason)
                            st.success("Decision saved for this exact evidence.")
                        except (ValueError, OSError):
                            st.error(
                                "Supply reviewer and reason; ensure this workspace is not being edited elsewhere."
                            )
    else:
        st.info("No evidence ledger has been created yet.")
    numeric = root / "numeric_audit.json"
    if numeric.exists():
        with st.expander("Numerical consistency findings"):
            st.json(json.loads(numeric.read_text(encoding="utf-8")))
    st.subheader("Controlled section revisions")
    sections_path = root / "manuscript_sections.json"
    if not sections_path.exists():
        st.info("Import a manuscript with research_review_cli.py to revise sections.")
        return
    sections = json.loads(sections_path.read_text(encoding="utf-8"))
    if not sections:
        return
    section_id = st.selectbox("Section", list(sections))
    st.text(sections[section_id]["text"])
    replacement = st.text_area(
        "Proposed replacement", value=sections[section_id]["text"], height=250
    )
    reason = st.text_input("Reason for revision")
    revision_reviewer = st.text_input("Reviewer accepting this revision")
    key = "revision_proposal_" + str(root.resolve())
    if st.button("Preview revision"):
        try:
            st.session_state[key] = propose_revision(
                sections, section_id, replacement, reason
            )
        except ValueError as error:
            st.error(str(error))
    if key in st.session_state:
        proposal = st.session_state[key]
        st.code(proposal["diff"], language="diff")
        st.write(
            {
                k: proposal[k]
                for k in (
                    "numbers_changed",
                    "citations_changed",
                    "conclusions_require_review",
                )
            }
        )
        if st.button("Accept this revision"):
            try:
                save_revision(root, proposal, revision_reviewer)
                del st.session_state[key]
                st.success(
                    "Revision accepted. Other sections are preserved; the changed section needs renewed approval. Re-export to create new manuscript files."
                )
            except (ValueError, OSError) as error:
                st.error(str(error))
