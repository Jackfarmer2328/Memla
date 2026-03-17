from __future__ import annotations

import os
import tempfile
import unittest

from memory_system.adapters.ewc import EWC, EWCConfig


class TestStep3BoldingProtectionToy(unittest.TestCase):
    def test_ewc_blocks_overwrite(self) -> None:
        try:
            import torch  # type: ignore
        except Exception:
            self.skipTest("torch is not installed in this environment.")

        class ToyRetrieval(torch.nn.Module):
            """
            Two opposing "preferences" share one LoRA-like weight vector.
            We'll bold preference A, then attempt to overwrite with preference B.
            """

            def __init__(self) -> None:
                super().__init__()
                self.lora_vec = torch.nn.Parameter(torch.zeros(2))

            def score_a(self) -> torch.Tensor:
                return self.lora_vec[0]

            def score_b(self) -> torch.Tensor:
                return self.lora_vec[1]

        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            user_id = "u_bold"
            model = ToyRetrieval()
            opt = torch.optim.SGD(model.parameters(), lr=0.2)

            ewc = EWC(user_id=user_id, adapters_dir=td)
            cfg = EWCConfig(lambda_ewc=500.0, fisher_num_samples=10)

            # Phase 1: Train preference A (increase lora_vec[0]).
            for _ in range(10):
                loss = (1.0 - model.score_a()) ** 2
                opt.zero_grad()
                loss.backward()
                opt.step()

            a_before = float(model.lora_vec[0].detach())
            # Compute fisher on A losses (bold A).
            losses = [(1.0 - model.score_a()) ** 2 for _ in range(10)]
            ewc.update_fisher(model=model, losses=losses, cfg=cfg)

            # Snapshot after bolding.
            ewc.snapshot_params(model)

            # Phase 2: Contradictory training pushing B up and (implicitly) could move A.
            for _ in range(10):
                task_loss = (1.0 - model.score_b()) ** 2
                penalty = ewc.ewc_loss(model, lambda_ewc=cfg.lambda_ewc)
                loss = task_loss + penalty
                opt.zero_grad()
                loss.backward()
                opt.step()

            a_after = float(model.lora_vec[0].detach())
            # A should not collapse significantly under strong EWC.
            self.assertGreaterEqual(a_after, a_before - 0.05)


if __name__ == "__main__":
    unittest.main()

