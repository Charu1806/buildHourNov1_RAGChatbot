"""Load config.yaml and .env. Ingestion does not require an API key."""

from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]

PROVIDER_KEYS = {
    "groq": "GROQ_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}


@dataclass(frozen=True)
class Settings:
    root: Path
    embedding_model: str
    chroma_path: Path
    chroma_collection: str
    chunk_strategy: str
    chunk_max_tokens: int
    chunk_overlap_tokens: int
    top_k: int
    score_threshold: float
    llm_provider: str
    llm_temperature: float
    llm_max_tokens: int
    sources_path: Path
    educational_url: str
    max_answer_sentences: int
    rebuild_index: bool
    allowed_hosts: tuple[str, ...]
    llm_model: str
    api_key: str


def load_settings(require_llm: bool = False) -> Settings:
    with (ROOT / "config.yaml").open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    load_dotenv(ROOT / ".env")

    provider = str(raw["llm_provider"]).strip().lower()
    if provider not in PROVIDER_KEYS:
        raise SystemExit(f"unknown llm_provider: {provider}")

    chunk_strategy = str(raw["chunk_strategy"]).strip()
    if chunk_strategy != "section_prefix_v1":
        raise SystemExit(f"unsupported chunk_strategy: {chunk_strategy}")

    chunk_max_tokens = int(raw["chunk_max_tokens"])
    if chunk_max_tokens > 240:
        raise SystemExit("chunk_max_tokens must be 240 or less")

    chunk_overlap_tokens = int(raw["chunk_overlap_tokens"])
    if chunk_overlap_tokens < 0:
        raise SystemExit("chunk_overlap_tokens must be 0 or more")

    top_k = int(raw["top_k"])
    if not 0 < top_k <= 8:
        raise SystemExit("top_k must be from 1 to 8")

    score_threshold = float(raw["score_threshold"])
    if not 0 <= score_threshold <= 1:
        raise SystemExit("score_threshold must be between 0 and 1")

    sources_path = _resolve(str(raw["sources_path"]))
    if not sources_path.is_file():
        raise SystemExit(f"sources file not found: {sources_path}")

    educational_url = str(raw.get("educational_url") or "").strip()
    llm_model = os.environ.get("LLM_MODEL", "").strip()
    api_key = os.environ.get(PROVIDER_KEYS[provider], "").strip()

    if require_llm:
        if not llm_model:
            raise SystemExit("LLM_MODEL is empty")
        if not api_key:
            raise SystemExit(f"{PROVIDER_KEYS[provider]} is empty")
        if not educational_url:
            raise SystemExit("educational_url is empty")
        if educational_url not in _source_urls(sources_path):
            raise SystemExit("educational_url is not listed in sources.csv")
        _check_embedding_manifest(str(raw["embedding_model"]))

    return Settings(
        root=ROOT,
        embedding_model=str(raw["embedding_model"]).strip(),
        chroma_path=_resolve(str(raw["chroma_path"])),
        chroma_collection=str(raw["chroma_collection"]).strip(),
        chunk_strategy=chunk_strategy,
        chunk_max_tokens=chunk_max_tokens,
        chunk_overlap_tokens=chunk_overlap_tokens,
        top_k=top_k,
        score_threshold=score_threshold,
        llm_provider=provider,
        llm_temperature=float(raw["llm_temperature"]),
        llm_max_tokens=int(raw["llm_max_tokens"]),
        sources_path=sources_path,
        educational_url=educational_url,
        max_answer_sentences=int(raw["max_answer_sentences"]),
        rebuild_index=bool(raw["rebuild_index"]),
        allowed_hosts=tuple(str(host).strip() for host in raw["allowed_hosts"]),
        llm_model=llm_model,
        api_key=api_key,
    )


def _resolve(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute():
        return path
    return (ROOT / path).resolve()


def _source_urls(path: Path) -> set[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["url"].strip() for row in csv.DictReader(handle) if row.get("url")}


def _check_embedding_manifest(embedding_model: str) -> None:
    manifest_path = ROOT / "data" / "embeddings" / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("embedding manifest missing; run python -m src.embed")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("embedding_model") != embedding_model:
        raise SystemExit("embedding model changed; run python -m src.embed")
