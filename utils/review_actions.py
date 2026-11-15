"""Shared local review actions for the screen and command-line clients."""

from pathlib import Path
import hashlib
import re
import json
from utils.project_store import private_path, load_project, update_project, file_receipt
from utils.project_results import approve_results
from utils.project_figures import figure_identity
from utils.project_review import compare_versions
from utils.research_quality import fingerprint
from utils.run_control import digest


def save_uploads(workspace, uploads):
    directory = private_path(workspace) / "uploads"
    directory.mkdir(exist_ok=True)
    paths = []
    names = {}
    for name, blob in uploads:
        if len(blob) > 200 * 1024**2:
            raise ValueError("File exceeds the 200 MB limit.")
        suffix = Path(name).suffix.lower()
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            raise ValueError("Choose a file with a recognised extension.")
        target = directory / (hashlib.sha256(blob).hexdigest() + suffix)
        if target.exists():
            if target.read_bytes() != blob:
                raise ValueError("Existing upload differs from its content hash.")
        else:
            with target.open("xb") as f:
                f.write(blob)
        paths.append(target)
        names[str(target.resolve())] = re.split(r"[\\/]", name)[-1]
    update_project(workspace, lambda d: d.setdefault("upload_names", {}).update(names))
    return paths


def approve_selected(workspace, ids, reviewer, reason):
    def apply(data):
        rows = [r for r in data["results"] if r["id"] in ids]
        if not ids or {r["id"] for r in rows} != set(ids):
            raise ValueError("Select known results to approve.")
        from utils.analysis_recipes import calculated_result_current

        for row in rows:
            if row.get("calculation_id"):
                calc = next(
                    (
                        c
                        for c in data["calculations"]
                        if c["id"] == row["calculation_id"]
                    ),
                    None,
                )
                if not calculated_result_current(row, calc):
                    raise ValueError("Calculation is stale or differs from the result.")
        approve_results(rows, reviewer, reason)

    return update_project(workspace, apply)


def confirm_figure(workspace, figure_id, checks, reviewer, reason):
    allowed = {
        "image_identity",
        "caption",
        "clinical",
        "cohort",
        "reproduction",
        "privacy",
    }
    if (
        not checks
        or set(checks) - allowed
        or not reviewer.strip()
        or not reason.strip()
    ):
        raise ValueError("Select checks and provide a reviewer and reason.")

    def apply(data):
        figure = next(f for f in data["figures"] if f["id"] == figure_id)
        for check in checks:
            figure.setdefault("checks", {})[check] = {
                "status": "confirmed",
                "reviewer": reviewer,
                "reason": reason,
                "identity": figure_identity(figure),
            }

    return update_project(workspace, apply)


def review_edit(workspace, before_id, after_id, key, status, reviewer, reason):
    if (
        status not in {"retained", "rejected", "superseded"}
        or not reviewer.strip()
        or not reason.strip()
    ):
        raise ValueError("A disposition, reviewer and reason are required.")

    def apply(data):
        by_id = {s["id"]: s for s in data["sources"]}
        report = compare_versions(by_id[before_id], by_id[after_id])
        if key not in {e["fingerprint"] for e in report["edits"]}:
            raise ValueError("The comparison changed; select the edit again.")
        data.setdefault("edit_decisions", []).append(
            {
                "fingerprint": key,
                "status": status,
                "reviewer": reviewer,
                "reason": reason,
            }
        )

    return update_project(workspace, apply)


def build_spec(
    workspace,
    manuscript,
    title,
    extras,
    mappings,
    stage,
    journal=None,
    results_folder=None,
):
    files = []
    for role, path in [("manuscript", manuscript), ("title_page", title)]:
        path = Path(path)
        if path.suffix.lower() != ".docx":
            raise ValueError("Select Word documents for the manuscript and title page.")
        files.append(
            {
                "role": role,
                "name": "Manuscript.docx" if role == "manuscript" else "TitlePage.docx",
                "preserve": role == "title_page",
                **file_receipt(path),
            }
        )
    for index, path in enumerate(extras, 1):
        path = Path(path)
        files.append(
            {
                "role": "supplement",
                "name": f"Supplement{index}{path.suffix.lower()}",
                "preserve": True,
                **file_receipt(path),
            }
        )
    spec = {
        "stage": stage,
        "files": files,
        "result_mappings": mappings,
        "apply_reviews": True,
        "render": True,
        "generate_figures": bool(load_project(workspace)["figures"]),
    }
    if journal:
        spec["journal_profile"] = journal
    if results_folder:
        folder = Path(results_folder)
        receipt_path = folder / "results_receipt.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt["results_fingerprint"] != fingerprint(
            load_project(workspace)["results"]
        ):
            raise ValueError(
                "Results export is stale. Export current approved results again."
            )
        names = {
            name: name
            for name in ("results.csv", "results.md", "results.png", "results.pdf")
        }
        for name in names:
            if receipt["files"].get(name) != digest(folder / name):
                raise ValueError("A statistical asset changed after export.")
            files.append(
                {
                    "role": "statistical_asset",
                    "name": name,
                    "preserve": True,
                    **file_receipt(folder / name),
                }
            )
        spec["result_assets"] = [
            {"receipt": str(receipt_path.resolve()), "files": names}
        ]
    return spec
