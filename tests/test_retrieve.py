"""Phase 5 retrieval: query embedding, allowlist filter, ranking, manifest guard."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src import retrieve
from src.config import load_settings
from src.embed import embed_chunks
from src.retrieve import Hit, Retriever, best_similarity, passes_threshold
from src.sources import SourceRow, write_sources

COLLECTION = "hdfc_mf_facts"


def _vec(*head: float) -> list[float]:
    return [float(value) for value in head] + [0.0] * (384 - len(head))


def _chunk(chunk_id: str, text: str, url: str) -> dict:
    return {
        "chunk_id": chunk_id,
        "doc_id": chunk_id.split("#")[0],
        "text": text,
        "scheme": "HDFC Large Cap Fund Direct Growth",
        "section": "Expense ratio",
        "source_url": url,
        "fetched_at": "2026-11-01",
        "token_count": 10,
    }


def _write_sources(path: Path, urls: list[str]) -> None:
    rows = [
        SourceRow(
            id=f"source-{index}",
            title=f"Source {index}",
            url=url,
            publisher="groww.in",
            scheme_or_topic="HDFC Large Cap Fund Direct Growth",
            fetched_at="2026-11-01",
            why_included="seed",
        )
        for index, url in enumerate(urls)
    ]
    write_sources(path, rows)


def _settings(tmp_path: Path, urls: list[str], **overrides):
    sources_path = tmp_path / "sources.csv"
    _write_sources(sources_path, urls)
    base = load_settings(require_llm=False)
    return replace(
        base,
        root=tmp_path,
        chroma_path=tmp_path / "chroma",
        sources_path=sources_path,
        **overrides,
    )


def _store(tmp_path: Path, chunks: list[dict], vectors: dict[str, list[float]], model: str) -> None:
    embed_chunks(
        chunks,
        embedding_model=model,
        chroma_path=tmp_path / "chroma",
        collection_name=COLLECTION,
        manifest_path=tmp_path / "data" / "embeddings" / "manifest.json",
        rebuild_index=False,
        encode=lambda texts: [vectors[text] for text in texts],
    )


def _fixture(tmp_path: Path, **overrides):
    chunks = [
        _chunk("a#expense-ratio#0", "doc a", "https://groww.in/a"),
        _chunk("b#expense-ratio#0", "doc b", "https://groww.in/b"),
        _chunk("c#expense-ratio#0", "doc c", "https://groww.in/c"),
        _chunk("d#expense-ratio#0", "doc d", "https://example.com/d"),
    ]
    vectors = {
        "doc a": _vec(1.0),
        "doc b": _vec(0.8, 0.6),
        "doc c": _vec(0.0, 1.0),
        "doc d": _vec(0.0, 0.0, 1.0),
    }
    settings = _settings(
        tmp_path,
        ["https://groww.in/a", "https://groww.in/b", "https://groww.in/c"],
        **overrides,
    )
    _store(tmp_path, chunks, vectors, settings.embedding_model)
    return settings


def test_returns_allowlisted_hits_sorted_by_similarity(tmp_path: Path):
    settings = _fixture(tmp_path, top_k=4)
    hits = Retriever(settings, encoder=lambda _: _vec(1.0)).search(
        "What is the expense ratio of HDFC Large Cap?"
    )

    assert [hit.chunk_id for hit in hits] == [
        "a#expense-ratio#0",
        "b#expense-ratio#0",
        "c#expense-ratio#0",
    ]
    assert hits[0].similarity == pytest.approx(1.0, abs=1e-6)
    assert hits[1].similarity == pytest.approx(0.8, abs=1e-5)
    assert hits[2].similarity == pytest.approx(0.0, abs=1e-6)
    assert all(hit.source_url != "https://example.com/d" for hit in hits)
    assert hits[0].scheme == "HDFC Large Cap Fund Direct Growth"
    assert hits[0].section == "Expense ratio"
    assert hits[0].fetched_at == "2026-11-01"


def test_honours_top_k(tmp_path: Path):
    settings = _fixture(tmp_path, top_k=2)
    hits = Retriever(settings, encoder=lambda _: _vec(1.0)).search("expense ratio")

    assert len(hits) == 2
    assert [hit.chunk_id for hit in hits] == ["a#expense-ratio#0", "b#expense-ratio#0"]


def test_question_is_not_prefixed(tmp_path: Path):
    settings = _fixture(tmp_path, top_k=1)
    seen: list[str] = []

    def encoder(text: str) -> list[float]:
        seen.append(text)
        return _vec(1.0)

    Retriever(settings, encoder=encoder).search("  What is the exit load?  ")
    assert seen == ["What is the exit load?"]


def test_empty_question_does_not_encode_or_query(tmp_path: Path):
    settings = _fixture(tmp_path)

    def encoder(_: str) -> list[float]:
        raise AssertionError("encoder must not run for an empty question")

    retriever = Retriever(settings, encoder=encoder)
    assert retriever.search("   ") == []


def test_snippet_is_capped_at_400_characters(tmp_path: Path):
    hit = Hit(
        chunk_id="a#x#0",
        doc_id="a",
        text="x" * 900,
        scheme="S",
        section="Sec",
        source_url="https://groww.in/a",
        fetched_at="2026-11-01",
        similarity=0.9,
    )
    assert len(hit.snippet) == 400
    assert hit.to_trace()["snippet"] == "x" * 400


def test_threshold_helpers(tmp_path: Path):
    settings = _fixture(tmp_path, top_k=4, score_threshold=0.35)
    hits = Retriever(settings, encoder=lambda _: _vec(1.0)).search("expense ratio")

    assert best_similarity(hits) == pytest.approx(1.0, abs=1e-6)
    assert passes_threshold(hits, 0.35) is True
    assert passes_threshold([], 0.35) is False
    assert best_similarity([]) == 0.0


def test_missing_manifest_exits_with_rebuild_hint(tmp_path: Path):
    settings = _settings(tmp_path, ["https://groww.in/a"])

    with pytest.raises(SystemExit, match="run python -m src.embed"):
        Retriever(settings, encoder=lambda _: _vec(1.0))


def test_manifest_model_mismatch_exits_with_rebuild_hint(tmp_path: Path):
    settings = _fixture(tmp_path)
    changed = replace(settings, embedding_model="some/other-model")

    with pytest.raises(SystemExit, match="run python -m src.embed"):
        Retriever(changed, encoder=lambda _: _vec(1.0))


def test_missing_collection_exits_with_rebuild_hint(tmp_path: Path):
    settings = _settings(tmp_path, ["https://groww.in/a"])
    manifest_path = tmp_path / "data" / "embeddings" / "manifest.json"
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "embedding_model": settings.embedding_model,
                "dimension": 384,
                "chunk_count": 0,
                "chunk_set_hash": "",
                "chroma_collection": COLLECTION,
                "created_at": "",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="run python -m src.embed"):
        Retriever(settings, encoder=lambda _: _vec(1.0))


def test_cli_prints_hits_and_verdict(tmp_path: Path, monkeypatch, capsys):
    settings = replace(_settings(tmp_path, ["https://groww.in/a"]), score_threshold=0.35)
    hit = Hit(
        chunk_id="a#expense-ratio#0",
        doc_id="a",
        text="The expense ratio is 0.75%.",
        scheme="HDFC Large Cap Fund Direct Growth",
        section="Expense ratio",
        source_url="https://groww.in/a",
        fetched_at="2026-11-01",
        similarity=0.91,
    )

    class FakeRetriever:
        def __init__(self, _settings):
            self.settings = _settings

        def search(self, question):
            assert question == "expense ratio"
            return [hit]

    monkeypatch.setattr(retrieve, "load_settings", lambda require_llm=False: settings)
    monkeypatch.setattr(retrieve, "Retriever", FakeRetriever)

    assert retrieve.main(["expense", "ratio"]) == 0

    output = capsys.readouterr().out
    assert "similarity=0.9100 a#expense-ratio#0" in output
    assert "source=https://groww.in/a" in output
    assert "best=0.9100 threshold=0.35 -> pass" in output


def test_cli_requires_a_question(monkeypatch):
    monkeypatch.setattr(retrieve, "load_settings", lambda require_llm=False: None)
    with pytest.raises(SystemExit, match="usage: python -m src.retrieve"):
        retrieve.main([])
