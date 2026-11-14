# Paper Orchestra Frontend

This directory contains the Streamlit frontend for Paper Orchestra.

This fork accepts separate writer, review and literature-ranking models. Configure credentials in `.env` as described in [FORK_NOTES.md](../FORK_NOTES.md). Supply checked figures. Email delivery and automatic figure generation are disabled. PDFs are drafts for human review.

## How to Launch the Demo Locally

1. Ensure you have activated your environment and installed dependencies.
2. Navigate to the project root directory:
   ```bash
   cd paper-orchestra
   conda activate paper_orchestra
   ```
3. Run the Streamlit application:
   ```bash
   streamlit run frontend/app.py
   ```
4. Open the URL provided in the terminal (usually `http://localhost:8501` or similar) in your browser.

## How to Kill Unfinished Writing Processes

The frontend launches a background process (`paper_writing_cli.py`) to handle the paper generation. 

### Automatic Cleanup
On Linux, the application is configured to automatically kill the background process if the Streamlit server process is stopped. Simply pressing **Ctrl+C** in the terminal where you ran `streamlit run` should clean up the running pipeline.

### Manual Cleanup
If you disconnect from the frontend or the server stops unexpectedly without cleaning up, you may have orphan processes running in the background. You can kill them manually using:

```bash
pkill -f paper_writing_cli.py
```

Or to find the process ID (PID) first:
```bash
pgrep -f paper_writing_cli.py
```
And then kill it:
```bash
kill <PID>
```

On Windows, the worker starts without a visible console. Automatic child-process cleanup is Linux-specific; keep the terminal open until the run ends.

The demo now selects literature sources and the general medical template. Outputs include Word drafts, evidence-review tables and a search coverage report. Configure the model policy, estimated spending limit and local Docker TeX image as described in [RELIABILITY.md](../RELIABILITY.md). Saved-run resume is available through the CLI.
