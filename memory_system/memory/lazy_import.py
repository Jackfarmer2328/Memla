"""
Lazy Import for Memla (Constraint 5).

Problem: Importing large text corpora (notes, docs, codebases) into Memla
is expensive — every sentence gets chunked, embedded, and indexed upfront.
Most of it is never recalled.

Solution: Three-phase lazy pipeline:
  Phase 1 — Metadata-only indexing: On import, store only the source path,
            title, and a lightweight fingerprint (word count, top terms).
            No embedding, no chunk extraction. Near-instant.
  Phase 2 — On-demand extraction: When a retrieval query hits a lazy source
            (keyword match on metadata), extract and index chunks just-in-time.
  Phase 3 — Behavioral GC: Chunks from lazy sources that are never recalled
            within a decay window get tombstoned (not deleted), freeing
            embedding cache space. They can be re-extracted if needed.

Usage:
    from memory_system.memory.lazy_import import LazyImporter
    importer = LazyImporter(episode_log)
    importer.register_source("notes/project-phoenix.md", user_id="default")
    # ... later, during retrieval:
    importer.on_demand_extract(query="phoenix timeline", user_id="default")
    # ... periodically:
    importer.gc(user_id="default", max_age_days=30)
"""
from __future__ import annotations

import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .episode_log import EpisodeLog


_LAZY_SOURCES_DDL = """
CREATE TABLE IF NOT EXISTS lazy_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    source_path TEXT NOT NULL,
    title TEXT NOT NULL,
    word_count INTEGER NOT NULL DEFAULT 0,
    top_terms TEXT NOT NULL DEFAULT '',
    registered_ts INTEGER NOT NULL,
    extracted_ts INTEGER,
    tombstoned INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, source_path)
);
CREATE INDEX IF NOT EXISTS idx_lazy_user ON lazy_sources(user_id);
"""


@dataclass
class LazySource:
    id: int
    user_id: str
    source_path: str
    title: str
    word_count: int
    top_terms: str
    registered_ts: int
    extracted_ts: Optional[int]
    tombstoned: bool


def _extract_top_terms(text: str, n: int = 20) -> str:
    stopwords = {
        "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
        "has", "have", "he", "her", "his", "i", "in", "is", "it", "its", "me",
        "my", "not", "of", "on", "or", "our", "she", "that", "the", "their",
        "them", "they", "this", "to", "was", "we", "were", "with", "you", "your",
    }
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    tokens = [t for t in tokens if len(t) >= 3 and t not in stopwords]
    return " ".join(w for w, _ in Counter(tokens).most_common(n))


def _title_from_path(path: str) -> str:
    return Path(path).stem.replace("-", " ").replace("_", " ").title()


class LazyImporter:
    def __init__(self, log: EpisodeLog) -> None:
        self.log = log
        self.log._conn.executescript(_LAZY_SOURCES_DDL)
        self.log._conn.commit()

    def register_source(self, source_path: str, *, user_id: str, title: str = "") -> int:
        """Phase 1: Index metadata only — no embedding, no chunking."""
        path = os.path.abspath(source_path)
        if not title:
            title = _title_from_path(source_path)

        word_count = 0
        top_terms = ""
        if os.path.isfile(path):
            try:
                text = Path(path).read_text(encoding="utf-8", errors="replace")
                words = text.split()
                word_count = len(words)
                top_terms = _extract_top_terms(text)
            except Exception:
                pass

        now = int(time.time())
        cur = self.log._conn.execute(
            """
            INSERT INTO lazy_sources(user_id, source_path, title, word_count, top_terms, registered_ts)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, source_path)
            DO UPDATE SET title=excluded.title, word_count=excluded.word_count,
                          top_terms=excluded.top_terms, tombstoned=0
            """,
            (user_id, path, title, word_count, top_terms, now),
        )
        self.log._conn.commit()
        return int(cur.lastrowid) if cur.lastrowid else 0

    def list_sources(self, user_id: str) -> list[LazySource]:
        rows = self.log._conn.execute(
            "SELECT * FROM lazy_sources WHERE user_id=? ORDER BY registered_ts DESC",
            (user_id,),
        ).fetchall()
        return [self._row_to_source(r) for r in rows]

    def on_demand_extract(self, *, query: str, user_id: str, session_id: str = "lazy") -> list[int]:
        """Phase 2: When retrieval finds keyword hits in lazy metadata, extract chunks JIT."""
        q_tokens = set(re.findall(r"[a-zA-Z0-9_]+", query.lower()))
        if not q_tokens:
            return []

        sources = self.log._conn.execute(
            "SELECT * FROM lazy_sources WHERE user_id=? AND tombstoned=0 AND extracted_ts IS NULL",
            (user_id,),
        ).fetchall()

        chunk_ids: list[int] = []
        for row in sources:
            src = self._row_to_source(row)
            meta_tokens = set(src.top_terms.split()) | set(re.findall(r"[a-zA-Z0-9_]+", src.title.lower()))
            overlap = q_tokens & meta_tokens
            if len(overlap) < 1:
                continue
            ids = self._extract_source(src, user_id=user_id, session_id=session_id)
            chunk_ids.extend(ids)

        return chunk_ids

    def _extract_source(self, src: LazySource, *, user_id: str, session_id: str) -> list[int]:
        """Actually extract chunks from a lazy source."""
        path = Path(src.source_path)
        if not path.is_file():
            return []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return []

        from .chunk_manager import ChunkManager, MemoryChunkDraft

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.strip()) >= 20]
        now = int(time.time())
        chunk_ids: list[int] = []

        for s in sentences[:100]:
            key = re.sub(r"[^a-zA-Z0-9_ ]+", " ", s[:80].lower()).strip()[:256]
            cid = self.log.add_or_bump_chunk(
                session_id=session_id,
                user_id=user_id,
                chunk_type="fact",
                key=key,
                text=f"[Imported: {src.title}] {s}",
                source_episode_id=None,
                meta={"lazy_source_id": src.id, "source_path": src.source_path},
                ts=now,
            )
            chunk_ids.append(cid)

        self.log._conn.execute(
            "UPDATE lazy_sources SET extracted_ts=? WHERE id=?",
            (now, src.id),
        )
        self.log._conn.commit()
        return chunk_ids

    def gc(self, *, user_id: str, max_age_days: int = 30) -> int:
        """Phase 3: Behavioral GC — tombstone chunks from lazy sources never recalled."""
        cutoff_ts = int(time.time()) - (max_age_days * 86400)
        cur = self.log._conn.execute(
            """
            UPDATE chunks SET parent_id = -1
            WHERE user_id = ?
              AND recall_count = 0
              AND ts < ?
              AND meta_json LIKE '%lazy_source_id%'
              AND parent_id IS NULL
            """,
            (user_id, cutoff_ts),
        )
        tombstoned = cur.rowcount
        if tombstoned > 0:
            self.log._conn.commit()
        return tombstoned

    def _row_to_source(self, row) -> LazySource:
        return LazySource(
            id=row["id"],
            user_id=row["user_id"],
            source_path=row["source_path"],
            title=row["title"],
            word_count=row["word_count"],
            top_terms=row["top_terms"],
            registered_ts=row["registered_ts"],
            extracted_ts=row["extracted_ts"],
            tombstoned=bool(row["tombstoned"]),
        )
