from __future__ import annotations

import unittest
from unittest.mock import patch

from benchmarks.locomo.run_memla_benchmark import (
    MemlaBenchmarkRunner,
    _compile_typed_answer,
    _graph_object_targets,
    _graph_relation_targets,
    _new_runtime,
)
from memory_system.memory.episode_log import Chunk
from memory_system.middleware.quality import ChunkQuality


class TestStep5LocomoGraphBridge(unittest.TestCase):
    def test_answer_from_memory_uses_graph_for_current_previous_and_work_queries(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=False,
            max_turns=None,
            train_steps=1,
        )

        try:
            runtime.chunks.persist_message(
                session_id="sess_bridge",
                user_id=runtime.user_id,
                role="assistant",
                text="Matthew Patterson lives in Seattle.",
                ts=100,
            )
            runtime.chunks.persist_message(
                session_id="sess_bridge",
                user_id=runtime.user_id,
                role="assistant",
                text="Matt works at Acme.",
                ts=110,
            )
            runtime.chunks.persist_message(
                session_id="sess_bridge",
                user_id=runtime.user_id,
                role="assistant",
                text="He lives in Chicago.",
                ts=120,
            )

            answer_current, retrieved_current = runner.answer_from_memory(
                runtime=runtime,
                prompt="Where does Matt live currently?",
                category="single-hop",
            )
            self.assertEqual("Chicago", answer_current)
            self.assertTrue(any(chunk.meta.get("source") == "graph_relation_edge" for chunk in retrieved_current))

            answer_previous, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="Where did Matthew Patterson move from?",
                category="single-hop",
            )
            self.assertEqual("Seattle", answer_previous)

            answer_work, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="Where does Matt work?",
                category="single-hop",
            )
            self.assertEqual("Acme", answer_work)
        finally:
            runtime.close()

    def test_answer_from_memory_uses_explicit_speaker_meta_for_first_person_graph_facts(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge_meta",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=False,
            max_turns=None,
            train_steps=1,
        )

        try:
            runtime.chunks.persist_message(
                session_id="sess_bridge_meta",
                user_id=runtime.user_id,
                role="user",
                text='I play clarinet and violin. I saw "Summer Sounds" and Matt Patterson live. I have been to Paris and Rome. Contemporary is my top pick.',
                ts=100,
                meta={"speaker": "Jon"},
            )

            answer_instruments, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="What instruments does Jon play?",
                category="multi-hop",
            )
            self.assertEqual("clarinet and violin", answer_instruments)

            answer_artists, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="What musical artists/bands has Jon seen?",
                category="multi-hop",
            )
            self.assertEqual("Summer Sounds, Matt Patterson", answer_artists)

            answer_cities, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="Which cities has Jon visited?",
                category="multi-hop",
            )
            self.assertEqual("Paris, Rome", answer_cities)

            answer_style, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="What is Jon's favorite style of dance?",
                category="single-hop",
            )
            self.assertEqual("Contemporary", answer_style)
        finally:
            runtime.close()

    def test_answer_from_memory_uses_generic_action_relations_for_holdout_style_questions(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge_actions",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=False,
            max_turns=None,
            train_steps=1,
        )
        try:
            runtime.chunks.persist_message(
                session_id="sess_graph_actions",
                user_id=runtime.user_id,
                role="assistant",
                text="Caroline researched adoption agencies. Caroline participated in the pride parade, school speech, and support group. Melanie bought shoes and figurines.",
                ts=100,
            )
            runtime.chunks.persist_message(
                session_id="sess_graph_actions",
                user_id=runtime.user_id,
                role="assistant",
                text="The charity race raised awareness for mental health.",
                ts=120,
            )

            answer_research, retrieved_research = runner.answer_from_memory(
                runtime=runtime,
                prompt="What did Caroline research?",
                category="multi-hop",
            )
            self.assertEqual("adoption agencies", answer_research)
            self.assertTrue(any(chunk.meta.get("source") == "graph_relation_edge" for chunk in retrieved_research))

            answer_events, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="What events has Caroline participated in?",
                category="multi-hop",
            )
            self.assertEqual("pride parade, school speech, support group", answer_events)

            answer_items, retrieved_items = runner.answer_from_memory(
                runtime=runtime,
                prompt="What items has Melanie bought?",
                category="multi-hop",
            )
            self.assertEqual("shoes, figurines", answer_items)

            answer_charity, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="What did the charity race raise awareness for?",
                category="single-hop",
            )
            self.assertEqual("mental health", answer_charity)
        finally:
            runtime.close()

    def test_compile_typed_answer_prefers_json_shapes(self) -> None:
        self.assertEqual(
            "clarinet, violin",
            _compile_typed_answer(
                "What instruments does Melanie play?",
                "multi-hop",
                '{"items":["clarinet","violin"]}',
            ),
        )
        self.assertEqual(
            "Yes",
            _compile_typed_answer(
                "Would John be considered a patriotic person?",
                "common-sense",
                '{"answer":"Yes"}',
            ),
        )

    def test_graph_target_parsing_avoids_likely_false_positive_and_keeps_phrase_target(self) -> None:
        self.assertNotIn(
            "like",
            _graph_relation_targets("What fields would Caroline be likely to pursue in her educaton?"),
        )
        self.assertNotIn(
            "plays_instrument",
            _graph_relation_targets("What games has John played with his friends at charity tournaments?"),
        )
        targets = _graph_object_targets("When did Caroline go to the LGBTQ support group?")
        self.assertIn("the LGBTQ support group", targets)
        self.assertNotIn("LGBTQ", targets)

    def test_graph_temporal_answer_uses_resolved_time_label(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge_time",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=False,
            max_turns=None,
            train_steps=1,
        )
        try:
            runtime.chunks.persist_message(
                session_id="sess_bridge_time",
                user_id=runtime.user_id,
                role="user",
                text="I took a short trip last week to Rome.",
                ts=100,
                meta={
                    "speaker": "Jon",
                    "session_date_text": "10:37 am on 27 June, 2023",
                    "resolved_time_hints": ["last week = the week before 27 June 2023"],
                },
            )

            answer, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="When did Jon visit Rome?",
                category="temporal",
            )
            self.assertEqual("the week before 27 June 2023", answer)
        finally:
            runtime.close()

    def test_answer_from_memory_uses_graph_for_event_and_history_questions(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge_events",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=False,
            max_turns=None,
            train_steps=1,
        )
        try:
            runtime.chunks.persist_message(
                session_id="sess_graph_events",
                user_id=runtime.user_id,
                role="user",
                text="I went to a LGBTQ support group yesterday. I applied to adoption agencies yesterday.",
                ts=100,
                meta={
                    "speaker": "Caroline",
                    "session_date_text": "10:37 am on 8 May, 2023",
                    "resolved_time_hints": ["yesterday = 7 May 2023"],
                },
            )
            runtime.chunks.persist_message(
                session_id="sess_graph_events",
                user_id=runtime.user_id,
                role="user",
                text="I went to a LGBTQ conference two days ago. I attended a LGBTQ+ pride parade last week.",
                ts=140,
                meta={
                    "speaker": "Caroline",
                    "session_date_text": "10:37 am on 12 July, 2023",
                    "resolved_time_hints": [
                        "two days ago = 10 July 2023",
                        "last week = the week before 12 July 2023",
                    ],
                },
            )
            runtime.chunks.persist_message(
                session_id="sess_graph_events",
                user_id=runtime.user_id,
                role="user",
                text="I signed with the Falcons. I had dinner with my mother.",
                ts=200,
                meta={"speaker": "John", "session_date_text": "10:37 am on 21 May, 2023"},
            )

            answer_group, retrieved_group = runner.answer_from_memory(
                runtime=runtime,
                prompt="When did Caroline go to the LGBTQ support group?",
                category="temporal",
            )
            self.assertEqual("7 May 2023", answer_group)
            self.assertTrue(any(str(chunk.text).startswith("[graph]") for chunk in retrieved_group))

            answer_apply, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="When did Caroline apply to adoption agencies?",
                category="temporal",
            )
            self.assertEqual("7 May 2023", answer_apply)

            answer_team, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="Which team did John sign with on 21 May, 2023?",
                category="single-hop",
            )
            self.assertEqual("Falcons", answer_team)

            answer_dinner, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="Who did John have dinner with on 21 May, 2023?",
                category="single-hop",
            )
            self.assertEqual("my mother", answer_dinner)
        finally:
            runtime.close()

    def test_answer_from_memory_uses_graph_for_inventory_questions(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge_inventory",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=False,
            max_turns=None,
            train_steps=1,
        )
        try:
            runtime.chunks.persist_message(
                session_id="sess_graph_inventory",
                user_id=runtime.user_id,
                role="user",
                text="I have turtles and a dog. I have done karate and judo. I love The Lord of the Rings and Harry Potter. I cooked pasta and curry.",
                ts=100,
                meta={"speaker": "Nate"},
            )

            answer_pets, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="What pets does Nate have?",
                category="single-hop",
            )
            self.assertEqual("turtles, dog", answer_pets)

            answer_martial, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="What martial arts has Nate done?",
                category="single-hop",
            )
            self.assertEqual("karate, judo", answer_martial)

            answer_movies, retrieved_movies = runner.answer_from_memory(
                runtime=runtime,
                prompt="What movies does Nate like?",
                category="single-hop",
            )
            self.assertEqual("The Lord of the Rings, Harry Potter", answer_movies)

            answer_cooked, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="What has Nate cooked?",
                category="single-hop",
            )
            self.assertEqual("pasta, curry", answer_cooked)
        finally:
            runtime.close()

    def test_answer_from_memory_uses_sequence_edges_for_previous_object_queries(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge_prev_place",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=False,
            max_turns=None,
            train_steps=1,
        )
        try:
            runtime.chunks.persist_message(
                session_id="sess_graph_prev_place",
                user_id=runtime.user_id,
                role="user",
                text="I have been to Paris.",
                ts=100,
                meta={"speaker": "Jon", "session_date_text": "10:37 am on 13 June, 2023"},
            )
            runtime.chunks.persist_message(
                session_id="sess_graph_prev_place",
                user_id=runtime.user_id,
                role="user",
                text="I took a short trip last week to Rome.",
                ts=200,
                meta={
                    "speaker": "Jon",
                    "session_date_text": "10:37 am on 27 June, 2023",
                    "resolved_time_hints": ["last week = the week before 27 June 2023"],
                },
            )

            answer, _ = runner.answer_from_memory(
                runtime=runtime,
                prompt="Which city did Jon visit before Rome?",
                category="temporal",
            )
            self.assertEqual("Paris", answer)
        finally:
            runtime.close()

    def test_answer_from_memory_triggers_training_when_enabled(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge_train",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=True,
            max_turns=None,
            train_steps=1,
        )
        try:
            runtime.chunks.persist_message(
                session_id="sess_bridge_train",
                user_id=runtime.user_id,
                role="assistant",
                text="Matthew Patterson lives in Seattle.",
                ts=100,
            )
            runtime.chunks.persist_message(
                session_id="sess_bridge_train",
                user_id=runtime.user_id,
                role="assistant",
                text="Matt works at Acme.",
                ts=110,
            )

            sample_retrieved = [
                ChunkQuality(
                    chunk=Chunk(
                        id=1,
                        ts=100,
                        session_id="x",
                        user_id=runtime.user_id,
                        chunk_type="fact",
                        key="matt lives seattle",
                        text="[graph] Matthew Patterson lives in Seattle.",
                        source_episode_id=1,
                        frequency_count=1,
                        recall_count=0,
                        last_recalled_ts=100,
                        meta={"source": "graph_relation_edge"},
                        parent_id=None,
                    ),
                    usage_score=0.9,
                    is_positive=True,
                ),
                ChunkQuality(
                    chunk=Chunk(
                        id=2,
                        ts=110,
                        session_id="x",
                        user_id=runtime.user_id,
                        chunk_type="fact",
                        key="matt works acme",
                        text="[graph] Matthew Patterson works at Acme.",
                        source_episode_id=2,
                        frequency_count=1,
                        recall_count=0,
                        last_recalled_ts=110,
                        meta={"source": "graph_relation_edge"},
                        parent_id=None,
                    ),
                    usage_score=0.0,
                    is_positive=False,
                ),
            ]

            with patch("benchmarks.locomo.run_memla_benchmark.score_chunk_usage", return_value=sample_retrieved), patch(
                "benchmarks.locomo.run_memla_benchmark.deferred_train"
            ) as mocked_train:
                answer, _ = runner.answer_from_memory(
                    runtime=runtime,
                    prompt="Where does Matt work?",
                    category="single-hop",
                )
                self.assertEqual("Acme", answer)
                self.assertTrue(mocked_train.called)
        finally:
            runtime.close()

    def test_feedback_from_reference_records_graph_feedback_and_adjusts_weights(self) -> None:
        runtime = _new_runtime(
            user_id="u_graph_bridge_feedback",
            extractor="heuristic",
            model="mock-model",
            num_ctx=None,
        )
        runner = MemlaBenchmarkRunner(
            model="mock-model",
            backend="mock",
            top_k=12,
            temperature=0.0,
            num_ctx=None,
            extractor="heuristic",
            train_online=True,
            max_turns=None,
            train_steps=1,
        )
        try:
            runtime.chunks.persist_message(
                session_id="sess_graph_feedback",
                user_id=runtime.user_id,
                role="user",
                text="I have been to Paris.",
                ts=100,
                meta={"speaker": "Jon", "session_date_text": "10:37 am on 13 June, 2023"},
            )
            runtime.chunks.persist_message(
                session_id="sess_graph_feedback",
                user_id=runtime.user_id,
                role="user",
                text="I took a short trip last week to Rome.",
                ts=200,
                meta={
                    "speaker": "Jon",
                    "session_date_text": "10:37 am on 27 June, 2023",
                    "resolved_time_hints": ["last week = the week before 27 June 2023"],
                },
            )

            _, retrieved = runner.answer_from_memory(
                runtime=runtime,
                prompt="Which city did Jon visit before Rome?",
                category="temporal",
            )
            runner.feedback_from_reference(
                runtime=runtime,
                prompt="Which city did Jon visit before Rome?",
                category="temporal",
                prediction="Rome",
                reference="Paris",
                retrieved=retrieved,
            )

            feedback = runtime.log.fetch_graph_path_feedback(user_id=runtime.user_id, limit=10)
            self.assertGreaterEqual(len(feedback), 1)
            self.assertLess(feedback[0].reward, 0.0)

            rome = runtime.log.resolve_entity(user_id=runtime.user_id, mention="Rome")
            self.assertIsNotNone(rome)
            assert rome is not None
            previous_edges = runtime.log.fetch_relation_edges(
                user_id=runtime.user_id,
                src_entity_id=rome.id,
                relation_type="previous_visited_place",
                limit=10,
            )
            self.assertEqual(len(previous_edges), 1)
            self.assertGreater(previous_edges[0].weight, 0.35)
        finally:
            runtime.close()


if __name__ == "__main__":
    unittest.main()
