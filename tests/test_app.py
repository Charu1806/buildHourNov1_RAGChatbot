"""HTTP + UI tests with Retriever.search and ChatModel.complete replaced."""

from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from src.app import create_app
from src.config import load_settings
from src.retrieve import Hit
from src.sources import SourceRow, write_sources

AMC_URL = "https://groww.in/mutual-funds/amc/hdfc-mutual-funds"
LARGE_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
FLEXI_URL = "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"
ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
MID_URL = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
EDU_URL = "https://investor.sebi.gov.in/education/investor-education.html"

VALID_DRAFT = (
    "The expense ratio is 1.02%.\n"
    f"Source: {LARGE_URL}\n"
    "Last updated from sources: 2026-11-01"
)


def _rows() -> list[SourceRow]:
    return [
        SourceRow("hdfc-amc", "HDFC Mutual Fund", AMC_URL, "groww.in", "HDFC Mutual Fund", "2026-11-01", "seed"),
        SourceRow("hdfc-large-cap", "HDFC Large Cap Fund Direct Growth", LARGE_URL, "groww.in", "HDFC Large Cap Fund Direct Growth", "2026-11-01", "seed"),
        SourceRow("hdfc-flexi-cap", "HDFC Flexi Cap Direct Plan Growth", FLEXI_URL, "groww.in", "HDFC Flexi Cap Direct Plan Growth", "2026-11-01", "seed"),
        SourceRow("hdfc-elss", "HDFC ELSS Tax Saver Fund Direct Plan Growth", ELSS_URL, "groww.in", "HDFC ELSS Tax Saver Fund Direct Plan Growth", "2026-11-01", "seed"),
        SourceRow("hdfc-mid-cap", "HDFC Mid Cap Fund Direct Growth", MID_URL, "groww.in", "HDFC Mid Cap Fund Direct Growth", "2026-11-01", "seed"),
        SourceRow("sebi-education", "Investor education", EDU_URL, "investor.sebi.gov.in", "Investor education", "2026-10-20", "education"),
    ]


def _settings(tmp_path):
    sources_path = tmp_path / "sources.csv"
    write_sources(sources_path, _rows())
    base = load_settings(require_llm=False)
    return replace(
        base,
        sources_path=sources_path,
        educational_url=EDU_URL,
        llm_model="test/model",
        api_key="test-key",
        max_answer_sentences=3,
        score_threshold=0.35,
    )


def _hit(similarity: float = 0.81) -> Hit:
    return Hit(
        chunk_id="hdfc-large-cap#expense-ratio#0",
        doc_id="hdfc-large-cap",
        text=(
            "AMC: HDFC Mutual Fund | Scheme: HDFC Large Cap Fund Direct Growth | "
            f"Section: Expense ratio | Source: {LARGE_URL}\nExpense ratio\n1.02%"
        ),
        scheme="HDFC Large Cap Fund Direct Growth",
        section="Expense ratio",
        source_url=LARGE_URL,
        fetched_at="2026-11-01",
        similarity=similarity,
    )


class FakeRetriever:
    def __init__(self, hits: list[Hit] | None = None) -> None:
        self.hits = hits if hits is not None else []
        self.calls = 0

    def search(self, question: str) -> list[Hit]:
        self.calls += 1
        return self.hits


class FakeChat:
    def __init__(self, reply=None, error: Exception | None = None) -> None:
        self.reply = reply if reply is not None else VALID_DRAFT
        self.error = error
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        if callable(self.reply):
            return self.reply(self.calls)
        return self.reply


def _client(tmp_path, *, hits=None, chat=None, retriever=None):
    settings = _settings(tmp_path)
    app = create_app(
        settings,
        retriever=retriever or FakeRetriever(hits),
        chat=chat or FakeChat(),
        sources=_rows(),
    )
    return TestClient(app)


def test_serves_the_page_with_disclaimer_examples_and_trace_summary(tmp_path):
    client = _client(tmp_path)
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    body = response.text
    assert "Ask a factual question about HDFC mutual fund schemes." in body
    assert "Facts-only. No investment advice." in body
    assert "What is the expense ratio of HDFC Large Cap Fund Direct Growth?" in body
    assert "What is the lock-in for HDFC ELSS Tax Saver Fund?" in body
    assert "How do I download a capital-gains statement?" in body
    assert "How this answer was built" in body


def test_serves_the_source_list(tmp_path):
    client = _client(tmp_path)
    response = client.get("/sources.csv")

    assert response.status_code == 200
    assert "text/csv" in response.headers["content-type"]
    assert "hdfc-amc" in response.text


def test_empty_question_is_400(tmp_path):
    client = _client(tmp_path)
    response = client.post("/api/ask", json={"question": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "Enter a question."


def test_advice_refuses_without_retrieval_or_llm(tmp_path):
    retriever = FakeRetriever([_hit()])
    chat = FakeChat()
    client = _client(tmp_path, retriever=retriever, chat=chat)

    response = client.post("/api/ask", json={"question": "Should I buy HDFC Flexi Cap?"})

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "refuse"
    assert body["reason"] == "advice"
    assert body["source"]["url"] == EDU_URL
    assert retriever.calls == 0
    assert chat.calls == 0
    words = {word.strip(".,").lower() for word in body["sentences"][0].split()}
    assert "yes" not in words and "no" not in words


def test_pan_question_has_null_trace_and_is_not_echoed(tmp_path):
    retriever = FakeRetriever([_hit()])
    chat = FakeChat()
    client = _client(tmp_path, retriever=retriever, chat=chat)

    response = client.post(
        "/api/ask",
        json={"question": "Expense ratio of HDFC Large Cap, my PAN is ABCDE1234F"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "refuse"
    assert body["reason"] == "pii"
    assert body["trace"] is None
    assert "ABCDE1234F" not in response.text
    assert retriever.calls == 0
    assert chat.calls == 0


def test_below_threshold_refuses_without_the_llm(tmp_path):
    chat = FakeChat()
    client = _client(tmp_path, hits=[_hit(similarity=0.2)], chat=chat)

    response = client.post(
        "/api/ask",
        json={"question": "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "refuse"
    assert body["reason"] == "below_threshold"
    assert body["source"]["url"] == LARGE_URL
    assert len(body["trace"]["chunks"]) == 1
    assert body["trace"]["chunks"][0]["similarity"] == pytest.approx(0.2)
    assert chat.calls == 0


def test_valid_hit_and_draft_return_one_sourced_answer(tmp_path):
    chat = FakeChat()
    client = _client(tmp_path, hits=[_hit()], chat=chat)

    response = client.post(
        "/api/ask",
        json={"question": "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "answer"
    assert body["reason"] == "in_scope"
    assert body["sentences"] == ["The expense ratio is 1.02%."]
    assert body["source"] == {
        "title": "HDFC Large Cap Fund Direct Growth",
        "url": LARGE_URL,
    }
    assert body["last_updated"] == "2026-11-01"
    assert body["trace"]["llm_model"] == "test/model"
    assert body["trace"]["embedding_model"] == _settings(tmp_path).embedding_model
    assert len(body["trace"]["chunks"]) == 1
    assert chat.calls == 1


def test_provider_failure_is_503_with_the_fixed_sentence(tmp_path):
    chat = FakeChat(error=RuntimeError("provider down"))
    client = _client(tmp_path, hits=[_hit()], chat=chat)

    response = client.post(
        "/api/ask",
        json={"question": "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["route"] == "error"
    assert body["sentences"] == ["I could not produce a sourced answer just now."]
    assert body["sources_url"] == "/sources.csv"
    assert chat.calls >= 1


def test_two_failed_drafts_are_retried_once_then_503(tmp_path):
    bad_draft = (
        "See https://example.com/a and https://example.com/b.\n"
        f"Source: {LARGE_URL}\n"
        "Last updated from sources: 2026-11-01"
    )
    chat = FakeChat(reply=bad_draft)
    client = _client(tmp_path, hits=[_hit()], chat=chat)

    response = client.post(
        "/api/ask",
        json={"question": "What is the expense ratio of HDFC Large Cap Fund Direct Growth?"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["sentences"] == ["I could not produce a sourced answer just now."]
    assert "example.com/a" not in response.text
    assert chat.calls == 2
