from __future__ import annotations

import argparse
import os
import secrets
import sys
import time

from .memory.episode_log import EpisodeLog
from .memory.chunk_manager import ChunkManager
from .memory.llm_extractor import LLMChunkExtractor
from .middleware.ttt_layer import TTTLayer
from .ollama_client import ChatMessage, UniversalLLMClient


BASE_SYSTEM = """
You are a helpful assistant running locally.

You may be given retrieved memory snippets about the user. Use them when relevant.
If the user asks about specific details from prior context, answer using retrieved memory.
If you do not know, say so and ask a precise question to resolve ambiguity.
""".strip()


def _new_session_id() -> str:
    return f"sess_{int(time.time())}_{secrets.token_hex(3)}"


def run_chat(
    *,
    model: str,
    db_path: str,
    user_id: str,
    ollama_base_url: str,
    top_k: int,
    temperature: float,
    num_ctx: int | None,
) -> int:
    log = EpisodeLog(db_path)
    # Default stays Ollama unless LLM_PROVIDER env overrides.
    client = UniversalLLMClient.from_env()
    if client.provider == "ollama":
        client.base_url = ollama_base_url.rstrip("/")
    extractor = LLMChunkExtractor(client=client, model=model, temperature=0.0, num_ctx=num_ctx)
    cm = ChunkManager(log, llm_extractor=extractor.extract)
    ttt = TTTLayer(episode_log=log, chunk_manager=cm)

    session_id = _new_session_id()
    conversation_history: list[ChatMessage] = []
    max_history_turns = 20

    print(f"[memory_system] user_id={user_id} session_id={session_id} model={model}")
    print("[memory_system] Commands: /new_session, /recall, /good, /bad, /merge_adapters, /exit\n")

    try:
        while True:
            try:
                user_text = input("> ").rstrip("\n")
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not user_text.strip():
                continue
            if user_text.strip() == "/exit":
                break
            if user_text.strip() == "/new_session":
                session_id = _new_session_id()
                conversation_history.clear()
                ttt.clear_turn_state()
                print(f"[memory_system] new session_id={session_id}")
                continue
            if user_text.strip() == "/good":
                if ttt.explicit_feedback(is_positive=True):
                    print("[memory_system] positive feedback recorded — retrieval adapter reinforced.")
                else:
                    print("[memory_system] no previous turn to give feedback on.")
                continue
            if user_text.strip() == "/bad":
                if ttt.explicit_feedback(is_positive=False):
                    print("[memory_system] negative feedback recorded — retrieval adapter corrected.")
                else:
                    print("[memory_system] no previous turn to give feedback on.")
                continue
            if user_text.strip() == "/recall":
                retrieved = ttt.last_retrieved
                if not retrieved:
                    print("[memory_system] no retrieved chunks yet (send a message first).")
                else:
                    print("[memory_system] last retrieved chunks:")
                    for c in retrieved:
                        print(f"  - ({c.chunk_type}, freq={c.frequency_count}) {c.text}")
                continue
            if user_text.strip() == "/merge_adapters":
                try:
                    from .adapters.lora_manager import RetrievalLoRAManager
                    from .adapters.merge import AdapterMerger

                    adapters_dir = os.environ.get("MEMORY_ADAPTERS_DIR", "./adapters")
                    base = os.path.abspath(adapters_dir)
                    user_ids = []
                    if os.path.isdir(base):
                        for name in os.listdir(base):
                            if name == "shared_base":
                                continue
                            d = os.path.join(base, name, "retrieval_adapter")
                            if os.path.isdir(d):
                                user_ids.append(name)

                    if not user_ids:
                        print("[memory_system] no user adapters found to merge.")
                        continue

                    mgr = RetrievalLoRAManager(adapters_dir=adapters_dir)
                    mgr.ensure_loaded()  # loads base retrieval model (may download)
                    merger = AdapterMerger(adapters_dir=adapters_dir)
                    report = merger.run_merge(user_ids=user_ids, base_model=mgr._model)  # noqa: SLF001
                    print(f"[memory_system] merge report: {report.to_dict()}")
                    print("[memory_system] note: shared base applies on next session start.")
                except Exception as e:
                    print(f"[memory_system] merge failed (no changes applied): {e}")
                continue
            if user_text.strip() == "/update_subspace":
                try:
                    from .projection.gradient_filter import GradientProjector
                    try:
                        from config import MIN_AGREEMENT  # type: ignore
                        min_agreement = float(MIN_AGREEMENT)
                    except Exception:
                        min_agreement = 0.6
                    GradientProjector(adapters_dir=os.environ.get("MEMORY_ADAPTERS_DIR", "./adapters")).update_subspace(
                        min_agreement=min_agreement
                    )
                    print("[memory_system] subspace update triggered (background).")
                except Exception as e:
                    print(f"[memory_system] subspace update failed: {e}")
                continue

            artifacts = ttt.on_user_message(
                session_id=session_id,
                user_id=user_id,
                user_text=user_text,
                base_system=BASE_SYSTEM,
                top_k=top_k,
            )

            messages = [
                ChatMessage(role="system", content=artifacts.built.system_prompt),
                *conversation_history[-(max_history_turns * 2):],
                ChatMessage(role="user", content=user_text),
            ]

            try:
                assistant_text = client.chat(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    num_ctx=num_ctx,
                )
            except Exception as e:
                print(f"[memory_system] Ollama call failed: {e}")
                print("[memory_system] Is Ollama running? Try: `ollama serve`")
                continue

            ttt.on_assistant_message(
                session_id=session_id,
                user_id=user_id,
                assistant_text=assistant_text,
                meta={"retrieved_chunk_ids": [c.id for c in artifacts.retrieved]},
            )

            conversation_history.append(ChatMessage(role="user", content=user_text))
            conversation_history.append(ChatMessage(role="assistant", content=assistant_text.strip()))

            print(assistant_text.strip())
            print()
    finally:
        log.close()

    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Local LLM memory system (Step 1).")
    p.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "llama3.2"))
    p.add_argument("--db", default=os.environ.get("MEMORY_DB", "./memory.sqlite"))
    p.add_argument("--user_id", default=os.environ.get("USER_ID", "default"))
    p.add_argument("--ollama_url", default=os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434"))
    p.add_argument("--top_k", type=int, default=12)
    p.add_argument("--temperature", type=float, default=0.2)
    p.add_argument("--num_ctx", type=int, default=int(os.environ["OLLAMA_NUM_CTX"]) if "OLLAMA_NUM_CTX" in os.environ else None)
    args = p.parse_args(argv)

    return run_chat(
        model=args.model,
        db_path=args.db,
        user_id=args.user_id,
        ollama_base_url=args.ollama_url,
        top_k=args.top_k,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
    )


if __name__ == "__main__":
    raise SystemExit(main())

