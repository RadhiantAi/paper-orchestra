"""Run: streamlit run review_app.py -- --workspace PATH"""

import argparse
from pathlib import Path
import streamlit as st

from frontend.research_review import render_review

parser = argparse.ArgumentParser()
parser.add_argument("--workspace")
args = parser.parse_args()
st.set_page_config(page_title="Manuscript review", layout="wide")
if "chosen_root" in st.session_state:
    st.session_state["projects_root"] = st.session_state.pop("chosen_root")
if "workspace" not in st.session_state:
    st.session_state["workspace"] = args.workspace
workspace = st.session_state["workspace"]
if workspace and st.sidebar.button("Choose another project"):
    st.session_state["workspace"] = None
    st.rerun()
if not workspace:
    from frontend.project_home import project_home

    project_home()
elif (Path(workspace) / "project.json").exists():
    from frontend.project_review import render_project

    render_project(workspace)
else:
    render_review(workspace)
