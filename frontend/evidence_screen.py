"""Workbook, claim and version-history controls for the local review screen."""

import json
import streamlit as st


def workbook_screen(workspace, source):
    from frontend.project_review import action
    from utils.workbook_sources import register_workbook_result

    cells = [b for b in source.get("blocks", []) if b.get("kind") == "workbook_cell"]
    if not cells:
        return
    with st.expander("Workbook cells and aggregate results"):
        st.caption(
            "Raw stored values. Formulas, date formatting and embedded charts are not recalculated. Review the source sheet before approving any result."
        )
        st.dataframe(
            [
                {
                    k: b.get(k, "")
                    for k in [
                        "sheet",
                        "cell",
                        "saved_value",
                        "formula",
                        "cell_type",
                        "sheet_state",
                    ]
                }
                for b in cells
            ]
        )
        numeric = {
            b["locator"]: b
            for b in cells
            if b["cell_type"] == "n"
            and "formula" not in b
            and b["saved_value"] is not None
        }
        if numeric:
            count = st.selectbox("Aggregate count cell", list(numeric))
            denominator = st.selectbox("Aggregate denominator cell", list(numeric))
            rid = st.text_input("Workbook result identifier")
            label = st.text_input("Workbook result label")
            definition = st.text_area("What this count and denominator measure")
            if st.button("Register workbook aggregate"):
                action(
                    lambda: register_workbook_result(
                        workspace,
                        source["id"],
                        count,
                        denominator,
                        rid,
                        label,
                        definition,
                    ),
                    "Result registered. It still needs review and approval.",
                )


def provenance_screen(workspace, source):
    from frontend.project_review import action
    from utils.version_provenance import set_source_provenance, provenance_status

    with st.expander("Document history"):
        st.write("Recorded origin: " + provenance_status(source).replace("_", " "))
        st.caption(
            "An issued-copy confirmation is a named review supported by a sent record. A reconstructed original-text view proves neither issuance nor author approval."
        )
        kind = st.selectbox(
            "Document origin",
            [
                "unknown",
                "confirmed_issued",
                "reconstructed",
                "published",
                "working_draft",
            ],
        )
        proof = st.text_input("Supporting sent record, tracked return or publication")
        who = st.text_input("Document history reviewer")
        why = st.text_area("Document history evidence and reason")
        if st.button("Record document history"):
            action(
                lambda: set_source_provenance(
                    workspace, source["id"], kind, who, why, proof or None
                )
            )


def consistency_screen(workspace, data):
    from frontend.project_review import action
    from frontend.project_home import selected_file
    from utils.project_pack import doc_text
    from utils.manuscript_consistency import (
        save_claim,
        audit_consistency,
        review_finding,
    )

    with st.expander("Claims and figure-label checks"):
        st.caption(
            "Checks explicit result comparisons and selected wording. Clinical interpretation and visual figure review still need a person."
        )
        if data["results"]:
            from utils.project_results import set_result_design

            with st.expander("Describe the groups being compared"):
                selected = st.selectbox(
                    "Result group", [r["id"] for r in data["results"]]
                )
                metric = st.text_input(
                    "Shared measure, such as sensitivity or specificity"
                )
                participants = st.number_input(
                    "Independent participants in this group", min_value=1, step=1
                )
                if st.button("Save comparison details"):
                    action(
                        lambda: set_result_design(
                            workspace, selected, metric, int(participants)
                        ),
                        "Comparison details saved. Review and approve the updated result.",
                    )
        with st.expander("Link a manuscript claim to its evidence"):
            cid = st.text_input("Claim identifier")
            quote = st.text_area("Exact claim paragraph")
            kind = st.selectbox("Claim type", ["ranking", "outcome"])
            row = {"id": cid, "quote": quote, "kind": kind}
            if kind == "ranking":
                ids = [r["id"] for r in data["results"]]
                row["result_ids"] = st.multiselect(
                    "Results included in the comparison", ids
                )
                row["result_id"] = (
                    st.selectbox("Result claimed to lead", ids) if ids else None
                )
                row["direction"] = st.selectbox(
                    "Ranking direction", ["highest", "lowest"]
                )
            else:
                row["classification"] = st.selectbox(
                    "Outcome status", ["proposed", "measured"]
                )
                if row["classification"] == "proposed":
                    row["qualification"] = st.text_input(
                        "Exact wording that marks this as a proposal"
                    )
                else:
                    passages = [
                        (s, b)
                        for s in data["sources"]
                        for b in s.get("blocks", [])
                        if b.get("text") and not b.get("review_required")
                    ]
                    if passages:
                        n = st.selectbox(
                            "Outcome evidence passage",
                            range(len(passages)),
                            format_func=lambda n: passages[n][1]["locator"],
                        )
                        s, b = passages[n]
                        evidence = st.text_area(
                            "Exact outcome evidence quote", b["text"]
                        )
                        row["evidence"] = [
                            {
                                "source_id": s["id"],
                                "source_sha256": s["sha256"],
                                "locator": b["locator"],
                                "quote": evidence,
                            }
                        ]
            if st.button("Save claim mapping"):
                action(lambda: save_claim(workspace, row))
        manuscript = selected_file(
            workspace, "Manuscript for consistency checks", "consistency_manuscript"
        )
        if manuscript:
            from utils.strict_trial import admit_file
            text = action(lambda: (admit_file(workspace, manuscript), doc_text(manuscript))[1], "Manuscript read locally.")
            if text is not None:
                report = audit_consistency(data, text)
                st.write(report)
                st.download_button(
                    "Download consistency report",
                    json.dumps(report, indent=2),
                    file_name="consistency-report.json",
                )
                pending = {
                    r["id"]: r for r in report["findings"] if r["severity"] != "error"
                }
                if pending:
                    fid = st.selectbox(
                        "Finding personally reviewed",
                        list(pending),
                        format_func=lambda k: (
                            pending[k]["kind"].replace("_", " ")
                            + ": "
                            + pending[k]["quote"][:70]
                        ),
                    )
                    who = st.text_input("Consistency reviewer")
                    why = st.text_area("Evidence and reason for retaining this wording")
                    if st.button("Record consistency review"):
                        action(lambda: review_finding(workspace, text, fid, who, why))
