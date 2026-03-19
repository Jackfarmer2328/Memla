"""
Quality signal for deferred LoRA training.

Instead of self-reinforcing the reranker's own scores, we measure
how much each retrieved chunk actually contributed to the LLM's response.

Two signals:
1. Chunk usage: did the LLM reference this chunk's content in its answer?
   - True positive: chunk was used → train the retriever to keep ranking it
   - False positive: chunk was injected but ignored → train it down
2. Correction detection: did the user's *next* message correct the response?
   - If yes: the chunks that drove the wrong answer get negative signal
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

from ..memory.episode_log import Chunk


_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from",
    "has", "have", "he", "her", "his", "i", "in", "is", "it", "its", "me",
    "my", "not", "of", "on", "or", "our", "she", "that", "the", "their",
    "them", "they", "this", "to", "was", "we", "were", "with", "you", "your",
})


def _tokenize(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return {t for t in tokens if len(t) >= 2 and t not in _STOPWORDS}


@dataclass(frozen=True)
class ChunkQuality:
    chunk: Chunk
    usage_score: float  # 0.0 = LLM ignored it, 1.0 = fully referenced
    is_positive: bool


def score_chunk_usage(
    *,
    retrieved_chunks: Sequence[Chunk],
    assistant_response: str,
    positive_threshold: float = 0.25,
) -> list[ChunkQuality]:
    """
    Measure how much of each chunk's content appeared in the LLM's response.

    A chunk the LLM actually referenced is a true positive for retrieval.
    A chunk injected but completely ignored is a false positive.
    """
    response_tokens = _tokenize(assistant_response)
    if not response_tokens:
        return [
            ChunkQuality(chunk=c, usage_score=0.0, is_positive=False)
            for c in retrieved_chunks
        ]

    results: list[ChunkQuality] = []
    for chunk in retrieved_chunks:
        chunk_tokens = _tokenize(chunk.text) | _tokenize(chunk.key)
        if not chunk_tokens:
            results.append(ChunkQuality(chunk=chunk, usage_score=0.0, is_positive=False))
            continue

        overlap = len(chunk_tokens & response_tokens)
        usage = overlap / len(chunk_tokens)
        results.append(ChunkQuality(
            chunk=chunk,
            usage_score=min(1.0, usage),
            is_positive=usage >= positive_threshold,
        ))

    return results


# Strong corrections: high confidence when matched at the start of the message.
_STRONG_PATTERNS = [
    r"^\s*no[,.\s]",
    r"^\s*wrong",
    r"^\s*incorrect",
    r"^\s*that'?s?\s+(?:not\s+(?:right|correct|what)|wrong|incorrect)",
    r"^\s*i\s+(?:said|meant|asked|told\s+you)",
    r"^\s*i\s+(?:didn'?t|did\s+not)\s+(?:mean|ask|say|want)",
    r"^\s*you\s+(?:got|have)\s+(?:it|that)\s+wrong",
    r"^\s*not\s+(?:what|that)",
    r"^\s*you'?re\s+wrong",
    r"^\s*no,?\s+i\s+told\s+you",
]

# Weaker corrections: can appear anywhere in the message.
_WEAK_PATTERNS = [
    r"\byou\s+said\b.+\bbut\b",
    r"\bthat'?s?\s+not\s+(?:right|correct|what\s+i)\b",
    r"\byou\s+misunderstood\b",
    r"\bthat\s+(?:was|is)n'?t?\s+(?:right|correct|what)\b",
    r"\bi\s+(?:never|already)\s+(?:said|told|mentioned)\b",
    r"\bnot\s+what\s+i\s+(?:said|meant|asked)\b",
    r"\bi\s+told\s+you\b",
    r"\bwell\s+actually\b",
    r"\bbut\s+i\s+(?:said|meant|asked)\b",
    # "Actually" now only counts as a weak correction when followed
    # closely by a clearly negative word.
    r"\bactually\b.{0,24}\b(wrong|incorrect|off|bad|no|not|missed|issue|problem)\b",
]


# Rhetorical / sarcasm exemptions (C2 frame detection).
# Beginning anchor + end anchor together reveal structural intent.
# "No way" + "!" = excitement, NOT a correction.
_RHETORICAL_PATTERNS = [
    r"^\s*no\s+way\b.*[!]",
    r"^\s*no\s+kidding\b",
    r"^\s*no\s+shit\b",
    r"^\s*no\s+doubt\b",
    r"^\s*no\b.*(?:awesome|amazing|perfect|great|incredible|wow|cool|nice|love|beautiful)[!?]*\s*$",
    r"^\s*(?:wait|oh)\s+no\b.*[!]",
    r"^\s*(?:hell|heck)\s+no\b.*[!]",
    r"^\s*actually[,\s].*(?:awesome|amazing|perfect|great|works?|love|nice|good)[!?]*\s*$",
    r"^\s*wrong\b.*(?:lol|haha|lmao|rofl)[!?]*\s*$",
]


def _is_rhetorical(text: str) -> bool:
    """Detect rhetorical/sarcastic excitement that looks like correction but isn't."""
    lowered = text.lower().strip()
    for pat in _RHETORICAL_PATTERNS:
        if re.search(pat, lowered):
            return True
    # Frame heuristic: starts with "no" but ends with exclamation/excitement
    if re.match(r"^\s*no\b", lowered) and lowered.rstrip().endswith("!"):
        words = lowered.split()
        if len(words) >= 3 and not any(w in words for w in ("wrong", "incorrect", "bad", "error")):
            return True
    return False


def detect_correction(user_text: str) -> float:
    """
    Returns a correction confidence: 0.0 = normal continuation, ~0.8 = likely correction.

    Uses frame detection (C2): reads the beginning anchor AND end punctuation/words
    together. "No way" + "worked!" = rhetorical excitement, no signal.
    "No," + "wrong." = genuine correction, fires signal.
    """
    text = user_text.strip()
    if not text:
        return 0.0

    if _is_rhetorical(text):
        return 0.0

    lowered = text.lower()

    for pattern in _STRONG_PATTERNS:
        if re.search(pattern, lowered):
            return 0.8

    for pattern in _WEAK_PATTERNS:
        if re.search(pattern, lowered):
            return 0.6

    words = lowered.split()
    if len(words) <= 5 and words and words[0] == "no":
        return 0.6

    return 0.0
