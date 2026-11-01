"""Phase 6: what actually lands in the Chroma collection."""

from pathlib import Path

import chromadb
import pytest

from src.embed import embed_chunks

COLLECTION = "hdfc_mf_facts"
METADATA_FIELDS = {
    "chunk_id",
    "scheme",
    "section",
    "source_url",
    "fetched_at",
    "doc_id",
}


def _chunk(chunk_id: str, text: str, *, scheme: str = "Scheme A", doc_id: str = "scheme-a") -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "text": text,
        "scheme": scheme,
        "section": "Exit load",
        "source_url": "https://groww.in/a",
        "fetched_at": "2026-11-01",
        "token_count": 10,
    }


def _vectors(texts):
    return [[0.5] * 384 for _ in texts]


def _run(tmp_path: Path, chunks: list[dict], **overrides):
    kwargs = {
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "chroma_path": tmp_path / "chroma",
        "collection_name": COLLECTION,
        "manifest_path": tmp_path / "manifest.json",
        "rebuild_index": False,
        "encode": _vectors,
    }
    kwargs.update(overrides)
    return embed_chunks(chunks, **kwargs)


def _collection(tmp_path: Path):
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    return client.get_collection(COLLECTION)


def test_stores_the_documented_schema(tmp_path: Path):
    chunks = [
        _chunk("a#exit-load#0", "AMC: HDFC Mutual Fund | body one"),
        _chunk("a#exit-load#1", "AMC: HDFC Mutual Fund | body two"),
    ]
    assert _run(tmp_path, chunks) == "wrote"

    collection = _collection(tmp_path)
    assert collection.metadata["hnsw:space"] == "cosine"
    stored = collection.get(include=["documents", "metadatas", "embeddings"])
    assert collection.count() == len(chunks)
    assert len(stored["embeddings"][0]) == 384

    by_id = {
        chunk_id: (document, metadata)
        for chunk_id, document, metadata in zip(
            stored["ids"], stored["documents"], stored["metadatas"]
        )
    }
    assert set(by_id) == {chunk["chunk_id"] for chunk in chunks}
    for chunk in chunks:
        document, metadata = by_id[chunk["chunk_id"]]
        assert document == chunk["text"]
        assert set(metadata) == METADATA_FIELDS
        assert all(isinstance(value, str) for value in metadata.values())
        assert metadata == {
            "chunk_id": chunk["chunk_id"],
            "scheme": chunk["scheme"],
            "section": chunk["section"],
            "source_url": chunk["source_url"],
            "fetched_at": chunk["fetched_at"],
            "doc_id": chunk["doc_id"],
        }


def test_adds_in_batches_of_sixty_four(tmp_path: Path):
    chunks = [_chunk(f"a#exit-load#{index}", f"body {index}") for index in range(130)]
    assert _run(tmp_path, chunks) == "wrote"

    collection = _collection(tmp_path)
    assert collection.count() == 130
    assert set(collection.get(include=[])["ids"]) == {
        chunk["chunk_id"] for chunk in chunks
    }


def test_rebuild_replaces_the_collection_and_removes_next(tmp_path: Path):
    _run(tmp_path, [_chunk("a#exit-load#0", "one"), _chunk("a#exit-load#1", "two")])
    assert _run(tmp_path, [_chunk("a#exit-load#0", "one")]) == "wrote"

    collection = _collection(tmp_path)
    assert collection.count() == 1
    assert collection.get(include=[])["ids"] == ["a#exit-load#0"]

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    assert {item.name for item in client.list_collections()} == {COLLECTION}


def test_stale_next_collection_is_cleaned_up(tmp_path: Path):
    _run(tmp_path, [_chunk("a#exit-load#0", "one")])
    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    client.create_collection(f"{COLLECTION}__next", metadata={"hnsw:space": "cosine"})

    assert _run(tmp_path, [_chunk("a#exit-load#0", "two")]) == "wrote"

    assert {item.name for item in client.list_collections()} == {COLLECTION}
    assert client.get_collection(COLLECTION).count() == 1


def test_failed_encode_leaves_the_live_collection_untouched(tmp_path: Path):
    _run(tmp_path, [_chunk("a#exit-load#0", "old body")])

    with pytest.raises(SystemExit, match="expected shape"):
        _run(
            tmp_path,
            [_chunk("a#exit-load#0", "new body")],
            encode=lambda texts: [[0.1, 0.2, 0.3] for _ in texts],
        )

    collection = _collection(tmp_path)
    assert collection.count() == 1
    assert collection.get(include=["documents"])["documents"] == ["old body"]


def test_count_mismatch_triggers_a_rebuild(tmp_path: Path):
    chunks = [_chunk("a#exit-load#0", "one"), _chunk("a#exit-load#1", "two")]
    _run(tmp_path, chunks)

    client = chromadb.PersistentClient(path=str(tmp_path / "chroma"))
    client.delete_collection(COLLECTION)

    assert _run(tmp_path, chunks) == "wrote"
    assert _collection(tmp_path).count() == 2
