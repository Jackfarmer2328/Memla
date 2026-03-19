"""
Reasoning trajectory framework (Constraint 6).

Defines the structured reasoning format that the LLM outputs, and
the parser that extracts trajectory steps for visualization and CPO training.
Each step is a typed node: Thought, Action, Observation, or Output.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


# ── Trajectory data structures ───────────────────────────────────

STEP_TYPES = ("thought", "action", "observation", "output")


@dataclass
class TrajectoryStep:
    step_type: str        # thought | action | observation | output
    content: str
    tool_name: str = ""   # only for action steps
    index: int = 0        # position in the trajectory


@dataclass
class Trajectory:
    id: Optional[int] = None
    session_id: str = ""
    user_id: str = ""
    user_query: str = ""
    steps: list[TrajectoryStep] = field(default_factory=list)
    ts: int = 0
    is_corrected: bool = False
    corrected_steps: list[TrajectoryStep] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user_query": self.user_query,
            "steps": [asdict(s) for s in self.steps],
            "ts": self.ts,
            "is_corrected": self.is_corrected,
            "corrected_steps": [asdict(s) for s in self.corrected_steps],
        }


# ── Structured reasoning system prompt injection ─────────────────

REASONING_PROMPT = """
When answering, structure your reasoning using this framework:

[Thought] Your internal reasoning about what the user needs
[Action] Any tool calls or memory retrievals (e.g., memory_retrieve, memory_expand)
[Observation] What you learned from the action
[Output] Your final response to the user

You may have multiple Thought/Action/Observation cycles before the Output.
Always wrap each step in the appropriate tag. The user can see and correct your reasoning.
"""


def inject_reasoning_prompt(base_system: str) -> str:
    return base_system.rstrip() + "\n" + REASONING_PROMPT


# ── Parser: extract structured steps from LLM output ─────────────

_STEP_PATTERN = re.compile(
    r"\[(?P<type>Thought|Action|Observation|Output)\]\s*(?P<content>.*?)(?=\[(?:Thought|Action|Observation|Output)\]|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_TOOL_PATTERN = re.compile(
    r"(?:tool:\s*|calling\s+)(\w+)",
    re.IGNORECASE,
)


def parse_trajectory(text: str) -> list[TrajectoryStep]:
    """Parse structured LLM output into trajectory steps."""
    steps: list[TrajectoryStep] = []
    for i, m in enumerate(_STEP_PATTERN.finditer(text)):
        step_type = m.group("type").lower()
        content = m.group("content").strip()
        tool_name = ""
        if step_type == "action":
            tm = _TOOL_PATTERN.search(content)
            if tm:
                tool_name = tm.group(1)
        steps.append(TrajectoryStep(
            step_type=step_type,
            content=content,
            tool_name=tool_name,
            index=i,
        ))
    return steps


def has_trajectory_format(text: str) -> bool:
    """Check if the text contains structured reasoning tags."""
    return bool(_STEP_PATTERN.search(text))


def extract_output_text(text: str) -> str:
    """Extract just the [Output] content for display, falling back to full text."""
    for m in _STEP_PATTERN.finditer(text):
        if m.group("type").lower() == "output":
            return m.group("content").strip()
    return text


# ── Structural token masking for CPO training ────────────────────

def get_structural_mask(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character ranges of structural reasoning tokens.

    Only these ranges should receive gradient during CPO training.
    The [Output] section is masked OUT — we only train on how to think,
    not what to say.
    """
    ranges: list[tuple[int, int]] = []
    for m in _STEP_PATTERN.finditer(text):
        if m.group("type").lower() != "output":
            ranges.append((m.start(), m.end()))
    return ranges


# ── SQLite persistence for trajectories ──────────────────────────

_TRAJECTORY_DDL = """
CREATE TABLE IF NOT EXISTS trajectories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    user_query TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    is_corrected INTEGER NOT NULL DEFAULT 0,
    corrected_steps_json TEXT NOT NULL DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_traj_user_ts ON trajectories(user_id, ts DESC);
"""


class TrajectoryLog:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(_TRAJECTORY_DDL)
        self._conn.commit()

    def save(self, traj: Trajectory) -> int:
        cur = self._conn.execute(
            """INSERT INTO trajectories
               (ts, session_id, user_id, user_query, steps_json, is_corrected, corrected_steps_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                traj.ts or int(time.time()),
                traj.session_id,
                traj.user_id,
                traj.user_query,
                json.dumps([asdict(s) for s in traj.steps]),
                int(traj.is_corrected),
                json.dumps([asdict(s) for s in traj.corrected_steps]),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def save_correction(self, trajectory_id: int, corrected_steps: list[TrajectoryStep]) -> None:
        self._conn.execute(
            "UPDATE trajectories SET is_corrected = 1, corrected_steps_json = ? WHERE id = ?",
            (json.dumps([asdict(s) for s in corrected_steps]), trajectory_id),
        )
        self._conn.commit()

    def fetch_uncorrected_pairs(self, user_id: str, limit: int = 100) -> list[Trajectory]:
        """Fetch trajectories that have been corrected — these are CPO training pairs."""
        rows = self._conn.execute(
            "SELECT * FROM trajectories WHERE user_id = ? AND is_corrected = 1 ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_traj(r) for r in rows]

    def fetch_recent(self, user_id: str, limit: int = 20) -> list[Trajectory]:
        rows = self._conn.execute(
            "SELECT * FROM trajectories WHERE user_id = ? ORDER BY ts DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [self._row_to_traj(r) for r in rows]

    def _row_to_traj(self, row: sqlite3.Row) -> Trajectory:
        steps_raw = json.loads(row["steps_json"])
        corrected_raw = json.loads(row["corrected_steps_json"])
        return Trajectory(
            id=int(row["id"]),
            ts=int(row["ts"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            user_query=str(row["user_query"]),
            steps=[TrajectoryStep(**s) for s in steps_raw],
            is_corrected=bool(row["is_corrected"]),
            corrected_steps=[TrajectoryStep(**s) for s in corrected_raw],
        )
