from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import threading


def _default_adapters_dir() -> str:
    return os.environ.get("MEMORY_ADAPTERS_DIR", "./adapters")


def _shared_base_dir(adapters_dir: Optional[str] = None) -> Path:
    return Path(adapters_dir or _default_adapters_dir()) / "shared_base"


def _base_update_path(adapters_dir: Optional[str] = None) -> Path:
    return _shared_base_dir(adapters_dir) / "base_retrieval_update.pt"

def _shared_dirs_path(ts: int, adapters_dir: Optional[str] = None) -> Path:
    return _shared_base_dir(adapters_dir) / f"shared_directions_{int(ts)}.pt"


def _merge_log_path(adapters_dir: Optional[str] = None) -> Path:
    return _shared_base_dir(adapters_dir) / "merge_log.json"


def _adapter_dir(user_id: str, adapters_dir: Optional[str] = None) -> Path:
    return Path(adapters_dir or _default_adapters_dir()) / user_id / "retrieval_adapter"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _atomic_torch_save(obj, path: Path) -> None:
    import tempfile

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


def _load_adapter_state(adapter_dir: Path) -> Tuple[dict, dict]:
    """
    Returns (adapter_state_dict, adapter_config_dict).
    Supports safetensors or torch bin.
    """
    config_path = adapter_dir / "adapter_config.json"
    cfg = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}

    st_path = adapter_dir / "adapter_model.safetensors"
    bin_path = adapter_dir / "adapter_model.bin"

    state = None
    if st_path.exists():
        try:
            from safetensors.torch import load_file  # type: ignore

            state = load_file(str(st_path))
        except Exception:
            state = None

    if state is None and bin_path.exists():
        import torch

        state = torch.load(str(bin_path), map_location="cpu", weights_only=True)

    if state is None:
        raise FileNotFoundError(f"No adapter model file in {adapter_dir}")
    return state, cfg


def _lora_scaling(cfg: dict) -> float:
    # PEFT config typically has r and lora_alpha.
    r = float(cfg.get("r") or cfg.get("lora_r") or 0.0) or 16.0
    alpha = float(cfg.get("lora_alpha") or 32.0)
    return alpha / r


def _extract_base_weight_deltas(adapter_state: dict, cfg: dict) -> Dict[str, "torch.Tensor"]:
    """
    Convert LoRA A/B weights into equivalent base weight deltas ΔW for each target module weight.

    We look for key pairs:
      <prefix>.lora_A.weight   (r, in)
      <prefix>.lora_B.weight   (out, r)
    and produce:
      <target_weight_name> = scaling * (B @ A)   (out, in)

    The <target_weight_name> is inferred by stripping ".lora_A.weight"/".lora_B.weight"
    and appending ".weight".
    """
    import torch

    scaling = _lora_scaling(cfg)
    keys = list(adapter_state.keys())

    a_keys = [k for k in keys if k.endswith("lora_A.weight")]
    deltas: Dict[str, torch.Tensor] = {}
    for a_key in a_keys:
        prefix = a_key[: -len("lora_A.weight")]
        b_key = prefix + "lora_B.weight"
        if b_key not in adapter_state:
            continue
        A = adapter_state[a_key].to(torch.float32)
        B = adapter_state[b_key].to(torch.float32)
        # B(out,r) @ A(r,in) => (out,in)
        dW = (B @ A) * float(scaling)

        # infer base weight param name
        # Example: "...q_proj." -> "...q_proj.weight"
        target = prefix.rstrip(".") + ".weight"
        deltas[target] = dW.to("cpu")
    return deltas


@dataclass
class MergeReport:
    users_merged: int
    params_updated: int
    variance_captured: float
    users_skipped: list[str]
    safe_subspace_updated: bool = False

    def to_dict(self) -> dict:
        return {
            "users_merged": int(self.users_merged),
            "params_updated": int(self.params_updated),
            "variance_captured": float(self.variance_captured),
            "users_skipped": list(self.users_skipped),
            "safe_subspace_updated": bool(self.safe_subspace_updated),
        }


class AdapterMerger:
    def __init__(self, *, adapters_dir: Optional[str] = None) -> None:
        self.adapters_dir = adapters_dir or _default_adapters_dir()

    def load_all_adapters(self, user_ids: list[str]) -> dict:
        """
        Returns {user_id: {"state": state_dict, "cfg": config_dict}}
        Skips missing adapters silently.
        """
        out = {}
        for uid in user_ids:
            adir = _adapter_dir(uid, self.adapters_dir)
            if not adir.exists():
                continue
            try:
                state, cfg = _load_adapter_state(adir)
                out[uid] = {"state": state, "cfg": cfg}
            except Exception:
                continue
        return out

    def compute_weight_deltas(self, base_model, adapter_weights: dict) -> dict:
        """
        Returns {user_id: {base_param_name: delta_tensor}}
        where base_param_name refers to base model param names (".weight").
        """
        deltas = {}
        for uid, pack in adapter_weights.items():
            try:
                deltas[uid] = _extract_base_weight_deltas(pack["state"], pack.get("cfg") or {})
            except Exception:
                continue
        return deltas

    def extract_shared_directions(
        self,
        deltas: dict,
        *,
        variance_threshold: float = 0.6,
    ) -> tuple[dict, float]:
        """
        For each base param, run PCA over user deltas using torch.linalg.svd.
        Returns ({param_name: Vh_k}, mean_variance_captured).
        """
        import torch

        user_ids = list(deltas.keys())
        if len(user_ids) < 2:
            return {}, 0.0

        # Collect param names present for all (or most) users.
        all_params = set()
        for uid in user_ids:
            all_params |= set(deltas[uid].keys())

        shared: dict[str, torch.Tensor] = {}
        captured: list[float] = []

        for pname in sorted(all_params):
            rows = []
            for uid in user_ids:
                if pname not in deltas[uid]:
                    continue
                rows.append(deltas[uid][pname].reshape(-1).to(torch.float32))
            if len(rows) < 2:
                continue
            X = torch.stack(rows, dim=0)  # [n, d]
            # Center for PCA.
            Xc = X - X.mean(dim=0, keepdim=True)
            try:
                # Xc = U S Vh
                U, S, Vh = torch.linalg.svd(Xc, full_matrices=False)
            except Exception:
                continue
            if S.numel() == 0:
                continue
            var = (S**2)
            tot = float(var.sum().item())
            if tot <= 0.0:
                continue
            frac = (var / var.sum()).cumsum(dim=0)
            k = int((frac < float(variance_threshold)).sum().item()) + 1
            k = max(1, min(k, Vh.shape[0]))
            shared[pname] = Vh[:k, :].to("cpu")  # [k, d]
            captured.append(float(frac[k - 1].item()))

        mean_captured = float(sum(captured) / max(1, len(captured))) if captured else 0.0
        return shared, mean_captured

    def bold_shared_into_base(
        self,
        base_model,
        shared_directions: dict,
        deltas: dict,
        *,
        bold_strength: float = 0.1,
    ) -> dict:
        """
        Writes an additive base update dict {param_name: delta_tensor}.
        Safety: clamp update to max 5% of base abs values elementwise.
        """
        import torch

        base_sd = dict(base_model.state_dict())
        user_ids = list(deltas.keys())
        update: dict[str, torch.Tensor] = {}

        for pname, basis in shared_directions.items():
            if pname not in base_sd:
                continue
            rows = []
            for uid in user_ids:
                if pname not in deltas[uid]:
                    continue
                rows.append(deltas[uid][pname].reshape(-1).to(torch.float32))
            if len(rows) < 2:
                continue
            X = torch.stack(rows, dim=0)  # [n, d]
            mean_delta = X.mean(dim=0)  # [d]
            B = basis.to(torch.float32)  # [k, d], rows orthonormal from SVD
            # Project mean_delta onto span(B).
            proj = B.T @ (B @ mean_delta)  # [d]
            upd_vec = proj * float(bold_strength)

            base_w = base_sd[pname].detach().to(torch.float32).reshape(-1)
            max_change = (base_w.abs() * 0.05).clamp(min=1e-6)
            upd_vec = torch.max(torch.min(upd_vec, max_change), -max_change)

            upd = upd_vec.reshape(base_sd[pname].shape).to("cpu")
            if float(upd.abs().sum().item()) <= 0.0:
                continue
            update[pname] = upd

        return update

    def run_merge(
        self,
        *,
        user_ids: list[str],
        base_model,
        variance_threshold: float = 0.6,
        bold_strength: float = 0.1,
    ) -> MergeReport:
        """
        Manual operation. If it fails, leaves everything untouched.
        """
        skipped = []
        loaded = self.load_all_adapters(user_ids)
        for uid in user_ids:
            if uid not in loaded:
                skipped.append(uid)

        if len(loaded) < 2:
            return MergeReport(users_merged=int(len(loaded)), params_updated=0, variance_captured=0.0, users_skipped=skipped)

        # Compute ΔW in base weight space.
        deltas = self.compute_weight_deltas(base_model, loaded)
        shared_dirs, mean_var = self.extract_shared_directions(deltas, variance_threshold=float(variance_threshold))
        if not shared_dirs:
            return MergeReport(
                users_merged=int(len(loaded)),
                params_updated=0,
                variance_captured=float(mean_var),
                users_skipped=skipped,
            )

        update = self.bold_shared_into_base(
            base_model,
            shared_dirs,
            deltas,
            bold_strength=float(bold_strength),
        )
        if not update:
            return MergeReport(
                users_merged=int(len(loaded)),
                params_updated=0,
                variance_captured=float(mean_var),
                users_skipped=skipped,
            )

        # Persist update + merge log
        ts = int(time.time())
        out_path = _base_update_path(self.adapters_dir)
        _atomic_torch_save(update, out_path)

        # Persist shared directions from this merge for Step 5 safe subspace.
        dirs_path = _shared_dirs_path(ts, self.adapters_dir)
        try:
            _atomic_torch_save(shared_dirs, dirs_path)
            dirs_ref = dirs_path.name  # store relative in log
        except Exception:
            dirs_ref = ""

        log_path = _merge_log_path(self.adapters_dir)
        if log_path.exists():
            try:
                hist = json.loads(log_path.read_text(encoding="utf-8"))
                if not isinstance(hist, list):
                    hist = []
            except Exception:
                hist = []
        else:
            hist = []
        hist.append(
            {
                "ts": ts,
                "shared_directions_path": dirs_ref,
                "report": {
                    "users_merged": int(len(loaded)),
                    "params_updated": int(len(update)),
                    "variance_captured": float(mean_var),
                    "users_skipped": skipped,
                    "variance_threshold": float(variance_threshold),
                    "bold_strength": float(bold_strength),
                },
            }
        )
        _atomic_write_text(log_path, json.dumps(hist, ensure_ascii=False, indent=2) + "\n")

        # Trigger safe subspace recompute in background (non-blocking).
        safe_updated = False
        try:
            from ..projection.gradient_filter import GradientProjector
            try:
                from config import MIN_AGREEMENT  # type: ignore
                min_agreement = float(MIN_AGREEMENT)
            except Exception:
                min_agreement = 0.6

            def _bg() -> None:
                try:
                    GradientProjector(adapters_dir=self.adapters_dir).update_subspace(min_agreement=min_agreement)
                except Exception:
                    return

            threading.Thread(target=_bg, daemon=True).start()
            safe_updated = True
        except Exception:
            safe_updated = False

        return MergeReport(
            users_merged=int(len(loaded)),
            params_updated=int(len(update)),
            variance_captured=float(mean_var),
            users_skipped=skipped,
            safe_subspace_updated=safe_updated,
        )

