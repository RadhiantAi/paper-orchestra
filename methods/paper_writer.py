# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import os.path as osp
import shutil
import traceback
import json
import tqdm
from concurrent.futures import ProcessPoolExecutor, as_completed

from utils.llm_backend_utils import validate_model_configuration
from utils.literature_discovery import DiscoveryEngine
from methods.agents.outline_agent import OutlineAgent
from methods.agents.literature_review_agent import HybridLiteratureAgent
from methods.agents.section_writing_agent import SectionWritingAgent
from methods.agents.content_refinement_agent import ContentRefinementAgent

from utils.common_utils import (
    create_log_folder,
)


def write_single_paper(
    base_dir,
    latex_template_dir,
    idea_filename="idea_dense.md",
    experimental_log_filename="experimental_log.md",
    writer_model_name=None,
    reflection_model_name=None,
    research_cutoff=None,
    search_model_name=None,
    discovery_engine=None,
    resume_run=None,
    run_policy=None,
    raw_materials_dir=None,
):
    from pathlib import Path
    from datetime import datetime
    import uuid
    from utils.provider_backend import resolve_model, call_llm_with_contents
    from utils.run_control import RunWorkspace, write_json
    from utils.model_policy import RunPolicy, use_policy
    from utils.safe_compile import check_compiler
    from utils.research_exports import evidence_ledger, export_word

    writer_model_name = writer_model_name or os.getenv("PAPER_WRITER_MODEL")
    reflection_model_name = (
        reflection_model_name or os.getenv("PAPER_REVIEW_MODEL") or writer_model_name
    )
    search_model_name = (
        search_model_name or os.getenv("PAPER_SEARCH_MODEL") or writer_model_name
    )
    models = [
        ":".join(resolve_model(m))
        for m in (writer_model_name, reflection_model_name, search_model_name)
    ]
    writer_model_name, reflection_model_name, search_model_name = models
    for model in models:
        validate_model_configuration(model)
    policy = run_policy or RunPolicy.from_env()
    has_figures = any(
        p.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf"}
        for p in (
            Path(raw_materials_dir)
            if raw_materials_dir
            else Path(base_dir, "raw_materials")
        )
        .joinpath("figures")
        .glob("*")
    )
    policy.check_role(writer_model_name, images=has_figures)
    policy.check_role(reflection_model_name, images=True)
    policy.check_role(search_model_name)
    discovery_engine = discovery_engine or DiscoveryEngine()
    research_cutoff = research_cutoff or datetime.now().strftime("%Y-%m")
    settings = {
        "models": models,
        "cutoff": research_cutoff,
        "idea_file": idea_filename,
        "log_file": experimental_log_filename,
        "discovery": vars(discovery_engine.config),
        "profiles": policy.profiles,
        "probe": policy.probe,
        "max_output_tokens": os.getenv("PAPER_MAX_OUTPUT_TOKENS", "16384"),
    }
    # Spending/call caps can be raised on explicit resume; completed inputs cannot change.
    run = RunWorkspace(
        base_dir, latex_template_dir, settings, resume_run, raw_materials_dir
    )
    folder = run.path
    materials = folder / "raw_materials"
    template = folder / "template_inputs"
    idea, log = materials / idea_filename, materials / experimental_log_filename
    if not idea.is_file() or not log.is_file():
        raise ValueError("The configured idea and experimental log files are required.")
    print(f"Run outputs: {folder}")

    def preflight():
        check_compiler()
        import pypandoc

        pypandoc.get_pandoc_path()
        checked = []
        for model in dict.fromkeys(models):
            images = model == reflection_model_name or (
                has_figures and model == writer_model_name
            )
            if policy.probe:
                contents = ['Return JSON {"ok": true}.']
                if images:
                    import io
                    from PIL import Image

                    buffer = io.BytesIO()
                    Image.new("RGB", (32, 32), "red").save(buffer, format="PNG")
                    contents = [
                        "Return JSON with ok true and colour equal to the dominant colour of the attached image.",
                        {"data": buffer.getvalue(), "mime_type": "image/png"},
                    ]
                answer = call_llm_with_contents(
                    contents,
                    model_name=model,
                    generation_configs={"max_output_tokens": 128},
                )
                if answer["parsed_response"].get("ok") is not True:
                    raise RuntimeError(
                        "Model capability probe did not return the expected JSON."
                    )
                if (
                    images
                    and str(answer["parsed_response"].get("colour", "")).lower()
                    != "red"
                ):
                    raise RuntimeError(
                        "Model did not identify the image in the capability probe."
                    )
            checked.append(
                {
                    "model": model,
                    "images_required": images,
                    "validation": "live_probe" if policy.probe else "declared_only",
                }
            )
        write_json(
            folder / "preflight.json",
            {"models": checked, "compiler": "local_container_image_available"},
        )

    def outline():
        OutlineAgent(model_name=writer_model_name, cutoff_date=research_cutoff).run(
            idea_file=str(idea),
            experimental_log_file=str(log),
            latex_template_file=str(template / "template.tex"),
            conference_guidelines_file=str(template / "guidelines.md"),
            output_filepath=str(folder / "outline.json"),
        )

    literature = folder / "literature_agent_output"

    def discover():
        HybridLiteratureAgent(
            str(idea),
            str(log),
            str(template / "template.tex"),
            str(template / "guidelines.md"),
            str(literature),
            model_name=writer_model_name,
            search_model_name=search_model_name,
            discovery_engine=discovery_engine,
        ).run(str(folder / "outline.json"), research_cutoff)

    latex = folder / "latex_writeup"

    def draft():
        shutil.copytree(template, latex, dirs_exist_ok=True)
        if (materials / "figures").exists():
            shutil.copytree(
                materials / "figures", latex / "figures", dirs_exist_ok=True
            )
        shutil.copy2(literature / "updated_template.tex", latex / "template.tex")
        shutil.copy2(literature / "references.bib", latex / "references.bib")
        SectionWritingAgent(
            outline_path=str(literature / "outline_v1.json"),
            template_path=str(latex / "template.tex"),
            idea_path=str(idea),
            experimental_log_path=str(log),
            citation_map_path=str(literature / "citation_map.json"),
            figures_info_path=str(latex / "figures" / "info.json"),
            guidelines_path=str(template / "guidelines.md"),
            model_name=writer_model_name,
        ).run(output_path=str(latex / "raw_draft_paper.tex"))

    def review():
        attempt = folder / "review_attempts" / uuid.uuid4().hex[:8]
        shutil.copytree(latex, attempt)
        result = ContentRefinementAgent(
            str(log),
            str(literature / "citation_map.json"),
            str(template / "guidelines.md"),
            model_name=reflection_model_name,
            work_dir=str(attempt),
        ).run(str(latex / "raw_draft_paper.tex"))
        if not Path(result).is_file():
            raise RuntimeError("Review did not produce a valid PDF.")
        shutil.copytree(attempt, folder / "reviewed", dirs_exist_ok=True)
        shutil.copy2(
            attempt / "final_refined_paper.tex", folder / "reviewed" / "main.tex"
        )
        shutil.copy2(result, folder / "final_paper.pdf")

    def exports():
        evidence_ledger(
            folder / "reviewed" / "main.tex", literature / "citation_map.json", folder
        )
        export_word(
            folder / "reviewed" / "main.tex",
            folder / "manuscript.docx",
            literature / "references.bib",
        )

    with run.lock(), use_policy(policy):
        policy.attach(folder)
        try:
            run.stage("preflight", preflight, ["preflight.json"])
            run.stage("outline", outline, ["outline.json"])
            run.stage("literature", discover, ["literature_agent_output"])
            run.stage("draft", draft, ["latex_writeup"])
            run.stage("review", review, ["reviewed", "final_paper.pdf"])
            run.stage(
                "exports",
                exports,
                [
                    "evidence_review.json",
                    "evidence_review.csv",
                    "manuscript.docx",
                    "word_export_report.json",
                ],
            )
            run.manifest.update(status="complete")
            run.save()
            return True
        except Exception as error:
            from utils.model_policy import ModelPolicyError
            from utils.safe_compile import CompilationError

            reason = (
                str(error)
                if isinstance(error, (ModelPolicyError, CompilationError))
                else "Inspect the stage reports; source exception text is not copied here."
            )
            run.manifest.update(
                status="failed", error_type=type(error).__name__, error=reason
            )
            run.save()
            print(
                f"Run stopped at {run.manifest.get('current_stage')}. Outputs preserved at {folder}."
            )
            # Provider errors are already sanitised. Do not echo arbitrary source exception messages.
            print(
                f"Failure type: {type(error).__name__}. Inspect the stage reports and resume this run."
            )
            return False


def process_paper_task(
    paper,
    output_dir,
    latex_template_dir,
    idea_filename,
    experimental_log_filename,
    writer_model_name,
    research_cutoff,
):
    """
    Worker function to process a single paper.
    Returns a dictionary with results to be handled by the main thread.
    """
    try:
        paper_id = paper["paper_id"]
        print(f"Starting processing for paper '{paper_id}'...")

        paper_dest_dir = osp.join(output_dir, paper_id)
        os.makedirs(paper_dest_dir, exist_ok=True)
        final_paper_path = osp.join(paper_dest_dir, "final_paper.pdf")

        result = {
            "paper_id": paper_id,
            "status": "failed",
            "paper_path": "",
        }

        success = write_single_paper(
            base_dir=paper_dest_dir,
            latex_template_dir=latex_template_dir,
            idea_filename=idea_filename,
            experimental_log_filename=experimental_log_filename,
            writer_model_name=writer_model_name,
            research_cutoff=research_cutoff,
            raw_materials_dir=paper["content_folder"],
        )
        if success:
            from utils.run_control import artifact_root

            result["status"] = "success"
            result["paper_path"] = str(
                artifact_root(paper_dest_dir) / "final_paper.pdf"
            )

        return result

    except Exception as e:
        print(f"CRITICAL ERROR in worker for paper {paper['paper_id']}: {e}")
        print(traceback.format_exc())
        return {"paper_id": paper["paper_id"], "status": "error", "error": str(e)}


def _load_papers_from_config(
    process_root_folder: bool,
    root_input_folder: str,
    paper_info_path: str,
    n_papers: int,
):
    """Loads a list of paper dictionaries from either a root folder or a JSON file."""
    if process_root_folder:
        if not root_input_folder:
            raise ValueError(
                "Please provide root_input_folder if process_root_folder is True."
            )
        all_papers_candidates = []
        all_paper_ids_raw = os.listdir(root_input_folder)
        all_paper_ids = [
            paper_id
            for paper_id in all_paper_ids_raw
            if os.path.isdir(os.path.join(root_input_folder, paper_id))
        ]
        for paper_id in all_paper_ids:
            content_folder = os.path.join(root_input_folder, paper_id, "raw_materials")
            pdf_path = os.path.join(root_input_folder, paper_id, f"{paper_id}.pdf")
            if not os.path.exists(content_folder) or not os.path.exists(pdf_path):
                continue
            paper_entry = {
                "paper_id": paper_id,
                "content_folder": content_folder,
                "pdf_path": pdf_path,
            }
            all_papers_candidates.append(paper_entry)
    else:
        if not paper_info_path:
            raise ValueError(
                "Please provide paper_info_path if process_root_folder is False."
            )
        with open(paper_info_path, "r") as f:
            all_papers_candidates = json.load(f)

    if n_papers < 0:
        n_papers = len(all_papers_candidates)
    else:
        n_papers = min(n_papers, len(all_papers_candidates))

    return all_papers_candidates[:n_papers]


def _load_logs(output_dir: str):
    """Loads existing logs to support resuming a batch job."""
    paper_writing_log_path = osp.join(output_dir, "paper_writing_log.json")
    write_log = {}
    if osp.exists(paper_writing_log_path):
        with open(paper_writing_log_path, "r") as f:
            write_log = json.load(f)
        print(f"Loaded existing writing log with {len(write_log)} entries.")

    return write_log


def _filter_and_prepare_papers(
    all_papers, write_log, process_root_folder, paper_info_path
):
    """Filters out completed papers and resolves paths."""
    papers_to_process = []
    base_info_dir = ""
    if (not process_root_folder) and (paper_info_path != ""):
        base_info_dir = osp.dirname(paper_info_path)

    for paper in all_papers:
        # Check if already successfully processed in log
        if (
            paper["paper_id"] in write_log
            and write_log[paper["paper_id"]].get("status") == "success"
            and osp.exists(write_log[paper["paper_id"]].get("paper_path", ""))
        ):
            continue

        if not osp.isabs(paper["content_folder"]):
            paper["content_folder"] = osp.join(base_info_dir, paper["content_folder"])
        if not osp.isabs(paper["pdf_path"]):
            paper["pdf_path"] = osp.join(base_info_dir, paper["pdf_path"])

        papers_to_process.append(paper)

    return papers_to_process


def run_batch_writeup(
    latex_template_dir: str,
    process_root_folder: bool = True,
    root_input_folder: str = "",
    paper_info_path: str = "",
    output_dir: str = "",
    output_dir_prefix: str = "",
    date_str: str = "",
    idea_filename: str = "idea_sparse.md",
    experimental_log_filename: str = "experimental_log.md",
    writer_model_name: str = None,
    research_cutoff: str = "2024-11",
    n_papers=-1,
    max_workers=4,
):
    if output_dir == "":
        output_dir = create_log_folder(prefix=output_dir_prefix, date_str=date_str)
    else:
        print(f"Resuming from output_dir = {output_dir}")
    os.makedirs(output_dir, exist_ok=True)

    all_papers = _load_papers_from_config(
        process_root_folder, root_input_folder, paper_info_path, n_papers
    )
    write_log = _load_logs(output_dir)

    papers_to_process = _filter_and_prepare_papers(
        all_papers, write_log, process_root_folder, paper_info_path
    )

    print(
        f"Starting batch writeup for {len(papers_to_process)} papers (skipped {len(all_papers) - len(papers_to_process)} already done)."
    )
    print(f"Parallel execution with max_workers={max_workers}")

    paper_writing_log_path = osp.join(output_dir, "paper_writing_log.json")
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                process_paper_task,
                paper,
                output_dir,
                latex_template_dir,
                idea_filename,
                experimental_log_filename,
                writer_model_name,
                research_cutoff,
            ): paper["paper_id"]
            for paper in papers_to_process
        }

        for future in tqdm.tqdm(
            as_completed(futures), total=len(futures), desc="Writing Papers"
        ):
            paper_id = futures[future]
            try:
                result = future.result()

                write_log[paper_id] = {
                    "status": result["status"],
                    "paper_path": result.get("paper_path", ""),
                }

                with open(paper_writing_log_path, "w") as f:
                    json.dump(write_log, f, indent=4)

            except Exception as e:
                print(f"Exception handling result for paper {paper_id}: {e}")

    success_count = sum(
        1 for entry in write_log.values() if entry.get("status") == "success"
    )
    error_count = sum(
        1 for entry in write_log.values() if entry.get("status") in ["failed", "error"]
    )

    print("\n" + "=" * 50)
    print("BATCH PROCESSING COMPLETE")
    print(f"Total Papers: {len(all_papers)}")
    print(f"Successfully written: {success_count}")
    print(f"Failed/Error: {error_count}")
    print(f"Logs saved to: {output_dir}")
    print("=" * 50 + "\n")

    return paper_writing_log_path
