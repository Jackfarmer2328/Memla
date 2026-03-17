from __future__ import annotations

import os
import tempfile
import unittest

from memory_system.adapters.merge import AdapterMerger


class TestStep4MinUsersGuard(unittest.TestCase):
    def test_merge_with_one_user_writes_nothing(self) -> None:
        try:
            import torch  # type: ignore
        except Exception:
            self.skipTest("torch is not installed in this environment.")

        class Base(torch.nn.Module):
            def __init__(self) -> None:
                super().__init__()
                self.w = torch.nn.Parameter(torch.zeros(2, 2))

        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            merger = AdapterMerger(adapters_dir=td)
            base = Base()
            report = merger.run_merge(user_ids=["only_user"], base_model=base)
            self.assertEqual(report.users_merged, 0)  # adapter missing => skipped
            self.assertEqual(report.params_updated, 0)


if __name__ == "__main__":
    unittest.main()

