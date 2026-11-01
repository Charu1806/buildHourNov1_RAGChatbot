"""Read and write the source allowlist."""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import urlparse

COLUMNS = [
    "id",
    "title",
    "url",
    "publisher",
    "scheme_or_topic",
    "fetched_at",
    "why_included",
]
MAX_ROWS = 25


@dataclass(frozen=True)
class SourceRow:
    id: str
    title: str
    url: str
    publisher: str
    scheme_or_topic: str
    fetched_at: str
    why_included: str

    def with_fetched_at(self, fetched_at: str) -> "SourceRow":
        return replace(self, fetched_at=fetched_at)


def read_sources(path: Path) -> list[SourceRow]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        missing = [column for column in COLUMNS if column not in fieldnames]
        if missing:
            raise ValueError(f"sources.csv missing columns: {', '.join(missing)}")
        rows: list[SourceRow] = []
        for raw in reader:
            if not any((raw.get(column) or "").strip() for column in COLUMNS):
                continue
            rows.append(
                SourceRow(
                    id=(raw.get("id") or "").strip(),
                    title=(raw.get("title") or "").strip(),
                    url=(raw.get("url") or "").strip(),
                    publisher=(raw.get("publisher") or "").strip().lower(),
                    scheme_or_topic=(raw.get("scheme_or_topic") or "").strip(),
                    fetched_at=(raw.get("fetched_at") or "").strip(),
                    why_included=(raw.get("why_included") or "").strip(),
                )
            )
    if len(rows) > MAX_ROWS:
        raise ValueError(f"sources.csv has {len(rows)} rows; cap is 25")
    if not rows:
        raise ValueError("sources.csv has no rows")
    _validate(rows)
    return rows


def write_sources(path: Path, rows: list[SourceRow]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "id": row.id,
                    "title": row.title,
                    "url": row.url,
                    "publisher": row.publisher,
                    "scheme_or_topic": row.scheme_or_topic,
                    "fetched_at": row.fetched_at,
                    "why_included": row.why_included,
                }
            )


def _validate(rows: list[SourceRow]) -> None:
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    for row in rows:
        if not row.id or not _safe_id(row.id):
            raise ValueError(f"invalid id: {row.id}")
        if row.id in seen_ids:
            raise ValueError(f"duplicate id: {row.id}")
        seen_ids.add(row.id)
        if row.url in seen_urls:
            raise ValueError(f"duplicate url: {row.url}")
        seen_urls.add(row.url)
        parsed = urlparse(row.url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError(f"url must be https: {row.url}")
        if not _host_matches(parsed.hostname, row.publisher):
            raise ValueError(f"publisher does not match url host: {row.id}")


def _safe_id(value: str) -> bool:
    return value.replace("-", "").isalnum() and value == value.lower() and "/" not in value and "." not in value


def _host_matches(host: str, publisher: str) -> bool:
    host = host.lower().rstrip(".")
    publisher = publisher.lower().rstrip(".")
    return host == publisher or host.endswith("." + publisher)
