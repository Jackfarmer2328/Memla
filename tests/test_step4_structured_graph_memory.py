from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime

from memory_system.memory.chunk_manager import ChunkManager
from memory_system.memory.episode_log import EpisodeLog


class TestStep4StructuredGraphMemory(unittest.TestCase):
    def test_versioned_relation_edges_close_previous_current_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            log = EpisodeLog(os.path.join(td, "memory.sqlite"))
            try:
                user_entity = log.get_or_create_entity(
                    user_id="u_graph",
                    canonical_name="User",
                    entity_type="self",
                    ts=100,
                )
                ny = log.get_or_create_entity(
                    user_id="u_graph",
                    canonical_name="New York",
                    entity_type="location",
                    ts=100,
                )
                tokyo = log.get_or_create_entity(
                    user_id="u_graph",
                    canonical_name="Tokyo",
                    entity_type="location",
                    ts=200,
                )

                old_edge = log.add_or_bump_relation_edge(
                    user_id="u_graph",
                    src_entity_id=user_entity,
                    relation_type="lives_in",
                    dst_entity_id=ny,
                    time_kind="validity",
                    source_episode_id=1,
                    ts=100,
                    close_existing=True,
                )
                new_edge = log.add_or_bump_relation_edge(
                    user_id="u_graph",
                    src_entity_id=user_entity,
                    relation_type="lives_in",
                    dst_entity_id=tokyo,
                    start_ts=200,
                    time_kind="validity",
                    source_episode_id=2,
                    ts=200,
                    close_existing=True,
                )

                self.assertNotEqual(old_edge, new_edge)

                active = log.fetch_relation_edges(
                    user_id="u_graph",
                    src_entity_id=user_entity,
                    relation_type="lives_in",
                    active_at_ts=300,
                )
                self.assertEqual(len(active), 1)
                self.assertEqual(active[0].dst_entity_id, tokyo)

                history = log.fetch_relation_edges(
                    user_id="u_graph",
                    src_entity_id=user_entity,
                    relation_type="lives_in",
                    limit=10,
                )
                by_id = {edge.id: edge for edge in history}
                self.assertEqual(by_id[old_edge].end_ts, 200)
                self.assertIn(2, by_id[new_edge].source_episode_ids)
            finally:
                log.close()

    def test_chunk_manager_persists_alias_and_pronoun_resolved_graph_edges(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            log = EpisodeLog(os.path.join(td, "memory.sqlite"))
            cm = ChunkManager(log)
            try:
                cm.persist_message(
                    session_id="sess_graph",
                    user_id="u_graph",
                    role="assistant",
                    text="Matthew Patterson lives in Seattle.",
                    ts=100,
                )
                cm.persist_message(
                    session_id="sess_graph",
                    user_id="u_graph",
                    role="assistant",
                    text="Matt works at Acme.",
                    ts=110,
                )
                cm.persist_message(
                    session_id="sess_graph",
                    user_id="u_graph",
                    role="assistant",
                    text="He lives in Chicago.",
                    ts=120,
                )

                matt = log.resolve_entity(user_id="u_graph", mention="Matt")
                self.assertIsNotNone(matt)
                assert matt is not None
                self.assertEqual(matt.canonical_name, "Matthew Patterson")

                edges = log.fetch_relation_edges(
                    user_id="u_graph",
                    src_entity_id=matt.id,
                    relation_type="works_at",
                    limit=10,
                )
                self.assertEqual(len(edges), 1)
                org = log.fetch_entity(edges[0].dst_entity_id or -1)
                self.assertIsNotNone(org)
                assert org is not None
                self.assertEqual(org.canonical_name, "Acme")

                active_home = log.fetch_relation_edges(
                    user_id="u_graph",
                    src_entity_id=matt.id,
                    relation_type="lives_in",
                    active_at_ts=130,
                    limit=10,
                )
                self.assertEqual(len(active_home), 1)
                home = log.fetch_entity(active_home[0].dst_entity_id or -1)
                self.assertIsNotNone(home)
                assert home is not None
                self.assertEqual(home.canonical_name, "Chicago")
            finally:
                log.close()

    def test_repeated_fact_thickens_edge_and_keeps_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            log = EpisodeLog(os.path.join(td, "memory.sqlite"))
            cm = ChunkManager(log)
            try:
                episode_a, _ = cm.persist_message(
                    session_id="sess_weight",
                    user_id="u_weight",
                    role="assistant",
                    text="Matthew Patterson works at Acme.",
                    ts=100,
                )
                episode_b, _ = cm.persist_message(
                    session_id="sess_weight",
                    user_id="u_weight",
                    role="assistant",
                    text="Matt works at Acme.",
                    ts=140,
                )

                matt = log.resolve_entity(user_id="u_weight", mention="Matthew Patterson")
                self.assertIsNotNone(matt)
                assert matt is not None
                edges = log.fetch_relation_edges(
                    user_id="u_weight",
                    src_entity_id=matt.id,
                    relation_type="works_at",
                    limit=10,
                )
                self.assertEqual(len(edges), 1)
                self.assertGreaterEqual(edges[0].weight, 2.0)
                self.assertEqual(set(edges[0].source_episode_ids), {episode_a, episode_b})
            finally:
                log.close()

    def test_graph_memory_creates_temporal_sequence_edges_for_ordered_relations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            log = EpisodeLog(os.path.join(td, "memory.sqlite"))
            cm = ChunkManager(log)
            try:
                cm.persist_message(
                    session_id="sess_time_chain",
                    user_id="u_time_chain",
                    role="user",
                    text="I have been to Paris.",
                    ts=100,
                    meta={
                        "speaker": "Jon",
                        "session_date_text": "10:37 am on 13 June, 2023",
                    },
                )
                cm.persist_message(
                    session_id="sess_time_chain",
                    user_id="u_time_chain",
                    role="user",
                    text="I took a short trip last week to Rome.",
                    ts=200,
                    meta={
                        "speaker": "Jon",
                        "session_date_text": "10:37 am on 27 June, 2023",
                        "resolved_time_hints": ["last week = the week before 27 June 2023"],
                    },
                )

                jon = log.resolve_entity(user_id="u_time_chain", mention="Jon")
                paris = log.resolve_entity(user_id="u_time_chain", mention="Paris")
                rome = log.resolve_entity(user_id="u_time_chain", mention="Rome")
                self.assertIsNotNone(jon)
                self.assertIsNotNone(paris)
                self.assertIsNotNone(rome)
                assert jon is not None and paris is not None and rome is not None

                visited = log.fetch_relation_edges(
                    user_id="u_time_chain",
                    src_entity_id=jon.id,
                    relation_type="visited_place",
                    limit=10,
                )
                by_dst = {edge.dst_entity_id: edge for edge in visited}
                self.assertEqual(
                    by_dst[paris.id].start_ts,
                    int(datetime.strptime("13 June 2023", "%d %B %Y").timestamp()),
                )
                self.assertEqual(
                    by_dst[rome.id].start_ts,
                    int(datetime.strptime("20 June 2023", "%d %B %Y").timestamp()),
                )

                previous_edges = log.fetch_relation_edges(
                    user_id="u_time_chain",
                    src_entity_id=rome.id,
                    relation_type="previous_visited_place",
                    limit=10,
                )
                self.assertEqual(len(previous_edges), 1)
                self.assertEqual(previous_edges[0].dst_entity_id, paris.id)

                before_edges = log.fetch_relation_edges(
                    user_id="u_time_chain",
                    src_entity_id=paris.id,
                    relation_type="before_visited_place",
                    limit=10,
                )
                self.assertEqual(len(before_edges), 1)
                self.assertEqual(before_edges[0].dst_entity_id, rome.id)
            finally:
                log.close()


if __name__ == "__main__":
    unittest.main()
