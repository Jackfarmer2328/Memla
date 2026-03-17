from __future__ import annotations

import os
import tempfile
import unittest

from memory_system.adapters.gradient_pass import micro_gradient_pass
from memory_system.adapters.lora_manager import AdapterMeta, RetrievalLoRAManager


class TestStep2AdapterPersistence(unittest.TestCase):
    def test_adapter_persistence_and_meta(self) -> None:
        """
        Test B — Adapter persistence:
        - Train on "booking" relevance
        - Save adapter + meta
        - Reload and verify booking chunk ranks higher than noise
        """
        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            user_id = "user_booking"
            mgr = RetrievalLoRAManager(adapters_dir=td)

            query = "I only care about booking-related chunks."
            retrieved = ["Hotel booking details: dates, price, location."]
            candidates = retrieved + [
                "Random noise about GPU drivers.",
                "A recipe for pancakes.",
                "Notes on gardening.",
            ]

            try:
                micro_gradient_pass(
                    manager=mgr,
                    user_id=user_id,
                    query=query,
                    retrieved_texts=retrieved,
                    candidate_texts=candidates,
                    steps=5,
                    learning_rate=1e-5,
                    quality_signal=1.0,
                )
            except RuntimeError:
                self.skipTest("HF model could not be loaded/downloaded in this environment.")

            meta = AdapterMeta.load(user_id=user_id, adapters_dir=td)
            self.assertGreaterEqual(meta.training_steps, 1)
            self.assertGreaterEqual(meta.total_sessions_trained, 1)

            # Reload in a new manager instance.
            mgr2 = RetrievalLoRAManager(adapters_dir=td)
            try:
                mgr2.load_adapter(user_id=user_id)
                scores = mgr2.score_chunks(query="booking hotel", chunks=candidates)
            except RuntimeError:
                self.skipTest("HF model could not be loaded/downloaded in this environment.")

            # booking chunk should be top-1 after training
            best_idx = max(range(len(scores)), key=lambda i: float(scores[i]))
            self.assertEqual(best_idx, 0)


if __name__ == "__main__":
    unittest.main()

