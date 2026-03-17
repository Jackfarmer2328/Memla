from __future__ import annotations

import os
import tempfile
import time
import unittest

from memory_system.memory.episode_log import EpisodeLog
from memory_system.memory.chunk_manager import ChunkManager
from memory_system.middleware.ttt_layer import TTTLayer


class TestPersistence(unittest.TestCase):
    def test_restart_retrieval_from_sqlite(self) -> None:
        """
        Verifies the Step 1 success property (mechanically):
        - write user message -> chunked into SQLite
        - "restart" by constructing new objects
        - retrieval finds the earlier memory for a later query

        This test does not require Ollama to be running.
        """
        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "memory.sqlite")
            user_id = "u_test"

            # Session 1: store a long-ish "document"
            log1 = EpisodeLog(db_path)
            cm1 = ChunkManager(log1)  # heuristic extractor (no Ollama needed)
            ttt1 = TTTLayer(episode_log=log1, chunk_manager=cm1)

            session1 = "sess_1"
            doc = (
                "Project Memory Spec.\n"
                "Page 87: The launch code is ORANGE-DELTA-741.\n"
                "Decision: We prefer SQLite as the episode store.\n"
                "Entity: The middleware layer is the TTT wrapper.\n"
            )
            ttt1.on_user_message(session_id=session1, user_id=user_id, user_text=doc, base_system="x", top_k=10)
            log1.close()

            time.sleep(1)

            # Session 2: new instance, same DB, query about page 87
            log2 = EpisodeLog(db_path)
            cm2 = ChunkManager(log2)
            ttt2 = TTTLayer(episode_log=log2, chunk_manager=cm2)

            q = "What was the launch code mentioned on page 87?"
            artifacts = ttt2.on_user_message(session_id="sess_2", user_id=user_id, user_text=q, base_system="x", top_k=10)
            log2.close()

            injected = artifacts.built.system_prompt
            self.assertIn("ORANGE-DELTA-741", injected)


if __name__ == "__main__":
    unittest.main()

