from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Optional, Sequence

from .lora_manager import AdapterMeta, RetrievalLoRAManager


@dataclass(frozen=True)
class TrainingExample:
    query: str
    positive: str
    negatives: list[str]


def _make_examples(
    *,
    query: str,
    retrieved_texts: Sequence[str],
    candidate_texts: Sequence[str],
    max_examples: int = 4,
    max_negs: int = 6,
) -> list[TrainingExample]:
    """
    Step 2 training signal is intentionally simple:
    - positives: retrieved chunks (assumed helpful)
    - negatives: other candidates (assumed less helpful)
    """
    retrieved = [t for t in retrieved_texts if t.strip()]
    cand = [t for t in candidate_texts if t.strip()]

    pool_negs = [t for t in cand if t not in set(retrieved)]
    if not retrieved or not pool_negs:
        return []

    examples: list[TrainingExample] = []
    for pos in retrieved[:max_examples]:
        negs = random.sample(pool_negs, k=min(max_negs, len(pool_negs)))
        examples.append(TrainingExample(query=query, positive=pos, negatives=negs))
    return examples


def micro_gradient_pass(
    *,
    manager: RetrievalLoRAManager,
    user_id: str,
    query: str,
    retrieved_texts: Sequence[str],
    candidate_texts: Sequence[str],
    steps: int = 6,
    learning_rate: float = 1e-5,
    quality_signal: Optional[float] = None,
    lambda_ewc: float = 500.0,
    apply_shared_projection: bool = False,
) -> AdapterMeta:
    """
    Runs a small number of optimization steps on the retrieval LoRA.

    This pass is designed to be safe and lightweight:
    - few steps
    - conservative lr
    - if anything fails, it should be caught by caller and ignored
    """
    manager.ensure_loaded(user_id=user_id)

    # Build simple contrastive examples.
    examples = _make_examples(
        query=query,
        retrieved_texts=retrieved_texts,
        candidate_texts=candidate_texts,
    )
    if not examples:
        meta = AdapterMeta.load(user_id=user_id, adapters_dir=manager.adapters_dir)
        return meta

    import torch

    peft_model = manager._peft_model  # noqa: SLF001 (internal use by design here)
    tokenizer = manager._tokenizer  # noqa: SLF001
    assert peft_model is not None and tokenizer is not None

    peft_model.train(True)
    opt = torch.optim.AdamW(peft_model.parameters(), lr=float(learning_rate))

    # Temperature scaling for InfoNCE.
    scale = 20.0

    def embed_train(texts: list[str]):
        toks = tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        )
        device = next(peft_model.parameters()).device
        toks = {k: v.to(device) for k, v in toks.items()}
        out = peft_model(**toks)
        last_hidden = out.last_hidden_state
        mask = toks["attention_mask"].unsqueeze(-1).float()
        summed = (last_hidden * mask).sum(dim=1)
        denom = mask.sum(dim=1).clamp(min=1.0)
        emb = summed / denom
        emb = torch.nn.functional.normalize(emb, p=2, dim=-1)
        return emb

    # Optional: down-weight training if quality is low.
    q_weight = 1.0 if quality_signal is None else max(0.0, min(1.0, float(quality_signal)))

    # EWC (fail silently; if anything goes wrong we fall back to plain contrastive).
    ewc = None
    ewc_cfg = None
    try:
        from .ewc import EWC, EWCConfig

        ewc = EWC(user_id=user_id, adapters_dir=manager.adapters_dir)
        ewc_cfg = EWCConfig(lambda_ewc=float(lambda_ewc))
        # Ensure we have a snapshot for the penalty term.
        if not ewc.snapshot:
            ewc.snapshot_params(peft_model)
    except Exception:
        ewc = None
        ewc_cfg = None

    total_steps = max(1, int(steps))
    step_count = 0
    fisher_losses: list[torch.Tensor] = []
    for _ in range(total_steps):
        random.shuffle(examples)
        for ex in examples:
            # Build batch: [query], [positive] + [negatives]
            q_emb = embed_train([ex.query])  # [1, H]
            cand_texts = [ex.positive] + ex.negatives
            c_emb = embed_train(cand_texts)  # [1+N, H]
            logits = (q_emb @ c_emb.T) * scale  # [1, 1+N]
            labels = torch.zeros((1,), dtype=torch.long, device=logits.device)  # positive at idx 0
            contrastive = torch.nn.functional.cross_entropy(logits, labels) * q_weight
            if ewc is not None:
                try:
                    penalty = ewc.ewc_loss(peft_model, lambda_ewc=float(lambda_ewc))
                    loss = contrastive + penalty
                except Exception:
                    loss = contrastive
            else:
                loss = contrastive

            opt.zero_grad(set_to_none=True)
            loss.backward()

            # Step 5: gradient projection is ONLY for shared-base updates.
            if apply_shared_projection or user_id == "shared":
                try:
                    from ..projection.gradient_filter import GradientProjector
                    try:
                        from config import MIN_AGREEMENT  # type: ignore

                        _ = float(MIN_AGREEMENT)  # imported for consistency; not used here
                    except Exception:
                        pass

                    proj = GradientProjector(user_id="shared", adapters_dir=manager.adapters_dir)
                    grads = {n: p.grad.detach().clone() for n, p in peft_model.named_parameters() if p.grad is not None}
                    fgrads = proj.project_gradient(grads)
                    for n, p in peft_model.named_parameters():
                        if p.grad is not None and n in fgrads:
                            p.grad = fgrads[n]
                except Exception:
                    pass

            opt.step()
            step_count += 1
            # Collect a few losses for Fisher approximation later (positive signal).
            if contrastive.requires_grad and len(fisher_losses) < 50:
                fisher_losses.append(contrastive)

            # Keep it very small per exchange.
            if step_count >= total_steps:
                break
        if step_count >= total_steps:
            break

    peft_model.train(False)

    meta = AdapterMeta.load(user_id=user_id, adapters_dir=manager.adapters_dir)
    meta.training_steps += int(step_count)
    meta.last_updated_ts = int(time.time())
    # "session" notion is external; treat each call as a session increment.
    meta.total_sessions_trained += 1

    manager.save_adapter(user_id=user_id, meta=meta)

    # Fisher update runs AFTER adapter save, and never blocks the caller.
    if ewc is not None and ewc_cfg is not None and fisher_losses:
        def _bg_update() -> None:
            try:
                # Use the post-update weights to recompute/merge Fisher and refresh snapshot.
                ewc.update_fisher(model=peft_model, losses=fisher_losses, cfg=ewc_cfg)
                # Also keep an in-memory snapshot for the manager hook.
                try:
                    manager.snapshot_trainable_params()
                except Exception:
                    pass
            except Exception:
                return

        threading.Thread(target=_bg_update, daemon=True).start()

    return meta

