from __future__ import annotations

from dataclasses import dataclass, field

from .memory_engine import MemoryEngine
from .policy_governor import PolicyGovernor


@dataclass
class NPCAgent:
    npc_id: str
    traits: dict[str, str]
    memory: MemoryEngine = field(default_factory=MemoryEngine)
    policy: PolicyGovernor = field(default_factory=PolicyGovernor)
    session_turns: int = 0

    def act(self, user_message: str) -> dict[str, str]:
        self.session_turns += 1
        if not self.policy.allows(user_message):
            return {"blocked": "true", "reply": "[policy blocked]", "reason": "adversarial_or_meta_pattern"}
        retrieved = self.memory.retrieve(user_message, top_k=3)
        ctx = " | ".join(r.text for r in retrieved) if retrieved else ""
        trait_bits = ", ".join(f"{k}={v}" for k, v in sorted(self.traits.items()))
        reply = (
            f"[npc={self.npc_id} traits={trait_bits}] "
            f"I recall: {ctx}. Regarding your message: acknowledged (session turn {self.session_turns})."
        )
        self.memory.working_push(f"user: {user_message[:200]}")
        self.memory.commit_to_episodic(
            f"turn {self.session_turns} user: {user_message[:280]}",
            tags=("dialogue", self.npc_id, f"t{self.session_turns}"),
        )
        return {"blocked": "false", "reply": reply, "memory_context": ctx}
