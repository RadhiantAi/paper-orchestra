"""Offline manuscript exchange for chat-assisted research, without model API calls."""

import argparse
import json
import re
from pathlib import Path

from utils.research_quality import aggregate_constraints, fingerprint, numeric_audit
from utils.run_control import write_json


def import_manuscript(
    manuscript, output, facts=None, denominator=None, execution="chat_assisted"
):
    source, output = Path(manuscript), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    # Never overwrite an existing review session and its approvals.
    if (output / "manuscript_sections.json").exists():
        raise ValueError(
            "Review workspace already exists; select a new output directory."
        )
    text = source.read_text(encoding="utf-8")
    sections = {}
    chunks = re.split(r"(?m)(?=^#{1,2} )", text)
    for index, chunk in enumerate(chunks):
        if chunk.strip():
            title = chunk.splitlines()[0].lstrip("# ").strip()[:100]
            sections[f"{index:03d}_{title}"] = {"text": chunk, "approval": None}
    report = numeric_audit(text, denominator=denominator, facts=facts)
    report["aggregate_constraints"] = aggregate_constraints(facts or [])
    if report["aggregate_constraints"]:
        report["status"] = "needs_review"
    write_json(output / "numeric_audit.json", report)
    write_json(output / "manuscript_sections.json", sections)
    write_json(
        output / "exchange_manifest.json",
        {
            "execution": execution,
            "model_api_calls": 0,
            "source_name": source.name,
            "source_fingerprint": fingerprint(text),
            "facts_fingerprint": fingerprint(facts or []),
            "human_approval": "pending",
        },
    )
    return report


def export_sections(workspace, destination):
    sections = json.loads(
        (Path(workspace) / "manuscript_sections.json").read_text(encoding="utf-8")
    )
    destination = Path(destination)
    if destination.exists():
        raise ValueError("Choose a new export path to preserve earlier drafts.")
    destination.write_text(
        "\n\n".join(s["text"].rstrip() for s in sections.values()) + "\n",
        encoding="utf-8",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("manuscript")
    imp.add_argument("--output", required=True)
    imp.add_argument("--facts")
    imp.add_argument("--denominator", type=int)
    exp = sub.add_parser("export")
    exp.add_argument("workspace")
    exp.add_argument("--output", required=True)
    args = parser.parse_args()
    if args.command == "export":
        export_sections(args.workspace, args.output)
    else:
        facts = (
            json.loads(Path(args.facts).read_text(encoding="utf-8"))
            if args.facts
            else []
        )
        report = import_manuscript(
            args.manuscript, args.output, facts, args.denominator
        )
        print(
            json.dumps(
                {"status": report["status"], "findings": len(report["findings"])}
            )
        )


if __name__ == "__main__":
    main()
