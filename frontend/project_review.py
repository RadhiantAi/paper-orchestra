"""Private review workbench. No model calls or external retrieval."""

from pathlib import Path
import json
import streamlit as st
from utils.project_store import load_project, dependency_status, private_path
from utils.project_review import (
    decide_query,
    query_status,
    compare_versions,
    import_host,
)
from utils.project_results import approved, export_result_assets
from utils.project_figures import figure_issues
from utils.project_sources import index_sources
from utils.project_pack import (
    doc_text,
    prepare_pack,
    check_pack,
    record_visual_review,
    release_pack,
)
from utils.review_actions import (
    save_uploads,
    approve_selected,
    confirm_figure,
    review_edit,
    build_spec,
)


def action(fn, success="Saved."):
    try:
        record = st.session_state.get("_project_record")
        before = (
            Path(record).stat().st_mtime_ns
            if record and Path(record).exists()
            else None
        )
        value = fn()
        if before is not None and Path(record).stat().st_mtime_ns != before:
            st.session_state["_saved_notice"] = success
            st.rerun()
        st.success(success)
        return value
    except (ValueError, OSError, KeyError, StopIteration, RuntimeError) as exc:
        st.error(str(exc) or "The record changed. Refresh the page.")
        return None


def source_label(s):
    return (
        s.get("display_name", Path(s.get("path", s.get("origin", s["id"]))).name)
        + " ["
        + s["id"][:8]
        + "]"
    )


def render_project(workspace):
    workspace = private_path(workspace)
    st.session_state["_project_record"] = str(workspace / "project.json")
    st.title("Manuscript project review")
    st.caption(
        "Confidential local workspace. Reviewer names record decisions; they do not authenticate identity."
    )
    st.info(
        "This review screen works locally. It makes no model calls or external searches."
    )
    data = load_project(workspace)
    if "_saved_notice" in st.session_state:
        st.success(st.session_state.pop("_saved_notice"))
    from frontend.project_home import readiness, selected_file, recovery_screen

    counts = readiness(data)
    with st.expander("What still needs attention", expanded=any(counts.values())):
        st.write(counts)
        next_step = next(
            (label for label, count in counts.items() if count),
            "No outstanding items in these project checks",
        )
        st.write("Next: " + next_step)
        st.caption("Project checks only. Run the complete pack checks before release.")
    if dependency_status(data):
        st.error(
            "Source files changed or disappeared. Reindex before releasing a pack."
        )
    (
        sources,
        questions,
        edits,
        results,
        figures,
        coverage,
        packs,
        coauthors,
        recovery,
    ) = st.tabs(
        [
            "Sources and manuscript",
            "Author questions",
            "Earlier edits",
            "Results",
            "Figures",
            "Journal and discussion",
            "Review pack",
            "Co-author returns",
            "Backup and recovery",
        ]
    )
    with sources:
        st.subheader("Source coverage")
        st.dataframe(
            [
                {
                    "source": source_label(s),
                    "status": s["status"],
                    "warnings": ", ".join(s.get("warnings", [])),
                }
                for s in data["sources"]
            ]
        )
        with st.expander("Add source files or host evidence"):
            uploads = st.file_uploader("Source documents", accept_multiple_files=True)
            convert = st.checkbox(
                "Convert legacy Word documents using installed Word or LibreOffice"
            )
            office = st.text_input("LibreOffice executable (optional)")
            if st.button("Index uploaded sources", disabled=not uploads):
                action(
                    lambda: index_sources(
                        workspace,
                        save_uploads(
                            workspace, [(f.name, f.getvalue()) for f in uploads]
                        ),
                        convert=convert,
                        libreoffice=office or None,
                    ),
                    "Sources indexed. Refresh to view them.",
                )
            exchange = st.file_uploader(
                "Evidence exchange from your assistant", type=["json"]
            )
            if st.button("Import evidence exchange", disabled=exchange is None):
                action(
                    lambda: import_host(workspace, json.loads(exchange.getvalue())),
                    "Evidence imported. Refresh to view it.",
                )
        if data["sources"]:
            by_id = {s["id"]: s for s in data["sources"]}
            selected = st.selectbox(
                "Source to inspect",
                list(by_id),
                format_func=lambda k: source_label(by_id[k]),
            )
            source = by_id[selected]
            from frontend.evidence_screen import workbook_screen, provenance_screen

            workbook_screen(workspace, source)
            provenance_screen(workspace, source)
            left, right = st.columns(2)
            with left:
                blocks = source.get("blocks", [])
                if blocks:
                    n = st.selectbox(
                        "Source passage",
                        range(len(blocks)),
                        format_func=lambda n: blocks[n]["locator"],
                    )
                    st.text_area(
                        "Original source passage",
                        blocks[n]["text"],
                        height=320,
                        disabled=True,
                    )
                else:
                    st.warning("No text recovered. Check the source warnings.")
            with right:
                draft = st.text_input("Manuscript file to compare", key="compare_draft")
                if draft:
                    from utils.strict_trial import admit_file
                    content = action(
                        lambda: (admit_file(workspace, draft), doc_text(draft))[1], "Manuscript opened locally."
                    )
                    if content is not None:
                        st.text_area(
                            "Current manuscript", content, height=320, disabled=True
                        )
        from frontend.review_extensions import source_recovery

        source_recovery(workspace, data)
    with questions:
        st.subheader("Author questions")
        if data["queries"]:
            choices = {q["id"]: q for q in data["queries"]}
            key = st.selectbox("Question", list(choices))
            q = choices[key]
            st.write({"owner": q["owner"], "status": query_status(q, data["sources"])})
            st.write(q["question"])
            st.info(q["quote"])
            proofs = []
            candidates = [
                (s, b)
                for s in data["sources"]
                for b in s.get("blocks", [])
                if b.get("text")
            ]
            for condition in q.get("conditions", []):
                st.write(condition["description"])
                chosen = st.selectbox(
                    "Supporting passage: " + condition["id"],
                    [None] + list(range(len(candidates))),
                    format_func=lambda i: (
                        "No evidence selected"
                        if i is None
                        else source_label(candidates[i][0])
                        + " / "
                        + candidates[i][1]["locator"]
                    ),
                    key=key + condition["id"],
                )
                if chosen is not None:
                    s, b = candidates[chosen]
                    st.text(b["text"])
                    quote = st.text_area(
                        "Exact supporting quote: " + condition["id"],
                        b["text"],
                        key=key + condition["id"] + str(chosen) + "quote",
                    )
                    proofs.append(
                        {
                            "id": condition["id"],
                            "evidence": [
                                {
                                    "source_id": s["id"],
                                    "source_sha256": s["sha256"],
                                    "locator": b["locator"],
                                    "quote": quote,
                                }
                            ],
                        }
                    )
            reviewer = st.text_input("Reviewer")
            reason = st.text_area("Reason")
            decision = st.selectbox("Decision", ["flag", "confirm"])
            if st.button("Record author decision"):
                updated = action(
                    lambda: decide_query(
                        workspace, key, reviewer, reason, decision, proofs
                    )
                )
                if updated:
                    st.write(
                        "Current status: "
                        + query_status(
                            next(q for q in updated["queries"] if q["id"] == key),
                            updated["sources"],
                        )
                    )
    with edits:
        st.subheader("Compare earlier versions")
        ids = {s["id"]: s for s in data["sources"]}
        if len(ids) >= 2:
            before = st.selectbox(
                "Earlier source", list(ids), format_func=lambda k: source_label(ids[k])
            )
            after = st.selectbox(
                "Revised source",
                list(ids),
                index=1,
                format_func=lambda k: source_label(ids[k]),
            )
            report = compare_versions(
                ids[before], ids[after], data.get("edit_decisions")
            )
            st.code(report["diff"], language="diff")
            st.write(report["change_report"])
            st.download_button(
                "Download version comparison",
                json.dumps(report, indent=2),
                file_name="version-comparison.json",
            )
            if report["edits"]:
                n = st.selectbox(
                    "Editorial point",
                    range(len(report["edits"])),
                    format_func=lambda n: (
                        str(n + 1) + " " + report["edits"][n]["status"]
                    ),
                )
                row = report["edits"][n]
                st.write(row["edit"])
                status = st.selectbox(
                    "Disposition", ["retained", "rejected", "superseded"]
                )
                who = st.text_input("Edit reviewer")
                why = st.text_area("Edit reason")
                if st.button("Save edit disposition"):
                    action(
                        lambda: review_edit(
                            workspace,
                            before,
                            after,
                            row["fingerprint"],
                            status,
                            who,
                            why,
                        )
                    )
    with results:
        st.subheader("Approved results")
        st.dataframe(
            [
                {
                    **{k: v for k, v in r.items() if k != "approval"},
                    "approved": approved(r),
                }
                for r in data["results"]
            ]
        )
        selected = st.multiselect(
            "Results to approve", [r["id"] for r in data["results"]]
        )
        who = st.text_input("Result reviewer")
        why = st.text_area("Result approval reason")
        if st.button("Approve selected results"):
            action(lambda: approve_selected(workspace, selected, who, why))
        output = st.text_input("New results folder", str(workspace / "results-v1"))
        if st.button("Export approved results"):
            action(
                lambda: export_result_assets(load_project(workspace)["results"], output)
            )
        from frontend.review_extensions import analysis_screen

        analysis_screen(workspace, data)
        from frontend.evidence_screen import consistency_screen

        consistency_screen(workspace, data)
    with figures:
        st.subheader("Figure checks")
        if data["figures"]:
            choices = {f["id"]: f for f in data["figures"]}
            fid = st.selectbox("Figure", list(choices))
            fig = choices[fid]
            st.write(fig["caption"])
            for col, panel in zip(st.columns(len(fig["panels"])), fig["panels"]):
                with col:
                    if Path(panel["display"]["path"]).is_file():
                        st.image(panel["display"]["path"], caption=panel["label"])
                    st.caption(panel["source_label"])
            st.write(figure_issues(fig))
            checks = st.multiselect(
                "Checks personally reviewed",
                [
                    "image_identity",
                    "caption",
                    "clinical",
                    "cohort",
                    "reproduction",
                    "privacy",
                ],
            )
            who = st.text_input("Figure reviewer")
            why = st.text_area("Figure review reason")
            if st.button("Record figure checks"):
                action(lambda: confirm_figure(workspace, fid, checks, who, why))
        from frontend.review_extensions import figure_editor

        figure_editor(workspace, data)
    with coverage:
        from frontend.review_extensions import journal_screen

        journal_screen(workspace, data)
    with packs:
        st.subheader("Prepare a review pack")
        st.caption("Files remain local. Creating a ZIP does not send or submit it.")
        manuscript = selected_file(workspace, "Manuscript Word file", "pack_manuscript")
        title = selected_file(workspace, "Approved title page Word file", "pack_title")
        extras = st.text_area("Supplement paths, one per line")
        result_folder = st.text_input("Exported results folder (optional)")
        mappings = []
        from frontend.trial_controls import continuous_mapping_controls
        continuous_mappings = continuous_mapping_controls(data)
        continuous_figures = st.multiselect("Calculation-linked figures for this pack", [r["id"] for r in data.get("continuous_figures", [])])
        for r in data["results"]:
            template = st.text_input(
                "Exact sentence or table text for " + r["id"],
                key="mapping" + r["id"],
                help="Replace its value with {{result:ID:pair}}, count, denominator or percent.",
            )
            if template:
                mappings.append({"id": r["id"], "template": template})
        stage = st.selectbox("Pack purpose", ["coauthor_review", "submission"])
        journal = st.text_input("Journal profile JSON file (optional)")
        out = st.text_input("New pack folder", str(workspace / "pack-v1"))
        office = st.text_input("Pack LibreOffice executable (optional)")
        from frontend.manuscript_checks import pack_quality_controls
        expectations, placements = pack_quality_controls(data)
        if st.button("Build Word and PDF pack"):

            def build():
                profile = (
                    json.loads(Path(journal).read_text())
                    if journal
                    else data.get("journal_profile")
                )
                spec = build_spec(
                    workspace,
                    manuscript,
                    title,
                    [p for p in extras.splitlines() if p.strip()],
                    mappings,
                    stage,
                    profile,
                    result_folder or None,
                )
                if expectations is not None:
                    spec["manuscript_expectations"] = expectations
                spec["figure_placements"] = placements
                spec["continuous_mappings"] = continuous_mappings
                spec["continuous_figures"] = continuous_figures
                return prepare_pack(workspace, spec, out, office or None)

            report = action(
                build, "Build complete. Read the check results before release."
            )
            if report:
                st.write(report["problems"])
                st.write(report["pending"])
        if st.button("Check existing pack"):
            report = action(lambda: check_pack(workspace, out), "Checks completed.")
            if report:
                st.write(report["problems"])
                st.write(report["pending"])
        who = st.text_input("Visual reviewer")
        notes = st.text_area("What you inspected in the Word and PDF files")
        if st.button("Record visual review"):
            action(lambda: record_visual_review(workspace, out, who, notes))
        dest = st.text_input("New review ZIP", str(workspace / "review-v1.zip"))
        if st.button("Create checked ZIP"):
            receipt = action(
                lambda: release_pack(workspace, out, dest),
                "Verified ZIP saved locally.",
            )
            if receipt:
                st.download_button(
                    "Download review ZIP",
                    Path(dest).read_bytes(),
                    file_name=Path(dest).name,
                    mime="application/zip",
                )
    with coauthors:
        from frontend.coauthor_screen import coauthor_screen

        coauthor_screen(workspace, data)
    with recovery:
        recovery_screen(workspace)
