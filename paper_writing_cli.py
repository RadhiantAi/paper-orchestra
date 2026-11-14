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

import argparse
import sys
import os
import shutil
from datetime import datetime
from utils.literature_discovery import DiscoveryConfig, DiscoveryEngine
from utils.llm_backend_utils import (
    validate_model_configuration,
    ModelConfigurationError,
)


def main():
    parser = argparse.ArgumentParser(
        description="CLI for generating a single paper from the Paper Orchestra pipeline."
    )

    parser.add_argument(
        "--raw_materials_dir",
        required=True,
        help="Directory containing the raw materials (e.g. idea and experimental log).",
    )
    parser.add_argument(
        "--output_dir",
        default=None,
        help="Directory to output the generated paper. If not specified, an automatic folder is created.",
    )
    parser.add_argument(
        "--latex_template_dir",
        required=True,
        help="Directory containing the LaTeX template (e.g. cvpr2025/iclr2025).",
    )
    parser.add_argument(
        "--idea_filename",
        default="idea_sparse.md",
        help="Filename of the idea document within raw_materials. Default: idea_sparse.md",
    )
    parser.add_argument(
        "--experimental_log_filename",
        default="experimental_log.md",
        help="Filename of the experimental log within raw_materials. Default: experimental_log.md",
    )
    parser.add_argument(
        "--writer_model_name",
        default=os.getenv("PAPER_WRITER_MODEL"),
        help="Writer model as provider:model, or PAPER_WRITER_MODEL.",
    )
    parser.add_argument(
        "--reflection_model_name",
        default=os.getenv("PAPER_REVIEW_MODEL"),
        help="Review model as provider:model. Defaults to the writer.",
    )
    parser.add_argument(
        "--research_cutoff",
        default=None,
        help="Year-Month cutoff date for literature review (e.g., 2024-11). If not provided, defaults to current Year-Month.",
    )
    parser.add_argument(
        "--use_plotting",
        type=lambda x: str(x).lower() in ["true", "1", "yes"],
        default=False,
        help="Automatic figure generation is disabled in this fork. Supply checked figures instead.",
    )
    parser.add_argument(
        "--search_model_name",
        default=os.getenv("PAPER_SEARCH_MODEL"),
        help="Model for ranking retrieved papers. Defaults to the writer.",
    )
    parser.add_argument(
        "--literature_sources",
        help="Comma-separated sources; defaults to LITERATURE_SOURCES or all four databases.",
    )
    args = parser.parse_args()

    if args.use_plotting:
        parser.error(
            "Automatic figure generation is disabled. Supply checked figures in raw_materials/figures."
        )

    args.reflection_model_name = args.reflection_model_name or args.writer_model_name
    args.search_model_name = args.search_model_name or args.writer_model_name
    try:
        for selected_model in (
            args.writer_model_name,
            args.reflection_model_name,
            args.search_model_name,
        ):
            validate_model_configuration(selected_model)
    except ModelConfigurationError as error:
        parser.error(str(error))

    try:
        discovery_config = DiscoveryConfig.from_env()
        if args.literature_sources is not None:
            discovery_config.sources = tuple(
                s.strip() for s in args.literature_sources.split(",") if s.strip()
            )
            discovery_config.__post_init__()
        discovery_engine = DiscoveryEngine(discovery_config)
    except ValueError as error:
        parser.error(str(error))

    print(
        "DRAFT: Human review of methods, results and full-text citations is required."
    )

    if args.research_cutoff is None:
        args.research_cutoff = datetime.now().strftime("%Y-%m")

    if not os.path.exists(args.raw_materials_dir):
        print(
            f"Error: Raw materials directory '{args.raw_materials_dir}' does not exist."
        )
        sys.exit(1)

    if args.output_dir:
        base_dir = args.output_dir
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_dir = f"./paper_output_{timestamp}"

    os.makedirs(base_dir, exist_ok=True)

    target_raw_materials = os.path.join(base_dir, "raw_materials")
    if os.path.abspath(target_raw_materials) != os.path.abspath(args.raw_materials_dir):
        if os.path.exists(target_raw_materials):
            shutil.rmtree(target_raw_materials)
        shutil.copytree(args.raw_materials_dir, target_raw_materials)

    if not args.use_plotting:
        has_figures = False
        figures_dir = os.path.join(args.raw_materials_dir, "figures")
        if os.path.exists(figures_dir):
            for f in os.listdir(figures_dir):
                if f.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")):
                    has_figures = True
                    break

        if not has_figures:
            print("\n" + "=" * 80)
            print(
                f"⚠️ WARNING: No figures (.pdf, .png, .jpg) detected in the {figures_dir} directory."
            )
            print(
                "Since you are running WITHOUT plotting, we are using the provided materials directly."
            )
            print(
                f"Please make sure you provide all necessary figures inside {figures_dir}."
            )
            print("If figures are missing, compilation may fail.")
            print(
                "Supply checked figures and their captions before generating a manuscript that needs figures."
            )
            print("=" * 80 + "\n")

    from methods.paper_writer import write_single_paper

    provided_figures_dir = os.path.join(args.raw_materials_dir, "figures")
    print(
        f"🚀 Starting Paper Generation (WITHOUT PLOTTING), with figures stored in {provided_figures_dir}"
    )
    success = write_single_paper(
        base_dir=base_dir,
        latex_template_dir=args.latex_template_dir,
        idea_filename=args.idea_filename,
        experimental_log_filename=args.experimental_log_filename,
        writer_model_name=args.writer_model_name,
        reflection_model_name=args.reflection_model_name,
        research_cutoff=args.research_cutoff,
        search_model_name=args.search_model_name,
        discovery_engine=discovery_engine,
    )

    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()
