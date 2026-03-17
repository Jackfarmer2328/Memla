from __future__ import annotations

import os
import tempfile
import unittest


class TestStep5AllPassColdStart(unittest.TestCase):
    def test_all_pass_when_no_safe_subspace(self) -> None:
        try:
            import torch  # type: ignore
        except Exception:
            self.skipTest("torch is not installed in this environment.")

        from memory_system.projection.gradient_filter import GradientProjector

        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            gp = GradientProjector(adapters_dir=td)
            grads = {"p": torch.randn(3, 3)}
            out = gp.project_gradient(grads)
            self.assertTrue(torch.allclose(out["p"], grads["p"]))


if __name__ == "__main__":
    unittest.main()

