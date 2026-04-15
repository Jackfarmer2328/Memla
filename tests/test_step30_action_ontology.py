from memory_system.action_capsules import create_action_capsule
from memory_system.action_ontology import create_action_draft, classify_action_prompt, summarize_action_ontology


def test_action_ontology_classifies_browser_scout_as_implemented():
    match = classify_action_prompt("find the top 10 github repos for local llms and bring back the best one")

    assert match.action_id == "browser_scout"
    assert match.status == "implemented"
    assert match.confirmation_required is False
    assert match.safe_next_step == "execute"


def test_action_ontology_gates_messages_rides_and_food_orders():
    message = classify_action_prompt("imessage my sister and ask what she wants")
    ride = classify_action_prompt("get me an uber in 10 minutes to the airport")
    food = classify_action_prompt("order pizza on doordash")

    assert message.action_id in {"ask_contact", "draft_message"}
    assert message.confirmation_required is True
    assert message.safe_next_step == "draft_then_confirm"

    assert ride.action_id == "book_ride_quote"
    assert ride.confirmation_required is True
    assert "action_status:planned" in ride.residual_constraints

    assert food.action_id == "food_order_quote"
    assert food.confirmation_required is True
    assert "action_status:planned" in food.residual_constraints


def test_action_ontology_summary_exposes_safe_capabilities():
    summary = summarize_action_ontology()

    assert summary["action_count"] >= 6
    assert "messaging" in summary["domains"]
    assert summary["confirmation_required_count"] >= 4
    assert any(item["action_id"] == "browser_scout" for item in summary["capabilities"])


def test_action_ontology_v2_drafts_contact_message_without_sending():
    draft = create_action_draft("ask my sister what she wants from DoorDash")

    assert draft.ok is True
    assert draft.action_id == "ask_contact"
    assert draft.confirmation_required is True
    assert draft.recipients == ["Sister"]
    assert draft.body == "What do you want from DoorDash?"
    assert draft.draft_text == "To Sister: What do you want from DoorDash?"
    assert "confirmation_required" in draft.residual_constraints


def test_action_ontology_v2_keeps_service_actions_bridge_gated():
    draft = create_action_draft("get me an uber in 10 minutes to the airport")

    assert draft.ok is False
    assert draft.action_id == "book_ride_quote"
    assert "service_bridge_required" in draft.residual_constraints
    assert draft.safe_next_step == "design_or_bridge_required"


def test_action_capsule_v1_opens_message_confirmation_bridge_without_autosend():
    capsule = create_action_capsule("ask my sister what she wants from DoorDash")

    assert capsule.action_id == "ask_contact"
    assert capsule.authorization_level == "open_confirmation_screen"
    assert capsule.status == "bridge_ready"
    assert capsule.auto_submit_allowed is False
    assert capsule.bridge_kind == "ios_sms_compose_body_only"
    assert capsule.bridge_url.startswith("sms:?&body=")
    assert "ios_messages_requires_user_send" in capsule.auto_submit_blockers


def test_action_capsule_v1_structures_food_orders_but_blocks_autosubmit():
    capsule = create_action_capsule("get pizza from Tony's with pepperoni and give the dasher a $6 tip on DoorDash")

    assert capsule.action_id == "food_order_quote"
    assert capsule.authorization_level == "open_confirmation_screen"
    assert capsule.status == "service_bridge_required"
    assert capsule.auto_submit_allowed is False
    assert capsule.slots["service"] == "DoorDash"
    assert capsule.slots["item"] == "pizza"
    assert capsule.slots["toppings"] == "pepperoni"
    assert capsule.slots["tip"] == "$6"
    assert [option.label for option in capsule.bridge_options] == ["Open DoorDash App", "Open DoorDash Web", "Search Web"]
    assert capsule.bridge_options[1].kind == "in_app_web"
    assert capsule.bridge_options[2].url.startswith("https://www.google.com/search")
    assert "payment_requires_user_confirmation" in capsule.auto_submit_blockers
    assert "user_checkout_confirmation" in capsule.verifier_requirements


def test_action_capsule_v1_avoids_duplicate_item_when_restaurant_contains_item():
    capsule = create_action_capsule("DoorDash pizza from Tony's pizza, make it cheese and tip the dasher $5")

    assert capsule.action_id == "food_order_quote"
    assert capsule.slots["restaurant"] == "Tony's pizza"
    assert capsule.slots["item"] == "pizza"
    assert capsule.slots["modifiers"] == "cheese"
    assert capsule.slots["toppings"] == "cheese"
    assert "Tony%27s%20pizza%20pizza" not in capsule.bridge_options[0].url
    assert "Tony%27s%20pizza" in capsule.bridge_options[0].url


def test_action_capsule_v1_extracts_size_toppings_and_add_ons_from_food_prompt():
    capsule = create_action_capsule(
        "DoorDash a large cheese pizza from Domino's, make the toppings chicken and pineapple, and add a coke"
    )

    assert capsule.action_id == "food_order_quote"
    assert capsule.slots["service"] == "DoorDash"
    assert capsule.slots["restaurant"] == "Domino's"
    assert capsule.slots["item"] == "cheese pizza"
    assert capsule.slots["size"] == "Large"
    assert capsule.slots["toppings"] == "chicken, pineapple"
    assert capsule.slots["modifiers"] == "chicken, pineapple"
    assert capsule.slots["add_ons"] == "coke"
    assert capsule.order_spec is not None
    assert capsule.order_spec.kind == "food_order"
    assert capsule.order_spec.restaurant.values == ["Domino's"]
    assert capsule.order_spec.restaurant.confidence >= 0.95
    assert capsule.order_spec.item.values == ["cheese pizza"]
    assert capsule.order_spec.size.values == ["Large"]
    assert capsule.order_spec.toppings.values == ["chicken", "pineapple"]
    assert capsule.order_spec.add_ons.values == ["coke"]
    assert capsule.order_spec.clarification_blockers == []
    assert "Domino%27s%20cheese%20pizza" in capsule.bridge_options[0].url


def test_action_capsule_v1_blocks_food_bridge_when_critical_order_fields_are_missing():
    capsule = create_action_capsule("DoorDash a large cheese pizza")

    assert capsule.action_id == "food_order_quote"
    assert capsule.order_spec is not None
    assert "clarify_restaurant" in capsule.order_spec.clarification_blockers
    assert capsule.status == "needs_order_clarification"
    assert capsule.bridge_options == []
    assert "order_spec:clarify_restaurant" in capsule.auto_submit_blockers
