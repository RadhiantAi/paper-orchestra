"""Deterministic aggregate plots from reviewed continuous calculation fields."""

import json
from pathlib import Path
import re
import shutil
from utils.project_store import (
    load_project,
    update_project,
    private_path,
    file_receipt,
    current_file,
    upsert,
)
from utils.continuous_results import resolve_continuous, result_identity
from utils.research_quality import fingerprint
from utils.run_control import write_json, digest


def figure_values(data, spec):
    if set(spec) != {"id", "title", "axis_label", "items"} or not re.fullmatch(
        r"[\w.-]+", spec.get("id", "")
    ):
        raise ValueError("Provide a simple figure ID, title, axis label and items.")
    if (
        not all(
            isinstance(spec[k], str) and spec[k].strip()
            for k in ["title", "axis_label"]
        )
        or not isinstance(spec["items"], list)
        or not 1 <= len(spec["items"]) <= 30
    ):
        raise ValueError("Provide labelled axes and one to thirty plotted results.")
    formatted = resolve_continuous(data)
    results = {r["id"]: r for r in data.get("continuous_results", [])}
    values, units, identities, levels = [], set(), {}, set()
    for item in spec["items"]:
        if (
            set(item) - {"result_id", "interval_id", "label"}
            or not isinstance(item.get("label"), str)
            or not item["label"].strip()
        ):
            raise ValueError(
                "Each point needs a result ID and a label; interval ID is optional."
            )
        row = results.get(item.get("result_id"))
        if row is None or isinstance(row["value"], list):
            raise ValueError("Select a reviewed scalar result for each point.")
        value = row["value"]
        bounds, interval_text = None, None
        interval = (
            results.get(item.get("interval_id")) if item.get("interval_id") else None
        )
        if item.get("interval_id") and interval is None:
            raise ValueError("Unknown interval result.")
        if interval:
            a, b = row["selector"], interval["selector"]
            valid_pair = (a["field"], b["field"]) in {
                ("mean", "ci"),
                ("coefficients", "coefficient_ci"),
            }
            same_selector = {k: v for k, v in a.items() if k != "field"} == {
                k: v for k, v in b.items() if k != "field"
            }
            if (
                not valid_pair
                or not same_selector
                or row["calculation_id"] != interval["calculation_id"]
                or row["unit"] != interval["unit"]
                or not isinstance(interval["value"], list)
            ):
                raise ValueError(
                    "Intervals must describe the same calculation, group and coefficient/variable as their point."
                )
            bounds = interval["value"]
            interval_text = formatted[interval["id"]]
            calculation = next(
                c for c in data["calculations"] if c["id"] == row["calculation_id"]
            )
            levels.add(calculation["recipe"].get("confidence", 0.95))
            identities[interval["id"]] = result_identity(interval)
        units.add(row["unit"])
        identities[row["id"]] = result_identity(row)
        values.append(
            {
                "id": row["id"],
                "label": item["label"],
                "value": value,
                "interval": bounds,
                "display_value": formatted[row["id"]],
                "display_interval": interval_text,
            }
        )
    if len(units) != 1 or len({v["label"] for v in values}) != len(values):
        raise ValueError("One figure requires common units and unique point labels.")
    if len(levels) > 1:
        raise ValueError("Use one confidence level per figure.")
    return {
        "spec": spec,
        "unit": units.pop(),
        "values": values,
        "result_identities": identities,
        "confidence": next(iter(levels), None),
        "renderer_sha256": digest(__file__),
        "author_approval": False,
    }


def export_continuous_figure(workspace, spec, destination):
    data = load_project(workspace)
    plot = figure_values(data, spec)
    dest = private_path(destination)
    if dest.exists():
        raise ValueError("Choose a new continuous figure directory.")
    dest.mkdir(parents=True)
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    fig, ax = plt.subplots(figsize=(9, max(3, len(plot["values"]) * 0.55)))
    try:
        for i, point in enumerate(plot["values"]):
            if point["interval"]:
                ax.hlines(i, *point["interval"], linewidth=2, color="#315b7d")
            ax.plot(point["value"], i, "o", color="#17354c")
            label = point["display_value"]
            if point["display_interval"]:
                label += " (" + point["display_interval"] + ")"
            ax.annotate(
                label,
                (point["value"], i),
                xytext=(6, 7),
                textcoords="offset points",
                fontsize=8,
            )
        ax.set_yticks(range(len(plot["values"])), [v["label"] for v in plot["values"]])
        ax.invert_yaxis()
        ax.set_xlabel(spec["axis_label"] + " (" + plot["unit"] + ")")
        ax.set_title(
            spec["title"]
            + (
                f"\nBars show {plot['confidence'] * 100:g}% confidence intervals"
                if plot["confidence"]
                else ""
            )
        )
        ax.margins(x=0.2, y=0.25)
        fig.tight_layout()
        fig.savefig(dest / "figure.png", dpi=200)
        fig.savefig(
            dest / "figure.pdf", metadata={"CreationDate": None, "ModDate": None}
        )
    finally:
        plt.close(fig)
    write_json(dest / "plot-data.json", plot)
    record = {
        "id": spec["id"],
        "spec": spec,
        "plot_identity": fingerprint(plot),
        "assets": [
            file_receipt(dest / name)
            for name in ["figure.png", "figure.pdf", "plot-data.json"]
        ],
    }
    write_json(dest / "figure-receipt.json", record)
    record["receipt"] = file_receipt(dest / "figure-receipt.json")

    def apply(current):
        if fingerprint(figure_values(current, spec)) != record["plot_identity"]:
            raise ValueError("Calculation changed while rendering.")
        upsert(current.setdefault("continuous_figures", []), record)
        from utils.strict_trial import register_derived

        register_derived(
            current,
            [r["path"] for r in record["assets"]] + [record["receipt"]["path"]],
            "continuous_figure",
        )

    update_project(workspace, apply)
    return record


def figure_current(data, record):
    try:
        return record["plot_identity"] == fingerprint(
            figure_values(data, record["spec"])
        ) and all(current_file(r) for r in record["assets"] + [record["receipt"]])
    except (ValueError, KeyError, OSError, TypeError):
        return False


def copy_figures(data, ids, output):
    if not isinstance(ids, list) or len(ids) != len(set(ids)):
        raise ValueError("Select unique continuous figure IDs.")
    rows = {r["id"]: r for r in data.get("continuous_figures", [])}
    for fid in ids:
        if fid not in rows or not figure_current(data, rows[fid]):
            raise ValueError("Continuous figure is stale or unknown: " + str(fid))
        for receipt in rows[fid]["assets"]:
            suffix = Path(receipt["path"]).suffix
            if suffix not in {".png", ".pdf"}:
                continue
            target = Path(output) / "StatisticalFigures" / (fid + suffix)
            target.parent.mkdir(exist_ok=True)
            if target.exists():
                raise ValueError(
                    "Continuous figure output collides with an existing pack file."
                )
            shutil.copyfile(receipt["path"], target)


def audit_figures(data, ids, directory):
    findings = []
    rows = {r["id"]: r for r in data.get("continuous_figures", [])}
    for fid in ids:
        row = rows.get(fid)
        if not row or not figure_current(data, row):
            findings.append({"kind": "continuous_figure_stale", "id": fid})
            continue
        for asset in row["assets"]:
            suffix = Path(asset["path"]).suffix
            if suffix in {".png", ".pdf"} and not current_file(
                {
                    "path": str(
                        Path(directory) / "StatisticalFigures" / (fid + suffix)
                    ),
                    "sha256": asset["sha256"],
                }
            ):
                findings.append(
                    {
                        "kind": "continuous_figure_changed_or_missing",
                        "id": fid,
                        "format": suffix,
                    }
                )
    return findings
