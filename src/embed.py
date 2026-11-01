"""Embed chunks locally with MiniLM and store them in Chroma."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from src.config import load_settings

DIMENSION = 384
BATCH = 64


def main() -> None:
    settings = load_settings(require_llm=False)
    chunk_path = settings.root / "data" / "chunks" / "chunks.jsonl"
    if not chunk_path.is_file():
        raise SystemExit("chunks missing; run python -m src.chunk")
    chunks = read_chunks(chunk_path)
    manifest_path = settings.root / "data" / "embeddings" / "manifest.json"
    try:
        outcome = embed_chunks(
            chunks,
            embedding_model=settings.embedding_model,
            chroma_path=settings.chroma_path,
            collection_name=settings.chroma_collection,
            manifest_path=manifest_path,
            rebuild_index=settings.rebuild_index,
            encode=lambda texts: _encode(settings.embedding_model, texts),
        )
    except SystemExit:
        raise
    except Exception as exc:
        print(f"error encode {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if outcome == "skip":
        print(
            f"skip data/chroma collection={settings.chroma_collection} chunks={len(chunks)}"
        )
    else:
        print(f"wrote data/embeddings/manifest.json chunks={len(chunks)} dim={DIMENSION}")


def embed_chunks(
    chunks: list[dict],
    *,
    embedding_model: str,
    chroma_path: Path,
    collection_name: str,
    manifest_path: Path,
    rebuild_index: bool,
    encode,
) -> str:
    if not chunks:
        raise SystemExit("chunks.jsonl has no rows")
    digest = chunk_set_hash(chunks)
    manifest = _read_manifest(manifest_path)
    count = _collection_count(chroma_path, collection_name)
    if not _needs_rebuild(rebuild_index, embedding_model, chunks, digest, manifest, count):
        return "skip"
    try:
        vectors = encode([chunk["text"] for chunk in chunks])
    except Exception:
        raise
    rows = _rows(vectors, len(chunks))
    _store(chroma_path, collection_name, chunks, rows)
    _write_manifest(
        manifest_path,
        {
            "embedding_model": embedding_model,
            "dimension": DIMENSION,
            "chunk_count": len(chunks),
            "chunk_set_hash": digest,
            "chroma_collection": collection_name,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )
    return "wrote"


def read_chunks(path: Path) -> list[dict]:
    chunks = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            chunks.append(json.loads(line))
    return chunks


def chunk_set_hash(chunks: list[dict]) -> str:
    material = []
    for chunk in chunks:
        text_hash = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
        material.append(f"{chunk['chunk_id']}\n{text_hash}\n")
    return hashlib.sha256("".join(material).encode("utf-8")).hexdigest()


def _needs_rebuild(
    rebuild_index: bool,
    embedding_model: str,
    chunks: list[dict],
    digest: str,
    manifest: dict | None,
    collection_count: int | None,
) -> bool:
    if rebuild_index or not manifest:
        return True
    if manifest.get("embedding_model") != embedding_model:
        return True
    if manifest.get("chunk_count") != len(chunks):
        return True
    if manifest.get("chunk_set_hash") != digest:
        return True
    return collection_count != len(chunks)


def _rows(vectors, expected: int) -> list[list[float]]:
    if hasattr(vectors, "shape"):
        shape = tuple(int(part) for part in vectors.shape)
        rows = vectors.tolist()
    else:
        rows = [[float(value) for value in row] for row in vectors]
        shape = (len(rows), len(rows[0]) if rows else 0)
    if shape != (expected, DIMENSION):
        raise SystemExit(f"expected shape ({expected}, {DIMENSION}), got {shape}")
    return rows


def _encode(model_id: str, texts: list[str]):
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_id, device="cpu")
    return model.encode(
        texts,
        batch_size=32,
        normalize_embeddings=True,
        show_progress_bar=False,
    )


def _store(chroma_path: Path, name: str, chunks: list[dict], rows: list[list[float]]) -> None:
    import chromadb

    chroma_path.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(chroma_path))
    next_name = f"{name}__next"
    _delete_if_exists(client, next_name)
    _fill(client, next_name, chunks, rows)
    if client.get_collection(next_name).count() != len(chunks):
        _delete_if_exists(client, next_name)
        raise SystemExit("next collection count mismatch")
    _delete_if_exists(client, name)
    _fill(client, name, chunks, rows)
    if client.get_collection(name).count() != len(chunks):
        raise SystemExit("collection count mismatch")
    _delete_if_exists(client, next_name)


def _fill(client, name: str, chunks: list[dict], rows: list[list[float]]) -> None:
    collection = client.create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=_StoredVectors(),
    )
    for start in range(0, len(chunks), BATCH):
        batch = chunks[start : start + BATCH]
        collection.add(
            ids=[chunk["chunk_id"] for chunk in batch],
            documents=[chunk["text"] for chunk in batch],
            metadatas=[_metadata(chunk) for chunk in batch],
            embeddings=rows[start : start + BATCH],
        )


def _metadata(chunk: dict) -> dict:
    return {
        "chunk_id": str(chunk["chunk_id"]),
        "scheme": str(chunk["scheme"]),
        "section": str(chunk["section"]),
        "source_url": str(chunk["source_url"]),
        "fetched_at": str(chunk["fetched_at"]),
        "doc_id": str(chunk["doc_id"]),
    }


def _collection_count(chroma_path: Path, name: str) -> int | None:
    if not chroma_path.exists():
        return None
    import chromadb

    client = chromadb.PersistentClient(path=str(chroma_path))
    try:
        return client.get_collection(name, embedding_function=_StoredVectors()).count()
    except Exception:
        return None


def _delete_if_exists(client, name: str) -> None:
    try:
        client.delete_collection(name)
    except Exception:
        return


def _read_manifest(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


class _StoredVectors:
    """Chroma calls this only when embeddings are not passed in."""

    def __call__(self, input):
        raise RuntimeError("embeddings are computed by MiniLM before insert")

    def embed_query(self, input):
        raise RuntimeError("embeddings are computed by MiniLM before insert")

    @staticmethod
    def name() -> str:
        return "minilm-precomputed"

    def is_legacy(self) -> bool:
        return True


if __name__ == "__main__":
    main()
