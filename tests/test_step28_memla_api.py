from __future__ import annotations

from dataclasses import asdict

from fastapi.testclient import TestClient

from memory_system.memory.ontology import record_memory_trace
from memory_system.memory.ontology import summarize_memory_ontology
from memory_system.natural_terminal import (
    BrowserSessionState,
    TerminalAction,
    TerminalExecutionRecord,
    TerminalExecutionResult,
    TerminalPlan,
    TerminalScoutResult,
    TerminalScoutStep,
    save_browser_session_state,
)
from memory_system.server_api import create_memla_app


def test_memla_api_health_exposes_runtime_defaults():
    app = create_memla_app(default_model="phi3:mini", default_provider="ollama", default_heuristic_only=True)
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["api_version"] == "0.1.1"
    assert payload["capabilities"]["browser_debug_upload"] is True
    assert payload["runtime_defaults"]["model"] == "phi3:mini"
    assert payload["runtime_defaults"]["heuristic_only"] is True


def test_memla_api_browser_debug_endpoint_logs_payload(capsys):
    app = create_memla_app(default_heuristic_only=True)
    client = TestClient(app)

    response = client.post(
        "/debug/browser",
        json={
            "source": "ios_browser",
            "reason": "pre_action:dd_modifier_option:Large",
            "title": "Build Your Own Pizza",
            "url": "https://www.doordash.com/store/example",
            "page_kind": "dd_item_modal",
            "inspection_status": "Inspecting...",
            "button_action_status": "Selecting Large...",
            "auto_drive_enabled": True,
            "auto_drive_status": "Selecting Large...",
            "pending_step": {"role": "dd_modifier_option", "label": "Large"},
            "top_candidates": [
                {
                    "role": "dd_modifier_option",
                    "label": "Large",
                    "score": 9.8,
                    "group_key": "size",
                    "group_label": "Choose your size",
                    "selected": False,
                    "opens_subflow": True,
                }
            ],
            "agency_trace": ["[00:00:01] Action: dd_modifier_option -> Large"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    captured = capsys.readouterr()
    assert "[Memla Browser Debug]" in captured.out
    assert "pre_action:dd_modifier_option:Large" in captured.out


def test_memla_api_state_reads_browser_state(tmp_path):
    state_path = tmp_path / "terminal_browser_state.json"
    save_browser_session_state(
        BrowserSessionState(
            current_url="https://github.com/ggml-org/llama.cpp",
            page_kind="repo_page",
            search_engine="github",
            search_query="llama.cpp",
            subject_title="ggml-org/llama.cpp",
            subject_url="https://github.com/ggml-org/llama.cpp",
        ),
        path=state_path,
    )
    app = create_memla_app(state_path=state_path)
    client = TestClient(app)

    response = client.get("/state")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["state"]["page_kind"] == "repo_page"
    assert payload["state"]["subject_title"] == "ggml-org/llama.cpp"


def test_memla_api_memory_exposes_ontology_summary(tmp_path):
    state_path = tmp_path / "terminal_browser_state.json"
    record_memory_trace(
        prompt="find a youtube video about this repo and open the first one",
        normalized_prompt="find a youtube video about this repo and open the first one",
        tokens=["youtube", "repo", "first"],
        context_profile={
            "page_kind": "repo_page",
            "search_engine": "",
            "has_search_results": False,
            "has_subject": True,
            "has_evidence": False,
        },
        action_signatures=["browser_search_subject:youtube", "open_search_result:1"],
        source="language_model",
        path=tmp_path / "terminal_memory_ontology.json",
    )
    app = create_memla_app(state_path=state_path)
    client = TestClient(app)

    response = client.get("/memory")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["summary"]["memory_count"] == 1
    assert payload["summary"]["episodic_count"] == 1


def test_memla_api_actions_exposes_action_ontology():
    app = create_memla_app(default_heuristic_only=True)
    client = TestClient(app)

    response = client.get("/actions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["summary"]["action_count"] >= 6
    assert any(item["action_id"] == "book_ride_quote" for item in payload["summary"]["capabilities"])


def test_memla_api_action_plan_classifies_risky_goal():
    app = create_memla_app(default_heuristic_only=True)
    client = TestClient(app)

    response = client.post("/actions/plan", json={"prompt": "get me an uber in 10 minutes to the airport"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["match"]["action_id"] == "book_ride_quote"
    assert payload["match"]["confirmation_required"] is True


def test_memla_api_action_draft_returns_safe_payload_and_records_memory(tmp_path):
    state_path = tmp_path / "terminal_browser_state.json"
    app = create_memla_app(state_path=state_path, default_heuristic_only=True)
    client = TestClient(app)

    response = client.post("/actions/draft", json={"prompt": "ask my sister what she wants from DoorDash"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["draft"]["ok"] is True
    assert payload["draft"]["action_id"] == "ask_contact"
    assert payload["draft"]["draft_text"] == "To Sister: What do you want from DoorDash?"
    summary = summarize_memory_ontology(tmp_path / "terminal_memory_ontology.json")
    assert summary["action_count"] == 1
    assert summary["kind_counts"]["action_ask_contact"] == 1


def test_memla_api_action_capsule_returns_authorization_ladder(tmp_path):
    state_path = tmp_path / "terminal_browser_state.json"
    app = create_memla_app(state_path=state_path, default_heuristic_only=True)
    client = TestClient(app)

    response = client.post("/actions/capsule", json={"prompt": "get pizza from Tony's with mushrooms and give the dasher a $6 tip on DoorDash"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["capsule"]["action_id"] == "food_order_quote"
    assert payload["capsule"]["authorization_level"] == "open_confirmation_screen"
    assert payload["capsule"]["auto_submit_allowed"] is False
    assert "payment_requires_user_confirmation" in payload["capsule"]["auto_submit_blockers"]
    summary = summarize_memory_ontology(tmp_path / "terminal_memory_ontology.json")
    assert summary["kind_counts"]["action_capsule_food_order_quote"] == 1


def test_memla_api_mission_queue_wraps_capsule_and_decisions():
    app = create_memla_app(default_heuristic_only=True)
    client = TestClient(app)

    response = client.post("/missions", json={"prompt": "get pizza from Tony's with pepperoni and give the dasher a $6 tip on DoorDash"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    mission = payload["mission"]
    assert mission["status"] == "needs_approval"
    assert mission["capsule"]["action_id"] == "food_order_quote"
    assert mission["checkpoint"]["kind"] == "bridge_approval"
    assert mission["checkpoint"]["safety_level"] == "final_confirmation_required"
    assert mission["checkpoint"]["bridge_option"]["kind"] == "in_app_web"

    mission_id = mission["mission_id"]
    decision = client.post(f"/missions/{mission_id}/decision", json={"decision": "approve"})
    assert decision.status_code == 200
    decided = decision.json()["mission"]
    assert decided["status"] == "needs_user_browser"
    assert decided["checkpoint"]["kind"] == "open_user_browser"
    assert decided["checkpoint"]["status"] == "ready"

    listing = client.get("/missions")
    assert listing.status_code == 200
    assert listing.json()["summary"]["mission_count"] == 1


def test_memla_api_scout_returns_structured_result(monkeypatch, tmp_path):
    state_path = tmp_path / "terminal_browser_state.json"

    def _fake_scout(prompt: str, **kwargs):
        assert prompt == "find the top 10 github repos for local llms"
        assert kwargs["save_state"] is True
        return TerminalScoutResult(
            prompt=prompt,
            scout_kind="github_repo_scout",
            source="heuristic",
            ok=True,
            query="local llms",
            goal="",
            requested_limit=10,
            inspected_limit=3,
            steps=[TerminalScoutStep(transmutation="browser_extract_cards", status="ok", message="Fetched cards.")],
            top_results=[{"title": "mudler/LocalAI", "url": "https://github.com/mudler/LocalAI"}],
            best_match={"title": "mudler/LocalAI", "url": "https://github.com/mudler/LocalAI"},
            summary="Best match: mudler/LocalAI",
            browser_state=asdict(BrowserSessionState(current_url="https://github.com/search?q=local+llms&type=repositories", page_kind="search_results")),
        )

    monkeypatch.setattr("memory_system.server_api.run_terminal_scout", _fake_scout)
    app = create_memla_app(state_path=state_path)
    client = TestClient(app)

    response = client.post("/scout", json={"prompt": "find the top 10 github repos for local llms"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["mode"] == "scout"
    assert payload["result"]["best_match"]["title"] == "mudler/LocalAI"


def test_memla_api_run_returns_plan_and_execution(monkeypatch, tmp_path):
    state_path = tmp_path / "terminal_browser_state.json"

    def _fake_build_plan(**kwargs):
        assert kwargs["prompt"] == "open github and search llama.cpp"
        assert kwargs["heuristic_only"] is True
        assert kwargs["model"] == "phi3:mini"
        return TerminalPlan(
            prompt=kwargs["prompt"],
            source="heuristic",
            actions=[
                TerminalAction(
                    kind="open_url",
                    target="https://github.com/search?q=llama.cpp&type=repositories",
                )
            ],
        )

    def _fake_execute(plan: TerminalPlan, **kwargs):
        assert plan.prompt == "open github and search llama.cpp"
        return TerminalExecutionResult(
            prompt=plan.prompt,
            plan_source=plan.source,
            ok=True,
            records=[
                TerminalExecutionRecord(
                    kind="open_url",
                    target="https://github.com/search?q=llama.cpp&type=repositories",
                    status="ok",
                    message="Opened GitHub search.",
                )
            ],
            browser_state=asdict(
                BrowserSessionState(
                    current_url="https://github.com/search?q=llama.cpp&type=repositories",
                    page_kind="search_results",
                    search_engine="github",
                    search_query="llama.cpp",
                )
            ),
        )

    monkeypatch.setattr("memory_system.server_api.build_terminal_plan", _fake_build_plan)
    monkeypatch.setattr("memory_system.server_api.execute_terminal_plan", _fake_execute)
    app = create_memla_app(state_path=state_path, default_model="phi3:mini", default_heuristic_only=True)
    client = TestClient(app)

    response = client.post("/run", json={"prompt": "open github and search llama.cpp"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["mode"] == "execution"
    assert payload["plan"]["source"] == "heuristic"
    assert payload["execution"]["records"][0]["status"] == "ok"
    assert payload["runtime_defaults"]["model"] == "phi3:mini"


def test_memla_api_run_inherits_default_provider_when_request_provider_blank(monkeypatch, tmp_path):
    state_path = tmp_path / "terminal_browser_state.json"
    captured: dict[str, object] = {}

    class DummyClient:
        provider = "anthropic"

    def _fake_build_plan(**kwargs):
        assert kwargs["model"] == "claude-sonnet-4-20250514"
        return TerminalPlan(
            prompt=kwargs["prompt"],
            source="heuristic",
            actions=[TerminalAction(kind="browser_answer_query", target="top news today")],
        )

    def _fake_execute(plan: TerminalPlan, **kwargs):
        return TerminalExecutionResult(
            prompt=plan.prompt,
            plan_source=plan.source,
            ok=True,
            records=[
                TerminalExecutionRecord(
                    kind="browser_answer_query",
                    target="top news today",
                    status="ok",
                    message="Top news today...",
                )
            ],
            browser_state=asdict(BrowserSessionState(current_url="https://example.com", page_kind="web_page")),
        )

    def _fake_build_client(*, provider=None, base_url=None, api_key=None):
        captured["provider"] = provider
        captured["base_url"] = base_url
        return DummyClient()

    monkeypatch.setattr("memory_system.server_api.build_llm_client", _fake_build_client)
    monkeypatch.setattr("memory_system.server_api.build_terminal_plan", _fake_build_plan)
    monkeypatch.setattr("memory_system.server_api.execute_terminal_plan", _fake_execute)
    app = create_memla_app(
        state_path=state_path,
        default_model="claude-sonnet-4-20250514",
        default_provider="anthropic",
        default_heuristic_only=False,
    )
    client = TestClient(app)

    response = client.post("/run", json={"prompt": "whats on the news"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert captured["provider"] == "anthropic"
    assert payload["runtime_defaults"]["provider"] == "anthropic"


def test_memla_api_followup_returns_plan_when_no_actions(monkeypatch, tmp_path):
    state_path = tmp_path / "terminal_browser_state.json"

    def _fake_build_plan(**kwargs):
        return TerminalPlan(
            prompt=kwargs["prompt"],
            source="fallback",
            clarification="Need a clearer follow-up.",
            residual_constraints=["unsupported_or_ambiguous_request"],
        )

    monkeypatch.setattr("memory_system.server_api.build_terminal_plan", _fake_build_plan)
    app = create_memla_app(state_path=state_path, default_heuristic_only=True)
    client = TestClient(app)

    response = client.post("/followup", json={"prompt": "do that thing again"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["mode"] == "plan"
    assert payload["execution"] is None
    assert payload["plan"]["clarification"] == "Need a clearer follow-up."
