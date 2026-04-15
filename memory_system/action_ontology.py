from __future__ import annotations

from dataclasses import asdict, dataclass, field
import re
from typing import Any


@dataclass(frozen=True)
class ActionCapability:
    action_id: str
    title: str
    domain: str
    description: str
    risk_level: str
    confirmation_required: bool
    status: str
    input_slots: list[str] = field(default_factory=list)
    safe_transmutations: list[str] = field(default_factory=list)
    trigger_hints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionOntologyMatch:
    prompt: str
    action_id: str
    title: str
    domain: str
    confidence: float
    risk_level: str
    confirmation_required: bool
    status: str
    missing_slots: list[str] = field(default_factory=list)
    safe_next_step: str = ""
    residual_constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionDraftPayload:
    prompt: str
    ok: bool
    action_id: str
    title: str
    domain: str
    confidence: float
    risk_level: str
    confirmation_required: bool
    status: str
    safe_next_step: str
    recipients: list[str] = field(default_factory=list)
    channel: str = ""
    subject: str = ""
    body: str = ""
    draft_text: str = ""
    residual_constraints: list[str] = field(default_factory=list)


ACTION_CAPABILITIES: tuple[ActionCapability, ...] = (
    ActionCapability(
        action_id="browser_scout",
        title="Browser scout",
        domain="browser",
        description="Search, collect candidates, rank them, inspect the best few, and return a report.",
        risk_level="low",
        confirmation_required=False,
        status="implemented",
        input_slots=["goal"],
        safe_transmutations=["browser_extract_cards", "browser_rank_cards", "browser_read_page"],
        trigger_hints=["scout", "top repos", "best repo", "compare sources", "bring back"],
    ),
    ActionCapability(
        action_id="ask_contact",
        title="Ask contact",
        domain="messaging",
        description="Draft a question for a contact and wait for the user-approved send path.",
        risk_level="medium",
        confirmation_required=True,
        status="design_ready",
        input_slots=["contact", "question"],
        safe_transmutations=["contacts_lookup", "draft_message", "confirm_send"],
        trigger_hints=["ask mom", "ask dad", "ask my sister", "text", "imessage", "message"],
    ),
    ActionCapability(
        action_id="draft_message",
        title="Draft message",
        domain="messaging",
        description="Prepare a message without sending it until the user confirms.",
        risk_level="medium",
        confirmation_required=True,
        status="design_ready",
        input_slots=["recipient", "message"],
        safe_transmutations=["contacts_lookup", "draft_message", "confirm_send"],
        trigger_hints=["send text", "send message", "imessage", "tell my"],
    ),
    ActionCapability(
        action_id="send_email",
        title="Send email",
        domain="mail",
        description="Draft or send email through a confirmed mail workflow.",
        risk_level="medium",
        confirmation_required=True,
        status="design_ready",
        input_slots=["recipient", "subject", "body"],
        safe_transmutations=["contacts_lookup", "draft_email", "confirm_send"],
        trigger_hints=["email", "mail"],
    ),
    ActionCapability(
        action_id="book_ride_quote",
        title="Ride quote",
        domain="transport",
        description="Find a ride quote and ask for confirmation before booking.",
        risk_level="high",
        confirmation_required=True,
        status="planned",
        input_slots=["destination", "pickup_time", "pickup_location"],
        safe_transmutations=["ride_quote", "confirm_purchase"],
        trigger_hints=["uber", "lyft", "ride", "get me a ride", "pick me up"],
    ),
    ActionCapability(
        action_id="food_order_quote",
        title="Food order quote",
        domain="commerce",
        description="Build a food order quote and ask for confirmation before purchase.",
        risk_level="high",
        confirmation_required=True,
        status="planned",
        input_slots=["restaurant", "items", "delivery_address"],
        safe_transmutations=["food_search", "food_order_quote", "confirm_purchase"],
        trigger_hints=["doordash", "uber eats", "order food", "order me", "get food"],
    ),
    ActionCapability(
        action_id="track_reply",
        title="Track reply",
        domain="communication",
        description="Track a reply through a supported channel such as email or a Memla share link.",
        risk_level="medium",
        confirmation_required=True,
        status="workaround_required",
        input_slots=["channel", "thread"],
        safe_transmutations=["reply_poll", "summarize_reply"],
        trigger_hints=["what they say", "what did they say", "reply", "response"],
    ),
)


def _normalize_action_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    return " ".join(text.split())


def _display_text(value: str) -> str:
    text = " ".join(str(value or "").strip().split())
    replacements = {
        "doordash": "DoorDash",
        "uber": "Uber",
        "lyft": "Lyft",
        "imessage": "iMessage",
    }
    for raw, pretty in replacements.items():
        text = re.sub(rf"\b{re.escape(raw)}\b", pretty, text, flags=re.IGNORECASE)
    return text


def _capability_score(capability: ActionCapability, prompt: str) -> float:
    normalized = _normalize_action_text(prompt)
    if not normalized:
        return 0.0
    score = 0.0
    for hint in capability.trigger_hints:
        clean_hint = _normalize_action_text(hint)
        if clean_hint and clean_hint in normalized:
            score += 0.45
    domain_tokens = set(_normalize_action_text(capability.domain).split())
    title_tokens = set(_normalize_action_text(capability.title).split())
    prompt_tokens = set(normalized.split())
    if domain_tokens & prompt_tokens:
        score += 0.15
    if title_tokens & prompt_tokens:
        score += 0.2
    if capability.action_id == "browser_scout" and {"github", "repo"} & prompt_tokens and {"best", "top", "find"} & prompt_tokens:
        score += 0.55
    if capability.action_id == "food_order_quote" and {"pizza", "burger", "sushi", "taco", "tacos", "wings"} & prompt_tokens and {"get", "order", "want", "buy", "grab"} & prompt_tokens:
        score += 0.45
    if capability.action_id == "track_reply" and {"say", "said", "reply", "response"} & prompt_tokens:
        score += 0.25
    return round(min(score, 1.0), 4)


def _missing_slots(capability: ActionCapability, prompt: str) -> list[str]:
    normalized = _normalize_action_text(prompt)
    missing: list[str] = []
    if capability.action_id in {"ask_contact", "draft_message"}:
        if not any(token in normalized for token in {"mom", "dad", "sister", "brother", "friend", "wife", "husband"}):
            missing.append("recipient")
        if not any(token in normalized for token in {"ask", "tell", "say", "what", "send"}):
            missing.append("message")
    if capability.action_id == "book_ride_quote":
        if not any(token in normalized for token in {"to", "airport", "home", "work", "downtown"}):
            missing.append("destination")
        if not any(token in normalized for token in {"now", "minute", "minutes", "tomorrow", "today"}):
            missing.append("pickup_time")
    if capability.action_id == "food_order_quote":
        if not any(token in normalized for token in {"from", "restaurant", "doordash", "uber eats"}):
            missing.append("restaurant")
        if not any(token in normalized for token in {"pizza", "burger", "sushi", "taco", "food", "order"}):
            missing.append("items")
    return missing


def _extract_recipients(prompt: str) -> list[str]:
    normalized = _normalize_action_text(prompt)
    contacts = [
        ("mom", "Mom"),
        ("dad", "Dad"),
        ("sister", "Sister"),
        ("brother", "Brother"),
        ("friend", "Friend"),
        ("wife", "Wife"),
        ("husband", "Husband"),
    ]
    recipients: list[str] = []
    for token, label in contacts:
        if re.search(rf"\b(?:my\s+)?{re.escape(token)}\b", normalized) and label not in recipients:
            recipients.append(label)
    return recipients


def _strip_recipient_prefix(text: str, recipients: list[str]) -> str:
    clean = str(text or "").strip()
    if not clean:
        return ""
    for recipient in recipients:
        label = recipient.lower()
        clean = re.sub(rf"^(?:my\s+)?{re.escape(label)}\b\s*(?:and\s+)?", "", clean, flags=re.IGNORECASE).strip()
    clean = re.sub(r"^(?:to|that|saying|asking)\s+", "", clean, flags=re.IGNORECASE).strip()
    return clean


def _extract_message_body(prompt: str, recipients: list[str]) -> str:
    raw = str(prompt or "").strip()
    if not raw:
        return ""
    patterns = (
        r"\bask\b\s+(.+)$",
        r"\btell\b\s+(.+)$",
        r"\bemail\b\s+(.+)$",
        r"\bmessage\b\s+(.+)$",
        r"\bimessage\b\s+(.+)$",
        r"\btext\b\s+(.+)$",
    )
    body = ""
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            body = str(match.group(1) or "").strip()
            break
    if not body:
        return ""
    body = _strip_recipient_prefix(body, recipients)
    body = re.sub(r"^and\s+ask\s+", "", body, flags=re.IGNORECASE).strip()
    body = re.sub(r"^and\s+tell\s+", "", body, flags=re.IGNORECASE).strip()
    body = re.sub(r"^ask\s+", "", body, flags=re.IGNORECASE).strip()
    body = _strip_recipient_prefix(body, recipients)
    body = re.sub(r"\bwhat\s+(?:she|he|they)\s+wants\b", "what do you want", body, flags=re.IGNORECASE)
    body = re.sub(r"\bwhat\s+(?:she|he|they)\s+want\b", "what do you want", body, flags=re.IGNORECASE)
    body = _display_text(body)
    if not body:
        return ""
    if body.lower().startswith(("what ", "when ", "where ", "who ", "why ", "how ", "can ", "could ", "would ", "do ", "did ", "are ", "is ")):
        body = body[0].upper() + body[1:]
        if not body.endswith("?"):
            body += "?"
        return body
    return body[0].upper() + body[1:]


def _extract_email_subject(prompt: str, body: str) -> str:
    raw = str(prompt or "")
    match = re.search(r"\bsubject\s+(?:is\s+)?(.+?)(?:\s+body\s+|\s+saying\s+|$)", raw, flags=re.IGNORECASE)
    if match:
        return _display_text(str(match.group(1) or "").strip())
    if body:
        words = body.rstrip(".?").split()
        return " ".join(words[:6]) if words else "Memla follow-up"
    return "Memla follow-up"


def classify_action_prompt(prompt: str) -> ActionOntologyMatch:
    scored = sorted(
        ((capability, _capability_score(capability, prompt)) for capability in ACTION_CAPABILITIES),
        key=lambda item: (-item[1], item[0].action_id),
    )
    capability, confidence = scored[0]
    if confidence <= 0.0:
        capability = ACTION_CAPABILITIES[0]
        confidence = 0.0
    missing = _missing_slots(capability, prompt)
    residuals: list[str] = []
    if capability.status in {"planned", "workaround_required"}:
        residuals.append(f"action_status:{capability.status}")
    if missing:
        residuals.append("missing_slots:" + ",".join(missing))
    safe_next_step = "execute" if capability.status == "implemented" and not capability.confirmation_required else "draft_then_confirm"
    if capability.status in {"planned", "workaround_required"}:
        safe_next_step = "design_or_bridge_required"
    return ActionOntologyMatch(
        prompt=prompt,
        action_id=capability.action_id,
        title=capability.title,
        domain=capability.domain,
        confidence=round(confidence, 4),
        risk_level=capability.risk_level,
        confirmation_required=capability.confirmation_required,
        status=capability.status,
        missing_slots=missing,
        safe_next_step=safe_next_step,
        residual_constraints=residuals,
    )


def create_action_draft(prompt: str) -> ActionDraftPayload:
    match = classify_action_prompt(prompt)
    residuals = list(match.residual_constraints)
    recipients = _extract_recipients(prompt)
    channel = ""
    subject = ""
    body = ""
    draft_text = ""
    ok = False

    if match.action_id in {"ask_contact", "draft_message"}:
        channel = "iMessage" if "imessage" in _normalize_action_text(prompt) else "message"
        body = _extract_message_body(prompt, recipients)
        if not recipients and "missing_slots:recipient" not in residuals:
            residuals.append("missing_slots:recipient")
        if not body and not any(item.startswith("missing_slots:") and "message" in item for item in residuals):
            residuals.append("missing_slots:message")
        ok = bool(recipients and body)
        recipient_text = ", ".join(recipients) if recipients else "recipient"
        draft_text = f"To {recipient_text}: {body}" if body else ""
    elif match.action_id == "send_email":
        channel = "email"
        recipients = recipients or []
        body = _extract_message_body(prompt, recipients)
        subject = _extract_email_subject(prompt, body)
        if not recipients and "missing_slots:recipient" not in residuals:
            residuals.append("missing_slots:recipient")
        if not body and not any(item.startswith("missing_slots:") and "body" in item for item in residuals):
            residuals.append("missing_slots:body")
        ok = bool(recipients and body)
        recipient_text = ", ".join(recipients) if recipients else "recipient"
        draft_text = f"Email to {recipient_text}\nSubject: {subject}\n\n{body}".strip() if body else ""
    elif match.action_id in {"book_ride_quote", "food_order_quote"}:
        channel = "service_bridge"
        draft_text = "Memla recognizes this request, but this action still needs a service bridge before it can prepare a real quote."
        residuals = list(dict.fromkeys(residuals + ["service_bridge_required", "confirmation_required"]))
    elif match.action_id == "track_reply":
        channel = "reply_bridge"
        draft_text = "Memla recognizes reply tracking, but iMessage replies need a supported bridge or workaround before Memla can read them."
        residuals = list(dict.fromkeys(residuals + ["reply_bridge_required", "confirmation_required"]))
    else:
        draft_text = "This action is already implemented as an executable Memla path."
        ok = match.status == "implemented"

    if match.confirmation_required and "confirmation_required" not in residuals:
        residuals.append("confirmation_required")

    return ActionDraftPayload(
        prompt=prompt,
        ok=ok,
        action_id=match.action_id,
        title=match.title,
        domain=match.domain,
        confidence=match.confidence,
        risk_level=match.risk_level,
        confirmation_required=match.confirmation_required,
        status=match.status,
        safe_next_step=match.safe_next_step,
        recipients=recipients,
        channel=channel,
        subject=subject,
        body=body,
        draft_text=draft_text,
        residual_constraints=list(dict.fromkeys(residuals)),
    )


def summarize_action_ontology() -> dict[str, Any]:
    domains = sorted({capability.domain for capability in ACTION_CAPABILITIES})
    statuses: dict[str, int] = {}
    risk_levels: dict[str, int] = {}
    for capability in ACTION_CAPABILITIES:
        statuses[capability.status] = statuses.get(capability.status, 0) + 1
        risk_levels[capability.risk_level] = risk_levels.get(capability.risk_level, 0) + 1
    return {
        "action_count": len(ACTION_CAPABILITIES),
        "domains": domains,
        "status_counts": statuses,
        "risk_counts": risk_levels,
        "confirmation_required_count": sum(1 for capability in ACTION_CAPABILITIES if capability.confirmation_required),
        "implemented_count": sum(1 for capability in ACTION_CAPABILITIES if capability.status == "implemented"),
        "capabilities": [asdict(capability) for capability in ACTION_CAPABILITIES],
    }


def action_match_to_dict(match: ActionOntologyMatch) -> dict[str, Any]:
    return asdict(match)


def action_draft_to_dict(draft: ActionDraftPayload) -> dict[str, Any]:
    return asdict(draft)
