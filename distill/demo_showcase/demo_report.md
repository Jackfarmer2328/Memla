# Memla Coding Distillation Demo

- Mode: `showcase`
- Repo: `C:\Users\samat\Project Memory\Project-Memory`
- DB: `.\memory.sqlite`
- Planner model: `qwen3.5:4b`
- Holdout cases: `.\distill\coding_holdout_cases.jsonl`

## Current Capability

- File recall: `1.0`
- Command recall: `1.0`

## Showcase Cases

### Case 1

**Prompt**: Give Memla a structured coding plan before the teacher responds by inferring likely files, commands, tests, and patch steps from accepted repo-specific examples.

- Predicted files: `tests/test_step6_coding_distillation.py, memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, tests/test_step5_locomo_graph_bridge.py, memory_system/distillation/__init__.py, memory_system/distillation/workflow_planner.py`
- Predicted commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Predicted tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- File recall: `1.0`
- Command recall: `1.0`
- Patch steps:
  - I'll extend the workflow planner and coding proxy to build and inject structured workflow plans, then add comprehensive test coverage
  - Extend `memory_system/distillation/workflow_planner
  - from typing import Dict, List, Optional, Tuple
  - from dataclasses import dataclass

### Case 2

**Prompt**: Create a clean export path that writes accepted coding traces plus workflow events into JSONL records for later training.

- Predicted files: `memory_system/distillation/workflow_planner.py, memory_system/distillation/coding_proxy.py, tests/test_step6_coding_distillation.py, memory_system/distillation/__init__.py, memory_system/distillation/exporter.py, memory_system/distillation/eval_harness.py`
- Predicted commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Predicted tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- File recall: `1.0`
- Command recall: `1.0`
- Patch steps:
  - I'll extend the workflow planner and coding proxy to build and inject structured workflow plans, then add comprehensive test coverage
  - Extend `memory_system/distillation/workflow_planner
  - from typing import Dict, List, Optional, Tuple
  - from dataclasses import dataclass

### Case 3

**Prompt**: Make the coding proxy persist actual shell runs and refresh the workspace snapshot after those commands execute.

- Predicted files: `memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, memory_system/distillation/workspace_capture.py, tests/test_step6_coding_distillation.py, memory_system/distillation/workflow_planner.py, memory_system/memory/chunk_manager.py`
- Predicted commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Predicted tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- File recall: `1.0`
- Command recall: `1.0`
- Patch steps:
  - I'll extend the workflow planner and coding proxy to build and inject structured workflow plans, then add comprehensive test coverage
  - Extend `memory_system/distillation/workflow_planner
  - from typing import Dict, List, Optional, Tuple
  - from dataclasses import dataclass

### Case 4

**Prompt**: Use accepted coding traces to supply repo-specific priors to the teacher, especially prior files and commands that worked.

- Predicted files: `memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, tests/test_step6_coding_distillation.py, memory_system/distillation/workflow_planner.py, memory_system/memory/chunk_manager.py, memory_system/main.py`
- Predicted commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Predicted tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- File recall: `1.0`
- Command recall: `1.0`
- Patch steps:
  - I'll add accepted-trace similarity retrieval and thread priors through the coding proxy with comprehensive test coverage
  - Create `memory_system/distillation/coding_log
  - from typing import List, Dict, Optional, Tuple
  - from dataclasses import dataclass

### Case 5

**Prompt**: Build an internal coding eval that grades Memla's predicted files and commands against expected repo-local outcomes.

- Predicted files: `memory_system/distillation/coding_proxy.py, memory_system/distillation/eval_harness.py, tests/test_step6_coding_distillation.py, memory_system/distillation/workflow_planner.py, memory_system/distillation/__init__.py, memory_system/memory/chunk_manager.py`
- Predicted commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Predicted tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- File recall: `1.0`
- Command recall: `1.0`
- Patch steps:
  - I'll extend the workflow planner and coding proxy to build and inject structured workflow plans, then add comprehensive test coverage
  - Extend `memory_system/distillation/workflow_planner
  - from typing import Dict, List, Optional, Tuple
  - from dataclasses import dataclass

## Run It

```powershell
cd "C:\Users\samat\Project Memory\Project-Memory"
py -3 -m memory_system.distillation.demo_runner --mode showcase --db ".\memory.sqlite" --repo_root "C:\Users\samat\Project Memory\Project-Memory" --user_id default --planner_model qwen3.5:4b --holdout_cases ".\distill\coding_holdout_cases.jsonl" --out_dir .\distill\demo_run
```
