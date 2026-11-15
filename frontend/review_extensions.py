"""Additional offline workbench panels."""

from pathlib import Path
from datetime import date
import json
import streamlit as st
from utils.project_store import update_project, private_path, file_receipt
from utils.project_pack import doc_text
from utils.project_review import discussion_coverage, import_host
from utils.research_quality import fingerprint
from utils.run_control import write_json


def source_recovery(workspace, data):
    from frontend.project_review import action, source_label
    from utils.source_recovery import source_inventory, recover_ocr, confirm_ocr

    with st.expander("Duplicates, missing sources and scanned pages"):
        st.write(source_inventory(data))
        local = {
            s["id"]: s
            for s in data["sources"]
            if s.get("path")
            and Path(s["path"]).suffix.lower()
            in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
        }
        if local:
            sid = st.selectbox(
                "Scanned source",
                list(local),
                format_func=lambda k: source_label(local[k]),
            )
            exe = st.text_input("Installed Tesseract executable")
            limit = st.number_input(
                "Maximum pages to recover", min_value=1, max_value=100, value=30
            )
            if st.button("Recover text locally"):
                action(
                    lambda: recover_ocr(workspace, sid, exe, int(limit)),
                    "Text recovered. Refresh and review each OCR passage.",
                )
            blocks = [b for b in local[sid]["blocks"] if b.get("method") == "local_ocr"]
            if blocks:
                n = st.selectbox(
                    "OCR passage to review",
                    range(len(blocks)),
                    format_func=lambda n: blocks[n]["locator"],
                )
                b = blocks[n]
                left, right = st.columns(2)
                with left:
                    action(
                        lambda: st.image(b["preview"]["path"]), "OCR preview opened."
                    )
                with right:
                    text = st.text_area(
                        "Check and correct recovered text",
                        b["text"],
                        key=sid + b["locator"],
                    )
                    who = st.text_input("OCR reviewer")
                    reason = st.text_input("OCR review reason")
                    if st.button("Confirm recovered passage"):
                        action(
                            lambda: confirm_ocr(
                                workspace, sid, b["locator"], who, reason, text
                            )
                        )


def analysis_screen(workspace, data):
    from frontend.project_review import action
    from utils.analysis_recipes import run_recipe, register_proportions

    with st.expander("Run a reproducible aggregate analysis"):
        st.caption(
            "These recipes use aggregate counts. Correlated or clustered observations need a different analysis."
        )
        name = st.selectbox(
            "Analysis recipe", ["binary_proportion", "paired_binary_agreement"]
        )
        st.code(
            "id,label,count,denominator,missing_count"
            if name == "binary_proportion"
            else "id,label,n00,n01,n10,n11,missing_count"
        )
        source = st.text_input("Aggregate CSV file")
        unit = st.text_input("Independent sampling unit")
        independent = st.checkbox(
            "I confirm these counts represent independent sampling units"
        )
        confidence = st.number_input(
            "Confidence level", min_value=0.51, max_value=0.999, value=0.95
        )
        seed = st.number_input(
            "Random seed", min_value=0, max_value=2**32 - 1, value=1729
        )
        iterations = st.number_input(
            "Bootstrap samples", min_value=100, max_value=20000, value=2000
        )
        dest = st.text_input("New analysis folder", str(workspace / "analysis-v1"))
        who = st.text_input("Analysis reviewer")
        why = st.text_area("Analysis method and assumptions checked")
        if st.button("Run local analysis"):
            recipe = {
                "name": name,
                "sampling_unit": unit,
                "independent_units_confirmed": independent,
                "confidence": confidence,
                "seed": int(seed),
                "bootstrap_iterations": int(iterations),
            }
            receipt = action(
                lambda: run_recipe(workspace, recipe, source, dest, who, why),
                "Calculation saved. Review it before approving manuscript results.",
            )
            if receipt:
                st.json(json.loads(Path(receipt["output"]["path"]).read_text()))
        calculations = {
            c["id"]: c for c in data["calculations"] if c.get("kind") == "local_recipe"
        }
        if calculations:
            cid = st.selectbox("Calculation to inspect", list(calculations))
            output = action(
                lambda: json.loads(
                    Path(calculations[cid]["output"]["path"]).read_text()
                ),
                "Calculation opened.",
            )
            if output is not None:
                st.json(output)
            definition = st.text_input("Scientific definition for count results")
            if st.button("Add calculated proportions to result register"):
                action(
                    lambda: register_proportions(workspace, cid, definition),
                    "Unapproved results added. Review and approve them in Results.",
                )


def journal_screen(workspace, data):
    from frontend.project_review import action
    from utils.journal_checks import check_journal, validate_profile

    st.subheader("Journal and discussion checks")
    with st.expander("Set the target journal requirements"):
        st.caption(
            "Enter requirements from the journal instructions you reviewed. Zero limits require zero items."
        )
        name = st.text_input("Journal and article type")
        source = st.text_input("Journal instructions URL or source")
        verified = st.date_input("Date requirements checked", date.today())
        who = st.text_input("Requirements checked by")
        values = {
            k: int(st.number_input(label, min_value=0, value=0, key=k))
            for k, label in [
                ("max_words", "Maximum main text words"),
                ("max_abstract_words", "Maximum abstract words"),
                ("max_references", "Maximum references"),
                ("max_figures", "Maximum figures"),
                ("figure_min_width_px", "Minimum figure width in pixels"),
                ("figure_min_dpi", "Minimum figure DPI"),
            ]
        }
        style = st.selectbox("Reference style", ["numeric", "author_year", "manual"])
        sections = st.text_area("Required section headings, one per line")
        declarations = st.text_area("Required declaration labels, one per line")
        checklist = st.text_area("Reporting checklist items, one per line")
        excludes = st.text_input(
            "Sections excluded from main word count, separated by commas",
            "Abstract,References,Bibliography",
        )
        formats = st.text_input(
            "Allowed figure extensions, separated by commas", "png,tif,tiff,jpg"
        )
        confirmed = st.checkbox(
            "I checked these requirements against the journal instructions"
        )
        if st.button("Save journal requirements", disabled=not confirmed):
            profile = {
                "schema": 1,
                "name": name,
                "source": source,
                "verified_on": verified.isoformat(),
                "confirmed_by": who,
                **values,
                "reference_style": style,
                "required_sections": sections.splitlines(),
                "required_declarations": declarations.splitlines(),
                "checklist_items": checklist.splitlines(),
                "exclude_from_main_count": [
                    x.strip() for x in excludes.split(",") if x.strip()
                ],
                "figure_formats": [
                    x.strip().lower().lstrip(".")
                    for x in formats.split(",")
                    if x.strip()
                ],
            }

            def save():
                validate_profile(profile)
                update_project(workspace, lambda d: d.update(journal_profile=profile))
                path = private_path(workspace) / (
                    "journal-" + fingerprint(profile)[:12] + ".json"
                )
                write_json(path, profile)

            action(save, "Journal requirements saved. Refresh to use them.")
    manuscript = st.text_input("Manuscript for journal checks")
    if manuscript:
        text = action(lambda: doc_text(manuscript), "Manuscript opened locally.")
        if text is not None:
            st.write(discussion_coverage(data, text))
            profile = data.get("journal_profile")
            if profile:
                st.write(
                    check_journal(
                        profile, text, data["figures"], data.get("journal_reviews")
                    )
                )
                item = st.selectbox(
                    "Checklist item reviewed",
                    profile["checklist_items"] + ["Reference formatting reviewed"],
                )
                quote = st.text_area("Exact manuscript passage supporting this check")
                who = st.text_input("Checklist reviewer")
                why = st.text_area("Checklist review reason")
                if st.button("Record checklist review"):

                    def record():
                        if (
                            not quote.strip()
                            or quote not in text
                            or not who.strip()
                            or not why.strip()
                        ):
                            raise ValueError(
                                "Provide an exact passage, reviewer and reason."
                            )
                        row = {
                            "item": item,
                            "quote": quote,
                            "reviewer": who,
                            "reason": why,
                            "identity": fingerprint([profile, text]),
                        }
                        update_project(
                            workspace,
                            lambda d: d.setdefault("journal_reviews", []).append(row),
                        )

                    action(record)


def figure_editor(workspace, data):
    from frontend.project_review import action, source_label
    from utils.project_figures import mask_image

    with st.expander("Create an authorised masked copy"):
        original = st.text_input("Original image path")
        target = st.text_input("New masked PNG path")
        rects = st.text_area("Mask rectangles: left, top, right, bottom; one per line")
        who = st.text_input("Mask authorised by")
        why = st.text_input("Masking reason")
        if st.button("Create masked copy"):
            action(
                lambda: mask_image(
                    original,
                    target,
                    [
                        [int(v.strip()) for v in line.split(",")]
                        for line in rects.splitlines()
                        if line.strip()
                    ],
                    who,
                    why,
                ),
                "Masked copy saved. Inspect it before confirming privacy.",
            )
    with st.expander("Register or revise a figure panel"):
        sources = {s["id"]: s for s in data["sources"] if s.get("images")}
        if not sources:
            st.info("Index images or a document containing images first.")
            return
        sid = st.selectbox(
            "Figure source",
            list(sources),
            format_func=lambda k: source_label(sources[k]),
        )
        images = sources[sid]["images"]
        n = st.selectbox(
            "Source image",
            range(len(images)),
            format_func=lambda n: images[n]["locator"],
        )
        image = images[n]
        fid = st.text_input("Figure identifier", "Figure 1")
        old = next((f for f in data["figures"] if f["id"] == fid), None)
        caption = st.text_area(
            "Complete figure legend", old["caption"] if old else "", key="caption" + fid
        )
        label = st.text_input("Panel label", "a")
        recovered = st.text_area("Recovered source label")
        display = st.text_input("Display image path (blank uses source image)")
        mask = st.text_input("Mask receipt JSON file (if masked)")
        if st.button("Save figure panel and legend"):

            def save():
                panel = {
                    "label": label,
                    "source_id": sid,
                    "source_locator": image["locator"],
                    "source_label": recovered,
                    "original": file_receipt(image["path"]),
                    "display": file_receipt(display or image["path"]),
                }
                if mask:
                    panel["mask_receipt"] = json.loads(Path(mask).read_text())
                fig = {
                    "id": fid,
                    "caption": caption,
                    "panels": [
                        p for p in (old or {}).get("panels", []) if p["label"] != label
                    ]
                    + [panel],
                }
                import_host(
                    workspace,
                    {
                        "schema": 1,
                        "mode": "host_assisted",
                        "host": "Local reviewer",
                        "figures": [fig],
                    },
                )

            action(
                save,
                "Figure saved. All figure confirmations require review after this change.",
            )
