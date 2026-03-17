from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Optional


def _default_adapters_dir() -> str:
    return os.environ.get("MEMORY_ADAPTERS_DIR", "./adapters")


def _shared_base_dir(adapters_dir: Optional[str] = None) -> Path:
    return Path(adapters_dir or _default_adapters_dir()) / "shared_base"


def _safe_subspace_path(adapters_dir: Optional[str] = None) -> Path:
    return _shared_base_dir(adapters_dir) / "safe_subspace.pt"


def _merge_log_path(adapters_dir: Optional[str] = None) -> Path:
    return _shared_base_dir(adapters_dir) / "merge_log.json"


def _subspace_log_path(adapters_dir: Optional[str] = None) -> Path:
    return _shared_base_dir(adapters_dir) / "subspace_log.json"


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


def _atomic_torch_save(obj, path: Path) -> None:
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


class GradientProjector:
    """
    Step 5: project updates through a safe shared subspace.

    Storage format (safe_subspace.pt):
      {param_name: {"basis": Tensor[k, d]}}   # orthonormal row basis

    Projection:
      g_proj = B^T (B g)
    """

    def __init__(self, *, user_id: str = "shared", adapters_dir: Optional[str] = None) -> None:
        self.user_id = user_id
        self.adapters_dir = adapters_dir or _default_adapters_dir()
        self.safe_subspace: dict = {}
        self._load_safe_subspace()

    def _load_safe_subspace(self) -> None:
        p = _safe_subspace_path(self.adapters_dir)
        if not p.exists():
            self.safe_subspace = {}
            return
        try:
            import torch

            data = torch.load(str(p), map_location="cpu")
            if not isinstance(data, dict):
                raise ValueError("safe_subspace.pt not a dict")
            self.safe_subspace = data
        except Exception:
            # If corrupted/unreadable: delete and fall back to all-pass.
            try:
                p.unlink()
            except Exception:
                pass
            self.safe_subspace = {}

    def compute_safe_subspace(self, *, min_agreement: float = 0.6) -> dict:
        """
        Compute safe subspace from merge history.

        We interpret "direction appeared consistently" as:
        eigenvectors of the average projector with eigenvalue >= min_agreement.

        Each merge run stores per-param PCA bases. For a param with bases V_i (k_i x d),
        define projector P_i = V_i^T V_i.
        Mean projector: P_bar = (1/M) sum P_i.
        Safe eigenvectors: eigen(P_bar) with eigenvalue >= min_agreement.

        Implemented via SVD on stacked basis rows to avoid forming full P_bar explicitly:
          A = stack(all basis rows across merges)  (R x d)
          (1/M) A^T A has eigenvalues s^2/M and eigenvectors from V of SVD(A).
        """
        import torch

        mlog = _merge_log_path(self.adapters_dir)
        if not mlog.exists():
            return {}
        try:
            hist = json.loads(mlog.read_text(encoding="utf-8"))
            if not isinstance(hist, list):
                return {}
        except Exception:
            return {}

        # Collect directions file references.
        per_param_rows: Dict[str, list[torch.Tensor]] = {}
        merges_with_param: Dict[str, int] = {}
        merge_count = 0

        for item in hist:
            if not isinstance(item, dict):
                continue
            dirs_path = (item.get("shared_directions_path") or "").strip()
            if not dirs_path:
                continue
            p = Path(dirs_path)
            if not p.is_absolute():
                p = _shared_base_dir(self.adapters_dir) / p
            if not p.exists():
                continue
            try:
                shared_dirs = torch.load(str(p), map_location="cpu")
            except Exception:
                continue
            if not isinstance(shared_dirs, dict):
                continue
            merge_count += 1
            for pname, basis in shared_dirs.items():
                if basis is None:
                    continue
                try:
                    B = basis.to(torch.float32)
                    if B.ndim != 2:
                        continue
                    per_param_rows.setdefault(pname, []).append(B)
                    merges_with_param[pname] = merges_with_param.get(pname, 0) + 1
                except Exception:
                    continue

        if merge_count == 0:
            return {}

        safe: dict[str, dict] = {}
        for pname, blocks in per_param_rows.items():
            # Only consider params that appear in enough merges.
            appear_frac = float(merges_with_param.get(pname, 0)) / float(merge_count)
            if appear_frac < float(min_agreement):
                continue
            try:
                A = torch.cat(blocks, dim=0)  # [R, d]
                # Normalize rows.
                A = torch.nn.functional.normalize(A, p=2, dim=1)
                # SVD of A => eigenvectors of A^T A are V, eigenvalues are s^2.
                U, S, Vh = torch.linalg.svd(A, full_matrices=False)
                eigvals = (S**2) / float(merge_count)
                keep = eigvals >= float(min_agreement)
                if int(keep.sum().item()) <= 0:
                    continue
                V_keep = Vh[keep, :]  # [k, d] row basis
                # Orthonormalize rows (SVD already gives orthonormal rows in Vh).
                safe[pname] = {"basis": V_keep.to("cpu")}
            except Exception:
                continue

        return safe

    def project_gradient(self, gradients: dict) -> dict:
        """
        Filter gradient vectors through safe subspace (if available).
        Fail silent: on any error, return original gradients.
        """
        if not self.safe_subspace:
            return gradients
        try:
            import torch

            out = {}
            for name, g in gradients.items():
                entry = self.safe_subspace.get(name)
                if entry is None:
                    out[name] = g
                    continue
                B = entry.get("basis")
                if B is None:
                    out[name] = g
                    continue
                B = B.to(torch.float32).to(g.device)
                gf = g.reshape(-1).to(torch.float32)
                # g_proj = B^T (B g)
                proj = B.T @ (B @ gf)
                out[name] = proj.reshape(g.shape).to(g.dtype)
            return out
        except Exception:
            return gradients

    def update_subspace(self, *, min_agreement: float = 0.6) -> None:
        """
        Background-safe recompute + persist safe subspace.
        """
        def _bg() -> None:
            try:
                safe = self.compute_safe_subspace(min_agreement=float(min_agreement))
                _atomic_torch_save(safe, _safe_subspace_path(self.adapters_dir))

                log_path = _subspace_log_path(self.adapters_dir)
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
                        "ts": int(time.time()),
                        "min_agreement": float(min_agreement),
                        "params": int(len(safe)),
                    }
                )
                _atomic_write_text(log_path, json.dumps(hist, ensure_ascii=False, indent=2) + "\n")
            except Exception:
                return

        threading.Thread(target=_bg, daemon=True).start()

