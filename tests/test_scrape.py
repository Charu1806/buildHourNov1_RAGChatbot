import csv
from pathlib import Path

import httpx
import pytest

from src.scrape import scrape_rows
from src.sources import SourceRow, read_sources, write_sources

ALLOWED = ("groww.in", "hdfcfund.com", "sebi.gov.in", "amfiindia.com")


def _row(doc_id: str = "hdfc-amc", url: str = "https://groww.in/mutual-funds/amc/hdfc-mutual-funds") -> SourceRow:
    return SourceRow(
        id=doc_id,
        title="HDFC Mutual Fund",
        url=url,
        publisher="groww.in",
        scheme_or_topic="HDFC Mutual Fund",
        fetched_at="",
        why_included="seed",
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_real_allowlist_has_five_seeds():
    rows = read_sources(Path("sources.csv"))
    seeds = [row.id for row in rows if row.why_included == "seed"]
    assert seeds == [
        "hdfc-amc",
        "hdfc-large-cap",
        "hdfc-flexi-cap",
        "hdfc-elss",
        "hdfc-mid-cap",
    ]
    assert any(row.why_included == "education" for row in rows)


def test_cap_duplicate_and_http_url_are_rejected(tmp_path: Path):
    path = tmp_path / "sources.csv"
    header = "id,title,url,publisher,scheme_or_topic,fetched_at,why_included\n"
    body = "".join(
        f"row-{index},Title,https://groww.in/p/{index},groww.in,Scheme,,seed\n"
        for index in range(26)
    )
    path.write_text(header + body, encoding="utf-8")
    with pytest.raises(ValueError, match="cap is 25"):
        read_sources(path)

    path.write_text(
        header
        + "hdfc-amc,Title,https://groww.in/a,groww.in,Scheme,,seed\n"
        + "hdfc-amc,Title,https://groww.in/b,groww.in,Scheme,,seed\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate id"):
        read_sources(path)

    path.write_text(
        header + "hdfc-amc,Title,http://groww.in/a,groww.in,Scheme,,seed\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="url must be https"):
        read_sources(path)


def test_saves_html_bytes_and_updates_fetched_at(tmp_path: Path):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=b"<html><a href='https://groww.in/other'>x</a></html>")

    csv_path = tmp_path / "sources.csv"
    write_sources(csv_path, [_row()])
    with _client(handler) as client:
        records, updated = scrape_rows(
            read_sources(csv_path),
            client,
            ALLOWED,
            tmp_path,
            sleep_s=0,
            retry_wait=0,
        )
    write_sources(csv_path, updated)

    assert records[0].status == "ok"
    assert records[0].source_type == "html"
    assert records[0].path == "hdfc-amc.html"
    assert (tmp_path / "hdfc-amc.html").read_bytes().startswith(b"<html>")
    assert seen == ["https://groww.in/mutual-funds/amc/hdfc-mutual-funds"]
    with csv_path.open(encoding="utf-8", newline="") as handle:
        saved = list(csv.DictReader(handle))
    assert saved[0]["fetched_at"] == records[0].fetched_at


def test_pdf_content_type_uses_pdf_extension(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"})

    with _client(handler) as client:
        records, _updated = scrape_rows([_row()], client, ALLOWED, tmp_path, sleep_s=0, retry_wait=0)
    assert records[0].source_type == "pdf"
    assert (tmp_path / "hdfc-amc.pdf").read_bytes() == b"%PDF-1.4"


def test_off_host_redirect_writes_no_body(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "groww.in":
            return httpx.Response(302, headers={"location": "https://evil.example/page"})
        return httpx.Response(200, content=b"secret")

    (tmp_path / "hdfc-amc.html").write_bytes(b"stale")
    with _client(handler) as client:
        records, updated = scrape_rows([_row()], client, ALLOWED, tmp_path, sleep_s=0, retry_wait=0)
    assert records[0].status == "error"
    assert records[0].reason == "off-host"
    assert records[0].path == ""
    assert not (tmp_path / "hdfc-amc.html").exists()
    assert updated[0].fetched_at == ""


def test_retries_503_once(tmp_path: Path):
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, content=b"busy")
        return httpx.Response(200, content=b"<html>ok</html>")

    with _client(handler) as client:
        records, _updated = scrape_rows([_row()], client, ALLOWED, tmp_path, sleep_s=0, retry_wait=0)
    assert calls["n"] == 2
    assert records[0].status == "ok"


def test_http_404_writes_no_body(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, content=b"missing")

    with _client(handler) as client:
        records, _updated = scrape_rows([_row()], client, ALLOWED, tmp_path, sleep_s=0, retry_wait=0)
    assert records[0].status == "error"
    assert records[0].reason == "http-404"
    assert list(tmp_path.glob("hdfc-amc.*")) == []


def test_disallowed_host_is_not_requested(tmp_path: Path):
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("request should not be sent")

    row = _row(url="https://evil.example/page")
    row = SourceRow(
        id=row.id,
        title=row.title,
        url=row.url,
        publisher="evil.example",
        scheme_or_topic=row.scheme_or_topic,
        fetched_at="",
        why_included="seed",
    )
    with _client(handler) as client:
        records, _updated = scrape_rows([row], client, ALLOWED, tmp_path, sleep_s=0, retry_wait=0)
    assert records[0].reason == "off-host"
