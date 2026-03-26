# Memla Head-to-Head Coding Demo

- Teacher model: `claude-sonnet-4-20250514`
- Repo: `C:\Users\samat\Project Memory\Project-Memory`
- Cases: `3`

## Aggregate Result

- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

## Case 1

**Prompt**: Give Memla a structured coding plan before the teacher responds by inferring likely files, commands, tests, and patch steps from accepted repo-specific examples.

- Expected files: `memory_system/distillation/workflow_planner.py, memory_system/distillation/coding_proxy.py, tests/test_step6_coding_distillation.py`
- Expected commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: ``
- Commands: ``
- Answer excerpt: I'd be happy to help create a structured coding plan for Memla, but I need more context about what specific task or feature you're working on. To provide the most useful plan with repo-specific examples, could you clarify: 1. **What is t...

**Memla in front**

- Prior trace ids: `21, 18, 20, 19`
- Plan files: `tests/test_step6_coding_distillation.py, memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, tests/test_step5_locomo_graph_bridge.py, memory_system/distillation/__init__.py, memory_system/distillation/workflow_planner.py`
- Plan commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Plan tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Combined files: `tests/test_step6_coding_distillation.py, memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, tests/test_step5_locomo_graph_bridge.py, memory_system/distillation/__init__.py, memory_system/distillation/workflow_planner.py`
- Combined commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Answer excerpt: [Thought] The user wants me to implement a structured workflow planner for Memla that can predict coding workflow steps before the teacher model responds. Based on the retrieved memory and distilled priors, I can see this involves extend...
- Patch steps:
  - I'll extend the workflow planner and coding proxy to build and inject structured workflow plans, then add comprehensive test coverage
  - Extend `memory_system/distillation/workflow_planner
  - from typing import Dict, List, Optional, Tuple
  - from dataclasses import dataclass

## Case 2

**Prompt**: Create a clean export path that writes accepted coding traces plus workflow events into JSONL records for later training.

- Expected files: `memory_system/distillation/exporter.py, memory_system/distillation/__init__.py, tests/test_step6_coding_distillation.py`
- Expected commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: `src/export/trace_exporter.py, src/export/hooks.py, scripts/export_traces.py, tests/test_trace_exporter.py`
- Commands: ``
- Answer excerpt: I'll help you create a clean export path for coding traces and workflow events. Based on typical repository patterns, I'll design a system that captures both coding activities and workflow events in a structured JSONL format. Here's the...

**Memla in front**

- Prior trace ids: `21, 17, 12, 20`
- Plan files: `memory_system/distillation/workflow_planner.py, memory_system/distillation/coding_proxy.py, tests/test_step6_coding_distillation.py, memory_system/distillation/__init__.py, memory_system/distillation/exporter.py, memory_system/distillation/eval_harness.py`
- Plan commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Plan tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Combined files: `memory_system/distillation/workflow_planner.py, memory_system/distillation/coding_proxy.py, tests/test_step6_coding_distillation.py, memory_system/distillation/__init__.py, memory_system/distillation/exporter.py, memory_system/distillation/eval_harness.py, test_auth.py`
- Combined commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Answer excerpt: [Thought] The user wants me to create a clean export system for writing accepted coding traces and workflow events to JSONL format for training data. Based on the retrieved memory and distilled priors, I can see there's already been work...
- Patch steps:
  - I'll extend the workflow planner and coding proxy to build and inject structured workflow plans, then add comprehensive test coverage
  - Extend `memory_system/distillation/workflow_planner
  - from typing import Dict, List, Optional, Tuple
  - from dataclasses import dataclass

## Case 3

**Prompt**: Use accepted coding traces to supply repo-specific priors to the teacher, especially prior files and commands that worked.

- Expected files: `memory_system/distillation/coding_log.py, memory_system/distillation/coding_proxy.py, tests/test_step6_coding_distillation.py`
- Expected commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Raw teacher file recall: `0.0`
- Raw teacher command recall: `0.0`
- Memla plan file recall: `1.0`
- Memla plan command recall: `1.0`
- Memla combined file recall: `1.0`
- Memla combined command recall: `1.0`

**Raw teacher**

- Files: ``
- Commands: ``
- Answer excerpt: I understand you want me to use accepted coding traces to provide repo-specific context and priors. However, I don't currently have access to any retrieved memory or coding traces from your repository. To help you effectively, I would ne...

**Memla in front**

- Prior trace ids: `19, 21, 18, 13`
- Plan files: `memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, tests/test_step6_coding_distillation.py, memory_system/distillation/workflow_planner.py, memory_system/memory/chunk_manager.py, memory_system/main.py`
- Plan commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Plan tests: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Combined files: `memory_system/distillation/coding_proxy.py, memory_system/distillation/coding_log.py, tests/test_step6_coding_distillation.py, memory_system/distillation/workflow_planner.py, memory_system/memory/chunk_manager.py, memory_system/main.py`
- Combined commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Answer excerpt: [Thought] The user wants me to implement a system that uses accepted coding traces to supply repo-specific priors to the teacher model, focusing on files and commands that previously worked. Based on the retrieved memory and distilled pr...
- Patch steps:
  - I'll add accepted-trace similarity retrieval and thread priors through the coding proxy with comprehensive test coverage
  - Create `memory_system/distillation/coding_log
  - from typing import List, Dict, Optional, Tuple
  - from dataclasses import dataclass

## Run It

```powershell
cd "C:\Users\samat\Project Memory\Project-Memory"
. .\.anthropic_env.ps1
py -3 -m memory_system.distillation.comparison_runner --db ".\memory.sqlite" --repo_root "C:\Users\samat\Project Memory\Project-Memory" --user_id default --teacher_model claude-sonnet-4-20250514 --cases ".\distill\coding_head_to_head_cases.jsonl" --out_dir .\distill\head_to_head_demo
```
