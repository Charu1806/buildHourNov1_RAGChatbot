"""Fetch allowlisted pages and save the response bytes."""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

from src.config import load_settings
from src.sources import SourceRow, read_sources, write_sources

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
RETRY_STATUSES = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class ScrapeRecord:
    id: str
    url: str
    status: str
    source_type: str
    path: str
    fetched_at: str
    reason: str


def main() -> None:
    settings = load_settings(require_llm=False)
    try:
        rows = read_sources(settings.sources_path)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    scraped_dir = settings.root / "data" / "scraped"
    scraped_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(
        timeout=20.0,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-IN,en;q=0.9",
        },
    ) as client:
        records, updated = scrape_rows(
            rows,
            client,
            settings.allowed_hosts,
            scraped_dir,
        )
    _write_manifest(scraped_dir / "manifest.json", records)
    write_sources(settings.sources_path, updated)
    ok = sum(record.status == "ok" for record in records)
    error = len(records) - ok
    print(f"wrote data/scraped/manifest.json documents={len(records)} ok={ok} error={error}")
    if ok == 0:
        raise SystemExit(1)


def scrape_rows(
    rows: list[SourceRow],
    client: httpx.Client,
    allowed_hosts: tuple[str, ...],
    scraped_dir: Path,
    sleep_s: float = 0.5,
    retry_wait: float = 2.0,
) -> tuple[list[ScrapeRecord], list[SourceRow]]:
    records: list[ScrapeRecord] = []
    updated: list[SourceRow] = []
    for row in rows:
        if sleep_s:
            time.sleep(sleep_s)
        record = _scrape_one(row, client, allowed_hosts, scraped_dir, retry_wait)
        records.append(record)
        if record.status == "ok":
            updated.append(row.with_fetched_at(record.fetched_at))
        else:
            updated.append(row)
            print(f"error {row.id} {record.reason}", file=sys.stderr)
    return records, updated


def _scrape_one(
    row: SourceRow,
    client: httpx.Client,
    allowed_hosts: tuple[str, ...],
    scraped_dir: Path,
    retry_wait: float,
) -> ScrapeRecord:
    requested_host = urlparse(row.url).hostname or ""
    if not _host_allowed(requested_host, allowed_hosts):
        _clear_body(scraped_dir, row.id)
        return _error(row, "off-host")

    try:
        response = _get(client, row.url, retry_wait)
    except httpx.TimeoutException:
        _clear_body(scraped_dir, row.id)
        return _error(row, "timeout")
    except httpx.HTTPError:
        _clear_body(scraped_dir, row.id)
        return _error(row, "http-error")

    if response.status_code >= 400:
        _clear_body(scraped_dir, row.id)
        return _error(row, f"http-{response.status_code}")

    final_host = response.url.host or ""
    if not _host_allowed(final_host, allowed_hosts):
        _clear_body(scraped_dir, row.id)
        return _error(row, "off-host")

    source_type = _source_type(str(response.url), response.headers.get("content-type", ""))
    filename = f"{row.id}.{source_type}"
    _clear_body(scraped_dir, row.id)
    (scraped_dir / filename).write_bytes(response.content)
    return ScrapeRecord(
        id=row.id,
        url=row.url,
        status="ok",
        source_type=source_type,
        path=filename,
        fetched_at=_today(),
        reason="",
    )


def _get(client: httpx.Client, url: str, retry_wait: float) -> httpx.Response:
    response = client.get(url)
    if response.status_code in RETRY_STATUSES:
        if retry_wait:
            time.sleep(retry_wait)
        response = client.get(url)
    return response


def _source_type(url: str, content_type: str) -> str:
    if "pdf" in content_type.lower() or urlparse(url).path.lower().endswith(".pdf"):
        return "pdf"
    return "html"


def _host_allowed(host: str, allowed_hosts: tuple[str, ...]) -> bool:
    host = host.lower().rstrip(".")
    for allowed in allowed_hosts:
        allowed = allowed.lower().rstrip(".")
        if host == allowed or host.endswith("." + allowed):
            return True
    return False


def _clear_body(directory: Path, doc_id: str) -> None:
    for ext in (".html", ".pdf"):
        path = directory / f"{doc_id}{ext}"
        if path.exists():
            path.unlink()


def _error(row: SourceRow, reason: str) -> ScrapeRecord:
    return ScrapeRecord(
        id=row.id,
        url=row.url,
        status="error",
        source_type="",
        path="",
        fetched_at="",
        reason=reason,
    )


def _write_manifest(path: Path, records: list[ScrapeRecord]) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "documents": [asdict(record) for record in records],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


if __name__ == "__main__":
    main()
