from __future__ import annotations

import os
import tempfile
import unittest

from memory_system.adapters.gradient_pass import micro_gradient_pass
from memory_system.adapters.lora_manager import RetrievalLoRAManager


class TestStep2RetrievalImprovement(unittest.TestCase):
    def test_retrieval_improves_over_sessions(self) -> None:
        """
        Test C — Retrieval improvement (synthetic):
        After a few micro-updates, the model should prefer relevant chunks over noise.
        """
        with tempfile.TemporaryDirectory() as td:
            os.environ["MEMORY_ADAPTERS_DIR"] = td
            user_id = "user_improve"
            mgr = RetrievalLoRAManager(adapters_dir=td)

            hotel_chunks = [
                "Hotel booking: check-in is April 3, check-out April 7.",
                "Hotel booking: preference is quiet room and late checkout.",
                "Hotel booking: address is Alexanderplatz, Berlin.",
            ]
            noise_chunks = [
                "Noise: the mitochondria is the powerhouse of the cell.",
                "Noise: notes about a fantasy novel plot.",
                "Noise: random CLI flags for ffmpeg.",
            ]
            candidates = hotel_chunks + noise_chunks

            # baseline (may already be reasonable due to pretraining)
            try:
                mgr.load_adapter(user_id=user_id)
                base_scores = mgr.score_chunks(query="hotel booking late checkout", chunks=candidates)
            except RuntimeError:
                self.skipTest("HF model could not be loaded/downloaded in this environment.")

            base_best = max(range(len(base_scores)), key=lambda i: float(base_scores[i]))

            # train for a few "sessions" to reinforce hotel chunks
            for _ in range(4):
                micro_gradient_pass(
                    manager=mgr,
                    user_id=user_id,
                    query="hotel booking late checkout",
                    retrieved_texts=hotel_chunks[:2],
                    candidate_texts=candidates,
                    steps=6,
                    learning_rate=1e-5,
                    quality_signal=1.0,
                )

            mgr2 = RetrievalLoRAManager(adapters_dir=td)
            mgr2.load_adapter(user_id=user_id)
            new_scores = mgr2.score_chunks(query="hotel booking late checkout", chunks=candidates)
            new_best = max(range(len(new_scores)), key=lambda i: float(new_scores[i]))

            # We expect top-1 to be a hotel chunk post-training.
            self.assertLess(new_best, len(hotel_chunks))

            # If baseline top-1 was noise, it should flip; if it was already hotel, it stays hotel.
            if base_best >= len(hotel_chunks):
                self.assertLess(new_best, len(hotel_chunks))


if __name__ == "__main__":
    unittest.main()

