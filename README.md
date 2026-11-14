# <div align="center">🎻 PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing</div>
<div align="center">Yiwen Song<sup>1</sup>, Yale Song<sup>1</sup>, Tomas Pfister<sup>1</sup>, and Jinsung Yoon<sup>1</sup></div>
<div align="center"><sup>1</sup>Google Cloud AI Research</div>
<br><br>

## RadhiantAi research trial fork

This fork supports OpenAI, Anthropic, Gemini and OpenAI-compatible endpoints. Writing, review and literature ranking can use different models. It removes generated-code execution and automatic email delivery. Outputs require human review.

Read [FORK_NOTES.md](FORK_NOTES.md) for configuration, search changes, safeguards and verification limits. The upstream authors listed above created PaperOrchestra; this fork is independently modified.


PaperOrchestra is a multi-agent framework for automated AI research paper writing. It transforms pre-writing materials (ideas, experimental logs and supplied figures) into draft LaTeX manuscripts, including literature synthesis.

Its agents handle outline generation, literature review, section writing and content refinement. The upstream architecture diagram below also shows plotting, which is disabled in this fork.

<div align="center">
  <img src="assets/overview.png" alt="PaperOrchestra Overview" width="90%"/>
</div>

## Key Features

- **Multi-Agent Pipeline**: Orchestrates agents for outline generation, literature review, section writing and content refinement.
- **Comprehensive Literature Synthesis**: Automatically searches, prioritizes, and integrates relevant literature into the manuscript.
- **Figures**: Uses supplied figures. Automatic figure generation is disabled in this fork.
- **LaTeX Automation**: Produces draft LaTeX manuscripts adhering to target conference templates.

## Installation

1.  **Environment Setup**: The project relies on a Conda environment named `paper_orchestra`. You can set up a similar environment with Python 3.11 and install the required dependencies.
    ```bash
    conda create -n paper_orchestra python=3.11
    conda activate paper_orchestra
    pip install -r requirements.txt
    ```

2. **Model configuration**: Copy `.env.example` to `.env`, choose a writer model and supply only the credentials for the providers you select. Review and literature-ranking models can be set separately. Model names use `openai:MODEL_ID`, `anthropic:MODEL_ID`, `gemini:MODEL_ID` or `compatible:MODEL_ID`. Do not commit `.env`.

3. **LaTeX**: Install a TeX distribution that provides `pdflatex` and `bibtex`, and ensure both commands are on PATH. Installing the Python requirements alone does not install these tools.

## Dataset

The dataset used for paper generation is **not included** in this code repository. It will be released separately at a later date.
Once available, you should download the dataset and place it under the `datasets/` directory.

## Usage

You can run the paper generation pipeline using the provided bash script or directly via the Python CLI.

### Using the Bash Script
```bash
./paper_writing_cli.sh
```

### Using the Python CLI directly
```bash
python paper_writing_cli.py \
  --raw_materials_dir /path_to_your_raw_materials/ \
  --latex_template_dir /path_to_your_latex_template/ \
  --output_dir /path_to_your_output_folder/ \
  --writer_model_name openai:YOUR_MODEL_ID
```

### Key Arguments
*   `--raw_materials_dir`: (Required) Directory containing the raw materials (e.g., idea and experimental log).
*   `--latex_template_dir`: (Required) Directory containing the LaTeX template (e.g., `templates/cvpr2025`).
*   `--output_dir`: Directory to output the generated paper. If not specified, an automatic folder with a timestamp is created.
*   `--use_plotting`: Retained for compatibility. `true` is rejected; supply checked figures instead.
*   `--writer_model_name`: LLM for writer and literature agents.
*   `--reflection_model_name`: Model for review and refinement; defaults to the writer.
*   `--search_model_name`: Model for ranking retrieved Semantic Scholar records; defaults to the writer.

### Interactive Demo

We provide an interactive Streamlit demo for the paper generation pipeline. For instructions on how to run and use it, please refer to the [README.md](frontend/README.md) in the `frontend` directory.

## Project Structure

*   `autoraters/`: Contains scripts for automated evaluation.
*   `methods/`: Core logic for agents and pipeline execution.
*   `templates/`: LaTeX templates for target conferences, you can add your own template by creating a new subfolder under this directory.
*   `utils/`: Utility functions for API calls, PDF handling, etc.

## Citation

If you find this repo or our paper helpful, please cite it as follows:

```bibtex
@article{song2026paperorchestra,
  title={PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing},
  author={Song, Yiwen and Song, Yale and Pfister, Tomas and Yoon, Jinsung},
  journal={arXiv preprint arXiv:2604.05018},
  year={2026}
}
```

# Disclaimer

This is not an officially supported Google product.
