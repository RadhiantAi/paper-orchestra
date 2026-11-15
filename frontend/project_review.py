"""Local author-query and source-coverage review screen."""

from pathlib import Path
import streamlit as st

from utils.project_store import load_project, dependency_status
from utils.project_review import decide_query, query_status
from utils.project_figures import figure_issues


def render_project(workspace):
    st.title("Manuscript project review")
    st.caption(
        "Private local records. Reviewer names are audit labels, not authenticated signatures."
    )
    data = load_project(workspace)
    changed = dependency_status(data)
    if changed:
        st.error(
            f"{len(changed)} source files have changed or disappeared. Reindex before releasing a pack."
        )
    st.subheader("Source coverage")
    st.write(
        {
            "sources": len(data["sources"]),
            "unreadable_or_partial": sum(
                s["status"] != "read" for s in data["sources"]
            ),
            "searches": len(data["searches"]),
        }
    )
    st.dataframe(
        [
            {
                "source": Path(s.get("path", s.get("origin", s["id"]))).name,
                "status": s["status"],
                "warnings": ", ".join(s.get("warnings", [])),
            }
            for s in data["sources"]
        ]
    )
    st.subheader("Author questions")
    if data["queries"]:
        choices = {q["id"]: q for q in data["queries"]}
        key = st.selectbox("Question", list(choices))
        q = choices[key]
        st.write({"owner": q["owner"], "status": query_status(q, data["sources"])})
        st.write(q["question"])
        st.quote(q["quote"]) if hasattr(st, "quote") else st.info(q["quote"])
        if q.get("conditions"):
            st.info(
                "This confirmation is conditional. Exact source evidence must be supplied through the project CLI to resolve the conditions."
            )
            st.write(q["conditions"])
        reviewer = st.text_input("Reviewer")
        reason = st.text_area("Reason")
        action = st.selectbox("Decision", ["flag", "confirm"])
        if st.button("Record author decision"):
            try:
                decide_query(workspace, key, reviewer, reason, action)
                st.success(
                    "Decision recorded. Conditional checks remain open until evidence is supplied."
                )
            except ValueError as e:
                st.error(str(e))
    st.subheader("Figure checks")
    st.dataframe(
        [
            {
                "figure": f["id"],
                "remaining_checks": ", ".join(i["kind"] for i in figure_issues(f)),
            }
            for f in data["figures"]
        ]
    )
