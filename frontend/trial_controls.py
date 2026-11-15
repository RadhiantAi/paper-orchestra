"""Offline trial intake, legacy workbook and continuous result controls."""

import json
from pathlib import Path
import streamlit as st


def intake_controls(workspace, data):
    from frontend.project_review import action
    from utils.strict_trial import allocate_host, enable_strict_trial
    from utils.source_structure import ROLES
    from utils.legacy_workbooks import convert_workbook

    with st.expander("Strict blinded trial and host source decisions"):
        enabled = data.get("strict_trial", {}).get("enabled", False)
        st.write("Strict blinded trial: " + ("on" if enabled else "off"))
        st.caption(
            "Strict mode requires an exact file allocation before intake. Enable it only on a new project. It cannot control what a person or external chat has already read."
        )
        who = st.text_input("Trial decision reviewer")
        why = st.text_input("Trial decision reason")
        if not enabled and st.button("Enable strict mode on this new project"):
            action(lambda: enable_strict_trial(workspace, who, why))
        origin = st.text_input("Host source origin or host-exchange:HOST")
        sha = st.text_input("Exact host source or canonical exchange SHA256")
        role = st.selectbox("Host source role", ROLES)
        if st.button("Record host allocation"):
            action(lambda: allocate_host(workspace, origin, sha, role, who, why))
    with st.expander("Convert a legacy Excel workbook with checks"):
        st.caption(
            "Requires installed Microsoft Excel on Windows. Preserves the original, blocks active content and compares cells and formulas. Layout and charts still need visual review. Strict trials also require a separate allocation for the converted file before indexing."
        )
        source = st.text_input("Original XLS path")
        output = st.text_input(
            "New workbook conversion folder", str(workspace / "conversion-v1")
        )
        who = st.text_input("Workbook conversion reviewer")
        why = st.text_input("Workbook conversion reason")
        if st.button("Preserve, convert and compare workbook"):
            record = action(
                lambda: convert_workbook(workspace, source, output, who, why)
            )
            if record:
                st.write(record["status"])


def continuous_controls(workspace, data):
    from frontend.project_review import action
    from utils.analysis_recipes import verify_calculation
    from utils.continuous_results import register_continuous, review_continuous

    with st.expander("Link continuous calculations to manuscript values"):
        calculations = {
            c["id"]: c
            for c in data["calculations"]
            if c.get("method") == "continuous_measurements"
        }
        if not calculations:
            st.caption("Run a continuous-measurement analysis first.")
            return
        cid = st.selectbox("Continuous calculation", list(calculations))
        calc = calculations[cid]
        if not verify_calculation(calc):
            st.error("Calculation evidence changed. Re-run it before linking values.")
            return
        output = json.loads(Path(calc["output"]["path"]).read_text(encoding="utf-8"))
        kind = st.selectbox("Result type", ["summary", "model"])
        rows = output["results" if kind == "summary" else "models"]
        if not rows:
            st.info("This calculation has no rows of that type.")
            return
        n = st.selectbox(
            "Calculation row",
            range(len(rows)),
            format_func=lambda i: (
                str(rows[i].get("group"))
                + ": "
                + str(rows[i].get("variable", rows[i].get("outcome")))
            ),
        )
        row = rows[n]
        fields = (
            ["mean", "sd", "ci", "min", "max", "available", "missing", "total"]
            if kind == "summary"
            else [
                "coefficients",
                "coefficient_ci",
                "r_squared",
                "loo_rmse",
                "mean_only_loo_rmse",
                "complete_cases",
                "excluded_missing",
            ]
        )
        field = st.selectbox("Calculated field", fields)
        selector = {"kind": kind, "group": row["group"], "field": field}
        if kind == "summary":
            selector["variable"] = row["variable"]
        else:
            selector.update(outcome=row["outcome"], predictors=row["predictors"])
            if field in {"coefficients", "coefficient_ci"}:
                selector["coefficient"] = st.selectbox(
                    "Model coefficient", ["intercept"] + row["predictors"]
                )
        rid = st.text_input("Continuous result ID")
        label = st.text_input("Continuous result label")
        definition = st.text_input("Continuous result scientific definition")
        precision = st.number_input("Decimal places", min_value=0, max_value=8, value=2)
        if st.button("Register selected calculation value"):
            action(
                lambda: register_continuous(
                    workspace, rid, cid, selector, label, definition, int(precision)
                )
            )
        ids = st.multiselect(
            "Continuous results checked",
            [r["id"] for r in data.get("continuous_results", [])],
        )
        who = st.text_input("Continuous result reviewer")
        why = st.text_input("Continuous result checks performed")
        st.caption(
            "This records a technical check. Scientific interpretation and author approval remain separate."
        )
        if st.button("Record continuous result technical review"):
            action(lambda: review_continuous(workspace, ids, who, why))


def continuous_mapping_controls(data):
    mappings = []
    for row in data.get("continuous_results", []):
        rid = row["id"]
        text = st.text_area(
            "Sentence or table cell for continuous result " + rid,
            key="continuous_map_" + rid,
            help="Use {{continuous:ID:value}}. One exact passage per line; list multiple occurrences separately when their text differs.",
        )
        document = st.text_input(
            "Target document for " + rid,
            "manuscript",
            key="continuous_doc_" + rid,
            help="Use manuscript or an exact pack filename, for example Supplement1.docx.",
        )
        count = st.number_input(
            "Expected occurrences per passage for " + rid,
            min_value=1,
            value=1,
            key="continuous_count_" + rid,
        )
        mappings.extend(
            {
                "id": rid,
                "template": line.strip(),
                "document": document,
                "occurrences": int(count),
            }
            for line in text.splitlines()
            if line.strip()
        )
    return mappings
