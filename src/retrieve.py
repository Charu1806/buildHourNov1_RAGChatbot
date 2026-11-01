"""Phase 5: embed the question and return the top-k allowlisted chunks.

This module never calls an LLM. `python -m src.retrieve "question"` prints the
hits so a reviewer can inspect retrieval before generation exists.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.config import Settings, load_settings
from src.sources import read_sources

DIMENSION = 384
SNIPPET_CHARS = 400

Encoder = Callable[[str], list[float]]


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    doc_id: str
    text: str
    scheme: str
    section: str
    source_url: str
    fetched_at: str
    similarity: float

    @property
    def snippet(self) -> str:
        return self.text[:SNIPPET_CHARS]

    def to_trace(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "snippet": self.snippet,
            "scheme": self.scheme,
            "section": self.section,
            "source_url": self.source_url,
            "similarity": self.similarity,
        }


class Retriever:
    def __init__(
        self,
        settings: Settings,
        *,
        encoder: Encoder | None = None,
        client=None,
    ) -> None:
        self.settings = settings
        self.model_id = manifest_model(settings.root, settings.embedding_model)
        self.source_urls = {row.url for row in read_sources(settings.sources_path)}
        self.encoder = encoder if encoder is not None else _Encoder(self.model_id)
        self.collection = _open_collection(settings, client)

    def search(self, question: str) -> list[Hit]:
        text = (question or "").strip()
        if not text:
            return []

        vector = self.encoder(text)
        if len(vector) != DIMENSION:
            raise SystemExit(
                f"question embedding has {len(vector)} dimensions, expected {DIMENSION}"
            )

        result = self.collection.query(
            query_embeddings=[vector],
            n_results=self.settings.top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = result.get("ids", [[]])[0]
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        hits: list[Hit] = []
        for chunk_id, document, metadata, distance in zip(
            ids, documents, metadatas, distances
        ):
            metadata = metadata or {}
            source_url = str(metadata.get("source_url") or "")
            if source_url not in self.source_urls:
                continue
            hits.append(
                Hit(
                    chunk_id=str(chunk_id),
                    doc_id=str(metadata.get("doc_id") or ""),
                    text=document or "",
                    scheme=str(metadata.get("scheme") or ""),
                    section=str(metadata.get("section") or ""),
                    source_url=source_url,
                    fetched_at=str(metadata.get("fetched_at") or ""),
                    similarity=round(1.0 - float(distance), 6),
                )
            )
        hits.sort(key=lambda hit: hit.similarity, reverse=True)
        return hits


def best_similarity(hits: list[Hit]) -> float:
    return hits[0].similarity if hits else 0.0


def passes_threshold(hits: list[Hit], threshold: float) -> bool:
    return bool(hits) and best_similarity(hits) >= threshold


def manifest_model(root: Path, configured_model: str) -> str:
    path = root / "data" / "embeddings" / "manifest.json"
    if not path.is_file():
        raise SystemExit("embedding manifest missing; run python -m src.embed")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    model = str(manifest.get("embedding_model") or "").strip()
    if model != configured_model:
        raise SystemExit(
            "embedding model changed "
            f"({model or 'missing'} != {configured_model}); run python -m src.embed"
        )
    return model


def _open_collection(settings: Settings, client):
    import chromadb

    if client is None:
        client = chromadb.PersistentClient(path=str(settings.chroma_path))
    try:
        return client.get_collection(
            settings.chroma_collection, embedding_function=None
        )
    except Exception as exc:
        raise SystemExit(
            f"collection {settings.chroma_collection} missing; run python -m src.embed"
        ) from exc


class _Encoder:
    """MiniLM loaded once, on CPU, from the model id in the manifest."""

    def __init__(self, model_id: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_id, device="cpu")

    def __call__(self, text: str) -> list[float]:
        vector = self._model.encode(
            [text],
            batch_size=1,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [float(value) for value in vector[0]]


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    question = " ".join(args).strip()
    if not question:
        raise SystemExit('usage: python -m src.retrieve "question"')

    settings = load_settings(require_llm=False)
    retriever = Retriever(settings)
    hits = retriever.search(question)

    if not hits:
        print("no hits")
        print(f"best=0.0000 threshold={settings.score_threshold} -> below_threshold")
        return 0

    for index, hit in enumerate(hits, start=1):
        print(f"{index}. similarity={hit.similarity:.4f} {hit.chunk_id}")
        print(f"   scheme={hit.scheme} section={hit.section}")
        print(f"   source={hit.source_url} fetched_at={hit.fetched_at}")
        print(f"   {hit.snippet}")
    best = best_similarity(hits)
    verdict = "pass" if best >= settings.score_threshold else "below_threshold"
    print(f"best={best:.4f} threshold={settings.score_threshold} -> {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
