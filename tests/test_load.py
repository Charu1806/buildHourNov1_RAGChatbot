import json
from pathlib import Path

from src.load import html_to_sections, load_documents, pdf_to_sections
from src.sources import SourceRow

HTML = """
<html><body>
<script>SECRET_SCRIPT_FACT 12345 expense ratio 9.99%</script>
<nav>Home link</nav>
<div class="cookie-banner">Accept cookies please</div>
<h1>HDFC ELSS Tax Saver Fund Direct Plan Growth</h1>
<div>ELSS • 3Y Lock-in</div>
<div><span>Expense ratio</span><span>1.20%</span></div>
<h2>Exit load</h2>
<p>Exit load is nil after one year for this direct plan scheme.</p>
<table>
  <tr><th>Min. for SIP</th><td>₹500</td><td></td></tr>
</table>
<h3>Fund benchmark</h3>
<div>NIFTY 500 Total Return Index is the published benchmark for this scheme.</div>
</body></html>
"""


def _source() -> SourceRow:
    return SourceRow(
        id="hdfc-elss",
        title="HDFC ELSS Tax Saver Fund Direct Plan Growth",
        url="https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
        publisher="groww.in",
        scheme_or_topic="HDFC ELSS Tax Saver Fund Direct Plan Growth",
        fetched_at="2026-11-01",
        why_included="seed",
    )


def test_html_sections_keep_facts_and_drop_chrome():
    sections = {section["heading"]: section["text"] for section in html_to_sections(HTML)}
    joined = "\n".join(sections.values())
    assert "SECRET_SCRIPT_FACT" not in joined
    assert "Accept cookies" not in joined
    assert "Home link" not in joined
    assert "Expense ratio 1.20%" in sections["HDFC ELSS Tax Saver Fund Direct Plan Growth"]
    assert "ELSS • 3Y Lock-in" in sections["HDFC ELSS Tax Saver Fund Direct Plan Growth"]
    assert "nil after one year" in sections["Exit load"]
    assert "Min. for SIP: ₹500" in sections["Exit load"]
    assert "NIFTY 500 Total Return Index" in sections["Fund benchmark"]


def test_thin_page_writes_no_body_and_removes_stale_file(tmp_path: Path):
    scraped = tmp_path / "scraped"
    raw = tmp_path / "raw"
    scraped.mkdir()
    raw.mkdir()
    (scraped / "hdfc-elss.html").write_text("<html><body><p>short</p></body></html>", encoding="utf-8")
    (raw / "hdfc-elss.json").write_text("{}", encoding="utf-8")
    records = load_documents(
        [
            {
                "id": "hdfc-elss",
                "url": _source().url,
                "status": "ok",
                "source_type": "html",
                "path": "hdfc-elss.html",
                "fetched_at": "2026-11-01",
                "reason": "",
            }
        ],
        {"hdfc-elss": _source()},
        scraped,
        raw,
    )
    assert records[0]["status"] == "thin"
    assert records[0]["path"] == ""
    assert not (raw / "hdfc-elss.json").exists()


def test_scrape_error_is_recorded_and_html_success_is_written(tmp_path: Path):
    scraped = tmp_path / "scraped"
    raw = tmp_path / "raw"
    scraped.mkdir()
    raw.mkdir()
    (scraped / "hdfc-elss.html").write_text(HTML, encoding="utf-8")
    records = load_documents(
        [
            {
                "id": "hdfc-elss",
                "url": _source().url,
                "status": "ok",
                "source_type": "html",
                "path": "hdfc-elss.html",
                "fetched_at": "2026-11-01",
                "reason": "",
            },
            {
                "id": "hdfc-amc",
                "url": "https://groww.in/mutual-funds/amc/hdfc-mutual-funds",
                "status": "error",
                "source_type": "",
                "path": "",
                "fetched_at": "",
                "reason": "http-404",
            },
        ],
        {"hdfc-elss": _source()},
        scraped,
        raw,
    )
    assert records[0]["status"] == "ok"
    assert records[0]["path"] == "hdfc-elss.json"
    assert records[1]["status"] == "error"
    assert records[1]["reason"] == "http-404"
    document = json.loads((raw / "hdfc-elss.json").read_text(encoding="utf-8"))
    assert document["scheme_or_topic"] == "HDFC ELSS Tax Saver Fund Direct Plan Growth"
    assert document["fetched_at"] == "2026-11-01"
    assert document["source_type"] == "html"
    assert len(document["text"]) >= 200
    assert document["content_hash"]
    assert not (raw / "hdfc-amc.json").exists()


def test_pdf_without_outline_uses_page_headings():
    sections = pdf_to_sections(_pdf("Expense ratio is 1.20 percent on the HDFC ELSS direct plan page."))
    assert sections[0]["heading"] == "Page 1"
    assert "1.20 percent" in sections[0]["text"]


def _pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 50 100 Td ({escaped}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Count 1 /Kids [3 0 R] >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 200] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{index} 0 obj\n".encode())
        out.extend(obj)
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)
