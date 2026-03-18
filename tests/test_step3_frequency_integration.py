from __future__ import annotations

import unittest

from memory_system.memory.chunk_manager import ewc_lambda_multiplier_for_chunks
from memory_system.memory.episode_log import Chunk


def _mk(freq: int) -> Chunk:
    return Chunk(
        id=1,
        ts=1,
        session_id="s",
        user_id="u",
        chunk_type="fact",
        key="k",
        text="t",
        source_episode_id=None,
        frequency_count=freq,
        recall_count=0,
        last_recalled_ts=1,
        meta={},
    )


class TestStep3FrequencyIntegration(unittest.TestCase):
    def test_multiplier_prefers_bold(self) -> None:
        self.assertEqual(ewc_lambda_multiplier_for_chunks([_mk(5)]), 1.5)

    def test_multiplier_prefers_faint(self) -> None:
        self.assertEqual(ewc_lambda_multiplier_for_chunks([_mk(1)]), 0.5)

    def test_multiplier_balanced(self) -> None:
        self.assertEqual(ewc_lambda_multiplier_for_chunks([_mk(2)]), 1.0)


if __name__ == "__main__":
    unittest.main()

