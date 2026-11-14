"""Run: streamlit run review_app.py -- --workspace PATH"""

import argparse

from frontend.research_review import render_review

parser = argparse.ArgumentParser()
parser.add_argument("--workspace", required=True)
args = parser.parse_args()
render_review(args.workspace)
