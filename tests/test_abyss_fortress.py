from __future__ import annotations

from memory_system.persistent_world_lab.abyss_fortress import abyss_fortress_v0_spec


def test_abyss_fortress_v0_shape():
    spec = abyss_fortress_v0_spec()
    assert spec["fortress_id"] == "abyss_fortress_v0"
    suites = spec["suites"]
    assert len(suites) == 6
    assert all(len(s["checks"]) == 3 for s in suites)
