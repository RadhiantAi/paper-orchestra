from pathlib import Path
import streamlit as st
from frontend.project_home import selected_file
from utils.coauthor_review import (
    register_issued,
    import_return,
    decide_return,
    return_conflicts,
    apply_returned_edits,
    export_response,
    record_manual_reconciliation,
    supersede_item,
)
from utils.review_rounds import ancestors


def coauthor_screen(workspace, data):
    from frontend.project_review import action

    st.subheader("Returned co-author reviews")
    issued = {r["id"]: r for r in data.get("issued_versions", [])}
    with st.expander("Register the version given to co-authors"):
        manuscript = selected_file(
            workspace, "Issued manuscript Word file", "issued_file"
        )
        label = st.text_input("Issued version label")
        parent = st.selectbox(
            "Earlier round this version follows",
            [None] + list(issued),
            format_func=lambda k: (
                "First or independent round" if k is None else issued[k]["label"]
            ),
        )
        round_reviewer = st.text_input("New round reviewer", disabled=parent is None)
        round_reason = st.text_area(
            "Why this starts a new round", disabled=parent is None
        )
        if st.button("Register issued version"):
            action(
                lambda: register_issued(
                    workspace, manuscript, label, parent, round_reviewer, round_reason
                )
            )
    if not issued:
        return
    iid = st.selectbox(
        "Issued version", list(issued), format_func=lambda k: issued[k]["label"]
    )
    st.caption(
        "Round "
        + str(issued[iid].get("round", 1))
        + ". Earlier decisions remain active until explicitly superseded."
    )
    with st.expander("Supersede an earlier decision with this round"):
        try:
            previous = ancestors(data, iid)
        except ValueError:
            previous = []
            st.error("Review-round ancestry needs repair before supersession.")
        earlier = {
            i["id"]: i
            for r in data.get("coauthor_returns", [])
            if r["issued_id"] in previous
            for i in r["items"]
            if i["status"] != "superseded"
        }
        later = {
            i["id"]: i
            for r in data.get("coauthor_returns", [])
            if r["issued_id"] == iid
            for i in r["items"]
            if i["status"] == "accepted"
        }
        if earlier and later:
            old_id = st.selectbox(
                "Earlier item to supersede",
                list(earlier),
                format_func=lambda k: (
                    earlier[k]["kind"] + " / " + earlier[k]["status"] + " / " + k[:8]
                ),
            )
            new_id = st.selectbox(
                "Accepted replacement decision",
                list(later),
                format_func=lambda k: later[k]["kind"] + " / " + k[:8],
            )
            left, right = st.columns(2)
            with left:
                st.text_area(
                    "Earlier wording or comment",
                    value=earlier[old_id].get("text")
                    or "\n".join(earlier[old_id]["after"]),
                    disabled=True,
                )
                st.caption(
                    "Status: "
                    + earlier[old_id]["status"]
                    + ". Owner: "
                    + earlier[old_id]["owner"]
                )
            with right:
                st.text_area(
                    "Replacement wording or comment",
                    value=later[new_id].get("text")
                    or "\n".join(later[new_id]["after"]),
                    disabled=True,
                )
                st.caption("Decision: accepted. Owner: " + later[new_id]["owner"])
            checked = selected_file(
                workspace,
                "Checked manuscript for supersession",
                "supersession_manuscript",
            )
            who = st.text_input("Supersession reviewer")
            why = st.text_area("Why this later decision replaces the earlier item")
            if st.button("Record explicit supersession"):
                action(
                    lambda: supersede_item(workspace, old_id, new_id, checked, who, why)
                )
        else:
            st.info(
                "Link a later issued round and accept its replacement decision first. Earlier records are preserved."
            )
    with st.expander("Import a returned Word document"):
        returned = selected_file(
            workspace, "Returned manuscript Word file", "returned_file"
        )
        owner = st.text_input("Review owner")
        if st.button("Import returned review"):
            action(lambda: import_return(workspace, iid, returned, owner))
    st.write({"conflicts": return_conflicts(data, iid)})
    reviews = {
        r["id"]: r for r in data.get("coauthor_returns", []) if r["issued_id"] == iid
    }
    if reviews:
        rid = st.selectbox(
            "Returned review",
            list(reviews),
            format_func=lambda k: reviews[k]["owner"] + " " + k[:8],
        )
        review = reviews[rid]
        if not review["base_verified"]:
            st.warning(
                "This return cannot be proved to start from the selected issued text. Reconcile it manually in Word."
            )
        st.caption(
            "Original Word author labels are retained as document metadata, not authenticated identities."
        )
        if review["items"]:
            items = {i["id"]: i for i in review["items"]}
            item_id = st.selectbox(
                "Returned item",
                list(items),
                format_func=lambda k: (
                    items[k]["kind"] + " / " + items[k]["status"] + " / " + k[:8]
                ),
            )
            item = items[item_id]
            st.write(item)
            status = st.selectbox(
                "Co-author decision", ["needs_discussion", "accepted", "rejected"]
            )
            owner = st.text_input(
                "Assigned owner", item["owner"], key=item_id + "owner"
            )
            reviewer = st.text_input("Co-author decision reviewer")
            reason = st.text_area("Co-author decision reason")
            if st.button("Save co-author decision"):
                action(
                    lambda: decide_return(
                        workspace, rid, item_id, status, owner, reviewer, reason
                    )
                )
    output = st.text_input(
        "New manuscript with accepted changes",
        str(Path(workspace) / "coauthor-draft.docx"),
    )
    if st.button("Apply accepted text edits to new draft"):
        action(lambda: apply_returned_edits(workspace, iid, output))
    with st.expander("Record edits reconciled manually in Word"):
        reconciled = selected_file(
            workspace, "Manually reconciled manuscript", "manual_reconciled"
        )
        accepted = {
            i["id"]: i
            for r in reviews.values()
            for i in r["items"]
            if i["status"] == "accepted"
        }
        selected = st.multiselect(
            "Accepted items reconciled",
            list(accepted),
            format_func=lambda k: accepted[k]["kind"] + " " + k[:8],
        )
        who = st.text_input("Manual reconciliation reviewer")
        why = st.text_area("Manual reconciliation reason")
        if st.button("Record manual reconciliation"):
            action(
                lambda: record_manual_reconciliation(
                    workspace, iid, reconciled, selected, who, why
                )
            )
    response = st.text_input(
        "New draft response document", str(Path(workspace) / "coauthor-response.docx")
    )
    if st.button("Prepare draft response"):
        action(lambda: export_response(workspace, iid, response))
