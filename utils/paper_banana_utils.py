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

def execute_plot_code_worker(code_text):
    """Reject code execution even when called outside the command-line entry point."""
    raise RuntimeError("Generated Python execution is disabled. Supply checked figures.")


def generate_figure_visuals(*args, **kwargs):
    raise RuntimeError("Automatic figure generation is disabled. Supply checked figures.")


retrieve_few_shot_examples = generate_figure_visuals
predict_figure_content = generate_figure_visuals
style_figure_content = generate_figure_visuals
critique_and_revise_figure = generate_figure_visuals
generate_figure_caption = generate_figure_visuals
