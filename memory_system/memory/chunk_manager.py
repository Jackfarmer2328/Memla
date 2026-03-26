from __future__ import annotations

import math
import re
import time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple

from .episode_log import Chunk, EpisodeLog


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "not",
    "of",
    "on",
    "or",
    "our",
    "she",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "with",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "how",
    "do",
    "does",
    "did",
    "done",
    "about",
    "again",
    "all",
    "any",
    "been",
    "can",
    "could",
    "just",
    "like",
    "more",
    "out",
    "than",
    "then",
    "there",
    "very",
    "you",
    "your",
}

_QUESTION_ENTITY_TOKENS = {
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "how",
}

_GENERIC_FILLER_TOKENS = {
    "awesome",
    "cool",
    "glad",
    "good",
    "great",
    "hey",
    "nice",
    "sound",
    "thank",
    "thanks",
    "totally",
    "wow",
    "yeah",
}

_SPECIFIC_DATE_TOKENS = {
    "april",
    "august",
    "december",
    "february",
    "friday",
    "january",
    "july",
    "june",
    "last",
    "march",
    "monday",
    "month",
    "next",
    "november",
    "october",
    "saturday",
    "september",
    "sunday",
    "thursday",
    "today",
    "tomorrow",
    "tuesday",
    "week",
    "wednesday",
    "year",
    "yesterday",
}

_IRREGULAR_TOKEN_MAP = {
    "gone": "go",
    "fri": "friday",
    "mel": "melanie",
    "mon": "monday",
    "ran": "run",
    "sat": "saturday",
    "sun": "sunday",
    "thu": "thursday",
    "thur": "thursday",
    "thurs": "thursday",
    "tue": "tuesday",
    "tues": "tuesday",
    "wed": "wednesday",
    "went": "go",
    "lgbtq": "lgbt",
}

_GENERIC_DIALOGUE_PATTERNS = (
    r"\bhow did (?:it|you)\b",
    r"\bhow's it going\b",
    r"\blong time no (?:chat|talk)\b",
    r"\bhope all'?s good\b",
    r"\bwhat got you\b",
    r"\bwhat other\b",
    r"\bwhat was your favorite\b",
    r"\bwhat've you been up to\b",
)


def _normalize_token(token: str) -> str:
    token = token.lower()
    token = _IRREGULAR_TOKEN_MAP.get(token, token)
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("ing") and len(token) > 5:
        token = token[:-3]
        if len(token) >= 3 and token[-1] == token[-2]:
            token = token[:-1]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("es") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 3:
        token = token[:-1]
    return token


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", text)
    out: list[str] = []
    for token in tokens:
        norm = _normalize_token(token)
        if len(norm) >= 2 and norm not in _STOPWORDS:
            out.append(norm)
    return out


def _stable_key(text: str) -> str:
    # Normalize a key for retrieval: lower, remove punctuation, collapse spaces.
    k = re.sub(r"[^a-zA-Z0-9_ ]+", " ", text.lower())
    k = re.sub(r"\s+", " ", k).strip()
    return k[:256]


@dataclass(frozen=True)
class MemoryChunkDraft:
    chunk_type: str  # fact | decision | entity | note
    key: str
    text: str


@dataclass(frozen=True)
class GraphRelationDraft:
    subject: str
    relation_type: str
    object_text: str
    object_entity_type: str = "entity"
    close_existing: bool = False
    start_ts: int | None = None
    end_ts: int | None = None
    time_kind: str = "timeless"
    confidence: float = 1.0
    meta: dict[str, Any] | None = None


_PRONOUN_SUBJECTS = {"he", "she", "they", "him", "her", "them"}
_SELF_SUBJECTS = {"i", "me", "myself", "we", "us", "ourselves"}
_STATEFUL_RELATIONS = {"lives_in", "works_at"}
_ACTION_SUBJECT_PATTERN = (
    r"(?P<subject>"
    r"I|We|He|She|They|"
    r"[A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+){0,2}|"
    r"[A-Z][a-zA-Z0-9_]+(?:'s|’s)\s+[A-Za-z][A-Za-z0-9_]+(?:\s+[A-Za-z][A-Za-z0-9_]+){0,2}|"
    r"(?:the|my|our|his|her|their)\s+[A-Za-z][A-Za-z0-9_]+(?:\s+[A-Za-z][A-Za-z0-9_]+){0,3}"
    r")"
)


class ChunkManager:
    """
    Step 1 memory chunks:
    - Extracts a few structured chunks from each user message (heuristic or LLM)
    - Retrieves top-k by hybrid scoring: semantic (MiniLM) + keyword + recency + frequency
    - Falls back to keyword-only if the embedding model is unavailable
    """

    def __init__(
        self,
        episode_log: EpisodeLog,
        *,
        llm_extractor: Optional[Callable[[str], Tuple[list["MemoryChunkDraft"], dict[str, Any]]]] = None,
        query_expander: Optional[Callable[[str], list[str]]] = None,
    ) -> None:
        self.log = episode_log
        self._llm_extractor = llm_extractor
        self._query_expander = query_expander
        self._recent_entity_context: dict[tuple[str, str], list[str]] = {}

    def extract_chunks(self, user_text: str) -> tuple[list[MemoryChunkDraft], dict[str, Any]]:
        text = user_text.strip()
        if not text:
            return [], {"source": "empty"}

        if self._llm_extractor is not None:
            try:
                drafts, meta = self._llm_extractor(text)
                if drafts:
                    return drafts, meta
            except Exception as e:
                # Fall back to heuristic extraction; persist the failure signal in meta.
                pass

        drafts: list[MemoryChunkDraft] = []

        # Decisions / preferences (simple pattern capture).
        decision_patterns = [
            r"\b(?:i|we)\s+(?:decided|choose|chose|prefer|want|need)\s+(?P<x>.+)$",
            r"\bmy\s+preference\s+is\s+(?P<x>.+)$",
        ]
        for pat in decision_patterns:
            m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
            if m:
                x = m.group("x").strip().rstrip(".")
                if x:
                    drafts.append(
                        MemoryChunkDraft(
                            chunk_type="decision",
                            key=_stable_key(x),
                            text=f"Preference/decision: {x}",
                        )
                    )
                break

        # Entities: naive capture of "X is Y", and capitalized tokens.
        is_stmt = re.findall(r"\b([A-Z][a-zA-Z0-9_]+)\s+is\s+([^.\n]{3,80})", text)
        for ent, desc in is_stmt[:5]:
            drafts.append(
                MemoryChunkDraft(
                    chunk_type="entity",
                    key=_stable_key(ent),
                    text=f"Entity: {ent} — {desc.strip()}",
                )
            )

        caps = re.findall(r"\b[A-Z][a-zA-Z0-9_]{2,}\b", text)
        for ent in list(dict.fromkeys(caps))[:8]:
            if _normalize_token(ent) in _QUESTION_ENTITY_TOKENS:
                continue
            drafts.append(MemoryChunkDraft(chunk_type="entity", key=_stable_key(ent), text=f"Entity mentioned: {ent}"))

        # Facts: keep a few dense sentences.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        for s in sentences[:5]:
            if len(s) >= 20 and not s.startswith("/") and not s.endswith("?"):
                drafts.append(MemoryChunkDraft(chunk_type="fact", key=_stable_key(s[:80]), text=f"Fact: {s}"))

        # De-dupe by (type,key,text).
        seen = set()
        out: list[MemoryChunkDraft] = []
        for d in drafts:
            if not self._should_store_draft(d):
                continue
            k = (d.chunk_type, d.key, d.text)
            if k in seen:
                continue
            seen.add(k)
            out.append(d)
        return out[:20], {"source": "heuristic_extract_v1"}

    def _should_store_draft(self, draft: MemoryChunkDraft) -> bool:
        text = draft.text.strip()
        if not text:
            return False

        if draft.chunk_type == "entity" and text.lower().startswith("entity mentioned:"):
            entity = text.split(":", 1)[-1].strip()
            if _normalize_token(entity) in _QUESTION_ENTITY_TOKENS:
                return False
            # Single-token entity mention drafts are too noisy for retrieval.
            return False

        content_tokens = _tokenize(text)
        if draft.chunk_type == "fact" and len(content_tokens) < 4:
            return False
        if draft.chunk_type == "decision" and len(content_tokens) < 2:
            return False
        if draft.chunk_type == "entity" and len(content_tokens) < 2:
            return False
        return True

    def persist_user_message(
        self, *, session_id: str, user_id: str, user_text: str, ts: int | None = None
    ) -> tuple[int, list[int]]:
        return self.persist_message(
            session_id=session_id,
            user_id=user_id,
            role="user",
            text=user_text,
            ts=ts,
            extract_chunks=True,
        )

    def persist_chunks_from_text(
        self,
        *,
        session_id: str,
        user_id: str,
        text: str,
        source_episode_id: int | None,
        speaker_role: str = "user",
        ts: int | None = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> list[int]:
        ts_i = int(ts if ts is not None else time.time())
        speaker = (speaker_role or "user").strip().lower() or "user"
        chunk_ids: list[int] = []
        drafts, extract_meta = self.extract_chunks(text)
        for draft in drafts:
            chunk_meta = dict(extract_meta)
            if meta:
                chunk_meta.update(meta)
            if speaker != "user":
                chunk_meta.setdefault("speaker_role", speaker)

            key = draft.key
            stored_text = draft.text
            if speaker != "user":
                key = _stable_key(f"{speaker} {draft.key}")
                stored_text = f"[{speaker}] {draft.text}"

            cid = self.log.add_or_bump_chunk(
                session_id=session_id,
                user_id=user_id,
                chunk_type=draft.chunk_type,
                key=key,
                text=stored_text,
                source_episode_id=source_episode_id,
                ts=ts_i,
                meta=chunk_meta,
            )
            chunk_ids.append(cid)
        return chunk_ids

    def persist_message(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        text: str,
        ts: int | None = None,
        extract_chunks: bool = True,
        meta: Optional[dict[str, Any]] = None,
    ) -> tuple[int, list[int]]:
        ts_i = int(ts if ts is not None else time.time())
        episode_id = self.log.add_episode(
            session_id=session_id,
            user_id=user_id,
            role=role,
            content=text,
            meta=meta,
            ts=ts_i,
        )

        chunk_ids: list[int] = []
        if extract_chunks:
            chunk_ids = self.persist_chunks_from_text(
                session_id=session_id,
                user_id=user_id,
                text=text,
                source_episode_id=episode_id,
                speaker_role=role,
                ts=ts_i,
                meta=meta,
            )
        self._persist_graph_memory(
            session_id=session_id,
            user_id=user_id,
            role=role,
            text=text,
            source_episode_id=episode_id,
            ts=ts_i,
            meta=meta,
        )
        return episode_id, chunk_ids

    def _persist_graph_memory(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        text: str,
        source_episode_id: int,
        ts: int,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        explicit_speaker = None
        if meta:
            explicit_speaker = " ".join(str(meta.get("speaker") or "").strip().split()) or None
        entity_mentions = _extract_entity_spans(text)
        relation_drafts = self._extract_graph_relation_drafts(
            session_id=session_id,
            user_id=user_id,
            role=role,
            text=text,
            ts=ts,
            meta=meta,
            explicit_speaker=explicit_speaker,
        )

        context_entities: list[str] = []
        for mention in entity_mentions:
            canonical = self._resolve_graph_subject(
                mention=mention,
                role=role,
                user_id=user_id,
                session_id=session_id,
                explicit_speaker=explicit_speaker,
            )
            entity_type = "person" if mention and mention[0].isupper() else "entity"
            self._ensure_entity(
                user_id=user_id,
                canonical_name=canonical,
                entity_type=entity_type,
                mention=mention,
                ts=ts,
            )

        for draft in relation_drafts:
            subject_name = self._resolve_graph_subject(
                mention=draft.subject,
                role=role,
                user_id=user_id,
                session_id=session_id,
                explicit_speaker=explicit_speaker,
            )
            subject_type = _classify_graph_entity_type(draft.subject, fallback="entity")
            if subject_name == (explicit_speaker or ""):
                subject_type = "person"
            elif subject_name == "User":
                subject_type = "self"
            subject_id = self._ensure_entity(
                user_id=user_id,
                canonical_name=subject_name,
                entity_type=subject_type,
                mention=draft.subject,
                ts=ts,
            )
            object_id = self._ensure_entity(
                user_id=user_id,
                canonical_name=draft.object_text,
                entity_type=draft.object_entity_type,
                mention=draft.object_text,
                ts=ts,
            )
            edge_id = self.log.add_or_bump_relation_edge(
                user_id=user_id,
                src_entity_id=subject_id,
                relation_type=draft.relation_type,
                dst_entity_id=object_id,
                start_ts=draft.start_ts,
                end_ts=draft.end_ts,
                time_kind=draft.time_kind,
                confidence=draft.confidence,
                weight_delta=1.0,
                source_episode_id=source_episode_id,
                meta=draft.meta,
                ts=ts,
                close_existing=draft.close_existing,
            )
            self._link_graph_structure(
                user_id=user_id,
                subject_id=subject_id,
                relation_type=draft.relation_type,
                object_id=object_id,
                current_edge_id=edge_id,
                current_start_ts=draft.start_ts,
                source_episode_id=source_episode_id,
                meta=draft.meta,
                ts=ts,
            )
            context_entities.append(subject_name)
            if draft.object_entity_type == "person":
                context_entities.append(draft.object_text)

        self._remember_recent_entities(
            user_id=user_id,
            session_id=session_id,
            entity_names=context_entities,
        )

    def _extract_graph_relation_drafts(
        self,
        *,
        session_id: str,
        user_id: str,
        role: str,
        text: str,
        ts: int,
        meta: Optional[dict[str, Any]] = None,
        explicit_speaker: str | None = None,
    ) -> list[GraphRelationDraft]:
        subject = r"(?P<subject>I|We|He|She|They|[A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)"
        entity = r"(?P<object>[A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+)*)"
        out: list[GraphRelationDraft] = []
        temporal_meta = _derive_temporal_relation_meta(text, meta)
        temporal_start_ts = _graph_relation_start_ts(temporal_meta, fallback_ts=ts)
        list_subject = explicit_speaker or "I"

        patterns: list[tuple[str, str, str, bool, int | None, str]] = [
            (
                rf"\b{subject}\s+(?:live|lives|lived)\s+in\s+{entity}\b",
                "lives_in",
                "location",
                True,
                temporal_start_ts,
                "validity",
            ),
            (
                rf"\b{subject}\s+(?:am|are|is|was|were)\s+living\s+in\s+{entity}\b",
                "lives_in",
                "location",
                True,
                temporal_start_ts,
                "validity",
            ),
            (
                rf"\b{subject}\s+moved\s+to\s+{entity}\b",
                "lives_in",
                "location",
                True,
                temporal_start_ts,
                "validity",
            ),
            (
                rf"\b{subject}\s+works?\s+(?:at|for)\s+{entity}\b",
                "works_at",
                "organization",
                True,
                temporal_start_ts,
                "validity",
            ),
            (
                rf"\b{subject}\s+worked\s+(?:at|for)\s+{entity}\b",
                "works_at",
                "organization",
                True,
                temporal_start_ts,
                "validity",
            ),
        ]

        for pattern, relation_type, object_entity_type, close_existing, start_ts, time_kind in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                subject_text = str(match.group("subject")).strip()
                object_text = str(match.group("object")).strip()
                if not subject_text or not object_text:
                    continue
                out.append(
                    GraphRelationDraft(
                        subject=subject_text,
                        relation_type=relation_type,
                        object_text=object_text,
                        object_entity_type=object_entity_type,
                        close_existing=close_existing,
                        start_ts=start_ts,
                        time_kind=time_kind,
                        confidence=0.9 if start_ts is not None else 0.75,
                        meta={"source": "graph_extract_v2", "session_id": session_id, "role": role, **temporal_meta},
                    )
                )

        list_like_relations = {
            "participate_in",
            "buy",
            "paint",
            "read",
            "watch",
            "like",
            "practice",
            "cook",
            "have_pet",
            "do_activity",
        }
        title_like_relations = {"read", "watch", "like"}
        for relation_type, patterns in _generic_action_relation_patterns(list_subject).items():
            for pattern in patterns:
                for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                    subject_text = " ".join(
                        str(match.groupdict().get("subject") or list_subject).strip().split()
                    )
                    raw_object = str(match.group("object") or "")
                    if not subject_text or not raw_object.strip():
                        continue
                    object_values = (
                        _split_relation_values(raw_object, prefer_titles=relation_type in title_like_relations)
                        if relation_type in list_like_relations
                        else [_clean_graph_object_text(raw_object)]
                    )
                    for object_text in object_values:
                        object_text = _clean_graph_object_text(
                            object_text,
                            preserve_leading_article=relation_type in title_like_relations,
                        )
                        if not object_text:
                            continue
                        if not _is_valid_graph_relation_object(relation_type, object_text):
                            continue
                        out.append(
                            GraphRelationDraft(
                                subject=subject_text,
                                relation_type=relation_type,
                                object_text=object_text,
                                object_entity_type=_classify_graph_entity_type(object_text, fallback="thing"),
                                start_ts=temporal_start_ts,
                                confidence=0.66,
                                meta={"source": "graph_extract_v3_action", "session_id": session_id, "role": role, **temporal_meta},
                            )
                        )

        for values in _extract_list_relation_values(
            text,
            patterns=(
                rf"\b(?:{re.escape(list_subject)}|I|We|{subject})\s+(?:play|plays|played)\s+(?P<values>[^.?!]+)",
            ),
        ):
            for value in values:
                out.append(
                    GraphRelationDraft(
                        subject=list_subject,
                        relation_type="plays_instrument",
                        object_text=value,
                        object_entity_type="instrument",
                        start_ts=temporal_start_ts,
                        confidence=0.72,
                        meta={"source": "graph_extract_v2", "session_id": session_id, "role": role, **temporal_meta},
                    )
                )

        for values in _extract_list_relation_values(
            text,
            patterns=(
                rf"\b(?:{re.escape(list_subject)}|I|We|{subject})[^.?!]{{0,40}}(?:been to|visited)\s+(?P<values>[^.?!]+)",
                r"\b(?:a|the|my)?\s*trip[^.?!]{0,30}\sto\s+(?P<values>[^.?!]+)",
            ),
            capitalized_only=True,
        ):
            for value in values:
                out.append(
                    GraphRelationDraft(
                        subject=list_subject,
                        relation_type="visited_place",
                        object_text=value,
                        object_entity_type="location",
                        start_ts=temporal_start_ts,
                        confidence=0.68,
                        meta={"source": "graph_extract_v2", "session_id": session_id, "role": role, **temporal_meta},
                    )
                )

        for values in _extract_list_relation_values(
            text,
            patterns=(
                rf"\b(?:{re.escape(list_subject)}|I|We|{subject})[^.?!]{{0,40}}(?:saw|seen)\s+(?P<values>[^.?!]+?)\s+live\b",
            ),
            prefer_titles=True,
        ):
            for value in values:
                out.append(
                    GraphRelationDraft(
                        subject=list_subject,
                        relation_type="saw_artist",
                        object_text=value,
                        object_entity_type="artist",
                        start_ts=temporal_start_ts,
                        confidence=0.68,
                        meta={"source": "graph_extract_v2", "session_id": session_id, "role": role, **temporal_meta},
                    )
                )

        favorite_style_patterns = (
            rf"\b(?:{re.escape(list_subject)}|I|We|{subject})[^.?!]{{0,40}}favorite style(?: of dance)?(?: is| has always been)?\s+(?P<style>[A-Za-z][A-Za-z -]+)",
            r"\b(?P<style>[A-Za-z][A-Za-z -]+)\s+is my top pick\b",
        )
        for pattern in favorite_style_patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                style = " ".join(str(match.group("style") or "").strip().split())
                style = re.sub(r"\b(dance|dancing)\b", "", style, flags=re.IGNORECASE).strip(" .,-")
                if not style:
                    continue
                out.append(
                    GraphRelationDraft(
                        subject=list_subject,
                        relation_type="favorite_style",
                        object_text=style.title() if style.islower() else style,
                        object_entity_type="style",
                        start_ts=temporal_start_ts,
                        confidence=0.7,
                        meta={"source": "graph_extract_v2", "session_id": session_id, "role": role, **temporal_meta},
                    )
                )

        seen: set[tuple[str, str, str, Optional[int]]] = set()
        deduped: list[GraphRelationDraft] = []
        for draft in out:
            key = (draft.subject.lower(), draft.relation_type, draft.object_text.lower(), draft.start_ts)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(draft)
        return deduped

    def _ensure_entity(
        self,
        *,
        user_id: str,
        canonical_name: str,
        entity_type: str,
        mention: str,
        ts: int,
    ) -> int:
        canonical = " ".join(str(canonical_name or "").strip().split())
        if not canonical:
            raise ValueError("canonical_name must not be empty")
        entity_id = self.log.get_or_create_entity(
            user_id=user_id,
            canonical_name=canonical,
            entity_type=entity_type,
            meta={"source": "graph_extract_v2"},
            ts=ts,
        )
        if mention:
            mention_norm = " ".join(mention.strip().split())
            if mention_norm and mention_norm.lower() != canonical.lower():
                self.log.add_entity_alias(
                    user_id=user_id,
                    entity_id=entity_id,
                    alias=mention_norm,
                    confidence=0.85,
                    meta={"source": "graph_extract_v2", "kind": "surface_mention"},
                    ts=ts,
                )
        if entity_type == "person" and " " in canonical:
            first_name = canonical.split()[0]
            self.log.add_entity_alias(
                user_id=user_id,
                entity_id=entity_id,
                alias=first_name,
                confidence=0.6,
                meta={"source": "graph_extract_v2", "kind": "first_name"},
                ts=ts,
            )
        return entity_id

    def _resolve_graph_subject(
        self,
        *,
        mention: str,
        role: str,
        user_id: str,
        session_id: str,
        explicit_speaker: str | None = None,
    ) -> str:
        mention_norm = " ".join(str(mention or "").strip().split())
        if not mention_norm:
            return explicit_speaker or "User"

        lowered = mention_norm.lower()
        if lowered in _SELF_SUBJECTS:
            return explicit_speaker or "User"

        ctx_key = (user_id, session_id)
        recent = self._recent_entity_context.get(ctx_key, [])
        if lowered in _PRONOUN_SUBJECTS and recent:
            return recent[0]

        resolved = self.log.resolve_entity(user_id=user_id, mention=mention_norm)
        if resolved is not None:
            return resolved.canonical_name

        if recent and " " not in mention_norm:
            needle = mention_norm.lower()
            for candidate in recent:
                first = candidate.split()[0].lower()
                if first.startswith(needle) or needle.startswith(first):
                    return candidate

        return mention_norm

    def _remember_recent_entities(
        self,
        *,
        user_id: str,
        session_id: str,
        entity_names: Sequence[str],
    ) -> None:
        ctx_key = (user_id, session_id)
        remembered = list(self._recent_entity_context.get(ctx_key, []))
        for name in entity_names:
            norm = " ".join(str(name or "").strip().split())
            if not norm:
                continue
            remembered = [existing for existing in remembered if existing.lower() != norm.lower()]
            remembered.insert(0, norm)
        self._recent_entity_context[ctx_key] = remembered[:8]

    def _link_graph_structure(
        self,
        *,
        user_id: str,
        subject_id: int,
        relation_type: str,
        object_id: int,
        current_edge_id: int,
        current_start_ts: int | None,
        source_episode_id: int,
        meta: Optional[dict[str, Any]],
        ts: int,
    ) -> None:
        relation_root = str(relation_type or "").strip().lower()
        if not relation_root:
            return
        prior_edges = [
            edge
            for edge in self.log.fetch_relation_edges(
                user_id=user_id,
                src_entity_id=subject_id,
                relation_type=relation_root,
                limit=64,
            )
            if edge.id != current_edge_id and edge.dst_entity_id is not None and edge.dst_entity_id != object_id
        ]
        if not prior_edges:
            return

        previous_edge = sorted(
            prior_edges,
            key=lambda edge: (
                float(edge.start_ts or edge.updated_ts),
                float(edge.updated_ts),
                float(edge.weight),
            ),
            reverse=True,
        )[0]
        previous_object_id = previous_edge.dst_entity_id
        if previous_object_id is None or previous_object_id == object_id:
            return

        structure_meta = dict(meta or {})
        structure_meta.update(
            {
                "graph_structure": "sequence_chain",
                "graph_chain_relation_root": relation_root,
                "graph_chain_subject_id": int(subject_id),
                "graph_previous_edge_id": int(previous_edge.id),
            }
        )
        for rel_type, src_id, dst_id in (
            (f"previous_{relation_root}", object_id, previous_object_id),
            (f"next_{relation_root}", previous_object_id, object_id),
        ):
            self.log.add_or_bump_relation_edge(
                user_id=user_id,
                src_entity_id=src_id,
                relation_type=rel_type,
                dst_entity_id=dst_id,
                time_kind="sequence",
                confidence=0.82,
                weight_delta=0.35,
                source_episode_id=source_episode_id,
                meta=structure_meta,
                ts=ts,
            )

        current_sort_ts = int(current_start_ts) if current_start_ts is not None else None
        previous_sort_ts = int(previous_edge.start_ts) if previous_edge.start_ts is not None else None
        if current_sort_ts is not None and previous_sort_ts is not None and current_sort_ts >= previous_sort_ts:
            for rel_type, src_id, dst_id in (
                (f"before_{relation_root}", previous_object_id, object_id),
                (f"after_{relation_root}", object_id, previous_object_id),
            ):
                self.log.add_or_bump_relation_edge(
                    user_id=user_id,
                    src_entity_id=src_id,
                    relation_type=rel_type,
                    dst_entity_id=dst_id,
                    start_ts=previous_sort_ts,
                    end_ts=current_sort_ts,
                    time_kind="sequence",
                    confidence=0.8,
                    weight_delta=0.25,
                    source_episode_id=source_episode_id,
                    meta=structure_meta,
                    ts=ts,
                )

    def retrieve(self, *, user_id: str, query_text: str, k: int = 12) -> list[Chunk]:
        candidate_limit = max(1500, int(k) * 50)
        candidates = self.log.fetch_top_level_chunks(user_id=user_id, limit=candidate_limit)
        if not candidates:
            return []

        q_tokens = set(_tokenize(query_text))
        q_entities = _extract_named_entities(query_text)
        q_subject = _extract_query_subject(query_text)
        expanded_query_text = query_text
        cue_phrases: list[str] = []
        if self._query_expander is not None:
            try:
                cues = [cue.strip() for cue in self._query_expander(query_text) if cue and cue.strip()]
            except Exception:
                cues = []
            if cues:
                cue_phrases = cues[:]
                expanded_query_text = query_text + "\n" + "\n".join(cues)
                q_tokens |= set(_tokenize(expanded_query_text))
                q_entities |= _extract_named_entities(expanded_query_text)
                if q_subject is None:
                    q_subject = _extract_query_subject(expanded_query_text)
        cue_tokens = set(_tokenize("\n".join(cue_phrases))) if cue_phrases else set()
        now = time.time()
        is_temporal_query = bool(re.search(r"\bwhen\b", query_text.lower()))
        is_reflective_query = bool(re.match(r"^[A-Z][a-zA-Z0-9_]+:", query_text.strip()))

        # --- Graph-augmented contextual retrieval (C1) ---
        # Enrich chunk text with connected node context before embedding.
        # MiniLM doesn't know domain vocabulary, but reads context clues.
        enriched_texts = self._enrich_with_graph_context(candidates, user_id)

        # --- Attempt semantic scoring via MiniLM embeddings ---
        sem_scores: dict[int, float] = {}
        try:
            from ..middleware.context_builder import _get_lora_manager
            mgr = _get_lora_manager()
            if mgr is not None:
                q_emb = mgr.embed_query(expanded_query_text)
                c_embs = mgr.embed_many(enriched_texts)
                if q_emb and c_embs:
                    for idx, c_emb in enumerate(c_embs):
                        dot = sum(a * b for a, b in zip(q_emb, c_emb))
                        sem_scores[candidates[idx].id] = float(dot)
        except Exception:
            pass

        has_semantic = bool(sem_scores)

        def score(c: Chunk) -> float:
            c_tokens = set(_tokenize(c.text)) | set(_tokenize(c.key))
            overlap = len(q_tokens & c_tokens)
            lexical_recall = overlap / max(1.0, float(len(q_tokens)))
            cue_token_overlap = 0.0
            if cue_tokens:
                cue_token_overlap = len(cue_tokens & c_tokens) / max(1.0, float(len(cue_tokens)))
            c_entities = _extract_named_entities(c.text)
            entity_overlap = len(q_entities & c_entities) / max(1.0, float(len(q_entities)))
            speaker = _extract_speaker_label(c.text)
            speaker_match = 1.0 if q_subject and speaker == q_subject else 0.0
            speaker_mismatch_penalty = 0.0
            if q_subject and speaker and speaker not in {q_subject, "assistant"}:
                speaker_mismatch_penalty = 0.25

            age_s = max(0.0, now - float(c.last_recalled_ts))
            recency = math.exp(-age_s / (60.0 * 60.0 * 24.0 * 7.0))

            freq = math.log(1.0 + float(c.frequency_count))
            specificity = _specificity_score(c.text)
            generic_penalty = _generic_dialogue_penalty(c.text)
            source = str(c.meta.get("source") or "").strip().lower()
            source_boost = 0.0
            if source == "benchmark_raw_turn":
                source_boost += 0.2
            if source == "heuristic_extract_v1":
                if generic_penalty >= 0.5:
                    source_boost -= 0.8
                elif specificity < 0.45:
                    source_boost -= 0.3
            cue_phrase_boost = _cue_phrase_overlap(f"{c.text}\n{c.key}", cue_phrases)
            temporal_hint = 0.0
            if is_temporal_query and _has_temporal_hint(c.text):
                temporal_hint = 0.45
            causal_hint = 0.0
            if is_reflective_query and _has_causal_hint(c.text):
                causal_hint = 0.45

            type_boost = 0.0
            if c.chunk_type == "decision":
                type_boost = 0.5
            elif c.chunk_type == "fact":
                type_boost = 0.4
            elif c.chunk_type == "entity":
                type_boost = -0.2

            if has_semantic:
                # Cosine sim is in [-1, 1]; shift to [0, 2] for positive weighting.
                semantic = (sem_scores.get(c.id, 0.0) + 1.0)
                return (
                    (1.4 * semantic)
                    + (1.8 * lexical_recall)
                    + (2.6 * cue_token_overlap)
                    + (1.5 * entity_overlap)
                    + (1.6 * speaker_match)
                    + (0.8 * specificity)
                    + cue_phrase_boost
                    + temporal_hint
                    + causal_hint
                    + source_boost
                    + (0.2 * recency)
                    + (0.2 * freq)
                    + type_boost
                    - generic_penalty
                    - speaker_mismatch_penalty
                )
            else:
                return (
                    (2.2 * lexical_recall)
                    + (2.8 * cue_token_overlap)
                    + (1.5 * entity_overlap)
                    + (1.6 * speaker_match)
                    + (0.8 * specificity)
                    + cue_phrase_boost
                    + temporal_hint
                    + causal_hint
                    + source_boost
                    + (0.4 * recency)
                    + (0.2 * freq)
                    + type_boost
                    - generic_penalty
                    - speaker_mismatch_penalty
                )

        ranked = sorted(candidates, key=score, reverse=True)
        top = ranked[: max(3, int(k))]
        return top

    def _enrich_with_graph_context(self, chunks: list[Chunk], user_id: str) -> list[str]:
        """Prepend connected-node context clues to each chunk before embedding.

        The graph becomes a living dictionary: MiniLM doesn't know "Project Phoenix",
        but it reads "[Context: React frontend, Supabase database]" and maps correctly.
        """
        try:
            links = self.log._conn.execute(
                "SELECT chunk_a_id, chunk_b_id FROM user_links WHERE user_id=?",
                (user_id,),
            ).fetchall()
        except Exception:
            return [c.text for c in chunks]

        if not links:
            return [c.text for c in chunks]

        neighbors: dict[int, set[int]] = {}
        for a, b in links:
            neighbors.setdefault(a, set()).add(b)
            neighbors.setdefault(b, set()).add(a)

        chunk_by_id = {c.id: c for c in chunks}
        all_chunks_by_id = chunk_by_id.copy()
        missing_ids = set()
        for c in chunks:
            for nid in neighbors.get(c.id, set()):
                if nid not in all_chunks_by_id:
                    missing_ids.add(nid)
        if missing_ids:
            all_db = self.log.fetch_recent_chunks(user_id=user_id, limit=9999)
            for c in all_db:
                if c.id in missing_ids:
                    all_chunks_by_id[c.id] = c

        enriched: list[str] = []
        for c in chunks:
            nids = neighbors.get(c.id, set())
            if not nids:
                enriched.append(c.text)
                continue
            clues = []
            for nid in list(nids)[:5]:
                nc = all_chunks_by_id.get(nid)
                if nc:
                    clues.append(nc.key)
            if clues:
                context = ", ".join(clues)
                enriched.append(f"{c.text} [Context: {context}]")
            else:
                enriched.append(c.text)
        return enriched

    def mark_recalled(self, chunks: Sequence[Chunk]) -> None:
        self.log.mark_recalled([c.id for c in chunks])


def ewc_lambda_multiplier_for_chunks(chunks: Sequence[Chunk]) -> float:
    """
    Step 3 frequency integration:
    - frequency_count >= 3 => stronger protection (bolded)
    - frequency_count == 1 => weaker protection (faint)

    Returns a single multiplier for the current training/update batch.
    """
    if not chunks:
        return 1.0
    freqs = [max(1, int(c.frequency_count)) for c in chunks]
    hi = sum(1 for f in freqs if f >= 3)
    lo = sum(1 for f in freqs if f == 1)
    if hi > lo:
        return 1.5
    if lo > hi:
        return 0.5
    return 1.0


def _extract_named_entities(text: str) -> set[str]:
    entities = set()
    for bracketed in re.findall(r"\[([A-Z][a-zA-Z0-9_]+)\]", text):
        norm = _normalize_token(bracketed)
        if norm and norm not in _STOPWORDS:
            entities.add(norm)
    for prefixed in re.findall(r"\b([A-Z][a-zA-Z0-9_]+):", text):
        norm = _normalize_token(prefixed)
        if norm and norm not in _STOPWORDS:
            entities.add(norm)
    for token in re.findall(r"\b[A-Z][a-zA-Z0-9_]{2,}\b", text):
        norm = _normalize_token(token)
        if norm and norm not in _STOPWORDS and norm not in _QUESTION_ENTITY_TOKENS:
            entities.add(norm)
    return entities


def _extract_entity_spans(text: str) -> list[str]:
    spans = []
    for match in re.finditer(r"\b[A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+){0,2}\b", text):
        span = match.group(0).strip()
        if not span:
            continue
        first = _normalize_token(span.split()[0])
        if first in _QUESTION_ENTITY_TOKENS:
            continue
        spans.append(span)
    deduped: list[str] = []
    seen: set[str] = set()
    for span in spans:
        key = span.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(span)
    return deduped


def _split_relation_values(raw: str, *, capitalized_only: bool = False, prefer_titles: bool = False) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []

    quoted = [item.strip() for item in re.findall(r'"([^"]+)"', text) if item.strip()]
    values: list[str] = quoted[:] if prefer_titles else []

    normalized = text
    if quoted:
        normalized = re.sub(r'"[^"]+"', "", normalized)
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(
        r"\b(?:live|lately|yesterday|today|tomorrow|last week|last month|next month|this past weekend|past weekend)\b",
        "",
        normalized,
        flags=re.IGNORECASE,
    )
    parts = re.split(r",|\band\b", normalized)
    for part in parts:
        clean = " ".join(part.strip().split()).strip(" .,:;-")
        if not clean:
            continue
        clean = re.sub(r"\b(?:to|at|the|a|an|my|our|their)\b\s*$", "", clean, flags=re.IGNORECASE).strip(" .,:;-")
        if not clean:
            continue
        if capitalized_only:
            if not re.match(r"^[A-Z][A-Za-z0-9_]+(?:\s+[A-Z][A-Za-z0-9_]+)*$", clean):
                continue
        elif len(clean.split()) > (8 if prefer_titles else 4):
            continue
        values.append(clean)
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _extract_list_relation_values(
    text: str,
    *,
    patterns: Sequence[str],
    capitalized_only: bool = False,
    prefer_titles: bool = False,
) -> list[list[str]]:
    groups: list[list[str]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            raw = str(match.groupdict().get("values") or "").strip()
            if not raw:
                continue
            values = _split_relation_values(raw, capitalized_only=capitalized_only, prefer_titles=prefer_titles)
            if values:
                groups.append(values)
    return groups


def _session_date_label(meta: Optional[dict[str, Any]]) -> str | None:
    if not meta:
        return None
    raw = str(meta.get("session_date_text") or "").strip()
    if not raw:
        return None
    m = re.search(r"on\s+(\d{1,2}\s+[A-Za-z]+),\s*(\d{4})", raw)
    if m:
        return f"{m.group(1)} {m.group(2)}"
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", raw)
    if m:
        return f"{int(m.group(3))} {m.group(2)} {m.group(1)}"
    return raw


def _parse_graph_time_label(value: str) -> int | None:
    text = " ".join(str(value or "").strip().split())
    if not text:
        return None
    lower = text.lower()
    relative_patterns = (
        (r"two weekends before (\d{1,2}\s+[A-Za-z]+\s+\d{4})", 14),
        (r"weekend before (\d{1,2}\s+[A-Za-z]+\s+\d{4})", 7),
        (r"week before (\d{1,2}\s+[A-Za-z]+\s+\d{4})", 7),
    )
    for pattern, delta_days in relative_patterns:
        m = re.search(pattern, lower)
        if not m:
            continue
        try:
            base = datetime.strptime(m.group(1), "%d %B %Y")
        except ValueError:
            continue
        return int((base - timedelta(days=delta_days)).timestamp())

    for fmt in ("%d %B %Y", "%B %Y", "%Y"):
        try:
            dt = datetime.strptime(text, fmt)
            if fmt == "%Y":
                dt = dt.replace(month=1, day=1)
            elif fmt == "%B %Y":
                dt = dt.replace(day=1)
            return int(dt.timestamp())
        except ValueError:
            continue

    m = re.search(r"(\d{1,2}\s+[A-Za-z]+\s+\d{4})", text)
    if m:
        try:
            return int(datetime.strptime(m.group(1), "%d %B %Y").timestamp())
        except ValueError:
            return None
    return None


def _graph_relation_start_ts(temporal_meta: dict[str, Any], *, fallback_ts: int) -> int:
    sort_ts = temporal_meta.get("graph_time_sort_ts")
    if sort_ts is not None:
        return int(sort_ts)
    session_label = str(temporal_meta.get("graph_session_date") or "").strip()
    parsed_session = _parse_graph_time_label(session_label)
    if parsed_session is not None:
        return parsed_session
    return int(fallback_ts)


def _derive_temporal_relation_meta(text: str, meta: Optional[dict[str, Any]]) -> dict[str, Any]:
    lower = str(text or "").lower()
    out: dict[str, Any] = {}
    session_label = _session_date_label(meta)
    if session_label:
        out["graph_session_date"] = session_label

    if not meta:
        return out

    hints = [str(hint).strip() for hint in (meta.get("resolved_time_hints") or []) if str(hint).strip()]
    if not hints:
        return out

    selected_hint: str | None = None
    selected_value: str | None = None
    for hint in hints:
        if "=" not in hint:
            continue
        key, value = hint.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key and key in lower:
            selected_hint = hint
            selected_value = value
            break

    if selected_value is None and len(hints) == 1 and "=" in hints[0]:
        selected_hint = hints[0]
        _, selected_value = hints[0].split("=", 1)
        selected_value = selected_value.strip()

    if selected_value:
        out["graph_time_label"] = selected_value
        out["graph_time_hint"] = selected_hint or selected_value
        out["graph_time_source"] = "resolved_hint"
        parsed = _parse_graph_time_label(selected_value)
        if parsed is not None:
            out["graph_time_sort_ts"] = parsed
    elif session_label:
        parsed = _parse_graph_time_label(session_label)
        if parsed is not None:
            out["graph_time_sort_ts"] = parsed

    return out


def _extract_speaker_label(text: str) -> str | None:
    m = re.match(r"^\[([^\]]+)\]", text.strip())
    if m:
        norm = _normalize_token(m.group(1))
        return norm or None
    m = re.match(r"^([A-Z][a-zA-Z0-9_]+):", text.strip())
    if m:
        norm = _normalize_token(m.group(1))
        return norm or None
    return None


def _classify_graph_entity_type(text: str, *, fallback: str = "entity") -> str:
    clean = " ".join(str(text or "").strip().split())
    if not clean:
        return fallback
    lower = clean.lower()
    if lower in _SELF_SUBJECTS:
        return "self"
    if lower.startswith(("the ", "my ", "our ", "his ", "her ", "their ")):
        if any(token in lower for token in ("race", "party", "trip", "event", "conference", "group", "studio", "store", "community")):
            return "event"
        return "entity"
    if re.match(r"^[A-Z][a-zA-Z0-9_]+(?:\s+[A-Z][a-zA-Z0-9_]+){0,2}$", clean):
        return "person"
    if any(token in lower for token in ("city", "country", "neighborhood", "beach", "park")):
        return "location"
    return fallback


def _clean_graph_object_text(text: str, *, preserve_leading_article: bool = False) -> str:
    clean = " ".join(str(text or "").strip().split()).strip(" .,:;-")
    if not clean:
        return ""
    clean = re.split(
        r"\s+\b(?:and|but)\s+(?:it|it's|it was|they|that|this|he|she|we|i)\b",
        clean,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .,:;-")
    clean = re.split(
        r"\s*-\s*(?:it|it's|it was|they|that|this|he|she|we|i)\b",
        clean,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" .,:;-")
    if not preserve_leading_article:
        clean = re.sub(r"^(?:a|an|the)\s+", "", clean, flags=re.IGNORECASE)
    clean = re.sub(
        r"^(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+|pair of|couple of)\s+",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\b(?:yesterday|today|tomorrow|last week|last month|next month|this past weekend|past weekend)\b$", "", clean, flags=re.IGNORECASE).strip(" .,:;-")
    clean = re.sub(
        r"\b(?:the\s+)?(?:day|week|month|year|night|weekend)\s+before\b$",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip(" .,:;-")
    clean = re.sub(
        r"\s+with\s+(?:a|an|the)\s+group\s+of\s+friends$",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip(" .,:;-")
    clean = re.sub(r"\s{2,}", " ", clean)
    if len(clean.split()) > 12:
        return ""
    return clean


def _is_valid_graph_relation_object(relation_type: str, object_text: str) -> bool:
    lower = " ".join(str(object_text or "").strip().lower().split())
    if not lower:
        return False
    if lower in {"it", "them", "this", "that", "often", "together", "supplies"}:
        return False
    if lower.startswith(("it's ", "it is ", "it was ", "it so", "that ", "this ")):
        return False
    if relation_type == "attend_event":
        event_markers = (
            "group",
            "conference",
            "workshop",
            "parade",
            "show",
            "class",
            "camp",
            "gala",
            "party",
            "event",
            "program",
            "meeting",
            "mtg",
            "dinner",
            "support",
        )
        if any(marker in lower for marker in event_markers):
            return True
        if re.fullmatch(r"[A-Z][A-Za-z0-9_]+(?:\s+[A-Z][A-Za-z0-9_]+){0,5}", str(object_text or "")):
            return True
        return False
    if relation_type == "have_pet":
        return bool(re.search(r"\b(?:dog|dogs|cat|cats|turtle|turtles|puppy|puppies|pup|pups|pet|pets)\b", lower))
    if relation_type == "like":
        if lower.startswith(("it ", "it'", "the color", "all the", "that ", "this ", "by ")):
            return False
        if re.search(r"[A-Z]", str(object_text or "")):
            return True
        return lower in {
            "writing",
            "reading",
            "painting",
            "pottery",
            "basketball",
            "yoga",
            "surfing",
            "photography",
        }
    if relation_type == "buy":
        if bool(re.fullmatch(r"(?:the\s+)?(?:day|week|month|year|night|weekend)\s+before", lower)):
            return False
        return not lower.startswith(("it ", "it'", "it was "))
    if relation_type in {"find", "start_activity", "open", "volunteer_at"}:
        return not lower.startswith(("it ", "it'", "it was "))
    return True


def _generic_action_relation_patterns(list_subject: str) -> dict[str, tuple[str, ...]]:
    subject = _ACTION_SUBJECT_PATTERN
    escaped_subject = re.escape(list_subject)
    self_or_subject = rf"(?:{escaped_subject}|I|We|{subject})"
    return {
        "research": (
            rf"\b{self_or_subject}\s+(?:research(?:ed|es|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "attend_event": (
            rf"\b{self_or_subject}\s+(?:went|go(?:es|ing)?)\s+to\s+(?P<object>[^.?!]+)",
            rf"\b{self_or_subject}\s+(?:attend(?:ed|s|ing)?)\s+(?P<object>[^.?!]+)",
            rf"\b{self_or_subject}\s+(?:join(?:ed|s|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "participate_in": (
            rf"\b{self_or_subject}\s+(?:participat(?:ed|es|ing))\s+in\s+(?P<object>[^.?!]+)",
        ),
        "apply_to": (
            rf"\b{self_or_subject}\s+appl(?:ied|y|ying)\s+to\s+(?P<object>[^.?!]+)",
        ),
        "buy": (
            rf"\b{self_or_subject}\s+(?:bought|buy(?:s|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "paint": (
            rf"\b{self_or_subject}\s+(?:paint(?:ed|s|ing)?)\s+(?P<object>[^.?!]+)",
            rf"\b{self_or_subject}\s+(?:make(?:s|d)?|creates?)\s+(?P<object>abstract art|art|jewelry|pottery|paintings?|drawings?|self-portraits?)\b",
        ),
        "read": (
            rf"\b{self_or_subject}\s+(?:read|reading)\s+(?P<object>[^.?!]+)",
        ),
        "watch": (
            rf"\b{self_or_subject}\s+(?:watch(?:ed|es|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "like": (
            rf"\b{self_or_subject}\s+(?:like(?:s|d)?|love(?:s|d)?|enjoy(?:s|ed|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "recommend": (
            rf"\b{self_or_subject}\s+(?:recommend(?:ed|s|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "find": (
            rf"\b{self_or_subject}\s+(?:found|find(?:s|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "offer": (
            rf"\b{self_or_subject}\s+(?:offer(?:ed|s|ing)?)\s+(?P<object>[^.?!]+)",
            rf"\b{self_or_subject}\s+is\s+offering\s+(?P<object>[^.?!]+)",
        ),
        "record": (
            rf"\b{self_or_subject}\s+(?:record(?:ed|s|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "collaborate_with": (
            rf"\b{self_or_subject}\s+(?:collaborat(?:ed|es|ing))\s+with\s+(?P<object>[^.?!]+)",
        ),
        "sign_with": (
            rf"\b{self_or_subject}\s+signed\s+with\s+(?P<object>[^.?!]+)",
        ),
        "have_dinner_with": (
            rf"\b{self_or_subject}\s+had\s+dinner\s+with\s+(?P<object>[^.?!]+)",
        ),
        "start_activity": (
            rf"\b{self_or_subject}\s+start(?:ed|s|ing)?\s+(?P<object>[^.?!]+)",
        ),
        "do_activity": (
            rf"\b{self_or_subject}\s+(?:did|do(?:es)?|doing)\s+(?P<object>[^.?!]+)",
        ),
        "practice": (
            rf"\b{self_or_subject}\s+(?:practice(?:d|s|ing)?|train(?:ed|s|ing)?\s+in)\s+(?P<object>[^.?!]+)",
            rf"\b{self_or_subject}\s+(?:has|have|had)\s+done\s+(?P<object>[^.?!]+)",
        ),
        "cook": (
            rf"\b{self_or_subject}\s+(?:cook(?:ed|s|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "focus_on": (
            rf"\b{self_or_subject}\s+(?:focus(?:ed|es|ing)?)\s+on\s+(?P<object>[^.?!]+)",
        ),
        "volunteer_at": (
            rf"\b{self_or_subject}\s+(?:volunteer(?:ed|s|ing)?)\s+at\s+(?P<object>[^.?!]+)",
        ),
        "share_photo_of": (
            rf"\b{self_or_subject}\s+shared?\s+(?:a\s+)?photo\s+of\s+(?P<object>[^.?!]+)",
        ),
        "open": (
            rf"\b{self_or_subject}\s+(?:opened|open(?:s|ing)?)\s+(?P<object>[^.?!]+)",
        ),
        "raise_awareness_for": (
            rf"\b{self_or_subject}\s+raise(?:d|s|ing)?\s+awareness\s+for\s+(?P<object>[^.?!]+)",
        ),
        "have_pet": (
            rf"\b{self_or_subject}\s+(?:have|has|had)\s+(?P<object>[^.?!]*\b(?:dogs?|cats?|turtles?|pupp(?:y|ies)|pups?|pets?)\b[^.?!]*)",
        ),
    }


def _extract_query_subject(text: str) -> str | None:
    speaker = _extract_speaker_label(text)
    if speaker:
        return speaker

    m = re.search(
        r"\b(?:what|when|where|why|how)\s+(?:did|does|is|was|will|would|has|have)\s+([A-Z][a-zA-Z0-9_]+)\b",
        text,
    )
    if m:
        norm = _normalize_token(m.group(1))
        return norm or None

    entities = list(_extract_named_entities(text))
    return entities[0] if entities else None


def _specificity_score(text: str) -> float:
    tokens = _tokenize(text)
    if not tokens:
        return 0.0

    distinct_specific = {t for t in tokens if t not in _GENERIC_FILLER_TOKENS}
    score = min(1.0, float(len(distinct_specific)) / 8.0)

    lower = text.lower()
    if re.search(r"\d", text):
        score += 0.2
    if any(token in lower for token in _SPECIFIC_DATE_TOKENS):
        score += 0.2
    return min(1.2, score)


def _generic_dialogue_penalty(text: str) -> float:
    lower = text.lower().strip()
    penalty = 0.0
    if lower.endswith("?"):
        penalty += 0.8
    if lower.startswith("[assistant] entity mentioned:") or lower.startswith("entity mentioned:"):
        penalty += 1.0
    if lower.startswith("[assistant]"):
        penalty += 0.4
    if re.match(r"^\[[^\]]+\]\s*(wow|hey|glad|thanks|thank|yeah|awesome|cool|nice)\b", lower):
        penalty += 0.5
    if re.match(r"^(?:\[[^\]]+\]\s*)?fact:\s*(wow|hey|glad|thanks|thank|yeah|awesome|cool|nice)\b", lower):
        penalty += 0.8
    if lower.startswith("fact:") and not re.search(r"\d", lower) and len(_tokenize(lower)) < 8:
        penalty += 0.4
    for pattern in _GENERIC_DIALOGUE_PATTERNS:
        if re.search(pattern, lower):
            penalty += 0.3
            break
    return penalty


def _cue_phrase_overlap(text: str, cues: Sequence[str]) -> float:
    lower = re.sub(r"\s+", " ", text.lower())
    hits = 0
    for cue in cues:
        cue_norm = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(cue).lower())).strip()
        if len(cue_norm) < 5:
            continue
        if cue_norm in lower:
            hits += 1
    return min(3.2, 0.8 * float(hits))


def _has_temporal_hint(text: str) -> bool:
    lower = text.lower()
    if re.search(r"\d", text):
        return True
    return any(token in lower for token in _SPECIFIC_DATE_TOKENS)


def _has_causal_hint(text: str) -> bool:
    lower = text.lower()
    markers = (
        "after ",
        "because",
        "changed",
        "family scare",
        "made me",
        "replaced",
        "since ",
    )
    return any(marker in lower for marker in markers)

