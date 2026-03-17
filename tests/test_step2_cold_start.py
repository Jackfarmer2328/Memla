from __future__ import annotations

import os
import tempfile
import unittest

from memory_system.middleware.context_builder import build_system_prompt
from memory_system.memory.episode_log import Chunk


class TestStep2ColdStart(unittest.TestCase):
    def test_cold_start_missing_adapter_does_not_error(self) -> None:
        """
        Test A — Cold start:
        Fresh user_id with no adapter on disk should not throw.
        """
        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            chunks = [
                Chunk(
                    id=1,
                    ts=1,
                    session_id="s",
                    user_id="u",
                    chunk_type="fact",
                    key="booking hotel",
                    text="Fact: User is booking a hotel in Berlin.",
                    source_episode_id=None,
                    frequency_count=1,
                    last_recalled_ts=1,
                    meta={},
                )
            ]
            ctx = build_system_prompt(base_system="x", retrieved_chunks=chunks, session_id="s", user_id="new_user")
            self.assertIn("Retrieved memory", ctx.system_prompt)


if __name__ == "__main__":
    unittest.main()

