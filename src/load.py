"""Turn scraped pages into cleaned documents. Does not fetch the network."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from bs4 import BeautifulSoup
from pypdf import PdfReader

from src.config import load_settings
from src.sources import SourceRow, read_sources

INLINE_TAGS = {
    "a",
    "abbr",
    "b",
    "br",
    "em",
    "font",
    "i",
    "label",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "u",
}
MIN_TEXT = 200


def main() -> None:
    settings = load_settings(require_llm=False)
    try:
        rows = read_sources(settings.sources_path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    scraped_dir = settings.root / "data" / "scraped"
    manifest_path = scraped_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("scrape manifest missing; run python -m src.scrape")
    scraped = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw_dir = settings.root / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    by_id = {row.id: row for row in rows}
    records = load_documents(scraped.get("documents") or [], by_id, scraped_dir, raw_dir)
    _write_manifest(raw_dir / "manifest.json", records)
    ok = sum(record["status"] == "ok" for record in records)
    thin = sum(record["status"] == "thin" for record in records)
    error = sum(record["status"] == "error" for record in records)
    print(f"wrote data/raw/manifest.json documents={len(records)} ok={ok} thin={thin} error={error}")
    if ok == 0:
        raise SystemExit(1)


def load_documents(
    scraped_docs: list[dict],
    sources_by_id: dict[str, SourceRow],
    scraped_dir: Path,
    raw_dir: Path,
) -> list[dict]:
    records: list[dict] = []
    kept: set[str] = set()
    for item in scraped_docs:
        record = _load_one(item, sources_by_id.get(item.get("id", "")), scraped_dir, raw_dir)
        records.append(record)
        if record["status"] == "ok":
            kept.add(record["id"])
        elif record["status"] == "thin":
            print(f"thin {record['id']}", file=sys.stderr)
        else:
            print(f"error {record['id']} {record['reason']}", file=sys.stderr)
    for path in raw_dir.glob("*.json"):
        if path.name == "manifest.json":
            continue
        if path.stem not in kept:
            path.unlink()
    return records


def html_to_sections(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup.find_all(["script", "style", "noscript", "nav", "footer", "iframe", "svg"]):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if not getattr(tag, "attrs", None):
            continue
        marker = " ".join(
            [str(tag.get("id") or "")] + [str(part) for part in (tag.get("class") or [])]
        ).lower()
        if any(word in marker for word in ("cookie", "banner", "consent")):
            tag.decompose()
    collector = _Collector()
    root = soup.body or soup
    _walk(root, collector)
    return collector.finish()


def pdf_to_sections(data: bytes) -> list[dict]:
    reader = PdfReader(BytesIO(data))
    page_texts: list[str] = []
    for page in reader.pages:
        raw = page.extract_text() or ""
        lines = [_collapse(line) for line in raw.splitlines()]
        page_texts.append("\n".join(line for line in lines if line))
    return _group_pages(page_texts, _outline_starts(reader))


def _load_one(
    item: dict,
    source: SourceRow | None,
    scraped_dir: Path,
    raw_dir: Path,
) -> dict:
    doc_id = str(item.get("id") or "")
    url = str(item.get("url") or (source.url if source else ""))
    if item.get("status") != "ok":
        _delete_raw(raw_dir, doc_id)
        return _record(doc_id, url, "error", "", str(item.get("reason") or "scrape-error"))
    filename = Path(str(item.get("path") or "")).name
    if filename not in {f"{doc_id}.html", f"{doc_id}.pdf"}:
        _delete_raw(raw_dir, doc_id)
        return _record(doc_id, url, "error", "", "missing-file")
    body_path = scraped_dir / filename
    if not body_path.is_file():
        _delete_raw(raw_dir, doc_id)
        return _record(doc_id, url, "error", "", "missing-file")
    try:
        if filename.endswith(".pdf") or item.get("source_type") == "pdf":
            sections = pdf_to_sections(body_path.read_bytes())
            source_type = "pdf"
        else:
            sections = html_to_sections(body_path.read_text(encoding="utf-8", errors="replace"))
            source_type = "html"
    except Exception:
        _delete_raw(raw_dir, doc_id)
        return _record(doc_id, url, "error", "", "parse-error")
    text = _render_text(sections)
    if len(text) < MIN_TEXT:
        _delete_raw(raw_dir, doc_id)
        return _record(doc_id, url, "thin", "", "thin")
    document = {
        "id": doc_id,
        "url": url,
        "title": source.title if source else "",
        "publisher": source.publisher if source else "",
        "scheme_or_topic": source.scheme_or_topic if source else "",
        "fetched_at": str(item.get("fetched_at") or (source.fetched_at if source else "")),
        "source_type": source_type,
        "text": text,
        "sections": sections,
        "content_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }
    (raw_dir / f"{doc_id}.json").write_text(
        json.dumps(document, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return _record(doc_id, url, "ok", f"{doc_id}.json", "", document["content_hash"])


def _walk(node, collector: "_Collector") -> None:
    name = getattr(node, "name", None)
    if name is None:
        return
    if name in {"h1", "h2", "h3"}:
        collector.heading(node.get_text(" ", strip=True))
        return
    if name == "table":
        collector.lines(_table_lines(node))
        return
    children = [child for child in node.children if getattr(child, "name", None)]
    if children and any(child.name not in INLINE_TAGS for child in children):
        for child in node.children:
            if isinstance(child, str):
                collector.line(child)
            elif getattr(child, "name", None):
                _walk(child, collector)
        return
    collector.line(node.get_text(" ", strip=True))


def _table_lines(table) -> list[str]:
    lines: list[str] = []
    for row in table.find_all("tr"):
        cells = []
        for cell in row.find_all(["th", "td"]):
            value = _collapse(cell.get_text(" ", strip=True))
            if value:
                cells.append(value)
        if cells:
            lines.append(": ".join(cells))
    return lines


def _outline_starts(reader: PdfReader) -> list[tuple[str, int]]:
    try:
        outline = reader.outline
    except Exception:
        return []
    found: list[tuple[str, int]] = []

    def walk(nodes) -> None:
        for node in nodes or []:
            if isinstance(node, list):
                walk(node)
                continue
            title = getattr(node, "title", None)
            if not title:
                continue
            try:
                page_no = reader.get_destination_page_number(node)
            except Exception:
                continue
            if isinstance(page_no, int):
                found.append((_collapse(str(title)), page_no))

    walk(outline)
    return found


def _group_pages(page_texts: list[str], outline: list[tuple[str, int]]) -> list[dict]:
    if not outline:
        return [
            {"heading": f"Page {index}", "text": text}
            for index, text in enumerate(page_texts, start=1)
            if text
        ]
    starts: dict[int, str] = {}
    for title, page_no in outline:
        starts.setdefault(page_no, title)
    sections: list[dict] = []
    current = ""
    for index, text in enumerate(page_texts):
        if index in starts:
            current = starts[index]
        heading = current or f"Page {index + 1}"
        if not text:
            continue
        if sections and sections[-1]["heading"] == heading:
            sections[-1]["text"] = sections[-1]["text"] + "\n" + text
        else:
            sections.append({"heading": heading, "text": text})
    return sections


def _render_text(sections: list[dict]) -> str:
    return "\n\n".join(f"{section['heading']}\n{section['text']}" for section in sections)


def _collapse(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split())


class _Collector:
    def __init__(self) -> None:
        self.sections: list[dict] = []
        self._heading = "Article"
        self._parts: list[str] = []

    def heading(self, text: str) -> None:
        self._flush()
        self._heading = _collapse(text) or "Article"

    def line(self, text: str) -> None:
        cleaned = _collapse(text)
        if cleaned:
            self._parts.append(cleaned)

    def lines(self, rows: list[str]) -> None:
        for row in rows:
            self.line(row)

    def finish(self) -> list[dict]:
        self._flush()
        unique: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for section in self.sections:
            key = (section["heading"], section["text"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(section)
        return unique

    def _flush(self) -> None:
        if not self._parts:
            return
        self.sections.append({"heading": self._heading, "text": "\n".join(self._parts)})
        self._parts = []


def _record(doc_id: str, url: str, status: str, path: str, reason: str, content_hash: str = "") -> dict:
    return {
        "id": doc_id,
        "path": path,
        "url": url,
        "status": status,
        "content_hash": content_hash,
        "reason": reason,
    }


def _delete_raw(raw_dir: Path, doc_id: str) -> None:
    path = raw_dir / f"{doc_id}.json"
    if path.is_file():
        path.unlink()


def _write_manifest(path: Path, records: list[dict]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "documents": records,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
