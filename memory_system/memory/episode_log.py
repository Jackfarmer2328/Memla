from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


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


class EpisodeLog:
    def __init__(self, db_path: str | os.PathLike[str]) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)
        self._migrate_recall_count()
        self._conn.commit()

    def _migrate_recall_count(self) -> None:
        try:
            self._conn.execute("SELECT recall_count FROM chunks LIMIT 1")
        except sqlite3.OperationalError:
            self._conn.execute("ALTER TABLE chunks ADD COLUMN recall_count INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        self._conn.close()

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

    def _row_to_chunk(self, row: sqlite3.Row) -> Chunk:
        recall_count = 0
        try:
            recall_count = int(row["recall_count"])
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
        )

