"""Split loaded documents into section-prefixed chunks."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from src.config import Settings, load_settings

GENERIC_HEADINGS = {"article", "overview", "fund details"}
FACT_RULES = (
    ("expense ratio", "Expense ratio"),
    ("exit load", "Exit load"),
    ("minimum sip", "Minimum SIP"),
    ("min. for sip", "Minimum SIP"),
    ("min. sip", "Minimum SIP"),
    ("min sip", "Minimum SIP"),
    ("lock-in", "Lock-in"),
    ("lock in", "Lock-in"),
    ("riskometer", "Riskometer"),
    ("benchmark", "Benchmark"),
)
NOISE_PHRASES = ("cookie", "download the app", "open demat", "scan the qr")
MARKET_RISK = "mutual fund investments are subject to market risks"
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def main() -> None:
    settings = load_settings(require_llm=False)
    raw_dir = settings.root / "data" / "raw"
    manifest_path = raw_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("raw manifest missing; run python -m src.load")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    documents = _read_ok_documents(manifest.get("documents") or [], raw_dir)
    tokenizer = MiniLMTokenizer(settings.embedding_model)
    chunks, skipped = chunk_documents(
        documents,
        settings.chunk_max_tokens,
        settings.chunk_overlap_tokens,
        tokenizer,
    )
    stats = build_stats(chunks, skipped, settings)
    if stats["chunk_count"] == 0 or stats["max_tokens"] > settings.chunk_max_tokens:
        _write_outputs(settings, chunks, stats)
        raise SystemExit(1)
    _write_outputs(settings, chunks, stats)
    print(
        f"wrote data/chunks/chunks.jsonl chunks={stats['chunk_count']} "
        f"skipped_docs={stats['skipped_docs']}"
    )


def chunk_documents(
    documents: list[dict],
    max_tokens: int,
    overlap_tokens: int,
    tokenizer,
) -> tuple[list[dict], int]:
    chunks: list[dict] = []
    skipped = 0
    for document in documents:
        produced = chunk_document(document, max_tokens, overlap_tokens, tokenizer)
        if produced:
            chunks.extend(produced)
        else:
            skipped += 1
    return chunks, skipped


def chunk_document(document: dict, max_tokens: int, overlap_tokens: int, tokenizer) -> list[dict]:
    doc_id = str(document["id"])
    scheme = str(document.get("scheme_or_topic") or "")
    source_url = str(document.get("url") or "")
    fetched_at = str(document.get("fetched_at") or "")
    counters: dict[str, int] = {}
    chunks: list[dict] = []
    for section in prepare_sections(document.get("sections") or []):
        heading = section["heading"]
        body = section["text"]
        prefix = (
            f"AMC: HDFC Mutual Fund | Scheme: {scheme} | Section: {heading} | Source: {source_url}"
        )
        budget = max_tokens - token_count(prefix, tokenizer) - 1
        if budget < 40:
            raise SystemExit(f"prefix too long for {doc_id}")
        if token_count(prefix + "\n" + body, tokenizer) <= max_tokens:
            bodies = [body]
        else:
            bodies = pack_bodies(body, budget, overlap_tokens, tokenizer)
        slug = _slug(heading)
        for part in bodies:
            part = part.strip()
            if not part or _drop_line(part):
                continue
            part = _fit(prefix, part, max_tokens, tokenizer)
            if not part:
                continue
            number = counters.get(slug, 0)
            counters[slug] = number + 1
            text = prefix + "\n" + part
            chunks.append(
                {
                    "chunk_id": f"{doc_id}#{slug}#{number}",
                    "doc_id": doc_id,
                    "text": text,
                    "scheme": scheme,
                    "section": heading,
                    "source_url": source_url,
                    "fetched_at": fetched_at,
                    "token_count": token_count(text, tokenizer),
                }
            )
    return chunks


def prepare_sections(sections: list[dict]) -> list[dict]:
    prepared: list[dict] = []
    for section in sections:
        heading = str(section.get("heading") or "Article")
        lines = [_clean_line(line) for line in str(section.get("text") or "").splitlines()]
        lines = [line for line in lines if line and not _drop_line(line)]
        if heading.strip().lower() not in GENERIC_HEADINGS:
            body = "\n".join(lines).strip()
            if body:
                prepared.append({"heading": heading, "text": body})
            continue
        buffer: list[str] = []

        def flush_buffer() -> None:
            body = "\n".join(buffer).strip()
            buffer.clear()
            if body:
                prepared.append({"heading": heading, "text": body})

        for line in lines:
            fact_heading = _fact_heading(line)
            if fact_heading and len(line) <= 240:
                flush_buffer()
                prepared.append({"heading": fact_heading, "text": line})
            else:
                buffer.append(line)
        flush_buffer()
    return prepared


def pack_bodies(body: str, budget: int, overlap_tokens: int, tokenizer) -> list[str]:
    pieces = break_down(body, budget, tokenizer)
    packed: list[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else current + "\n" + piece
        if token_count(candidate, tokenizer) <= budget:
            current = candidate
            continue
        if current:
            packed.append(current)
            current = _with_overlap(current, piece, budget, overlap_tokens, tokenizer)
        else:
            current = piece
    if current:
        packed.append(current)
    return packed


def break_down(text: str, budget: int, tokenizer) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if token_count(text, tokenizer) <= budget:
        return [text]
    if "\n" in text:
        blocks = re.split(r"\n\s*\n", text) if "\n\n" in text else text.splitlines()
        blocks = [block.strip() for block in blocks if block.strip()]
        if len(blocks) > 1:
            pieces: list[str] = []
            for block in blocks:
                pieces.extend(break_down(block, budget, tokenizer))
            return pieces
    sentences = [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]
    if len(sentences) > 1:
        pieces = []
        for sentence in sentences:
            pieces.extend(break_down(sentence, budget, tokenizer))
        return pieces
    return _windows(text, budget, tokenizer)


def build_stats(chunks: list[dict], skipped: int, settings: Settings) -> dict:
    counts = [chunk["token_count"] for chunk in chunks]
    per_scheme: dict[str, int] = {}
    for chunk in chunks:
        per_scheme[chunk["scheme"]] = per_scheme.get(chunk["scheme"], 0) + 1
    return {
        "strategy": settings.chunk_strategy,
        "chunk_count": len(chunks),
        "skipped_docs": skipped,
        "per_scheme": per_scheme,
        "min_tokens": min(counts) if counts else 0,
        "median_tokens": _median(counts),
        "max_tokens": max(counts) if counts else 0,
    }


def token_count(text: str, tokenizer) -> int:
    return len(tokenizer.encode(text, add_special_tokens=False))


class MiniLMTokenizer:
    def __init__(self, model_id: str) -> None:
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        path = hf_hub_download(repo_id=model_id, filename="tokenizer.json")
        self._tokenizer = Tokenizer.from_file(path)
        self._tokenizer.no_padding()
        self._tokenizer.no_truncation()

    def encode(self, text: str, add_special_tokens: bool = False) -> list[int]:
        try:
            encoding = self._tokenizer.encode(text, add_special_tokens=add_special_tokens)
        except TypeError:
            encoding = self._tokenizer.encode(text)
        return list(encoding.ids)

    def decode(self, token_ids: list[int]) -> str:
        return self._tokenizer.decode(token_ids, skip_special_tokens=True)


def _with_overlap(previous: str, piece: str, budget: int, overlap_tokens: int, tokenizer) -> str:
    token_ids = tokenizer.encode(previous, add_special_tokens=False)
    take = min(overlap_tokens, len(token_ids))
    while take > 0:
        overlap = tokenizer.decode(token_ids[-take:]).strip()
        candidate = f"{overlap}\n{piece}".strip() if overlap else piece
        if overlap and token_count(candidate, tokenizer) <= budget:
            return candidate
        take -= 1
    return piece


def _windows(text: str, budget: int, tokenizer) -> list[str]:
    token_ids = tokenizer.encode(text, add_special_tokens=False)
    pieces: list[str] = []
    start = 0
    while start < len(token_ids):
        end = min(len(token_ids), start + budget)
        fitted = ""
        fitted_end = start
        while end > start:
            piece = tokenizer.decode(token_ids[start:end]).strip()
            if piece and token_count(piece, tokenizer) <= budget:
                fitted = piece
                fitted_end = end
                break
            end -= 1
        if not fitted:
            start += 1
            continue
        pieces.append(fitted)
        start = fitted_end
    return pieces


def _fit(prefix: str, body: str, max_tokens: int, tokenizer) -> str:
    while body and token_count(prefix + "\n" + body, tokenizer) > max_tokens:
        token_ids = tokenizer.encode(body, add_special_tokens=False)
        if len(token_ids) <= 1:
            return ""
        body = tokenizer.decode(token_ids[:-1]).strip()
    return body


def _fact_heading(line: str) -> str:
    lowered = line.lower()
    for label, heading in FACT_RULES:
        if label in lowered:
            return heading
    return ""


def _drop_line(line: str) -> bool:
    lowered = line.lower()
    if any(phrase in lowered for phrase in NOISE_PHRASES):
        return True
    if MARKET_RISK in lowered and not _fact_heading(line):
        return True
    return False


def _clean_line(line: str) -> str:
    return " ".join(line.replace("\xa0", " ").split())


def _slug(heading: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
    return slug or "section"


def _median(values: list[int]):
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _read_ok_documents(entries: list[dict], raw_dir: Path) -> list[dict]:
    documents = []
    for entry in entries:
        if entry.get("status") != "ok":
            continue
        path = raw_dir / str(entry.get("path") or "")
        if not path.is_file():
            print(f"error {entry.get('id')} missing-raw", file=sys.stderr)
            continue
        documents.append(json.loads(path.read_text(encoding="utf-8")))
    return documents


def _write_outputs(settings: Settings, chunks: list[dict], stats: dict) -> None:
    chunk_dir = settings.root / "data" / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(chunk, ensure_ascii=False) for chunk in chunks]
    (chunk_dir / "chunks.jsonl").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    (chunk_dir / "stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
