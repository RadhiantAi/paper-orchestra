"""Run: streamlit run review_app.py -- --workspace PATH"""

import argparse
from pathlib import Path

from frontend.research_review import render_review

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True)
args = parser.parse_args()
if (Path(args.workspace) / "project.json").exists():
    from frontend.project_review import render_project

    render_project(args.workspace)
else:
    render_review(args.workspace)
