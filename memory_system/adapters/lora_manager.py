from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


def _default_adapters_dir() -> str:
    return os.environ.get("MEMORY_ADAPTERS_DIR", "./adapters")


def _user_dir(user_id: str, adapters_dir: Optional[str] = None) -> Path:
    base = Path(adapters_dir or _default_adapters_dir())
    return base / user_id


def _adapter_dir(user_id: str, adapters_dir: Optional[str] = None) -> Path:
    return _user_dir(user_id, adapters_dir) / "retrieval_adapter"


def _meta_path(user_id: str, adapters_dir: Optional[str] = None) -> Path:
    return _user_dir(user_id, adapters_dir) / "adapter_meta.json"

def _shared_base_update_path(adapters_dir: Optional[str] = None) -> Path:
    base = Path(adapters_dir or _default_adapters_dir())
    return base / "shared_base" / "base_retrieval_update.pt"


@dataclass
class AdapterMeta:
    training_steps: int = 0
    last_updated_ts: int = 0
    total_sessions_trained: int = 0

    @classmethod
    def load(cls, *, user_id: str, adapters_dir: Optional[str] = None) -> "AdapterMeta":
        p = _meta_path(user_id, adapters_dir)
        if not p.exists():
            return cls()
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls(
                training_steps=int(data.get("training_steps") or 0),
                last_updated_ts=int(data.get("last_updated_ts") or 0),
                total_sessions_trained=int(data.get("total_sessions_trained") or 0),
            )
        except Exception:
            return cls()

    def save(self, *, user_id: str, adapters_dir: Optional[str] = None) -> None:
        d = _user_dir(user_id, adapters_dir)
        d.mkdir(parents=True, exist_ok=True)
        p = _meta_path(user_id, adapters_dir)
        p.write_text(
            json.dumps(
                {
                    "training_steps": int(self.training_steps),
                    "last_updated_ts": int(self.last_updated_ts),
                    "total_sessions_trained": int(self.total_sessions_trained),
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


class RetrievalLoRAManager:
    """
    A tiny local retrieval model with a LoRA adapter.

    Base model: sentence-transformers/all-MiniLM-L6-v2 (requested)
    Output: cosine similarity scores between query and chunk texts.

    IMPORTANT: This module must never break the chat loop if HF download/load fails.
    Callers should catch RuntimeError from `ensure_loaded()` and fall back.
    """

    def __init__(
        self,
        *,
        base_model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        adapters_dir: Optional[str] = None,
        device: Optional[str] = None,
    ) -> None:
        self.base_model_name = base_model_name
        self.adapters_dir = adapters_dir or _default_adapters_dir()
        self.device = device

        self._tokenizer = None
        self._model = None
        self._peft_model = None
        self.previous_params = {}

    def adapter_exists(self, *, user_id: str) -> bool:
        return _adapter_dir(user_id, self.adapters_dir).exists()

    def ensure_loaded(self, *, user_id: Optional[str] = None) -> None:
        if self._peft_model is not None:
            return

        try:
            import torch
            from transformers import AutoModel, AutoTokenizer
            from peft import LoraConfig, PeftModel, TaskType, get_peft_model
        except Exception as e:
            raise RuntimeError(f"HF/PEFT imports unavailable: {e}") from e

        try:
            tokenizer = AutoTokenizer.from_pretrained(self.base_model_name)
            base = AutoModel.from_pretrained(self.base_model_name)
        except Exception as e:
            raise RuntimeError(f"Failed to load base retrieval model: {e}") from e

        # Choose device.
        if self.device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            device = self.device
        base.to(device)
        base.eval()

        # Apply shared base update (if any) BEFORE attaching personal LoRA.
        self.load_shared_base_update(base)

        # Attach LoRA.
        # The prompt asked for target_modules=["q","v"]; MiniLM commonly uses "query"/"value".
        # We keep the requested default but allow broader matching via PEFT's substring match.
        lora_cfg = LoraConfig(
            r=16,
            lora_alpha=32,
            target_modules=["q", "v", "query", "value", "q_proj", "v_proj"],
            lora_dropout=0.05,
            bias="none",
            task_type=TaskType.FEATURE_EXTRACTION,
        )
        peft_model = get_peft_model(base, lora_cfg)

        # Load adapter weights if they exist.
        if user_id is not None:
            adir = _adapter_dir(user_id, self.adapters_dir)
            if adir.exists():
                try:
                    peft_model = PeftModel.from_pretrained(peft_model, str(adir), is_trainable=True)
                except Exception:
                    # If adapter load fails, continue with fresh LoRA.
                    pass

        peft_model.to(device)
        peft_model.train(False)

        self._tokenizer = tokenizer
        self._model = base
        self._peft_model = peft_model

    def load_shared_base_update(self, base_model) -> None:
        """
        Apply shared base delta updates if present.

        Order: base model -> shared update -> personal LoRA adapter.
        """
        p = _shared_base_update_path(self.adapters_dir)
        if not p.exists():
            return
        try:
            import torch

            upd = torch.load(str(p), map_location="cpu")
            if not isinstance(upd, dict):
                return
            sd = base_model.state_dict()
            changed = False
            for name, delta in upd.items():
                if name not in sd:
                    continue
                try:
                    sd[name] = (sd[name].to(torch.float32) + delta.to(torch.float32)).to(sd[name].dtype)
                    changed = True
                except Exception:
                    continue
            if changed:
                base_model.load_state_dict(sd, strict=False)
        except Exception:
            return

    def load_adapter(self, *, user_id: str) -> None:
        # In this design, "load adapter" means: ensure model + load adapter if present.
        self.ensure_loaded(user_id=user_id)

    def save_adapter(self, *, user_id: str, meta: Optional[AdapterMeta] = None) -> None:
        if self._peft_model is None:
            return
        adir = _adapter_dir(user_id, self.adapters_dir)
        adir.parent.mkdir(parents=True, exist_ok=True)
        self._peft_model.save_pretrained(str(adir))
        if meta is not None:
            meta.save(user_id=user_id, adapters_dir=self.adapters_dir)

    def snapshot_trainable_params(self) -> None:
        """
        Keep an in-memory snapshot of current trainable params.
        EWC persists snapshots on disk separately; this is a cheap local hook.
        """
        if self._peft_model is None:
            self.previous_params = {}
            return
        snap = {}
        for name, p in self._peft_model.named_parameters():
            if getattr(p, "requires_grad", False) and "lora" in name.lower():
                snap[name] = p.detach().clone()
        self.previous_params = snap

    def _embed_texts(self, texts: list[str]):
        import torch

        assert self._tokenizer is not None and self._peft_model is not None

        toks = self._tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=256,
            return_tensors="pt",
        )
        device = next(self._peft_model.parameters()).device
        toks = {k: v.to(device) for k, v in toks.items()}

        with torch.no_grad():
            out = self._peft_model(**toks)
            last_hidden = out.last_hidden_state  # [B, T, H]
            mask = toks["attention_mask"].unsqueeze(-1).float()  # [B, T, 1]
            summed = (last_hidden * mask).sum(dim=1)
            denom = mask.sum(dim=1).clamp(min=1.0)
            emb = summed / denom
            emb = torch.nn.functional.normalize(emb, p=2, dim=-1)
        return emb

    def score_chunks(self, *, query: str, chunks: Iterable[str]) -> list[float]:
        """
        Returns cosine similarity scores aligned with `chunks`.
        """
        self.ensure_loaded()
        chunk_list = list(chunks)
        if not chunk_list:
            return []

        import torch

        q_emb = self._embed_texts([query])  # [1, H]
        c_emb = self._embed_texts(chunk_list)  # [N, H]
        scores = (q_emb @ c_emb.T).squeeze(0)  # [N]
        return scores.detach().cpu().tolist()

