"""Local project chooser, recovery controls and file selection."""

from pathlib import Path
import re
import streamlit as st
from utils.project_store import (
    create_project,
    load_project,
    private_path,
    dependency_status,
)
from utils.project_review import query_status
from utils.project_results import approved
from utils.project_figures import figure_issues
from utils.project_recovery import backup_project, restore_project


def choose_folder():
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(parent=root, mustexist=True)
    finally:
        root.destroy()


def project_home():
    from frontend.project_review import action

    st.title("Open a manuscript project")
    st.caption("Private local projects. Live models stay off.")
    root = st.text_input(
        "Projects folder",
        str(Path.home() / "PaperOrchestraProjects"),
        key="projects_root",
    )
    if st.button("Browse for projects folder"):
        chosen = action(choose_folder, "Folder selected.")
        if chosen:
            st.session_state["chosen_root"] = chosen
            st.rerun()
    projects = (
        sorted(p for p in Path(root).glob("*/project.json"))
        if Path(root).is_dir()
        else []
    )
    if projects:
        selected = st.selectbox(
            "Existing project", projects, format_func=lambda p: p.parent.name
        )
        if st.button("Open selected project"):
            st.session_state["workspace"] = str(selected.parent)
            st.rerun()
    with st.expander("Create a project"):
        name = st.text_input("New project name")
        if st.button("Create and open project"):

            def create():
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,79}", name):
                    raise ValueError(
                        "Use a simple project name without slashes or dots."
                    )
                path = private_path(Path(root) / name)
                create_project(path)
                return path

            path = action(create)
            if path:
                st.session_state["workspace"] = str(path)
                st.rerun()
    with st.expander("Restore a private recovery ZIP"):
        backup = st.file_uploader("Recovery archive", type=["zip"])
        dest = st.text_input(
            "New restored project folder", str(Path(root) / "restored-project")
        )
        if st.button("Restore and open project", disabled=backup is None):
            import tempfile

            def restore():
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / "backup.zip"
                    path.write_bytes(backup.getvalue())
                    return restore_project(path, dest)

            if action(restore):
                st.session_state["workspace"] = dest
                st.rerun()


def selected_file(workspace, label, key, extensions=("docx",)):
    from utils.review_actions import save_uploads

    data = load_project(workspace)
    choices = [None] + [
        s["path"]
        for s in data["sources"]
        if s.get("path") and Path(s["path"]).suffix.lower().lstrip(".") in extensions
    ]
    with st.expander("Choose " + label.lower()):
        selected = st.selectbox(
            "Indexed file",
            choices,
            key=key + "_choice",
            format_func=lambda x: (
                "Choose a file"
                if x is None
                else data.get("upload_names", {}).get(x, Path(x).name)
            ),
        )
        upload = st.file_uploader(
            "Browse files", type=list(extensions), key=key + "_upload"
        )
        if st.button(
            "Use selected file", key=key + "_use", disabled=not (upload or selected)
        ):
            if upload:
                # Save outside action's automatic refresh so the selection is retained first.
                try:
                    selected = str(
                        save_uploads(workspace, [(upload.name, upload.getvalue())])[0]
                    )
                except (OSError, ValueError) as exc:
                    st.error(str(exc))
                    selected = None
            if selected:
                st.session_state[key] = selected
                st.rerun()
    return st.text_input(label, key=key)


def readiness(data):
    from utils.coauthor_review import coauthor_findings

    return {
        "Changed or missing sources": len(dependency_status(data)),
        "Incomplete sources": sum(
            s["status"] in {"partial", "unreadable"} for s in data["sources"]
        ),
        "Author questions": sum(
            query_status(q, data["sources"]) != "resolved" for q in data["queries"]
        ),
        "Unapproved results": sum(not approved(r) for r in data["results"]),
        "Figure checks": sum(len(figure_issues(f)) for f in data["figures"]),
        "Co-author items": len(coauthor_findings(data)),
    }


def recovery_screen(workspace):
    from frontend.project_review import action

    st.subheader("Project backup and recovery")
    st.warning(
        "Recovery ZIPs contain private sources and review history. Keep them private; use the separate review-pack export for co-authors."
    )
    snapshots = sorted(
        (Path(workspace) / ".recovery" / "snapshots").glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    selected = st.selectbox(
        "Snapshot to export",
        [None] + snapshots,
        format_func=lambda p: "Current project" if p is None else p.name,
    )
    destination = st.text_input(
        "New private backup ZIP",
        str(Path(workspace).parent / (Path(workspace).name + "-recovery.zip")),
    )
    if st.button("Create checked recovery ZIP"):
        result = action(lambda: backup_project(workspace, destination, selected))
        if result:
            if result["status"] == "incomplete":
                st.warning(
                    "This backup is incomplete because referenced files are missing. Review the missing-file inventory before relying on it."
                )
            st.write(result)
            st.download_button(
                "Download private backup",
                Path(destination).read_bytes(),
                file_name=Path(destination).name,
                mime="application/zip",
            )
    st.caption(
        "Automatic snapshots retain the state before and after saved decisions. Restore to a new folder from the project chooser."
    )
