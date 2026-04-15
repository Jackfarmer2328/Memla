from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import re
from typing import Any
from urllib.parse import quote

from .action_ontology import ActionDraftPayload, classify_action_prompt, create_action_draft


@dataclass(frozen=True)
class ActionBridgeOption:
    option_id: str
    label: str
    kind: str
    url: str
    instructions: str = ""


@dataclass(frozen=True)
class OrderSpecField:
    values: list[str] = field(default_factory=list)
    confidence: float = 0.0
    criticality: str = "optional"
    source: str = ""
    needs_clarification: bool = False


@dataclass(frozen=True)
class OrderSpec:
    kind: str = ""
    service: OrderSpecField = field(default_factory=OrderSpecField)
    restaurant: OrderSpecField = field(default_factory=OrderSpecField)
    item: OrderSpecField = field(default_factory=OrderSpecField)
    size: OrderSpecField = field(default_factory=OrderSpecField)
    toppings: OrderSpecField = field(default_factory=OrderSpecField)
    add_ons: OrderSpecField = field(default_factory=OrderSpecField)
    tip: OrderSpecField = field(default_factory=OrderSpecField)
    clarification_blockers: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ActionCapsule:
    prompt: str
    capsule_id: str
    action_id: str
    title: str
    domain: str
    risk_level: str
    authorization_level: str
    confirmation_required: bool
    auto_submit_allowed: bool
    status: str
    summary: str
    slots: dict[str, str] = field(default_factory=dict)
    draft_text: str = ""
    bridge_kind: str = ""
    bridge_url: str = ""
    bridge_label: str = ""
    bridge_options: list[ActionBridgeOption] = field(default_factory=list)
    bridge_instructions: str = ""
    verifier_requirements: list[str] = field(default_factory=list)
    auto_submit_blockers: list[str] = field(default_factory=list)
    residual_constraints: list[str] = field(default_factory=list)
    order_spec: OrderSpec | None = None


_UBER_DEFAULT_PICKUP_PROFILE: dict[str, Any] = {
    "addressLine1": "18720 Clear View Ct",
    "addressLine2": "Minnetonka, MN",
    "id": "dbd7d11b-a92a-7fbe-84f7-eb24356a3583",
    "source": "SEARCH",
    "latitude": 44.893797,
    "longitude": -93.517025,
    "provider": "uber_places",
}

_UBER_KNOWN_DESTINATIONS: dict[str, dict[str, Any]] = {
    "us bank stadium": {
        "addressLine1": "U.S. Bank Stadium",
        "addressLine2": "401 Chicago Ave, Minneapolis, MN",
        "id": "99b775c2-b2b3-337c-a970-4a6c6fc4b91c",
        "source": "SEARCH",
        "latitude": 44.9731726,
        "longitude": -93.2605274,
        "provider": "uber_places",
    },
}


def _capsule_id(action_id: str, prompt: str) -> str:
    digest = hashlib.sha1(f"{action_id}:{prompt}".encode("utf-8")).hexdigest()[:12]
    return f"{action_id}:{digest}"


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_text(value: str) -> str:
    text = _clean_text(value).lower()
    text = re.sub(r"[^a-z0-9+$.\s-]+", " ", text)
    return " ".join(text.split())


def _title_text(value: str) -> str:
    text = _clean_text(value)
    replacements = {
        "doordash": "DoorDash",
        "uber eats": "Uber Eats",
        "uber": "Uber",
        "lyft": "Lyft",
    }
    for raw, pretty in replacements.items():
        text = re.sub(rf"\b{re.escape(raw)}\b", pretty, text, flags=re.IGNORECASE)
    return text


def _extract_between(prompt: str, start_pattern: str, stop_pattern: str) -> str:
    match = re.search(start_pattern + r"\s+(.+?)(?:" + stop_pattern + r"|$)", prompt, flags=re.IGNORECASE)
    if not match:
        return ""
    return _title_text(str(match.group(1) or "").strip(" .,"))


_FOOD_SIZE_PATTERNS: list[tuple[str, str]] = [
    (r"\bextra[\s-]?large\b", "Extra Large"),
    (r"\bx[\s-]?large\b", "Extra Large"),
    (r"\bxl\b", "Extra Large"),
    (r"\blarge\b", "Large"),
    (r"\bmedium\b", "Medium"),
    (r"\bsmall\b", "Small"),
    (r"\bpersonal(?:\s+size)?\b", "Personal"),
    (r"\bfamily(?:\s+size)?\b", "Family Size"),
]


def _strip_food_leading_words(value: str) -> str:
    return re.sub(r"^(?:me|the|a|an|some)\s+", "", _clean_text(value), flags=re.IGNORECASE).strip(" .,")


def _extract_food_size(value: str) -> str:
    for pattern, label in _FOOD_SIZE_PATTERNS:
        if re.search(pattern, value, flags=re.IGNORECASE):
            return label
    return ""


def _remove_food_size(value: str) -> str:
    text = _clean_text(value)
    for pattern, _label in _FOOD_SIZE_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(pattern, " ", text, count=1, flags=re.IGNORECASE)
            break
    return " ".join(text.split()).strip(" .,")


def _clean_food_phrase(value: str) -> str:
    text = _clean_text(value)
    text = re.sub(r"\b(?:that's it|that is it|thats it|please)\b", "", text, flags=re.IGNORECASE)
    return text.strip(" .,")


def _split_food_list(value: str) -> list[str]:
    text = _clean_food_phrase(value)
    if not text:
        return []
    text = re.sub(r"\s*&\s*", " and ", text)
    text = re.sub(r"\s*\+\s*", ", ", text)
    raw_parts = re.split(r"\s*(?:,|/|\band\b)\s*", text, flags=re.IGNORECASE)
    parts: list[str] = []
    for part in raw_parts:
        clean_part = _strip_food_leading_words(part)
        if clean_part:
            parts.append(_title_text(clean_part))
    return parts


def _food_list_display(value: str) -> str:
    parts = _split_food_list(value)
    if not parts:
        return _title_text(_clean_food_phrase(value))
    return ", ".join(parts)


def _extract_food_slots(prompt: str) -> dict[str, str]:
    raw = _clean_text(prompt)
    normalized = _normalize_text(raw)
    slots: dict[str, str] = {}
    if "doordash" in normalized:
        slots["service"] = "DoorDash"
    elif "uber eats" in normalized:
        slots["service"] = "Uber Eats"
    else:
        slots["service"] = "food delivery"

    food_stop_pattern = r",|\b(?:from|with|make(?:\s+it|\s+the)?|have|add|and\s+add|give|tip|for delivery|to|top(?:\s+it)?(?:\s+with)?|toppings?)\b"
    restaurant = _extract_between(raw, r"\bfrom\b", r",|\b(?:with|make(?:\s+it|\s+the)?|have|add|and\s+add|give|tip|for delivery|to|top(?:\s+it)?(?:\s+with)?|toppings?)\b")
    if restaurant and restaurant.lower() not in {"doordash", "uber eats"}:
        slots["restaurant"] = restaurant

    item = _extract_between(raw, r"\b(?:get|order|want|buy|grab)\b", food_stop_pattern)
    if not item:
        item = _extract_between(raw, r"\b(?:doordash|uber eats)\b", food_stop_pattern)
    if item:
        item = _strip_food_leading_words(item)
    if not item:
        known_items = ["pizza", "burger", "sushi", "taco", "tacos", "burrito", "wings", "salad", "food"]
        for known_item in known_items:
            if re.search(rf"\b{re.escape(known_item)}\b", normalized):
                item = known_item
                break
    size = _extract_food_size(item or raw)
    if size:
        slots["size"] = size
        item = _remove_food_size(item or "")
    if item:
        slots["item"] = _title_text(item)

    modifiers = _extract_between(raw, r"\b(?:with|make it(?: have)?|have)\b", r",|\b(?:and\s+add|give|tip|that's it|that is it|thats it|for delivery|to)\b")
    if modifiers:
        slots["modifiers"] = _food_list_display(modifiers)

    toppings = _extract_between(raw, r"\b(?:make(?:\s+the)?\s+toppings?|toppings?|top(?:\s+it)?(?:\s+with)?)\b", r",|\b(?:and\s+add|give|tip|that's it|that is it|thats it|for delivery|to)\b")
    if not toppings and item and re.search(r"\bpizza\b", item, flags=re.IGNORECASE) and modifiers:
        toppings = modifiers
    if toppings:
        toppings_display = _food_list_display(toppings)
        slots["toppings"] = toppings_display
        slots["modifiers"] = toppings_display

    add_ons = _extract_between(raw, r"\badd\b", r"\b(?:give|tip|that's it|that is it|thats it|for delivery|to)\b")
    if add_ons:
        slots["add_ons"] = _food_list_display(add_ons)

    tip_match = re.search(r"(?:\$([0-9]+(?:\.[0-9]{1,2})?)\s*(?:tip)?|tip(?:\s+the\s+dasher)?\s+\$?([0-9]+(?:\.[0-9]{1,2})?))", raw, flags=re.IGNORECASE)
    if tip_match:
        amount = tip_match.group(1) or tip_match.group(2)
        slots["tip"] = f"${amount}"

    return slots


def _order_spec_field(
    values: list[str] | None,
    *,
    confidence: float,
    criticality: str,
    source: str,
    needs_clarification: bool = False,
) -> OrderSpecField:
    clean_values = [_clean_text(value) for value in (values or []) if _clean_text(value)]
    return OrderSpecField(
        values=clean_values,
        confidence=round(max(0.0, min(1.0, confidence)), 2),
        criticality=criticality,
        source=source,
        needs_clarification=needs_clarification,
    )


def _compile_food_order_spec(prompt: str, slots: dict[str, str]) -> OrderSpec:
    normalized = _normalize_text(prompt)
    service = slots.get("service", "")
    restaurant = slots.get("restaurant", "")
    item = slots.get("item", "")
    size = slots.get("size", "")
    toppings = _split_food_list(slots.get("toppings", ""))
    add_ons = _split_food_list(slots.get("add_ons", ""))
    tip = slots.get("tip", "")

    explicit_service = "doordash" in normalized or "uber eats" in normalized
    explicit_order_phrase = bool(re.search(r"\b(?:get|order|want|buy|grab)\b", prompt, flags=re.IGNORECASE))
    explicit_toppings = bool(re.search(r"\b(?:make(?:\s+the)?\s+toppings?|toppings?|top(?:\s+it)?(?:\s+with)?)\b", prompt, flags=re.IGNORECASE))
    explicit_add_ons = bool(re.search(r"\b(?:and\s+)?add\b", prompt, flags=re.IGNORECASE))
    explicit_tip = bool(re.search(r"\btip\b|\$\d+(?:\.\d{1,2})?", prompt, flags=re.IGNORECASE))

    service_field = _order_spec_field(
        [service] if service else [],
        confidence=0.99 if explicit_service and service else (0.75 if service else 0.0),
        criticality="required",
        source="explicit_service" if explicit_service else "default_service_inference",
        needs_clarification=not service,
    )
    restaurant_field = _order_spec_field(
        [restaurant] if restaurant else [],
        confidence=0.99 if restaurant else 0.0,
        criticality="required",
        source="from_clause" if restaurant else "missing",
        needs_clarification=not restaurant,
    )
    item_field = _order_spec_field(
        [item] if item else [],
        confidence=0.99 if item and explicit_order_phrase else (0.72 if item else 0.0),
        criticality="required",
        source="explicit_order_phrase" if item and explicit_order_phrase else ("fallback_item_inference" if item else "missing"),
        needs_clarification=not item,
    )
    size_explicit = bool(size and _extract_food_size(prompt))
    size_field = _order_spec_field(
        [size] if size else [],
        confidence=0.99 if size_explicit else (0.0 if not size else 0.7),
        criticality="important",
        source="explicit_size" if size_explicit else ("size_inference" if size else "missing"),
        needs_clarification=False,
    )
    toppings_field = _order_spec_field(
        toppings,
        confidence=0.95 if toppings and explicit_toppings else (0.88 if toppings else 0.0),
        criticality="optional",
        source="explicit_toppings" if toppings and explicit_toppings else ("modifier_inference" if toppings else "missing"),
        needs_clarification=False,
    )
    add_ons_field = _order_spec_field(
        add_ons,
        confidence=0.92 if add_ons and explicit_add_ons else (0.85 if add_ons else 0.0),
        criticality="optional",
        source="explicit_add_on" if add_ons and explicit_add_ons else ("add_on_inference" if add_ons else "missing"),
        needs_clarification=False,
    )
    tip_field = _order_spec_field(
        [tip] if tip else [],
        confidence=0.99 if tip and explicit_tip else (0.0 if not tip else 0.7),
        criticality="optional",
        source="explicit_tip" if tip and explicit_tip else ("tip_inference" if tip else "missing"),
        needs_clarification=False,
    )

    clarification_blockers: list[str] = []
    if not restaurant_field.values or restaurant_field.confidence < 0.65:
        clarification_blockers.append("clarify_restaurant")
    if not item_field.values or item_field.confidence < 0.65:
        clarification_blockers.append("clarify_item")
    if explicit_service and (not service_field.values or service_field.confidence < 0.65):
        clarification_blockers.append("clarify_service")

    return OrderSpec(
        kind="food_order",
        service=service_field,
        restaurant=restaurant_field,
        item=item_field,
        size=size_field,
        toppings=toppings_field,
        add_ons=add_ons_field,
        tip=tip_field,
        clarification_blockers=list(dict.fromkeys(clarification_blockers)),
    )


def _extract_ride_slots(prompt: str) -> dict[str, str]:
    raw = _clean_text(prompt)
    slots: dict[str, str] = {}
    if re.search(r"\buber\b", raw, flags=re.IGNORECASE):
        slots["service"] = "Uber"
    elif re.search(r"\blyft\b", raw, flags=re.IGNORECASE):
        slots["service"] = "Lyft"
    else:
        slots["service"] = "ride share"
    pickup = _extract_between(raw, r"\bfrom\b", r"\b(?:to|in|at|around|for)\b")
    if pickup:
        slots["pickup_location"] = pickup
    destination = _extract_between(raw, r"\bto\b", r"\b(?:in|at|around|from|for)\b")
    if destination:
        slots["destination"] = destination
    time_match = re.search(r"\b(?:in\s+\d+\s+minutes?|now|today|tomorrow|at\s+\d+(?::\d+)?)\b", raw, flags=re.IGNORECASE)
    if time_match:
        slots["pickup_time"] = _title_text(time_match.group(0))
    return slots


def _slot_lines(slots: dict[str, str]) -> list[str]:
    return [f"{key.replace('_', ' ').title()}: {value}" for key, value in slots.items() if value]


def _food_draft_text(slots: dict[str, str]) -> str:
    lines = ["Food order capsule"]
    lines.extend(_slot_lines(slots))
    return "\n".join(lines)


def _ride_draft_text(slots: dict[str, str]) -> str:
    lines = ["Ride quote capsule"]
    lines.extend(_slot_lines(slots))
    return "\n".join(lines)


def _sms_bridge_url(draft: ActionDraftPayload) -> str:
    body = quote(draft.body or "", safe="")
    return f"sms:?&body={body}" if body else ""


def _food_search_query(*, restaurant: str, item: str) -> str:
    clean_restaurant = _clean_text(restaurant)
    clean_item = _clean_text(item)
    if clean_restaurant and clean_item:
        restaurant_tokens = set(_normalize_text(clean_restaurant).split())
        item_tokens = set(_normalize_text(clean_item).split())
        if item_tokens and item_tokens <= restaurant_tokens:
            return clean_restaurant
        return f"{clean_restaurant} {clean_item}"
    return clean_restaurant or clean_item or "food"


def _service_search_url(service: str, query: str) -> str:
    clean_query = quote(_clean_text(query), safe="")
    if service.lower() == "doordash":
        return f"https://www.doordash.com/search/store/{clean_query}/" if clean_query else "https://www.doordash.com/"
    if service.lower() == "uber eats":
        return f"https://www.ubereats.com/search?q={clean_query}" if clean_query else "https://www.ubereats.com/"
    if service.lower() == "uber":
        return "https://www.uber.com/us/en/start-riding/"
    if clean_query:
        return f"https://www.google.com/search?q={quote(service + ' ' + _clean_text(query), safe='')}"
    return ""


def _lookup_uber_destination_profile(destination: str) -> dict[str, Any] | None:
    normalized = _normalize_text(destination)
    if not normalized:
        return None
    if normalized in _UBER_KNOWN_DESTINATIONS:
        return dict(_UBER_KNOWN_DESTINATIONS[normalized])
    for key, profile in _UBER_KNOWN_DESTINATIONS.items():
        if normalized in key or key in normalized:
            return dict(profile)
    return None


def _uber_product_selection_url(*, pickup_profile: dict[str, Any], destination_profile: dict[str, Any], vehicle: str = "") -> str:
    pickup_payload = quote(json.dumps(pickup_profile, separators=(",", ":")), safe="")
    destination_payload = quote(json.dumps(destination_profile, separators=(",", ":")), safe="")
    url = f"https://m.uber.com/go/product-selection?pickup={pickup_payload}&drop%5B0%5D={destination_payload}"
    if vehicle:
        url += f"&vehicle={quote(vehicle, safe='')}"
    return url


def _ride_bridge_options(service: str, slots: dict[str, str]) -> list[ActionBridgeOption]:
    if service != "Uber":
        return _service_bridge_options(service, "")
    destination = slots.get("destination", "")
    pickup_profile = dict(_UBER_DEFAULT_PICKUP_PROFILE)
    destination_profile = _lookup_uber_destination_profile(destination)
    fallback_url = _service_search_url(service, "")
    if destination_profile:
        direct_url = _uber_product_selection_url(
            pickup_profile=pickup_profile,
            destination_profile=destination_profile,
        )
        return [
            ActionBridgeOption(
                option_id="uber_direct_quote",
                label="Open Uber Quote",
                kind="in_app_web",
                url=direct_url,
                instructions="Open Uber directly at product selection so Memla can skip the fragile pickup builder and stop before the final ride request.",
            ),
            ActionBridgeOption(
                option_id="uber_builder_fallback",
                label="Open Uber Builder",
                kind="in_app_web",
                url=fallback_url,
                instructions="Fallback to the generic Uber ride builder when the direct quote bridge is unavailable or stale.",
            ),
        ]
    return [
        ActionBridgeOption(
            option_id="service_web",
            label="Open Uber Builder",
            kind="in_app_web",
            url=fallback_url,
            instructions="Open the standard Uber ride builder when no direct destination profile is available yet.",
        )
    ]


def _generic_web_search_url(service: str, query: str) -> str:
    search = _clean_text(" ".join(part for part in [service, query] if part))
    return f"https://www.google.com/search?q={quote(search, safe='')}" if search else "https://www.google.com/"


def _service_bridge_options(service: str, query: str) -> list[ActionBridgeOption]:
    url = _service_search_url(service, query)
    if not url:
        return []
    if service in {"DoorDash", "Uber Eats"}:
        return [
            ActionBridgeOption(
                option_id="service_app",
                label=f"Open {service} App",
                kind="universal_link",
                url=url,
                instructions="Let iOS route this through the installed service app if available.",
            ),
            ActionBridgeOption(
                option_id="service_web",
                label=f"Open {service} Web",
                kind="in_app_web",
                url=url,
                instructions="Open the same capsule bridge inside Memla Browser to keep the web path visible.",
            ),
            ActionBridgeOption(
                option_id="generic_web_search",
                label="Search Web",
                kind="in_app_web",
                url=_generic_web_search_url(service, query),
                instructions="Start from a general web search when the service URL drops part of the capsule intent.",
            ),
        ]
    return [
        ActionBridgeOption(
            option_id="service_web",
            label=f"Open {service}",
            kind="in_app_web",
            url=url,
            instructions="Open the capsule bridge inside Memla Browser.",
        )
    ]


def _message_capsule(prompt: str, draft: ActionDraftPayload) -> ActionCapsule:
    blockers = ["ios_messages_requires_user_send"]
    if draft.recipients:
        blockers.append("recipient_alias_not_bound_yet")
    return ActionCapsule(
        prompt=prompt,
        capsule_id=_capsule_id(draft.action_id, prompt),
        action_id=draft.action_id,
        title=draft.title,
        domain=draft.domain,
        risk_level=draft.risk_level,
        authorization_level="open_confirmation_screen" if draft.ok else "draft_only",
        confirmation_required=True,
        auto_submit_allowed=False,
        status="bridge_ready" if draft.ok else "needs_slots",
        summary="Message draft is ready. Memla can open Messages, then the user chooses the recipient and presses Send." if draft.ok else "Memla needs a recipient and message body before opening a message draft.",
        slots={
            "recipients": ", ".join(draft.recipients),
            "channel": draft.channel,
            "body": draft.body,
        },
        draft_text=draft.draft_text,
        bridge_kind="ios_sms_compose_body_only" if draft.ok else "",
        bridge_url=_sms_bridge_url(draft),
        bridge_label="Open Message Draft" if draft.ok else "",
        bridge_options=[
            ActionBridgeOption(
                option_id="ios_messages_body",
                label="Open Message Draft",
                kind="ios_messages",
                url=_sms_bridge_url(draft),
                instructions="User chooses the recipient and presses Send. Memla does not auto-send.",
            )
        ] if draft.ok else [],
        bridge_instructions="User chooses the recipient and presses Send. Memla does not auto-send.",
        verifier_requirements=["user_selected_recipient", "user_pressed_send"],
        auto_submit_blockers=blockers,
        residual_constraints=draft.residual_constraints,
    )


def _food_capsule(prompt: str, draft: ActionDraftPayload) -> ActionCapsule:
    slots = _extract_food_slots(prompt)
    order_spec = _compile_food_order_spec(prompt, slots)
    service = slots.get("service", "food delivery")
    item = slots.get("item", "")
    restaurant = slots.get("restaurant", "")
    search_query = _food_search_query(restaurant=restaurant, item=item)
    clarification_blockers = [f"order_spec:{item}" for item in order_spec.clarification_blockers]
    bridge_options = [] if clarification_blockers else _service_bridge_options(service, search_query)
    bridge_url = bridge_options[0].url if bridge_options else ("" if clarification_blockers else _service_search_url(service, search_query))
    blockers = [
        "consumer_ordering_bridge_not_implemented",
        "price_not_verified",
        "delivery_address_not_verified",
        "checkout_schema_not_verified",
        "payment_requires_user_confirmation",
    ]
    if not item:
        blockers.insert(0, "missing_item")
    if not restaurant:
        blockers.insert(0, "missing_restaurant")
    if clarification_blockers:
        blockers = clarification_blockers + blockers
    summary = (
        "Food order spec compiled, but Memla needs to clarify the order before opening the service bridge."
        if clarification_blockers
        else "Food order capsule prepared. Memla can structure the cart intent, but checkout must stay user-confirmed until the service bridge and price verifiers exist."
    )
    return ActionCapsule(
        prompt=prompt,
        capsule_id=_capsule_id(draft.action_id, prompt),
        action_id=draft.action_id,
        title=draft.title,
        domain=draft.domain,
        risk_level=draft.risk_level,
        authorization_level="open_confirmation_screen",
        confirmation_required=True,
        auto_submit_allowed=False,
        status="needs_order_clarification" if clarification_blockers else "service_bridge_required",
        summary=summary,
        slots=slots,
        draft_text=_food_draft_text(slots),
        bridge_kind="commerce_bridge_options",
        bridge_url=bridge_url,
        bridge_label="" if clarification_blockers else f"Open {service}",
        bridge_options=bridge_options,
        bridge_instructions=(
            "Clarify the missing critical order fields before opening the commerce bridge."
            if clarification_blockers
            else "Use the structured capsule to search/build the cart. Stop at checkout for user review and purchase confirmation."
        ),
        verifier_requirements=["restaurant_match", "item_match", "modifier_match", "tip_match", "total_price_limit", "delivery_address_match", "user_checkout_confirmation"],
        auto_submit_blockers=blockers,
        residual_constraints=list(dict.fromkeys(list(draft.residual_constraints) + clarification_blockers)),
        order_spec=order_spec,
    )


def _ride_capsule(prompt: str, draft: ActionDraftPayload) -> ActionCapsule:
    slots = _extract_ride_slots(prompt)
    service = slots.get("service", "ride share")
    bridge_options = _ride_bridge_options(service, slots)
    bridge_url = bridge_options[0].url if bridge_options else _service_search_url(service, "")
    blockers = [
        "pickup_location_not_verified",
        "price_not_verified",
        "driver_eta_not_verified",
        "booking_requires_user_confirmation",
    ]
    if "destination" not in slots:
        blockers.insert(0, "missing_destination")
    return ActionCapsule(
        prompt=prompt,
        capsule_id=_capsule_id(draft.action_id, prompt),
        action_id=draft.action_id,
        title=draft.title,
        domain=draft.domain,
        risk_level=draft.risk_level,
        authorization_level="open_confirmation_screen",
        confirmation_required=True,
        auto_submit_allowed=False,
        status="service_bridge_ready" if bridge_options else "service_bridge_required",
        summary="Ride capsule prepared. Memla can open a direct ride quote bridge when the service profile is known, but booking still stays user-confirmed until pickup, price, and ETA are verified.",
        slots=slots,
        draft_text=_ride_draft_text(slots),
        bridge_kind="web_or_deeplink_bridge",
        bridge_url=bridge_url,
        bridge_label=f"Open {service}",
        bridge_options=bridge_options,
        bridge_instructions="Use the structured capsule to request a quote. Stop before booking for user review and confirmation.",
        verifier_requirements=["pickup_location_match", "destination_match", "pickup_time_match", "price_limit", "eta_acceptance", "user_booking_confirmation"],
        auto_submit_blockers=blockers,
        residual_constraints=draft.residual_constraints,
    )


def create_action_capsule(prompt: str) -> ActionCapsule:
    match = classify_action_prompt(prompt)
    draft = create_action_draft(prompt)
    if match.action_id in {"ask_contact", "draft_message", "send_email"}:
        return _message_capsule(prompt, draft)
    if match.action_id == "food_order_quote":
        return _food_capsule(prompt, draft)
    if match.action_id == "book_ride_quote":
        return _ride_capsule(prompt, draft)
    if match.action_id == "browser_scout":
        return ActionCapsule(
            prompt=prompt,
            capsule_id=_capsule_id(match.action_id, prompt),
            action_id=match.action_id,
            title=match.title,
            domain=match.domain,
            risk_level=match.risk_level,
            authorization_level="auto_execute",
            confirmation_required=False,
            auto_submit_allowed=False,
            status="implemented",
            summary="Browser scout is safe to run automatically because it only searches, reads, ranks, and reports.",
            slots={"goal": _clean_text(prompt)},
            draft_text="",
            bridge_kind="memla_runtime",
            bridge_url="",
            bridge_label="Run Scout",
            bridge_instructions="Execute through Memla's bounded browser scout runtime.",
            verifier_requirements=["result_cards_present", "best_match_ranked", "report_returned"],
            auto_submit_blockers=[],
            residual_constraints=match.residual_constraints,
        )
    return ActionCapsule(
        prompt=prompt,
        capsule_id=_capsule_id(match.action_id, prompt),
        action_id=match.action_id,
        title=match.title,
        domain=match.domain,
        risk_level=match.risk_level,
        authorization_level="draft_only",
        confirmation_required=match.confirmation_required,
        auto_submit_allowed=False,
        status=match.status,
        summary="Memla recognizes this action, but it still needs a safe bridge before execution.",
        slots={},
        draft_text=draft.draft_text,
        bridge_kind="",
        bridge_url="",
        bridge_label="",
        bridge_instructions="",
        verifier_requirements=[],
        auto_submit_blockers=["safe_bridge_not_implemented"],
        residual_constraints=match.residual_constraints,
    )


def action_capsule_to_dict(capsule: ActionCapsule) -> dict[str, Any]:
    return asdict(capsule)
