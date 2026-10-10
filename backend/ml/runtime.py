"""Process-wide runtime for the real models.

- Models are heavy, so each one is loaded once per process and shared by every call session.
- Each model family gets its own single-thread executor. All loading AND inference for that
  model happens on that one thread: MLX keeps per-thread GPU streams, torch-on-MPS is not
  re-entrant, and a single thread per model serialises access without extra locks. Different
  models still run in parallel (Whisper on MLX, spoof on MPS, ECAPA on CPU), and the asyncio
  event loop only awaits futures, so the WebSocket stays responsive.
- Nothing here imports torch/mlx at module import time: the base install (no `ml` extra)
  must keep working with stub providers.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, TypeVar

log = logging.getLogger(__name__)
T = TypeVar("T")

_executors: dict[str, ThreadPoolExecutor] = {}
_exec_lock = threading.Lock()
_models: dict[tuple, Any] = {}
_model_lock = threading.Lock()


def has_modules(*names: str) -> bool:
    """True when every module is importable (without importing it)."""
    try:
        return all(importlib.util.find_spec(n) is not None for n in names)
    except (ImportError, ValueError):
        return False


def executor(name: str) -> ThreadPoolExecutor:
    with _exec_lock:
        ex = _executors.get(name)
        if ex is None:
            ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"ml-{name}")
            _executors[name] = ex
        return ex


async def run(name: str, fn: Callable[..., T], *args: Any) -> T:
    """Run `fn(*args)` on model `name`'s dedicated thread without blocking the event loop."""
    return await asyncio.get_running_loop().run_in_executor(executor(name), fn, *args)


def submit(name: str, fn: Callable[..., T], *args: Any) -> Future:
    """Synchronous-world variant of `run` (scripts, warmup from a non-async context)."""
    return executor(name).submit(fn, *args)


def cached(key: tuple, factory: Callable[[], T]) -> T:
    """Load-once cache. Call from the model's own executor thread."""
    with _model_lock:
        if key in _models:
            return _models[key]
    obj = factory()
    with _model_lock:
        return _models.setdefault(key, obj)


def torch_device(pref: str = "auto") -> str:
    import torch

    if pref == "auto":
        return "mps" if torch.backends.mps.is_available() else "cpu"
    if pref == "mps" and not torch.backends.mps.is_available():
        log.warning("MPS requested but not available; using CPU")
        return "cpu"
    return pref


def sync_device(device: str) -> None:
    if device == "mps":
        import torch

        torch.mps.synchronize()


def shutdown() -> None:
    with _exec_lock:
        for ex in _executors.values():
            ex.shutdown(wait=False, cancel_futures=True)
        _executors.clear()
