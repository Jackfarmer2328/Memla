from __future__ import annotations

import os
import tempfile
import unittest

from memory_system.adapters.ewc import EWC, EWCConfig


class TestStep3EWCColdStart(unittest.TestCase):
    def test_fisher_and_snapshot_created(self) -> None:
        try:
            import torch  # type: ignore
        except Exception:
            self.skipTest("torch is not installed in this environment.")

        class TinyModel(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                # Include "lora" in the name so EWC tracks it.
                self.lora_weight = torch.nn.Parameter(torch.randn(4, 4))

            def forward(self) -> torch.Tensor:
                return (self.lora_weight**2).sum()

        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            user_id = "u_ewc"
            model = TinyModel()
            ewc = EWC(user_id=user_id, adapters_dir=td)

            # Cold start: no fisher/snapshot yet.
            self.assertFalse(ewc.fisher)
            self.assertFalse(ewc.snapshot)

            # Create a few losses and update fisher.
            losses = [model.forward() for _ in range(3)]
            ewc.update_fisher(model=model, losses=losses, cfg=EWCConfig(fisher_num_samples=3))

            # Should now have fisher + snapshot, and files should exist.
            self.assertTrue(ewc.fisher)
            self.assertTrue(ewc.snapshot)
            self.assertTrue((ewc.user_path / "fisher_matrix.pt").exists())
            self.assertTrue((ewc.user_path / "param_snapshot.pt").exists())


if __name__ == "__main__":
    unittest.main()

