from __future__ import annotations

from memory_system.persistent_world_lab.reality_compiler_fortress import reality_compiler_fortress_v0_spec


def test_reality_compiler_fortress_v0_shape():
    spec = reality_compiler_fortress_v0_spec()
    assert spec["fortress_id"] == "reality_compiler_fortress_v0"
    suites = spec["suites"]
    assert len(suites) == 5
    assert all(len(s["checks"]) == 3 for s in suites)
