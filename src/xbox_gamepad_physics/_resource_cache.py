"""Portable locking and staged publication shared by resource acquisition."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import time
import uuid

from .errors import ResourceError


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # Access denied: do not steal it.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextmanager
def cache_lock(root: Path, *, timeout: float = 600, stale_after: float = 3600):
    """O_EXCL lock; reclaim dead owners, never evict a live long-running build."""
    root.parent.mkdir(parents=True, exist_ok=True)
    path = root.with_name(root.name + ".lock")
    deadline = time.monotonic() + timeout
    owner = json.dumps({"pid": os.getpid(), "timestamp": time.time(), "token": uuid.uuid4().hex})
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                raw = path.read_text(encoding="utf-8")
                try:
                    record = json.loads(raw)
                    stale = time.time() - float(record["timestamp"]) > 1 and not _pid_alive(int(record["pid"]))
                except (ValueError, TypeError, KeyError):
                    stale = time.time() - path.stat().st_mtime > stale_after
                if stale and path.read_text(encoding="utf-8") == raw:
                    path.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise ResourceError(f"timed out waiting for resource lock {path}")
            time.sleep(0.05)
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(owner)
            break
    try:
        yield
    finally:
        if path.exists() and path.read_text(encoding="utf-8") == owner:
            path.unlink()


def publish_directory(staged: Path, destination: Path) -> None:
    """Publish on the same filesystem under the caller's lock, with rollback.

    Windows cannot replace a nonempty directory. Move the previous generation
    aside before the final rename; waiting acquirers observe only the completed tree.
    """
    previous = destination.with_name(destination.name + ".previous")
    if previous.exists():
        if not destination.exists():
            previous.rename(destination)
        else:
            shutil.rmtree(previous)
    if destination.exists():
        destination.rename(previous)
    try:
        staged.rename(destination)
    except OSError:
        if previous.exists():
            previous.rename(destination)
        raise
    if previous.exists():
        shutil.rmtree(previous)
