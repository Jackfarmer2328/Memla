from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path


class TestStep5SubspaceUpdateAfterMerge(unittest.TestCase):
    def test_update_creates_safe_subspace_and_log(self) -> None:
        try:
            import torch  # type: ignore
        except Exception:
            self.skipTest("torch is not installed in this environment.")

        from memory_system.projection.gradient_filter import (
            GradientProjector,
            _merge_log_path,
            _safe_subspace_path,
            _shared_base_dir,
            _subspace_log_path,
        )

        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            shared_dir = _shared_base_dir(td)
            shared_dir.mkdir(parents=True, exist_ok=True)

            # Fake a merge history with a shared_directions file.
            ts = int(time.time())
            dirs = {"p": torch.eye(2, 4)}  # 2 directions in R^4
            dirs_file = shared_dir / f"shared_directions_{ts}.pt"
            torch.save(dirs, str(dirs_file))

            merge_log = [
                {
                    "ts": ts,
                    "shared_directions_path": dirs_file.name,
                    "report": {"users_merged": 2},
                }
            ]
            _merge_log_path(td).write_text(json.dumps(merge_log), encoding="utf-8")

            gp = GradientProjector(adapters_dir=td)
            safe = gp.compute_safe_subspace(min_agreement=0.6)
            self.assertIn("p", safe)

            gp.update_subspace(min_agreement=0.6)
            # allow background thread to write
            time.sleep(0.2)

            self.assertTrue(_safe_subspace_path(td).exists())
            self.assertTrue(_subspace_log_path(td).exists())


if __name__ == "__main__":
    unittest.main()

