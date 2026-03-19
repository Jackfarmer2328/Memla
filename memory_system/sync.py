"""
Cloud sync for Memla (Constraint 4).

Syncs SQLite database and LoRA adapter files to/from cloud storage.
Local-first by default; cloud-optional via env flags.

Supported backends:
  - S3 (via boto3): set MEMLA_SYNC_S3_BUCKET
  - Local folder (for Dropbox/OneDrive/Google Drive): set MEMLA_SYNC_DIR

Usage:
    # Pull latest from cloud on session start
    from memory_system.sync import pull_if_enabled
    pull_if_enabled()

    # Push to cloud on session end
    from memory_system.sync import push_if_enabled
    push_if_enabled()

Env vars:
    MEMLA_SYNC_BACKEND   = "s3" | "folder" | "" (disabled, default)
    MEMLA_SYNC_S3_BUCKET = "my-memla-backup"
    MEMLA_SYNC_S3_PREFIX = "memla/"  (default)
    MEMLA_SYNC_DIR       = "/Users/me/Dropbox/memla-sync"
    MEMLA_DB             = "./memory.sqlite"
    MEMORY_ADAPTERS_DIR  = "./adapters"
"""
from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Optional


SYNC_BACKEND = os.environ.get("MEMLA_SYNC_BACKEND", "").lower()
S3_BUCKET = os.environ.get("MEMLA_SYNC_S3_BUCKET", "")
S3_PREFIX = os.environ.get("MEMLA_SYNC_S3_PREFIX", "memla/")
SYNC_DIR = os.environ.get("MEMLA_SYNC_DIR", "")
DB_PATH = os.environ.get("MEMLA_DB", os.environ.get("MEMORY_DB", "./memory.sqlite"))
ADAPTERS_DIR = os.environ.get("MEMORY_ADAPTERS_DIR", "./adapters")

_FILES_TO_SYNC = [
    lambda: DB_PATH,
    lambda: DB_PATH + "-wal",
    lambda: DB_PATH + "-shm",
]


def _adapter_files() -> list[str]:
    """Collect all adapter files for sync."""
    base = Path(ADAPTERS_DIR)
    if not base.exists():
        return []
    return [str(p) for p in base.rglob("*") if p.is_file()]


def is_enabled() -> bool:
    return SYNC_BACKEND in ("s3", "folder")


# ── Folder backend (Dropbox / OneDrive / Google Drive) ───────────

def _folder_push() -> int:
    if not SYNC_DIR:
        return 0
    dst = Path(SYNC_DIR)
    dst.mkdir(parents=True, exist_ok=True)
    count = 0
    for fn in _FILES_TO_SYNC:
        src = Path(fn())
        if src.exists():
            shutil.copy2(src, dst / src.name)
            count += 1
    adapters_dst = dst / "adapters"
    for fpath in _adapter_files():
        rel = Path(fpath).relative_to(ADAPTERS_DIR)
        target = adapters_dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fpath, target)
        count += 1
    return count


def _folder_pull() -> int:
    if not SYNC_DIR:
        return 0
    src = Path(SYNC_DIR)
    if not src.exists():
        return 0
    count = 0
    for fn in _FILES_TO_SYNC:
        local = Path(fn())
        remote = src / local.name
        if remote.exists():
            remote_mtime = remote.stat().st_mtime
            if not local.exists() or remote_mtime > local.stat().st_mtime:
                shutil.copy2(remote, local)
                count += 1
    adapters_src = src / "adapters"
    if adapters_src.exists():
        for fpath in adapters_src.rglob("*"):
            if fpath.is_file():
                rel = fpath.relative_to(adapters_src)
                target = Path(ADAPTERS_DIR) / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.exists() or fpath.stat().st_mtime > target.stat().st_mtime:
                    shutil.copy2(fpath, target)
                    count += 1
    return count


# ── S3 backend ───────────────────────────────────────────────────

def _s3_push() -> int:
    try:
        import boto3
    except ImportError:
        print("[sync] boto3 not installed — skipping S3 sync")
        return 0
    s3 = boto3.client("s3")
    count = 0
    for fn in _FILES_TO_SYNC:
        local = Path(fn())
        if local.exists():
            key = S3_PREFIX + local.name
            s3.upload_file(str(local), S3_BUCKET, key)
            count += 1
    for fpath in _adapter_files():
        rel = Path(fpath).relative_to(ADAPTERS_DIR)
        key = S3_PREFIX + "adapters/" + str(rel).replace("\\", "/")
        s3.upload_file(fpath, S3_BUCKET, key)
        count += 1
    return count


def _s3_pull() -> int:
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        print("[sync] boto3 not installed — skipping S3 sync")
        return 0
    s3 = boto3.client("s3")
    count = 0
    for fn in _FILES_TO_SYNC:
        local = Path(fn())
        key = S3_PREFIX + local.name
        try:
            local.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(S3_BUCKET, key, str(local))
            count += 1
        except ClientError:
            pass
    try:
        resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=S3_PREFIX + "adapters/")
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            rel = key[len(S3_PREFIX + "adapters/"):]
            target = Path(ADAPTERS_DIR) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(S3_BUCKET, key, str(target))
            count += 1
    except ClientError:
        pass
    return count


# ── Public API ───────────────────────────────────────────────────

def push_if_enabled() -> Optional[int]:
    if not is_enabled():
        return None
    if SYNC_BACKEND == "s3":
        return _s3_push()
    if SYNC_BACKEND == "folder":
        return _folder_push()
    return None


def pull_if_enabled() -> Optional[int]:
    if not is_enabled():
        return None
    if SYNC_BACKEND == "s3":
        return _s3_pull()
    if SYNC_BACKEND == "folder":
        return _folder_pull()
    return None
