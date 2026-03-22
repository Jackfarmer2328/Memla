from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS episodes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  role TEXT NOT NULL,              -- "user" | "assistant" | "system"
  content TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  chunk_type TEXT NOT NULL,         -- "fact" | "decision" | "entity" | "note"
  key TEXT NOT NULL,                -- normalized key for retrieval
  text TEXT NOT NULL,               -- human-readable memory
  source_episode_id INTEGER,         -- nullable
  frequency_count INTEGER NOT NULL DEFAULT 1,  -- times user mentioned/restated this
  recall_count INTEGER NOT NULL DEFAULT 0,     -- times system retrieved this
  last_recalled_ts INTEGER NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(user_id, chunk_type, key, text)
);

CREATE INDEX IF NOT EXISTS idx_chunks_user_ts ON chunks(user_id, ts DESC);
CREATE INDEX IF NOT EXISTS idx_chunks_user_key ON chunks(user_id, key);

CREATE TABLE IF NOT EXISTS user_links (
  user_id TEXT NOT NULL,
  chunk_a_id INTEGER NOT NULL,
  chunk_b_id INTEGER NOT NULL,
  created_ts INTEGER NOT NULL,
  PRIMARY KEY(user_id, chunk_a_id, chunk_b_id)
);

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  canonical_name TEXT NOT NULL COLLATE NOCASE,
  entity_type TEXT NOT NULL DEFAULT 'entity',
  meta_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(user_id, canonical_name)
);

CREATE INDEX IF NOT EXISTS idx_entities_user_name
ON entities(user_id, canonical_name);

CREATE TABLE IF NOT EXISTS entity_aliases (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_ts INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  alias TEXT NOT NULL COLLATE NOCASE,
  entity_id INTEGER NOT NULL,
  confidence REAL NOT NULL DEFAULT 1.0,
  meta_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(user_id, alias)
);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_user_alias
ON entity_aliases(user_id, alias);

CREATE TABLE IF NOT EXISTS relation_edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_ts INTEGER NOT NULL,
  updated_ts INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  src_entity_id INTEGER NOT NULL,
  relation_type TEXT NOT NULL,
  dst_entity_id INTEGER,
  dst_value TEXT,
  start_ts INTEGER,
  end_ts INTEGER,
  time_kind TEXT NOT NULL DEFAULT 'timeless',
  weight REAL NOT NULL DEFAULT 1.0,
  confidence REAL NOT NULL DEFAULT 1.0,
  signature TEXT NOT NULL,
  meta_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(user_id, signature)
);

CREATE INDEX IF NOT EXISTS idx_relation_edges_user_src_rel
ON relation_edges(user_id, src_entity_id, relation_type);

CREATE INDEX IF NOT EXISTS idx_relation_edges_user_rel_end
ON relation_edges(user_id, relation_type, end_ts);

CREATE TABLE IF NOT EXISTS edge_sources (
  edge_id INTEGER NOT NULL,
  episode_id INTEGER NOT NULL,
  created_ts INTEGER NOT NULL,
  PRIMARY KEY(edge_id, episode_id)
);

CREATE TABLE IF NOT EXISTS graph_path_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_ts INTEGER NOT NULL,
  user_id TEXT NOT NULL,
  question TEXT NOT NULL,
  predicted_answer TEXT NOT NULL,
  reference_answer TEXT NOT NULL,
  reward REAL NOT NULL,
  chosen_edge_ids_json TEXT NOT NULL DEFAULT '[]',
  rejected_edge_ids_json TEXT NOT NULL DEFAULT '[]',
  meta_json TEXT NOT NULL DEFAULT '{}'
);
"""


@dataclass(frozen=True)
class Episode:
    id: int
    ts: int
    session_id: str
    user_id: str
    role: str
    content: str
    meta: dict[str, Any]


@dataclass(frozen=True)
class Chunk:
    id: int
    ts: int
    session_id: str
    user_id: str
    chunk_type: str
    key: str
    text: str
    source_episode_id: Optional[int]
    frequency_count: int
    recall_count: int
    last_recalled_ts: int
    meta: dict[str, Any]
    parent_id: Optional[int] = None


@dataclass(frozen=True)
class MemoryEntity:
    id: int
    created_ts: int
    updated_ts: int
    user_id: str
    canonical_name: str
    entity_type: str
    meta: dict[str, Any]


@dataclass(frozen=True)
class RelationEdge:
    id: int
    created_ts: int
    updated_ts: int
    user_id: str
    src_entity_id: int
    relation_type: str
    dst_entity_id: Optional[int]
    dst_value: Optional[str]
    start_ts: Optional[int]
    end_ts: Optional[int]
    time_kind: str
    weight: float
    confidence: float
    signature: str
    meta: dict[str, Any]
    source_episode_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class GraphPathFeedback:
    id: int
    created_ts: int
    user_id: str
    question: str
    predicted_answer: str
    reference_answer: str
    reward: float
    chosen_edge_ids: tuple[int, ...]
    rejected_edge_ids: tuple[int, ...]
    meta: dict[str, Any]


class EpisodeLog:
    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._migrate_recall_count()
        self._migrate_parent_id()
        self._conn.commit()

    @staticmethod
    def _normalize_entity_name(text: str) -> str:
        return " ".join(str(text or "").strip().split())

    @staticmethod
    def _normalize_edge_value(text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        value = " ".join(str(text or "").strip().split())
        return value or None

    @classmethod
    def _edge_signature(
        cls,
        *,
        src_entity_id: int,
        relation_type: str,
        dst_entity_id: Optional[int],
        dst_value: Optional[str],
        start_ts: Optional[int],
        end_ts: Optional[int],
        time_kind: str,
    ) -> str:
        dst_norm = cls._normalize_edge_value(dst_value)
        return "|".join(
            [
                str(int(src_entity_id)),
                str(relation_type or "").strip().lower(),
                str(int(dst_entity_id)) if dst_entity_id is not None else "",
                str(dst_norm or "").lower(),
                str(int(start_ts)) if start_ts is not None else "",
                str(int(end_ts)) if end_ts is not None else "",
                str(time_kind or "timeless").strip().lower(),
            ]
        )

    def _migrate_recall_count(self) -> None:
        try:
            self._conn.execute("SELECT recall_count FROM chunks LIMIT 1")
        except sqlite3.OperationalError:
            self._conn.execute("ALTER TABLE chunks ADD COLUMN recall_count INTEGER NOT NULL DEFAULT 0")

    def _migrate_parent_id(self) -> None:
        try:
            self._conn.execute("SELECT parent_id FROM chunks LIMIT 1")
        except sqlite3.OperationalError:
            self._conn.execute("ALTER TABLE chunks ADD COLUMN parent_id INTEGER")

    def close(self) -> None:
        self._conn.close()

    def get_or_create_entity(
        self,
        *,
        user_id: str,
        canonical_name: str,
        entity_type: str = "entity",
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> int:
        ts_i = int(ts if ts is not None else time.time())
        canonical = self._normalize_entity_name(canonical_name)
        if not canonical:
            raise ValueError("canonical_name must not be empty")
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO entities(created_ts, updated_ts, user_id, canonical_name, entity_type, meta_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, canonical_name)
            DO UPDATE SET
              updated_ts = excluded.updated_ts,
              entity_type = excluded.entity_type,
              meta_json = excluded.meta_json
            """,
            (ts_i, ts_i, user_id, canonical, entity_type, meta_json),
        )
        row = self._conn.execute(
            """
            SELECT id FROM entities
            WHERE user_id = ? AND canonical_name = ?
            """,
            (user_id, canonical),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to resolve entity row after upsert")
        self._conn.commit()
        return int(row["id"])

    def add_entity_alias(
        self,
        *,
        user_id: str,
        entity_id: int,
        alias: str,
        confidence: float = 1.0,
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> None:
        alias_norm = self._normalize_entity_name(alias)
        if not alias_norm:
            return
        ts_i = int(ts if ts is not None else time.time())
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO entity_aliases(created_ts, user_id, alias, entity_id, confidence, meta_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, alias)
            DO UPDATE SET
              entity_id = excluded.entity_id,
              confidence = MAX(entity_aliases.confidence, excluded.confidence),
              meta_json = excluded.meta_json
            """,
            (ts_i, user_id, alias_norm, int(entity_id), float(confidence), meta_json),
        )
        self._conn.commit()

    def fetch_entity(self, entity_id: int) -> Optional[MemoryEntity]:
        row = self._conn.execute(
            "SELECT * FROM entities WHERE id = ?",
            (int(entity_id),),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_entity(row)

    def resolve_entity(self, *, user_id: str, mention: str) -> Optional[MemoryEntity]:
        mention_norm = self._normalize_entity_name(mention)
        if not mention_norm:
            return None

        row = self._conn.execute(
            """
            SELECT * FROM entities
            WHERE user_id = ? AND canonical_name = ?
            ORDER BY updated_ts DESC
            LIMIT 1
            """,
            (user_id, mention_norm),
        ).fetchone()
        if row is not None:
            return self._row_to_entity(row)

        row = self._conn.execute(
            """
            SELECT e.*
            FROM entity_aliases a
            JOIN entities e ON e.id = a.entity_id
            WHERE a.user_id = ? AND a.alias = ?
            ORDER BY a.confidence DESC, e.updated_ts DESC
            LIMIT 1
            """,
            (user_id, mention_norm),
        ).fetchone()
        if row is not None:
            return self._row_to_entity(row)

        prefix = mention_norm.lower()
        rows = self._conn.execute(
            """
            SELECT e.*
            FROM entities e
            WHERE e.user_id = ?
              AND LOWER(e.canonical_name) LIKE ?
            ORDER BY e.updated_ts DESC
            LIMIT 8
            """,
            (user_id, f"{prefix}%"),
        ).fetchall()
        if rows:
            return self._row_to_entity(rows[0])
        return None

    def fetch_entity_aliases(self, *, entity_id: int) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT alias FROM entity_aliases
            WHERE entity_id = ?
            ORDER BY confidence DESC, alias ASC
            """,
            (int(entity_id),),
        ).fetchall()
        return [str(r["alias"]) for r in rows]

    def close_open_edges(
        self,
        *,
        user_id: str,
        src_entity_id: int,
        relation_type: str,
        end_ts: int,
        exclude_edge_id: Optional[int] = None,
    ) -> None:
        params: list[Any] = [int(end_ts), int(end_ts), user_id, int(src_entity_id), relation_type]
        sql = """
            UPDATE relation_edges
            SET end_ts = ?, updated_ts = ?
            WHERE user_id = ?
              AND src_entity_id = ?
              AND relation_type = ?
              AND end_ts IS NULL
        """
        if exclude_edge_id is not None:
            sql += " AND id != ?"
            params.append(int(exclude_edge_id))
        self._conn.execute(sql, params)
        self._conn.commit()

    def add_or_bump_relation_edge(
        self,
        *,
        user_id: str,
        src_entity_id: int,
        relation_type: str,
        dst_entity_id: Optional[int] = None,
        dst_value: Optional[str] = None,
        start_ts: Optional[int] = None,
        end_ts: Optional[int] = None,
        time_kind: str = "timeless",
        confidence: float = 1.0,
        weight_delta: float = 1.0,
        source_episode_id: Optional[int] = None,
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
        close_existing: bool = False,
    ) -> int:
        ts_i = int(ts if ts is not None else time.time())
        dst_value_norm = self._normalize_edge_value(dst_value)
        relation_norm = str(relation_type or "").strip().lower()
        time_kind_norm = str(time_kind or "timeless").strip().lower()
        if not relation_norm:
            raise ValueError("relation_type must not be empty")

        existing = self._conn.execute(
            """
            SELECT id FROM relation_edges
            WHERE user_id = ?
              AND src_entity_id = ?
              AND relation_type = ?
              AND COALESCE(dst_entity_id, -1) = COALESCE(?, -1)
              AND COALESCE(dst_value, '') = COALESCE(?, '')
              AND end_ts IS NULL
            ORDER BY updated_ts DESC
            LIMIT 1
            """,
            (user_id, int(src_entity_id), relation_norm, dst_entity_id, dst_value_norm),
        ).fetchone()

        if existing is not None:
            edge_id = int(existing["id"])
            self._conn.execute(
                """
                UPDATE relation_edges
                SET updated_ts = ?,
                    weight = weight + ?,
                    confidence = MAX(confidence, ?),
                    meta_json = ?
                WHERE id = ?
                """,
                (
                    ts_i,
                    float(weight_delta),
                    float(confidence),
                    json.dumps(meta or {}, ensure_ascii=False),
                    edge_id,
                ),
            )
            if source_episode_id is not None:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO edge_sources(edge_id, episode_id, created_ts)
                    VALUES (?, ?, ?)
                    """,
                    (edge_id, int(source_episode_id), ts_i),
                )
            self._conn.commit()
            return edge_id

        signature = self._edge_signature(
            src_entity_id=src_entity_id,
            relation_type=relation_norm,
            dst_entity_id=dst_entity_id,
            dst_value=dst_value_norm,
            start_ts=start_ts,
            end_ts=end_ts,
            time_kind=time_kind_norm,
        )

        if close_existing:
            self.close_open_edges(
                user_id=user_id,
                src_entity_id=src_entity_id,
                relation_type=relation_norm,
                end_ts=int(start_ts) if start_ts is not None else ts_i,
            )

        self._conn.execute(
            """
            INSERT INTO relation_edges(
              created_ts, updated_ts, user_id, src_entity_id, relation_type,
              dst_entity_id, dst_value, start_ts, end_ts, time_kind,
              weight, confidence, signature, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, signature)
            DO UPDATE SET
              updated_ts = excluded.updated_ts,
              weight = relation_edges.weight + excluded.weight,
              confidence = MAX(relation_edges.confidence, excluded.confidence),
              meta_json = excluded.meta_json
            """,
            (
                ts_i,
                ts_i,
                user_id,
                int(src_entity_id),
                relation_norm,
                int(dst_entity_id) if dst_entity_id is not None else None,
                dst_value_norm,
                int(start_ts) if start_ts is not None else None,
                int(end_ts) if end_ts is not None else None,
                time_kind_norm,
                float(weight_delta),
                float(confidence),
                signature,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        row = self._conn.execute(
            """
            SELECT id FROM relation_edges
            WHERE user_id = ? AND signature = ?
            """,
            (user_id, signature),
        ).fetchone()
        if row is None:
            raise RuntimeError("Failed to resolve relation edge row after upsert")
        edge_id = int(row["id"])
        if source_episode_id is not None:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO edge_sources(edge_id, episode_id, created_ts)
                VALUES (?, ?, ?)
                """,
                (edge_id, int(source_episode_id), ts_i),
            )
        self._conn.commit()
        return edge_id

    def fetch_edge_sources(self, edge_id: int) -> list[int]:
        rows = self._conn.execute(
            """
            SELECT episode_id FROM edge_sources
            WHERE edge_id = ?
            ORDER BY episode_id ASC
            """,
            (int(edge_id),),
        ).fetchall()
        return [int(r["episode_id"]) for r in rows]

    def fetch_relation_edges(
        self,
        *,
        user_id: str,
        src_entity_id: Optional[int] = None,
        dst_entity_id: Optional[int] = None,
        relation_type: Optional[str] = None,
        active_at_ts: Optional[int] = None,
        limit: int = 200,
    ) -> list[RelationEdge]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if src_entity_id is not None:
            clauses.append("src_entity_id = ?")
            params.append(int(src_entity_id))
        if dst_entity_id is not None:
            clauses.append("dst_entity_id = ?")
            params.append(int(dst_entity_id))
        if relation_type is not None:
            clauses.append("relation_type = ?")
            params.append(str(relation_type).strip().lower())
        if active_at_ts is not None:
            clauses.append("(start_ts IS NULL OR start_ts <= ?)")
            clauses.append("(end_ts IS NULL OR end_ts > ?)")
            params.extend([int(active_at_ts), int(active_at_ts)])
        sql = f"""
            SELECT * FROM relation_edges
            WHERE {' AND '.join(clauses)}
            ORDER BY updated_ts DESC, weight DESC
            LIMIT ?
        """
        params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_relation_edge(r) for r in rows]

    def adjust_relation_edge_weight(
        self,
        *,
        edge_id: int,
        delta: float,
        confidence: Optional[float] = None,
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> None:
        row = self._conn.execute(
            "SELECT weight, confidence, meta_json FROM relation_edges WHERE id = ?",
            (int(edge_id),),
        ).fetchone()
        if row is None:
            return
        ts_i = int(ts if ts is not None else time.time())
        current_meta = json.loads(row["meta_json"] or "{}")
        if meta:
            current_meta.update(meta)
        next_weight = max(0.05, float(row["weight"]) + float(delta))
        next_confidence = float(row["confidence"])
        if confidence is not None:
            next_confidence = max(next_confidence, float(confidence))
        self._conn.execute(
            """
            UPDATE relation_edges
            SET updated_ts = ?,
                weight = ?,
                confidence = ?,
                meta_json = ?
            WHERE id = ?
            """,
            (
                ts_i,
                next_weight,
                next_confidence,
                json.dumps(current_meta, ensure_ascii=False),
                int(edge_id),
            ),
        )
        self._conn.commit()

    def record_graph_path_feedback(
        self,
        *,
        user_id: str,
        question: str,
        predicted_answer: str,
        reference_answer: str,
        reward: float,
        chosen_edge_ids: Sequence[int] | None = None,
        rejected_edge_ids: Sequence[int] | None = None,
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> int:
        ts_i = int(ts if ts is not None else time.time())
        cur = self._conn.execute(
            """
            INSERT INTO graph_path_feedback(
              created_ts, user_id, question, predicted_answer, reference_answer,
              reward, chosen_edge_ids_json, rejected_edge_ids_json, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts_i,
                user_id,
                str(question or ""),
                str(predicted_answer or ""),
                str(reference_answer or ""),
                float(reward),
                json.dumps([int(edge_id) for edge_id in (chosen_edge_ids or [])], ensure_ascii=False),
                json.dumps([int(edge_id) for edge_id in (rejected_edge_ids or [])], ensure_ascii=False),
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def fetch_graph_path_feedback(self, *, user_id: str, limit: int = 100) -> list[GraphPathFeedback]:
        rows = self._conn.execute(
            """
            SELECT * FROM graph_path_feedback
            WHERE user_id = ?
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (user_id, int(limit)),
        ).fetchall()
        out: list[GraphPathFeedback] = []
        for row in rows:
            out.append(
                GraphPathFeedback(
                    id=int(row["id"]),
                    created_ts=int(row["created_ts"]),
                    user_id=str(row["user_id"]),
                    question=str(row["question"]),
                    predicted_answer=str(row["predicted_answer"]),
                    reference_answer=str(row["reference_answer"]),
                    reward=float(row["reward"]),
                    chosen_edge_ids=tuple(int(x) for x in json.loads(row["chosen_edge_ids_json"] or "[]")),
                    rejected_edge_ids=tuple(int(x) for x in json.loads(row["rejected_edge_ids_json"] or "[]")),
                    meta=json.loads(row["meta_json"] or "{}"),
                )
            )
        return out

    def add_episode(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        content: str,
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> int:
        ts_i = int(ts if ts is not None else time.time())
        meta_json = json.dumps(meta or {}, ensure_ascii=False)
        cur = self._conn.execute(
            """
            INSERT INTO episodes(ts, session_id, user_id, role, content, meta_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts_i, session_id, user_id, role, content, meta_json),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def add_or_bump_chunk(
        self,
        *,
        session_id: str,
        user_id: str,
        chunk_type: str,
        key: str,
        text: str,
        source_episode_id: Optional[int],
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> int:
        ts_i = int(ts if ts is not None else time.time())
        meta_json = json.dumps(meta or {}, ensure_ascii=False)

        # Upsert by UNIQUE(user_id, chunk_type, key, text).
        # If it already exists, bump frequency + last_recalled_ts (acts as "seen again").
        cur = self._conn.execute(
            """
            INSERT INTO chunks(
              ts, session_id, user_id, chunk_type, key, text, source_episode_id,
              frequency_count, last_recalled_ts, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(user_id, chunk_type, key, text)
            DO UPDATE SET
              frequency_count = frequency_count + 1,
              last_recalled_ts = excluded.last_recalled_ts,
              meta_json = excluded.meta_json
            """,
            (
                ts_i,
                session_id,
                user_id,
                chunk_type,
                key,
                text,
                source_episode_id,
                ts_i,
                meta_json,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def mark_recalled(self, chunk_ids: Iterable[int], *, ts: Optional[int] = None) -> None:
        ids = [int(x) for x in chunk_ids]
        if not ids:
            return
        ts_i = int(ts if ts is not None else time.time())
        q = ",".join("?" for _ in ids)
        self._conn.execute(
            f"""
            UPDATE chunks
            SET recall_count = recall_count + 1,
                last_recalled_ts = ?
            WHERE id IN ({q})
            """,
            (ts_i, *ids),
        )
        self._conn.commit()

    def fetch_recent_chunks(self, *, user_id: str, limit: int = 50) -> list[Chunk]:
        rows = self._conn.execute(
            """
            SELECT * FROM chunks
            WHERE user_id = ?
            ORDER BY last_recalled_ts DESC, ts DESC
            LIMIT ?
            """,
            (user_id, int(limit)),
        ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def fetch_chunks_by_keys(self, *, user_id: str, keys: list[str], limit: int = 50) -> list[Chunk]:
        if not keys:
            return []
        q = ",".join("?" for _ in keys)
        rows = self._conn.execute(
            f"""
            SELECT * FROM chunks
            WHERE user_id = ? AND key IN ({q})
            ORDER BY last_recalled_ts DESC, ts DESC
            LIMIT ?
            """,
            (user_id, *keys, int(limit)),
        ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def fetch_episode(self, episode_id: int) -> Optional[Episode]:
        row = self._conn.execute("SELECT * FROM episodes WHERE id = ?", (int(episode_id),)).fetchone()
        if row is None:
            return None
        return Episode(
            id=int(row["id"]),
            ts=int(row["ts"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            role=str(row["role"]),
            content=str(row["content"]),
            meta=json.loads(row["meta_json"] or "{}"),
        )

    def fetch_children(self, parent_id: int) -> list[Chunk]:
        rows = self._conn.execute(
            "SELECT * FROM chunks WHERE parent_id = ? ORDER BY ts DESC",
            (int(parent_id),),
        ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def set_parent(self, chunk_ids: Iterable[int], parent_id: int) -> None:
        ids = [int(x) for x in chunk_ids]
        if not ids:
            return
        q = ",".join("?" for _ in ids)
        self._conn.execute(
            f"UPDATE chunks SET parent_id = ? WHERE id IN ({q})",
            (int(parent_id), *ids),
        )
        self._conn.commit()

    def fetch_top_level_chunks(self, *, user_id: str, limit: int = 400) -> list[Chunk]:
        rows = self._conn.execute(
            """
            SELECT * FROM chunks
            WHERE user_id = ? AND parent_id IS NULL
            ORDER BY last_recalled_ts DESC, ts DESC
            LIMIT ?
            """,
            (user_id, int(limit)),
        ).fetchall()
        return [self._row_to_chunk(r) for r in rows]

    def _row_to_entity(self, row: sqlite3.Row) -> MemoryEntity:
        return MemoryEntity(
            id=int(row["id"]),
            created_ts=int(row["created_ts"]),
            updated_ts=int(row["updated_ts"]),
            user_id=str(row["user_id"]),
            canonical_name=str(row["canonical_name"]),
            entity_type=str(row["entity_type"]),
            meta=json.loads(row["meta_json"] or "{}"),
        )

    def _row_to_relation_edge(self, row: sqlite3.Row) -> RelationEdge:
        edge_id = int(row["id"])
        return RelationEdge(
            id=edge_id,
            created_ts=int(row["created_ts"]),
            updated_ts=int(row["updated_ts"]),
            user_id=str(row["user_id"]),
            src_entity_id=int(row["src_entity_id"]),
            relation_type=str(row["relation_type"]),
            dst_entity_id=int(row["dst_entity_id"]) if row["dst_entity_id"] is not None else None,
            dst_value=str(row["dst_value"]) if row["dst_value"] is not None else None,
            start_ts=int(row["start_ts"]) if row["start_ts"] is not None else None,
            end_ts=int(row["end_ts"]) if row["end_ts"] is not None else None,
            time_kind=str(row["time_kind"]),
            weight=float(row["weight"]),
            confidence=float(row["confidence"]),
            signature=str(row["signature"]),
            meta=json.loads(row["meta_json"] or "{}"),
            source_episode_ids=tuple(self.fetch_edge_sources(edge_id)),
        )

    def _row_to_chunk(self, row: sqlite3.Row) -> Chunk:
        recall_count = 0
        try:
            recall_count = int(row["recall_count"])
        except (IndexError, KeyError):
            pass
        parent_id = None
        try:
            if row["parent_id"] is not None:
                parent_id = int(row["parent_id"])
        except (IndexError, KeyError):
            pass
        return Chunk(
            id=int(row["id"]),
            ts=int(row["ts"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            chunk_type=str(row["chunk_type"]),
            key=str(row["key"]),
            text=str(row["text"]),
            source_episode_id=int(row["source_episode_id"]) if row["source_episode_id"] is not None else None,
            frequency_count=int(row["frequency_count"]),
            recall_count=recall_count,
            last_recalled_ts=int(row["last_recalled_ts"]),
            meta=json.loads(row["meta_json"] or "{}"),
            parent_id=parent_id,
        )

