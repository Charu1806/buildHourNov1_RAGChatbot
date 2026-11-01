"""Guard routing table from implementation.md section 9."""

import re

from src.guard import (
    Decision,
    amc_row,
    below_threshold,
    classify,
    refusal,
    scheme_row,
)
from src.sources import SourceRow

AMC_URL = "https://groww.in/mutual-funds/amc/hdfc-mutual-funds"
LARGE_URL = "https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth"
FLEXI_URL = "https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth"
ELSS_URL = "https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth"
MID_URL = "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth"
FACTSHEET_URL = "https://www.hdfcfund.com/factsheet/hdfc-large-cap.pdf"
EDU_URL = "https://investor.sebi.gov.in/education/investor-education.html"


def _sources() -> list[SourceRow]:
    return [
        SourceRow("hdfc-amc", "HDFC Mutual Fund", AMC_URL, "groww.in", "HDFC Mutual Fund", "2026-11-01", "seed"),
        SourceRow("hdfc-large-cap", "HDFC Large Cap Fund Direct Growth", LARGE_URL, "groww.in", "HDFC Large Cap Fund Direct Growth", "2026-11-01", "seed"),
        SourceRow("hdfc-flexi-cap", "HDFC Flexi Cap Direct Plan Growth", FLEXI_URL, "groww.in", "HDFC Flexi Cap Direct Plan Growth", "2026-11-01", "seed"),
        SourceRow("hdfc-elss", "HDFC ELSS Tax Saver Fund Direct Plan Growth", ELSS_URL, "groww.in", "HDFC ELSS Tax Saver Fund Direct Plan Growth", "2026-11-01", "seed"),
        SourceRow("hdfc-mid-cap", "HDFC Mid Cap Fund Direct Growth", MID_URL, "groww.in", "HDFC Mid Cap Fund Direct Growth", "2026-11-01", "seed"),
        SourceRow("hdfc-large-cap-factsheet", "HDFC Large Cap factsheet", FACTSHEET_URL, "hdfcfund.com", "HDFC Large Cap Fund Direct Growth", "2026-10-28", "factsheet"),
        SourceRow("sebi-education", "Investor education", EDU_URL, "investor.sebi.gov.in", "Investor education", "2026-10-20", "education"),
    ]


def _decide(question: str):
    sources = _sources()
    decision = classify(question)
    template = None
    if decision.route == "refuse":
        template = refusal(decision, sources, EDU_URL)
    return decision, template


def test_advice_buy_refuses_with_the_education_link():
    decision, template = _decide("Should I buy HDFC Flexi Cap?")

    assert decision.route == "refuse"
    assert decision.reason == "advice"
    assert template.url == EDU_URL
    words = {word.strip(".,").lower() for word in template.sentences[0].split()}
    assert "yes" not in words and "no" not in words


def test_advice_hold_matches_even_with_a_scheme():
    decision, _ = _decide("Is HDFC Mid Cap a good hold?")
    assert decision.reason == "advice"


def test_higher_returns_is_performance_and_adds_no_percentage():
    decision, template = _decide("Which of these had higher returns?")

    assert decision.reason == "performance"
    assert template.url == AMC_URL
    assert not re.search(r"\d+(?:\.\d+)?\s*%", template.sentences[0])


def test_cagr_is_checked_before_the_fact_path_and_uses_the_factsheet():
    decision, template = _decide("What is the CAGR of HDFC Large Cap?")

    assert decision.reason == "performance"
    assert template.url == FACTSHEET_URL


def test_pan_is_pii_and_not_retained_on_the_decision():
    decision, template = _decide(
        "Expense ratio of HDFC Large Cap, my PAN is ABCDE1234F"
    )

    assert decision.reason == "pii"
    assert "ABCDE1234F" not in repr(decision)
    assert template.url == EDU_URL


def test_mobile_number_is_pii():
    decision, _ = _decide("Call me on 9876543210 about the exit load")
    assert decision.reason == "pii"


def test_otp_is_pii():
    decision, _ = _decide("OTP is 123456")
    assert decision.reason == "pii"


def test_another_amc_is_out_of_scope():
    decision, template = _decide("What is the exit load of SBI Bluechip?")

    assert decision.reason == "out_of_scope"
    assert template.url == EDU_URL


def test_no_scheme_named_is_out_of_scope():
    decision, _ = _decide("What is an exit load?")
    assert decision.reason == "out_of_scope"


def test_lock_in_for_elss_is_in_scope():
    decision, _ = _decide("What is the lock-in for HDFC ELSS Tax Saver?")

    assert decision.route == "answer"
    assert decision.reason == "in_scope"
    assert decision.scheme == "elss"


def test_statement_download_is_in_scope_without_a_scheme():
    decision, _ = _decide("How do I download a capital-gains statement?")

    assert decision.route == "answer"
    assert decision.reason == "in_scope"
    assert decision.scheme is None


def test_compare_expense_ratio_is_not_a_performance_question():
    decision, _ = _decide(
        "Compare the expense ratio of HDFC Large Cap and HDFC Mid Cap"
    )

    assert decision.reason == "in_scope"
    assert decision.scheme == "large_cap"


def test_below_threshold_template_cites_the_named_scheme_then_the_amc():
    sources = _sources()

    named = below_threshold("mid_cap", sources)
    assert named.url == MID_URL
    assert named.last_updated == "2026-11-01"

    unnamed = below_threshold(None, sources)
    assert unnamed.url == AMC_URL


def test_scheme_and_amc_lookups():
    sources = _sources()
    assert scheme_row("elss", sources).url == ELSS_URL
    assert scheme_row("flexi_cap", sources).url == FLEXI_URL
    assert amc_row(sources).url == AMC_URL
    assert refusal(Decision("refuse", "advice"), sources, EDU_URL).url == EDU_URL
