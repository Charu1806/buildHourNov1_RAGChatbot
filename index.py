"""ASGI entrypoint for Vercel (container and Python runtimes).

`app` is the top-level name Vercel loads. Locally, `python -m src.app` still
works and keeps its 127.0.0.1:8000 behaviour.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

from src.app import create_app
from src.config import load_settings


def _is_writable(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


settings = load_settings(require_llm=True)

# Serverless filesystems are read-only outside /tmp, and Chroma opens its
# SQLite store read-write. Copy the baked index to /tmp when needed.
if settings.chroma_path.is_dir() and not _is_writable(settings.chroma_path):
    tmp_path = Path("/tmp/chroma")
    if not tmp_path.exists():
        shutil.copytree(settings.chroma_path, tmp_path)
    settings = replace(settings, chroma_path=tmp_path)

app = create_app(settings)
