"""Offline enforcement of exact Python and GitHub Actions build dependencies."""

from pathlib import Path
import re
import sys
import yaml


def findings(root):
    root = Path(root)
    problems = []
    lines = (root / "requirements-lock.txt").read_text().splitlines()
    packages = set()
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;*]+)(?:\s*;.*)?", line)
        if not match:
            problems.append("Unpinned requirement: " + line.split("=")[0])
        elif match[1].lower().replace("_", "-") in packages:
            problems.append("Duplicate requirement: " + match[1])
        else:
            packages.add(match[1].lower().replace("_", "-"))
    for path in (root / ".github" / "workflows").glob("*.y*ml"):
        workflow = yaml.safe_load(path.read_text())
        for job in workflow.get("jobs", {}).values():
            for step in [job, *job.get("steps", [])]:
                use = step.get("uses")
                if (
                    use
                    and not use.startswith("./")
                    and not re.fullmatch(r"[A-Za-z0-9_.\-/]+@[a-f0-9]{40}", use)
                ):
                    problems.append("Unpinned action in " + path.name)
    return problems


if __name__ == "__main__":
    errors = findings(Path(__file__).resolve().parents[1])
    print("\n".join(errors) if errors else "Build dependency pins checked.")
    sys.exit(bool(errors))
