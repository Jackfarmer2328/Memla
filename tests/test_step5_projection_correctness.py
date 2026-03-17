from __future__ import annotations

import os
import tempfile
import unittest


class TestStep5ProjectionCorrectness(unittest.TestCase):
    def test_1d_projection_strips_orthogonal_component(self) -> None:
        try:
            import torch  # type: ignore
        except Exception:
            self.skipTest("torch is not installed in this environment.")

        from memory_system.projection.gradient_filter import GradientProjector, _safe_subspace_path

        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            # basis projects onto e1.
            basis = torch.zeros(1, 3)
            basis[0, 0] = 1.0
            safe = {"p": {"basis": basis}}

            torch.save(safe, str(_safe_subspace_path(td)))
            gp = GradientProjector(adapters_dir=td)

            g = torch.tensor([1.0, 2.0, 0.0])
            out = gp.project_gradient({"p": g})["p"]
            self.assertTrue(torch.allclose(out, torch.tensor([1.0, 0.0, 0.0])))


if __name__ == "__main__":
    unittest.main()

