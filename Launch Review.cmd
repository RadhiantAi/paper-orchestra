@echo off
cd /d "%~dp0"
set PAPER_NETWORK_MODE=offline
if not exist ".venv\Scripts\python.exe" (
  echo First install the pinned environment using the setup instructions in REVIEW_WORKBENCH.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m streamlit run review_app.py --server.address 127.0.0.1
