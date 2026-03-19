"""
Sleep-phase trainer for Memla (Constraint 6).

Loads the generative model in 4-bit via QLoRA and trains a LoRA adapter
on corrected reasoning trajectories using Contrastive Preference Optimization.

The model learns HOW to reason (structural tokens only), not WHAT to say
(output tokens are masked). EWC protects important LoRA weights.

Usage:
    python sleep_train.py                         # default: use memory.sqlite
    python sleep_train.py --db ./memory.sqlite --model Qwen/Qwen2.5-3B
    python sleep_train.py --epochs 3 --lr 1e-5

Prerequisites:
    pip install bitsandbytes accelerate
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Optional

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model, PeftModel


# ── Configuration ────────────────────────────────────────────────

DEFAULT_MODEL = "Qwen/Qwen2.5-3B"
ADAPTER_DIR = "./adapters/generative_lora"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ── Load corrected trajectory pairs from SQLite ──────────────────

def load_cpo_pairs(db_path: str, user_id: str = "default") -> list[dict]:
    """Load trajectory pairs where the user corrected the reasoning."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM trajectories WHERE user_id = ? AND is_corrected = 1 ORDER BY ts DESC",
        (user_id,),
    ).fetchall()
    conn.close()

    pairs = []
    for row in rows:
        original_steps = json.loads(row["steps_json"])
        corrected_steps = json.loads(row["corrected_steps_json"])
        user_query = row["user_query"]

        original_text = _steps_to_text(original_steps)
        corrected_text = _steps_to_text(corrected_steps)

        if original_text != corrected_text:
            pairs.append({
                "query": user_query,
                "chosen": corrected_text,
                "rejected": original_text,
                "chosen_mask": _structural_mask(corrected_steps),
                "rejected_mask": _structural_mask(original_steps),
            })

    return pairs


def _steps_to_text(steps: list[dict]) -> str:
    parts = []
    for s in steps:
        tag = s.get("step_type", s.get("type", "thought")).capitalize()
        content = s.get("content", "")
        parts.append(f"[{tag}] {content}")
    return "\n".join(parts)


def _structural_mask(steps: list[dict]) -> list[bool]:
    """True for structural steps (trainable), False for output (masked)."""
    return [
        s.get("step_type", s.get("type", "")).lower() != "output"
        for s in steps
    ]


# ── QLoRA model loading ─────────────────────────────────────────

def load_model_qlora(model_name: str, adapter_path: Optional[str] = None):
    """Load model in 4-bit NF4 quantization with LoRA."""
    print(f"Loading {model_name} in 4-bit NF4...")

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )

    if adapter_path and Path(adapter_path).exists():
        print(f"Loading existing LoRA from {adapter_path}")
        model = PeftModel.from_pretrained(model, adapter_path)
    else:
        print("Creating new LoRA adapter")
        lora_config = LoraConfig(
            r=16,
            lora_alpha=32,
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
            lora_dropout=0.05,
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, lora_config)

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"Trainable: {trainable:,} / {total:,} ({100*trainable/total:.2f}%)")

    return model, tokenizer


# ── CPO Training Loop ────────────────────────────────────────────

def cpo_loss(
    model, tokenizer, query: str, chosen: str, rejected: str,
    chosen_mask: list[bool], rejected_mask: list[bool],
    beta: float = 0.1,
) -> torch.Tensor:
    """
    Contrastive Preference Optimization loss.

    Trains the model to prefer the corrected trajectory (chosen) over
    the original flawed trajectory (rejected).

    Only structural tokens receive gradient — output tokens are masked.
    """
    chosen_input = f"User: {query}\n\n{chosen}"
    rejected_input = f"User: {query}\n\n{rejected}"

    def get_logprobs(text: str) -> torch.Tensor:
        tokens = tokenizer(text, return_tensors="pt", truncation=True, max_length=1024)
        tokens = {k: v.to(model.device) for k, v in tokens.items()}
        with torch.no_grad() if not model.training else torch.enable_grad():
            outputs = model(**tokens, labels=tokens["input_ids"])
        return -outputs.loss

    model.train()
    chosen_lp = get_logprobs(chosen_input)
    rejected_lp = get_logprobs(rejected_input)

    loss = -torch.nn.functional.logsigmoid(beta * (chosen_lp - rejected_lp))
    return loss


def compute_ewc_penalty(model, snapshot: dict, fisher: dict, lambda_ewc: float = 100.0) -> torch.Tensor:
    """EWC penalty on LoRA parameters to prevent forgetting."""
    penalty = torch.tensor(0.0, device=model.device)
    for name, param in model.named_parameters():
        if param.requires_grad and name in snapshot and name in fisher:
            diff = param - snapshot[name].to(param.device)
            penalty += (fisher[name].to(param.device) * diff.pow(2)).sum()
    return lambda_ewc * penalty


def train_sleep(
    db_path: str,
    model_name: str = DEFAULT_MODEL,
    user_id: str = "default",
    epochs: int = 2,
    lr: float = 1e-5,
    beta: float = 0.1,
    lambda_ewc: float = 100.0,
) -> dict:
    """Run the sleep-phase training."""
    pairs = load_cpo_pairs(db_path, user_id)
    if not pairs:
        print("No corrected trajectory pairs found. Nothing to train on.")
        return {"trained": False, "reason": "no_pairs"}

    print(f"Found {len(pairs)} corrected trajectory pairs")

    adapter_path = ADAPTER_DIR
    model, tokenizer = load_model_qlora(model_name, adapter_path if Path(adapter_path).exists() else None)

    snapshot = {}
    fisher = {}
    for name, param in model.named_parameters():
        if param.requires_grad:
            snapshot[name] = param.data.clone()
            fisher[name] = torch.ones_like(param.data) * 0.01

    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=lr,
    )

    total_loss = 0.0
    step_count = 0

    for epoch in range(epochs):
        print(f"\nEpoch {epoch + 1}/{epochs}")
        for i, pair in enumerate(pairs):
            loss = cpo_loss(
                model, tokenizer,
                query=pair["query"],
                chosen=pair["chosen"],
                rejected=pair["rejected"],
                chosen_mask=pair["chosen_mask"],
                rejected_mask=pair["rejected_mask"],
                beta=beta,
            )

            ewc_pen = compute_ewc_penalty(model, snapshot, fisher, lambda_ewc)
            total = loss + ewc_pen

            optimizer.zero_grad()
            total.backward()
            torch.nn.utils.clip_grad_norm_(
                [p for p in model.parameters() if p.requires_grad], 1.0
            )
            optimizer.step()

            total_loss += total.item()
            step_count += 1

            if (i + 1) % 5 == 0 or i == len(pairs) - 1:
                avg = total_loss / step_count
                print(f"  Step {i+1}/{len(pairs)}, avg_loss={avg:.4f}")

    print(f"\nTraining complete. {step_count} total steps.")

    for name, param in model.named_parameters():
        if param.requires_grad and name in snapshot:
            diff = param.data - snapshot[name].to(param.device)
            fisher[name] = fisher[name].to(param.device) + diff.pow(2)

    Path(adapter_path).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    print(f"LoRA adapter saved to {adapter_path}")

    ewc_path = Path(adapter_path) / "ewc_fisher.pt"
    torch.save({
        "fisher": {k: v.cpu() for k, v in fisher.items()},
        "snapshot": {k: v.cpu() for k, v in snapshot.items()},
    }, ewc_path)
    print(f"EWC state saved to {ewc_path}")

    print(f"""
Next steps:
  1. Create an Ollama Modelfile:
       FROM your-base-model
       ADAPTER {adapter_path}
  2. Build the model:
       ollama create memla-tuned -f Modelfile
  3. Use it:
       python app.py --model memla-tuned
""")

    return {
        "trained": True,
        "pairs": len(pairs),
        "epochs": epochs,
        "steps": step_count,
        "avg_loss": total_loss / max(1, step_count),
        "adapter_path": adapter_path,
    }


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Memla Sleep-Phase Trainer (QLoRA + CPO)")
    p.add_argument("--db", default="./memory.sqlite", help="SQLite database path")
    p.add_argument("--model", default=DEFAULT_MODEL, help="HuggingFace model name")
    p.add_argument("--user_id", default="default")
    p.add_argument("--epochs", type=int, default=2)
    p.add_argument("--lr", type=float, default=1e-5)
    p.add_argument("--beta", type=float, default=0.1, help="CPO temperature")
    p.add_argument("--lambda_ewc", type=float, default=100.0, help="EWC regularization strength")
    a = p.parse_args()

    report = train_sleep(
        db_path=a.db,
        model_name=a.model,
        user_id=a.user_id,
        epochs=a.epochs,
        lr=a.lr,
        beta=a.beta,
        lambda_ewc=a.lambda_ewc,
    )
    print(f"\nReport: {json.dumps(report, indent=2)}")
