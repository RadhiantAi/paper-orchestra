"""Compile generated TeX in a disposable, network-disabled container."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import uuid

from utils.draft_output import mark_pdf_as_draft


class CompilationError(RuntimeError):
    pass


def check_compiler():
    image = os.getenv("PAPER_TEX_IMAGE", "paper-orchestra-tex:local")
    try:
        result = subprocess.run(
            ["docker", "image", "inspect", image], capture_output=True, timeout=15
        )
        if result.returncode:
            raise CompilationError(
                "Docker or the local TeX image is unavailable. See RELIABILITY.md."
            )
    except (OSError, subprocess.TimeoutExpired):
        raise CompilationError(
            "Docker compilation is unavailable. See RELIABILITY.md."
        ) from None
    return image


def copy_build_inputs(source, destination):
    source, destination = Path(source).resolve(), Path(destination)
    allowed = {
        ".tex",
        ".bib",
        ".sty",
        ".bst",
        ".cls",
        ".png",
        ".jpg",
        ".jpeg",
        ".pdf",
        ".eps",
    }
    total = 0
    for path in source.rglob("*"):
        if path.is_symlink():
            raise CompilationError("Symlinks are not permitted in compilation inputs.")
        if not path.is_file() or path.suffix.lower() not in allowed:
            continue
        total += path.stat().st_size
        if total > 100_000_000:
            raise CompilationError("Compilation inputs exceed 100 MB.")
        target = destination / path.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def compile_latex(cwd, pdf_file, texfile_name="template", timeout=60):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", texfile_name):
        raise CompilationError("Invalid TeX job name.")
    image = check_compiler()
    logs = []
    with tempfile.TemporaryDirectory(prefix="paper-orchestra-tex-") as folder:
        work = Path(folder)
        copy_build_inputs(cwd, work)
        work.chmod(0o777)
        for item in work.rglob("*"):
            item.chmod(0o755 if item.is_dir() else 0o644)
        # Never accept a PDF copied from an earlier build.
        (work / f"{texfile_name}.pdf").unlink(missing_ok=True)
        commands = [
            [
                "pdflatex",
                "-no-shell-escape",
                "-halt-on-error",
                "-interaction=nonstopmode",
                f"{texfile_name}.tex",
            ]
        ]
        uses_bibtex = "\\bibliography{" in (work / f"{texfile_name}.tex").read_text(
            encoding="utf-8"
        )
        if uses_bibtex:
            commands.append(["bibtex", texfile_name])
        commands.extend([commands[0], commands[0]])
        try:
            for command in commands:
                name = "paper-tex-" + uuid.uuid4().hex
                args = [
                    "docker",
                    "run",
                    "--rm",
                    "--pull=never",
                    "--name",
                    name,
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--pids-limit=64",
                    "--memory=512m",
                    "--cpus=1",
                    "--user=65534:65534",
                    "--mount",
                    f"type=bind,source={work},target=/work",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=64m",
                    "--workdir=/work",
                    "--env=HOME=/tmp",
                    "--env=TEXMFVAR=/tmp/texmf",
                    "--env=openin_any=p",
                    "--env=openout_any=p",
                    "--entrypoint",
                    command[0],
                    image,
                    *command[1:],
                ]
                # A dedicated temporary mount is the only host data exposed to TeX.
                try:
                    result = subprocess.run(
                        args, capture_output=True, text=True, timeout=timeout
                    )
                except subprocess.TimeoutExpired:
                    subprocess.run(
                        ["docker", "rm", "-f", name], capture_output=True, timeout=15
                    )
                    raise CompilationError("TeX compilation timed out.") from None
                logs.append(
                    {
                        "command": command[0],
                        "returncode": result.returncode,
                        "stdout": result.stdout[-16000:],
                        "stderr": result.stderr[-4000:],
                    }
                )
                if result.returncode:
                    raise CompilationError(
                        "TeX compilation failed. See compilation_report.json."
                    )
            log_path = work / f"{texfile_name}.log"
            if not log_path.exists():
                raise CompilationError("TeX did not produce a validation log.")
            log = log_path.read_text(encoding="utf-8", errors="replace")
            if re.search(
                r"undefined references|undefined citations|Citation .+ undefined|Reference .+ undefined|Rerun to get cross-references right",
                log,
                re.I,
            ):
                raise CompilationError("TeX has unresolved citations or references.")
            pdf = work / f"{texfile_name}.pdf"
            if not pdf.is_file():
                raise CompilationError("TeX produced no PDF.")
            mark_pdf_as_draft(pdf)
            target = Path(pdf_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            staged = target.with_suffix(".pdf.tmp")
            shutil.copy2(pdf, staged)
            staged.replace(target)
        finally:
            Path(cwd, "compilation_report.json").write_text(
                json.dumps(logs, indent=2), encoding="utf-8"
            )
