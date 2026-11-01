"""Answer contract from implementation.md section 7."""

from src.generate import check_draft
from src.retrieve import Hit

SOURCE = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"


def _hit() -> Hit:
    return Hit(
        chunk_id="hdfc-large-cap#expense-ratio#0",
        doc_id="hdfc-large-cap",
        text=(
            "AMC: HDFC Mutual Fund | Scheme: HDFC Large Cap Fund Direct Growth | "
            "Section: Expense ratio | Source: "
            f"{SOURCE}\nExpense ratio\n1.02%"
        ),
        scheme="HDFC Large Cap Fund Direct Growth",
        section="Expense ratio",
        source_url=SOURCE,
        fetched_at="2026-11-01",
        similarity=0.81,
    )


def _draft(body: str, url: str = SOURCE, date: str = "2026-11-01") -> str:
    return f"{body}\nSource: {url}\nLast updated from sources: {date}"


def test_accepts_a_short_sourced_draft():
    result, errors = check_draft(
        _draft("The expense ratio is 1.02%."), [_hit()], 3
    )

    assert errors == []
    assert result is not None
    assert result.sentences == ["The expense ratio is 1.02%."]
    assert result.source_url == SOURCE
    assert result.last_updated == "2026-11-01"


def test_rejects_two_urls():
    draft = _draft("See https://example.com/other for more. The expense ratio is 1.02%.")
    result, errors = check_draft(draft, [_hit()], 3)

    assert result is None
    assert any("exactly one URL" in error for error in errors)


def test_rejects_a_url_that_was_not_retrieved():
    result, errors = check_draft(
        _draft("The expense ratio is 1.02%.", url="https://example.com/nope"),
        [_hit()],
        3,
    )

    assert result is None
    assert any("not one of the retrieved" in error for error in errors)


def test_rejects_a_wrong_date():
    result, errors = check_draft(
        _draft("The expense ratio is 1.02%.", date="2026-10-01"), [_hit()], 3
    )

    assert result is None
    assert any("does not match" in error for error in errors)


def test_rejects_a_number_missing_from_the_cited_chunk():
    result, errors = check_draft(
        _draft("The expense ratio is 1.5%."), [_hit()], 3
    )

    assert result is None
    assert any("1.5%" in error for error in errors)


def test_rejects_more_than_three_sentences():
    result, errors = check_draft(
        _draft("One. Two. Three. Four."), [_hit()], 3
    )

    assert result is None
    assert any("sentences" in error for error in errors)


def test_rejects_a_missing_source_line():
    result, errors = check_draft(
        "The expense ratio is 1.02%.\nLast updated from sources: 2026-11-01",
        [_hit()],
        3,
    )

    assert result is None
    assert any("Source:" in error for error in errors)


def test_rejects_a_missing_date_line():
    result, errors = check_draft(f"The expense ratio is 1.02%.\nSource: {SOURCE}", [_hit()], 3)

    assert result is None
    assert any("Last updated" in error for error in errors)
