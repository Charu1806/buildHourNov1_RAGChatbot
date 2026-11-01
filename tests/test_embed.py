import json
from pathlib import Path

import pytest

from src.embed import chunk_set_hash, embed_chunks


def _chunk(chunk_id: str, text: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": "scheme-a",
        "text": text,
        "scheme": "Scheme A",
        "section": "Exit load",
        "source_url": "https://groww.in/a",
        "fetched_at": "2026-11-01",
    }


def _vectors(texts, dimension=384):
    return [[float(len(text) % 7) / 10] * dimension for text in texts]


def _run(tmp_path: Path, chunks: list[dict], **overrides):
    kwargs = {
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "chroma_path": tmp_path / "chroma",
        "collection_name": "hdfc_mf_facts",
        "manifest_path": tmp_path / "manifest.json",
        "rebuild_index": False,
        "encode": _vectors,
    }
    kwargs.update(overrides)
    return embed_chunks(chunks, **kwargs)


def test_hash_changes_when_text_changes():
    first = chunk_set_hash([_chunk("a#exit-load#0", "Exit load is 1%")])
    second = chunk_set_hash([_chunk("a#exit-load#0", "Exit load is 2%")])
    assert first != second


def test_second_run_skips_without_encoding_again(tmp_path: Path):
    chunks = [_chunk("a#exit-load#0", "Exit load is 1%")]
    calls = {"n": 0}

    def encode(texts):
        calls["n"] += 1
        return _vectors(texts)

    assert _run(tmp_path, chunks, encode=encode) == "wrote"
    created = json.loads((tmp_path / "manifest.json").read_text())["created_at"]
    assert _run(tmp_path, chunks, encode=encode) == "skip"
    assert json.loads((tmp_path / "manifest.json").read_text())["created_at"] == created
    assert calls["n"] == 1


def test_changed_text_rebuilds(tmp_path: Path):
    _run(tmp_path, [_chunk("a#exit-load#0", "Exit load is 1%")])
    assert _run(tmp_path, [_chunk("a#exit-load#0", "Exit load is 2%")]) == "wrote"


def test_different_model_rebuilds(tmp_path: Path):
    chunks = [_chunk("a#exit-load#0", "Exit load is 1%")]
    _run(tmp_path, chunks)
    assert _run(tmp_path, chunks, embedding_model="other-model") == "wrote"
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["embedding_model"] == "other-model"
    assert manifest["dimension"] == 384


def test_wrong_dimension_leaves_the_collection(tmp_path: Path):
    chunks = [_chunk("a#exit-load#0", "Exit load is 1%")]
    _run(tmp_path, chunks)

    def bad_encode(texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    with pytest.raises(SystemExit, match="expected shape"):
        _run(tmp_path, [_chunk("a#exit-load#0", "changed")], encode=bad_encode)
    assert _run(tmp_path, chunks) == "skip"
