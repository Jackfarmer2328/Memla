from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PolicyGovernor:
    """Lightweight safety gate before actions alter persistent state."""

    blocked_substrings: tuple[str, ...] = (
        "ignore previous",
        "system prompt",
        "jailbreak",
        " reveal secrets",
    )

    def allows(self, text: str) -> bool:
        low = text.lower()
        return not any(s in low for s in self.blocked_substrings)
