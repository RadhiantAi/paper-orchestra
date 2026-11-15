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
    with st.expander("Restore a private recovery archive"):
        backup = st.file_uploader("Recovery archive", type=["zip", "porx"])
        dest = st.text_input(
            "New restored project folder", str(Path(root) / "restored-project")
        )
        with st.form("restore_passphrase", clear_on_submit=True):
            password = st.text_input(
                "Recovery passphrase (encrypted archives only)", type="password"
            )
            restore_clicked = st.form_submit_button(
                "Restore and open project", disabled=backup is None
            )
        if restore_clicked:
            import tempfile

            def restore():
                with tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / (
                        "backup.porx"
                        if backup.name.lower().endswith(".porx")
                        else "backup.zip"
                    )
                    path.write_bytes(backup.getvalue())
                    return restore_project(path, dest, password or None)

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
    with st.expander("Storage warnings and retention preview"):
        from utils.recovery_storage import retention_preview
        import json

        keep = int(
            st.number_input(
                "Recent snapshots to keep", min_value=1, max_value=10000, value=20
            )
        )
        days = int(
            st.number_input(
                "Also keep snapshots from the last number of days",
                min_value=0,
                max_value=36500,
                value=30,
            )
        )
        budget = st.number_input(
            "Project storage warning threshold (GiB)", min_value=0.1, value=5.0
        )
        st.caption(
            "The preview preserves shared objects and current project receipts. It deletes nothing. Keep a verified backup in separate protected storage before considering cleanup."
        )
        if st.button("Preview storage and retention"):
            report = action(
                lambda: retention_preview(workspace, keep, days, int(budget * 1024**3)),
                "Preview calculated. No files removed.",
            )
            if report:
                left, middle, right = st.columns(3)
                left.metric(
                    "Project size",
                    f"{report['storage']['project_bytes'] / 1024**2:,.1f} MiB",
                )
                middle.metric(
                    "Free disk space",
                    f"{report['storage']['disk_free_bytes'] / 1024**3:,.1f} GiB",
                )
                right.metric(
                    "Could free after review",
                    f"{report['estimated_reclaimable_bytes'] / 1024**2:,.1f} MiB",
                )
                if report["storage"]["warnings"] or report["problems"]:
                    st.warning(
                        "Storage or recovery inventory needs attention. Review the preview before relying on a cleanup estimate."
                    )
                st.write(
                    f"{report['snapshot_count']} snapshots found; {len(report['candidate_snapshots'])} are candidates for a separately approved cleanup."
                )
                if report["status"] == "blocked":
                    st.error(
                        "The recovery inventory is incomplete or unreadable. No cleanup candidates are proposed."
                    )
                st.download_button(
                    "Download retention preview",
                    json.dumps(report, indent=2),
                    "retention-preview.json",
                    "application/json",
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
    encrypted = st.checkbox("Encrypt the recovery export", value=False)
    st.caption(
        "Encrypted exports hide file names and contents. Use a long, unique passphrase stored separately. A lost passphrase cannot be recovered. Source and restored folders remain unencrypted. Encrypted exports support up to 127 MiB of source content."
    )
    destination = st.text_input(
        "New private backup ZIP",
        str(
            Path(workspace).parent
            / (
                Path(workspace).name
                + ("-recovery.porx" if encrypted else "-recovery.zip")
            )
        ),
        key="backup_destination_encrypted" if encrypted else "backup_destination_plain",
    )
    with st.form("backup_passphrase", clear_on_submit=True):
        password = st.text_input(
            "Export passphrase", type="password", disabled=not encrypted
        )
        repeated = st.text_input(
            "Repeat export passphrase", type="password", disabled=not encrypted
        )
        export_clicked = st.form_submit_button("Create checked recovery ZIP")
    if export_clicked:

        def export():
            if encrypted and password != repeated:
                raise ValueError("Passphrases do not match.")
            return backup_project(
                workspace, destination, selected, password if encrypted else None
            )

        result = action(export)
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
                mime="application/octet-stream" if encrypted else "application/zip",
            )
    st.caption(
        "Automatic snapshots retain the state before and after saved decisions. Restore to a new folder from the project chooser."
    )
