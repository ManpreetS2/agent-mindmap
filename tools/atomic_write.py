#!/usr/bin/env python3
"""
Atomic file writes: same-directory temp → fsync → os.replace (QA-MM020c-3).

Public API
----------
atomic_write_text(path, text, *, encoding="utf-8") -> None
atomic_write_bytes(path, data) -> None

Crash mid-write leaves the destination untouched (temp may remain).
Stdlib only.
"""

from __future__ import annotations

import os
from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` via temp file in the same directory + fsync + replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    try:
        view = memoryview(data)
        while view:
            n = os.write(fd, view)
            view = view[n:]
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    """UTF-8 (default) text wrapper around :func:`atomic_write_bytes`."""
    atomic_write_bytes(path, text.encode(encoding))
