# Memla Head-to-Head Coding Demo

- Teacher model: `claude-sonnet-4-20250514`
- Repo: `C:\Users\samat\Project Memory\Project-Memory`
- Cases: `3`

## Aggregate Result

- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.7778`
- Memla plan command recall: `1.0`
- Memla combined file recall: `0.8889`
- Memla combined command recall: `1.0`

## Case 1

**Prompt**: Ship a ready-made demo experience for Memla's coding distillation results, including markdown and JSON artifacts for the current state.

- Expected files: `memory_system/distillation/demo_runner.py, memory_system/distillation/__init__.py, tests/test_step6_coding_distillation.py`
- Expected commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.6667`
- Memla plan command recall: `1.0`
- Memla combined file recall: `0.6667`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `memla/cli.py, memla/core.py, distill.py, demo/run_demo.py`
- Commands: ``
- Answer excerpt: I'll help you create a ready-made demo experience for Memla's coding distillation results. Based on the repository structure, I'll create comprehensive demo artifacts that showcase the distillation capabilities. ## Demo Structure Let me...

**Memla in front**

- Prior trace ids: `21, 18, 20, 13`
- Plan files: `tests/test_step6_coding_distillation.py, memory_system/distillation/coding_proxy.py, memory_system/distillation/workflow_planner.py, memory_system/distillation/eval_harness.py, memory_system/distillation/__init__.py, memory_system/distillation/workspace_capture.py`
- Plan commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Plan tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Combined files: `tests/test_step6_coding_distillation.py, memory_system/distillation/coding_proxy.py, memory_system/distillation/workflow_planner.py, memory_system/distillation/eval_harness.py, memory_system/distillation/__init__.py, memory_system/distillation/workspace_capture.py, demo/run_demo.py, test_auth.py, middleware/rate_limit.py, api/routes.py, demo/analyze_predictions.py, demo/generate_samples.py, demo/export_training_data.py, tests/test_processor.py, tests/test_auth.py, manage.py`
- Combined commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Answer excerpt: [Thought] The user wants me to create a comprehensive demo experience showcasing Memla's coding distillation capabilities. Based on the retrieved memory, this should include markdown documentation and JSON artifacts that demonstrate the...
- Patch steps:
  - I'll extend the workflow planner and coding proxy to build and inject structured workflow plans, then add comprehensive test coverage
  - Extend `memory_system/distillation/workflow_planner
  - from typing import Dict, List, Optional, Tuple
  - from dataclasses import dataclass

## Case 2

**Prompt**: Add a buyer-facing raw-teacher versus Memla comparison runner for coding tasks and export it from the distillation package with regression coverage.

- Expected files: `memory_system/distillation/comparison_runner.py, memory_system/distillation/__init__.py, tests/test_step6_coding_distillation.py`
- Expected commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `0.6667`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `src/distillation/comparison/coding_comparison.py, src/distillation/evaluation/code_evaluator.py`
- Commands: ``
- Answer excerpt: I'll help you create a buyer-facing comparison runner for coding tasks between raw-teacher and Memla models. Let me analyze the repository structure and implement this feature. Based on the codebase structure, I'll create a comparison ru...

**Memla in front**

- Prior trace ids: `17, 20, 12, 7`
- Plan files: `tests/test_step6_coding_distillation.py, memory_system/distillation/coding_proxy.py, memory_system/distillation/__init__.py, memory_system/distillation/exporter.py, memory_system/distillation/eval_harness.py, memory_system/distillation/workspace_capture.py`
- Plan commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Plan tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Combined files: `tests/test_step6_coding_distillation.py, memory_system/distillation/coding_proxy.py, memory_system/distillation/__init__.py, memory_system/distillation/exporter.py, memory_system/distillation/eval_harness.py, memory_system/distillation/workspace_capture.py, memory_system/distillation/comparison_runner.py`
- Combined commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Answer excerpt: [Thought] The user wants me to create a comparison runner that shows the difference between raw teacher responses and Memla-enhanced responses for coding tasks. This should be buyer-facing (demo-ready) and include regression test coverag...
- Patch steps:
  - I'll add JSONL export support with the required files and test coverage
  - Create `memory_system/distillation/exporter
  - from typing import Dict, List, Iterator, Optional, Any
  - from dataclasses import dataclass, asdict

## Case 3

**Prompt**: Store the ranked planned files in coding trace metadata instead of the noisier raw suggestion list, while still preserving the raw list for analysis.

- Expected files: `memory_system/distillation/coding_proxy.py, tests/test_step6_coding_distillation.py`
- Expected commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `aider/coders/base_coder.py, aider/coders/wholefile_coder.py, aider/models/coding_trace.py, aider/dump.py, tests/test_coding_trace.py, tests/test_coder.py`
- Commands: ``
- Answer excerpt: Looking at the codebase, I can see this relates to the coding trace system that tracks file planning and suggestions. You want to store a cleaner ranked list in the metadata while keeping the raw suggestions available. Here's the impleme...

**Memla in front**

- Prior trace ids: `21, 19, 20, 18`
- Plan files: `memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, tests/test_step6_coding_distillation.py, memory_system/distillation/__init__.py, memory_system/distillation/workflow_planner.py, memory_system/distillation/eval_harness.py`
- Plan commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Plan tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Combined files: `memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, tests/test_step6_coding_distillation.py, memory_system/distillation/__init__.py, memory_system/distillation/workflow_planner.py, memory_system/distillation/eval_harness.py`
- Combined commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Answer excerpt: [Thought] The user wants me to modify the coding trace storage to store ranked planned files in the metadata while preserving the raw suggestion list for analysis purposes. Based on the retrieved memory, this aligns with the decision to...
- Patch steps:
  - I'll extend the workflow planner and coding proxy to build and inject structured workflow plans, then add comprehensive test coverage
  - Extend `memory_system/distillation/workflow_planner
  - from typing import Dict, List, Optional, Tuple
  - from dataclasses import dataclass

## Run It

```powershell
cd "C:\Users\samat\Project Memory\Project-Memory"
. .\.anthropic_env.ps1
py -3 -m memory_system.distillation.comparison_runner --db ".\memory.sqlite" --repo_root "C:\Users\samat\Project Memory\Project-Memory" --user_id default --teacher_model claude-sonnet-4-20250514 --cases ".\distill\coding_unseen_cases_v2.jsonl" --out_dir .\distill\head_to_head_demo
```
