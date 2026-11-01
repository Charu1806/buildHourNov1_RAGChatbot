from src.chunk import chunk_document, chunk_documents, prepare_sections


class WordTokenizer:
    def encode(self, text: str, add_special_tokens: bool = False) -> list[str]:
        return text.split()

    def decode(self, token_ids: list[str]) -> str:
        return " ".join(token_ids)


def _doc(doc_id: str, scheme: str, sections: list[dict], url: str = "https://groww.in/a") -> dict:
    return {
        "id": doc_id,
        "url": url,
        "scheme_or_topic": scheme,
        "fetched_at": "2026-11-01",
        "sections": sections,
    }


def test_short_section_keeps_scheme_prefix_and_source():
    chunks = chunk_document(
        _doc(
            "hdfc-elss",
            "HDFC ELSS Tax Saver Fund Direct Plan Growth",
            [{"heading": "Exit load", "text": "Exit load of 1% if redeemed within 1 year."}],
            url="https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth",
        ),
        max_tokens=180,
        overlap_tokens=40,
        tokenizer=WordTokenizer(),
    )
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk["chunk_id"] == "hdfc-elss#exit-load#0"
    assert chunk["scheme"] == "HDFC ELSS Tax Saver Fund Direct Plan Growth"
    assert chunk["text"].startswith(
        "AMC: HDFC Mutual Fund | Scheme: HDFC ELSS Tax Saver Fund Direct Plan Growth | "
        "Section: Exit load | Source: https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
    )
    assert "1%" in chunk["text"]
    assert chunk["token_count"] <= 180


def test_long_section_overlaps_and_stays_under_the_cap():
    words = " ".join(f"w{index}" for index in range(80))
    chunks = chunk_document(
        _doc("scheme-a", "Scheme A", [{"heading": "Holdings", "text": words}]),
        max_tokens=70,
        overlap_tokens=5,
        tokenizer=WordTokenizer(),
    )
    assert len(chunks) >= 2
    assert all(chunk["token_count"] <= 70 for chunk in chunks)
    assert all(chunk["text"].startswith("AMC: HDFC Mutual Fund | Scheme: Scheme A |") for chunk in chunks)
    first_body = chunks[0]["text"].split("\n", 1)[1]
    second_body = chunks[1]["text"].split("\n", 1)[1]
    assert any(word in second_body.split() for word in first_body.split()[-5:])


def test_two_schemes_are_not_merged():
    documents = [
        _doc("scheme-a", "Scheme A", [{"heading": "Exit load", "text": "UNIQUEA exit load is 1%."}]),
        _doc("scheme-b", "Scheme B", [{"heading": "Exit load", "text": "UNIQUEB exit load is 2%."}]),
    ]
    chunks, skipped = chunk_documents(documents, 180, 40, WordTokenizer())
    assert skipped == 0
    assert {chunk["scheme"] for chunk in chunks} == {"Scheme A", "Scheme B"}
    for chunk in chunks:
        if chunk["scheme"] == "Scheme A":
            assert "UNIQUEB" not in chunk["text"]
            assert chunk["doc_id"] == "scheme-a"
        else:
            assert "UNIQUEA" not in chunk["text"]
            assert chunk["doc_id"] == "scheme-b"


def test_generic_heading_splits_a_single_fact_line():
    sections = prepare_sections(
        [
            {
                "heading": "Fund details",
                "text": "Intro line about the scheme\nExpense ratio 1.20%\nOther commentary stays here",
            }
        ]
    )
    headings = [section["heading"] for section in sections]
    assert "Expense ratio" in headings
    fact = next(section for section in sections if section["heading"] == "Expense ratio")
    assert fact["text"] == "Expense ratio 1.20%"
    assert all("1.20%" not in section["text"] for section in sections if section["heading"] != "Expense ratio")


def test_noise_and_market_risk_lines_are_dropped():
    chunks = chunk_document(
        _doc(
            "scheme-a",
            "Scheme A",
            [
                {
                    "heading": "Exit load",
                    "text": (
                        "Mutual fund investments are subject to market risks.\n"
                        "Download the app to continue.\n"
                        "Exit load of 1% if redeemed within 1 year."
                    ),
                }
            ],
        ),
        max_tokens=180,
        overlap_tokens=40,
        tokenizer=WordTokenizer(),
    )
    assert len(chunks) == 1
    assert "market risks" not in chunks[0]["text"].lower()
    assert "download the app" not in chunks[0]["text"].lower()
    assert "1%" in chunks[0]["text"]
