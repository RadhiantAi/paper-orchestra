"""Human decisions and a visible protocol/freeze/reveal sequence."""

import json
from pathlib import Path
import streamlit as st


def reviewer_controls(workspace, data):
    from frontend.project_review import action
    from utils.reviewer_checks import review_check, review_status, CHECKS

    with st.expander("Complete workbook and interpretation checks"):
        kinds = {
            "workbook_visual": "Workbook visual review",
            "calculation_interpretation": "Calculation interpretation",
        }
        kind = st.selectbox("Human check type", list(kinds), format_func=kinds.get)
        targets = (
            [r["source"]["sha256"] for r in data.get("legacy_conversions", [])]
            if kind == "workbook_visual"
            else [
                c["id"] for c in data["calculations"] if c.get("kind") == "local_recipe"
            ]
        )
        if not targets:
            st.caption(
                "No eligible workbook conversions or calculations for this check."
            )
            return
        target = st.selectbox("Evidence to review", list(dict.fromkeys(targets)))
        st.write("Current decision: " + review_status(data, kind, target))
        st.caption(
            "Acceptance closes only this human check. Technical failures remain blocking and author approval stays separate."
        )
        checks = {
            k: st.checkbox(
                k.replace("_", " ").capitalize() + " checked", key="human_" + kind + target + k
            )
            for k in sorted(CHECKS[kind])
        }
        decision = st.selectbox("Human check decision", ["unresolved", "accepted"], key="decision_" + kind + target)
        manuscript = quote = None
        if kind == "calculation_interpretation":
            manuscript = st.text_input("Manuscript evidence for interpretation review")
            quote = st.text_area(
                "Exact passage addressing interpretation and limitations"
            )
        who = st.text_input("Human check reviewer")
        reason = st.text_area("Human check reasoning and remaining limitations")
        if st.button("Record human check decision"):
            action(
                lambda: review_check(
                    workspace,
                    kind,
                    target,
                    who,
                    reason,
                    decision,
                    checks,
                    manuscript,
                    quote,
                )
            )


def trial_controls(workspace, data):
    from frontend.project_review import action
    from utils.trial_evaluation import (
        freeze_protocol,
        register_draft,
        freeze_candidate,
        unblind,
        compare_reference,
    )

    with st.expander("Blinded trial: plan, freeze and compare"):
        if not data.get("strict_trial", {}).get("enabled"):
            st.caption("Create a strict blinded project to use this workflow.")
            return
        phase = (
            "reference revealed"
            if data.get("trial_unblinding")
            else "candidate frozen"
            if data.get("trial_freeze")
            else "protocol frozen"
            if data.get("trial_protocol")
            else "planning"
        )
        st.write("Trial phase: " + phase)
        who = st.text_input("Trial phase reviewer")
        why = st.text_input("Trial phase reason")
        if not data.get("trial_protocol"):
            question = st.text_area("Trial research question")
            plan = st.text_area("Prespecified analysis plan")
            criteria = st.text_area("Trial success criteria")
            exposure = st.text_area("What the trial operator has already seen")
            recipes = st.text_area("Exact planned recipes as a JSON list", "[]")
            if st.button("Freeze protocol and admitted inputs"):
                action(
                    lambda: freeze_protocol(
                        workspace,
                        {
                            "question": question,
                            "analysis_plan": plan,
                            "success_criteria": criteria,
                            "exposure_statement": exposure,
                            "recipes": json.loads(recipes),
                        },
                        who,
                        why,
                    )
                )
        elif not data.get("trial_freeze"):
            st.caption(
                "Declare only drafts produced from admitted evidence. This records your statement; it cannot prove what an external chat has read."
            )
            draft = st.text_input("Operator-produced candidate file")
            if st.button("Register candidate draft declaration"):
                action(lambda: register_draft(workspace, draft, who, why))
            pack = st.text_input("Checked candidate pack folder")
            if st.button("Seal checked candidate before unblinding"):
                action(lambda: freeze_candidate(workspace, pack, who, why))
        elif not data.get("trial_unblinding"):
            hashes = st.multiselect(
                "Withheld reference hashes to reveal",
                data["trial_protocol"]["reference_hashes"],
            )
            if st.button("Record explicit unblinding"):
                action(lambda: unblind(workspace, hashes, who, why))
        else:
            reference = st.text_input("Unblinded reference file")
            out = st.text_input(
                "New comparison report", str(Path(workspace) / "comparison-v1.json")
            )
            if st.button("Compare with frozen candidate"):
                report = action(lambda: compare_reference(workspace, reference, out))
                if report:
                    st.write(report)


def plot_controls(workspace, data):
    from frontend.project_review import action
    from utils.continuous_figures import export_continuous_figure

    with st.expander("Create a calculation-linked statistical figure"):
        rows = {r["id"]: r for r in data.get("continuous_results", [])}
        scalars = [rid for rid, r in rows.items() if not isinstance(r["value"], list)]
        if not scalars:
            st.caption("Register and technically review continuous values first.")
            return
        ids = st.multiselect("Continuous values to plot", scalars)
        items = []
        for rid in ids:
            label = st.text_input(
                "Plot label for " + rid, rows[rid]["label"], key="plot_label_" + rid
            )
            interval = st.selectbox(
                "Interval for " + rid,
                [None] + [k for k, r in rows.items() if isinstance(r["value"], list)],
                key="plot_ci_" + rid,
            )
            item = {"result_id": rid, "label": label}
            if interval:
                item["interval_id"] = interval
            items.append(item)
        fid = st.text_input("Statistical figure ID", "continuous-summary")
        title = st.text_input("Statistical figure title")
        axis = st.text_input("Statistical figure axis label")
        dest = st.text_input(
            "New statistical figure folder",
            str(Path(workspace) / "continuous-figure-v1"),
        )
        if st.button("Generate checked statistical figure"):
            action(
                lambda: export_continuous_figure(
                    workspace,
                    {"id": fid, "title": title, "axis_label": axis, "items": items},
                    dest,
                )
            )
