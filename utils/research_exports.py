"""Editable Word drafts and evidence passages for human claim review."""

import csv
import json
from pathlib import Path
import re
import subprocess

from docx import Document
import pypandoc

from utils.run_control import write_json


def export_word(tex_path, output_path, bibliography=None):
    tex_path, output_path = Path(tex_path).resolve(), Path(output_path).resolve()
    temporary = output_path.with_suffix(".tmp.docx")
    command = [
        pypandoc.get_pandoc_path(),
        "--sandbox",
        "--from=latex",
        "--to=docx",
        "--standalone",
        str(tex_path),
        "--output",
        str(temporary),
    ]
    if bibliography and Path(bibliography).is_file():
        command.extend(
            ["--citeproc", "--bibliography", str(Path(bibliography).resolve())]
        )
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=60, cwd=tex_path.parent
    )
    if result.returncode or not temporary.is_file():
        raise RuntimeError("Word export failed. The PDF and LaTeX remain available.")
    document = Document(temporary)
    document.sections[0].header.paragraphs[0].text = "DRAFT - Human review required"
    document.core_properties.subject = "Editable research draft; verify equations, references and layout against the PDF."
    document.save(temporary)
    temporary.replace(output_path)
    write_json(
        output_path.with_name("word_export_report.json"),
        {
            "status": "created",
            "converter": "Pandoc with sandbox enabled",
            "warnings": result.stderr[-8000:],
            "review_required": "Compare equations, tables, images and citations with the compiled PDF.",
        },
    )


def evidence_ledger(tex_path, citation_map_path, output_dir):
    tex = Path(tex_path).read_text(encoding="utf-8")
    citations = json.loads(Path(citation_map_path).read_text(encoding="utf-8"))
    rows = []
    # Paragraphs are candidates for review, not automatically extracted atomic claims.
    for paragraph in re.split(r"\n\s*\n", tex):
        keys = [
            key.strip()
            for group in re.findall(r"\\cite\w*\*?(?:\[[^]]*\])?\{([^}]+)\}", paragraph)
            for key in group.split(",")
        ]
        if not keys and not re.search(
            r"\b\d+(?:\.\d+)?\s*(?:%|patients|participants|subjects)\b", paragraph, re.I
        ):
            continue
        claim = re.sub(r"\\cite\w*\*?(?:\[[^]]*\])?\{[^}]+\}", "", paragraph)
        claim = (
            re.sub(r"\\[A-Za-z]+(?:\[[^]]*\])?", "", claim)
            .replace("{", "")
            .replace("}", "")
            .strip()
        )
        words = set(re.findall(r"\w{4,}", claim.casefold()))
        for key in dict.fromkeys(keys or [""]):
            reference = citations.get(key)
            row = {
                "claim_context": claim,
                "citation_key": key,
                "doi": "",
                "pmid": "",
                "source_url": "",
                "evidence_level": "none",
                "candidate_passage": "",
                "passage_origin": "",
                "status": "missing_citation" if not key else "unknown_reference",
            }
            if reference:
                full_text, abstract = (
                    reference.get("full_text") or "",
                    reference.get("abstract") or "",
                )
                text = full_text or abstract
                passages = [
                    p.strip()
                    for p in re.split(r"(?<=[.!?])\s+|\n\n", text)
                    if p.strip()
                ]
                ranked = sorted(
                    passages,
                    key=lambda p: len(words & set(re.findall(r"\w{4,}", p.casefold()))),
                    reverse=True,
                )
                candidate = (
                    ranked[0]
                    if ranked
                    and words & set(re.findall(r"\w{4,}", ranked[0].casefold()))
                    else ""
                )
                row.update(
                    doi=reference.get("doi", ""),
                    pmid=reference.get("pmid", ""),
                    source_url=reference.get("url", ""),
                    evidence_level="full_text"
                    if full_text
                    else "abstract"
                    if abstract
                    else "metadata",
                    candidate_passage=candidate,
                    passage_origin="full_text"
                    if full_text
                    else "abstract"
                    if abstract
                    else "",
                    status="candidate_passage_needs_review"
                    if full_text and candidate
                    else "needs_full_text"
                    if not full_text
                    else "no_matching_passage",
                )
            rows.append(row)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    write_json(
        output / "evidence_review.json",
        {
            "status": "human_review_required",
            "method": "Lexical passage matching, not entailment verification. Uncited prose may remain outside this report.",
            "claims": rows,
        },
    )
    with (output / "evidence_review.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as stream:
        fields = [
            "claim_context",
            "citation_key",
            "doi",
            "pmid",
            "source_url",
            "evidence_level",
            "candidate_passage",
            "passage_origin",
            "status",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            # Avoid spreadsheet formula evaluation of untrusted source text.
            writer.writerow(
                {
                    k: "'" + v
                    if isinstance(v, str) and v.startswith(("=", "+", "-", "@"))
                    else v
                    for k, v in row.items()
                }
            )
    return rows
