from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional


def _default_adapters_dir() -> str:
    return os.environ.get("MEMORY_ADAPTERS_DIR", "./adapters")


def _user_dir(user_id: str, adapters_dir: Optional[str] = None) -> Path:
    base = Path(adapters_dir or _default_adapters_dir())
    return base / user_id


def _atomic_torch_save(obj, path: Path) -> None:
    """
    Async-safe-ish: write to temp file then rename.
    """
    import torch

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=str(path.parent), prefix=path.name, suffix=".tmp") as tmp:
        tmp_path = Path(tmp.name)
    try:
        torch.save(obj, str(tmp_path))
        os.replace(str(tmp_path), str(path))
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except Exception:
            pass


@dataclass
class EWCConfig:
    lambda_ewc: float = 500.0
    fisher_num_samples: int = 50
    fisher_running_avg_old: float = 0.7
    fisher_running_avg_new: float = 0.3


class EWC:
    """
    Elastic Weight Consolidation for protecting LoRA parameters.

    Stores:
    - fisher_matrix.pt: dict[name -> tensor]
    - param_snapshot.pt: dict[name -> tensor] (previous values)
    """

    def __init__(self, *, user_id: str, adapters_dir: Optional[str] = None) -> None:
        self.user_id = user_id
        self.adapters_dir = adapters_dir or _default_adapters_dir()

        self.user_path = _user_dir(user_id, self.adapters_dir)
        self.fisher_path = self.user_path / "fisher_matrix.pt"
        self.snapshot_path = self.user_path / "param_snapshot.pt"

        self.fisher: Dict[str, "torch.Tensor"] = {}
        self.snapshot: Dict[str, "torch.Tensor"] = {}

        self._load_if_exists()

    def _load_if_exists(self) -> None:
        try:
            import torch

            if self.fisher_path.exists():
                self.fisher = torch.load(str(self.fisher_path), map_location="cpu") or {}
            if self.snapshot_path.exists():
                self.snapshot = torch.load(str(self.snapshot_path), map_location="cpu") or {}
        except Exception:
            self.fisher = {}
            self.snapshot = {}

    def _trainable_lora_named_params(self, model) -> list[tuple[str, "torch.nn.Parameter"]]:
        import torch

        params: list[tuple[str, torch.nn.Parameter]] = []
        for name, p in model.named_parameters():
            if not getattr(p, "requires_grad", False):
                continue
            # Heuristic: focus on PEFT/LoRA parameters only.
            if "lora" not in name.lower():
                continue
            params.append((name, p))
        return params

    def snapshot_params(self, model) -> None:
        """
        Store a CPU snapshot of current trainable LoRA params.
        """
        try:
            import torch

            snap: Dict[str, torch.Tensor] = {}
            for name, p in self._trainable_lora_named_params(model):
                snap[name] = p.detach().clone().to("cpu")
            self.snapshot = snap
            _atomic_torch_save(self.snapshot, self.snapshot_path)
        except Exception:
            # Fail silently
            return

    def ewc_loss(self, model, *, lambda_ewc: float) -> "torch.Tensor":
        """
        Sum_i fisher_i * (theta_i - theta_i_prev)^2
        """
        import torch

        if not self.fisher or not self.snapshot:
            return torch.tensor(0.0, device=next(model.parameters()).device)

        loss = torch.tensor(0.0, device=next(model.parameters()).device)
        for name, p in self._trainable_lora_named_params(model):
            if name not in self.fisher or name not in self.snapshot:
                continue
            fisher = self.fisher[name].to(p.device)
            prev = self.snapshot[name].to(p.device)
            loss = loss + (fisher * (p - prev).pow(2)).sum()

        return loss * float(lambda_ewc)

    def compute_fisher(
        self,
        *,
        model,
        losses: Iterable["torch.Tensor"],
        num_samples: int = 50,
    ) -> Dict[str, "torch.Tensor"]:
        """
        Approximate Fisher as E[g^2] for each LoRA param, using provided losses.
        """
        import torch

        params = self._trainable_lora_named_params(model)
        if not params:
            return {}

        fisher_acc = {name: torch.zeros_like(p, device="cpu") for name, p in params}
        count = 0

        for loss in losses:
            if count >= int(num_samples):
                break
            model.zero_grad(set_to_none=True)
            loss.backward(retain_graph=False)
            for name, p in params:
                if p.grad is None:
                    continue
                fisher_acc[name] += (p.grad.detach().pow(2)).to("cpu")
            count += 1

        if count == 0:
            return {}
        for name in list(fisher_acc.keys()):
            fisher_acc[name] = fisher_acc[name] / float(count)
        return fisher_acc

    def update_fisher(
        self,
        *,
        model,
        losses: Iterable["torch.Tensor"],
        cfg: EWCConfig,
    ) -> None:
        """
        Recompute fisher on new examples, then running-average with existing fisher.
        Also refresh param snapshot.
        """
        try:
            import torch

            computed = self.compute_fisher(model=model, losses=losses, num_samples=cfg.fisher_num_samples)
            if not computed:
                return

            if not self.fisher:
                self.fisher = computed
            else:
                old_w = float(cfg.fisher_running_avg_old)
                new_w = float(cfg.fisher_running_avg_new)
                merged: Dict[str, torch.Tensor] = {}
                for name, new_f in computed.items():
                    old_f = self.fisher.get(name)
                    if old_f is None:
                        merged[name] = new_f
                    else:
                        merged[name] = (old_w * old_f) + (new_w * new_f)
                self.fisher = merged

            _atomic_torch_save(self.fisher, self.fisher_path)
            self.snapshot_params(model)
        except Exception:
            return

