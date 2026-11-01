"""Deterministic routing. The LLM never classifies a question."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.sources import SourceRow

PII = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+"                      # email
    r"|(?<!\d)(?:\+?91[\s-]?)?[6-9]\d{9}(?!\d)"       # Indian mobile
    r"|\b[A-Z]{5}\d{4}[A-Z]\b"                        # PAN
    r"|(?<!\d)\d{4}\s?\d{4}\s?\d{4}(?!\d)"            # Aadhaar
    r"|(?<!\d)\d{9,}(?!\d)"                           # account-like run
    r"|\botp\b\D{0,12}\d{4,8}\b",                     # OTP next to digits
    re.IGNORECASE,
)

ADVICE = re.compile(
    r"\b(?:should\s+i|buy|sell|hold|switch|invest\w*|recommend\w*|"
    r"allocate|allocation|portfolio)\b"
    r"|\bis this good\b|\bwhich is best\b",
    re.IGNORECASE,
)

PERFORMANCE = re.compile(
    r"\b(?:returns?|cagr|performance|alpha|rank(?:ing|ed)?|beating|outperform\w*)\b"
    r"|\bhigher returns?\b|\bdid better\b",
    re.IGNORECASE,
)

OTHER_AMC = re.compile(
    r"\b(?:sbi|icici|axis|nippon|kotak|mirae|parag parikh|quant|uti|tata|"
    r"aditya birla|dsp|franklin|motilal)\b",
    re.IGNORECASE,
)

SCHEMES = (
    ("large_cap", re.compile(r"\blarge[\s-]?cap\b", re.IGNORECASE)),
    ("flexi_cap", re.compile(r"\bflexi[\s-]?cap\b|\bequity fund\b", re.IGNORECASE)),
    ("elss", re.compile(r"\belss\b|\btax saver\b", re.IGNORECASE)),
    ("mid_cap", re.compile(r"\bmid[\s-]?cap\b", re.IGNORECASE)),
    ("amc", re.compile(r"\bhdfc mutual fund\b|\bhdfc amc\b", re.IGNORECASE)),
)

STATEMENT = re.compile(r"\bstatement\b", re.IGNORECASE)
STATEMENT_HINT = re.compile(r"\bdownload\b|\bcapital[\s-]?gain|\bcas\b", re.IGNORECASE)

TEXTS = {
    "pii": (
        "Please resend your question without account numbers, identity numbers, "
        "email addresses, or phone numbers."
    ),
    "advice": (
        "I can only share published facts about HDFC schemes, not whether you "
        "should buy, sell, or hold."
    ),
    "out_of_scope": (
        "I only cover published facts for HDFC Mutual Fund and its Large Cap, "
        "Flexi Cap, ELSS Tax Saver, and Mid Cap direct schemes."
    ),
    "performance": (
        "I do not calculate or compare returns. Published performance figures "
        "are on the official factsheet."
    ),
    "below_threshold": "I could not find that fact in the fetched official pages.",
}


@dataclass(frozen=True)
class Decision:
    route: str
    reason: str
    scheme: str | None = None


@dataclass(frozen=True)
class Template:
    sentences: list[str]
    url: str
    last_updated: str


def classify(question: str) -> Decision:
    text = question or ""

    if PII.search(text):
        return Decision("refuse", "pii")

    scheme = detect_scheme(text)

    if ADVICE.search(text):
        return Decision("refuse", "advice", scheme)
    if PERFORMANCE.search(text):
        return Decision("refuse", "performance", scheme)

    statement = bool(STATEMENT.search(text) and STATEMENT_HINT.search(text))

    if OTHER_AMC.search(text):
        return Decision("refuse", "out_of_scope", scheme)
    if scheme is None and not statement:
        return Decision("refuse", "out_of_scope", None)
    return Decision("answer", "in_scope", scheme)


def detect_scheme(question: str) -> str | None:
    for key, pattern in SCHEMES:
        if pattern.search(question):
            return key
    return None


def refusal(decision: Decision, sources: list[SourceRow], educational_url: str) -> Template:
    if decision.reason not in {"pii", "advice", "out_of_scope", "performance"}:
        raise ValueError(f"not a refusal reason: {decision.reason}")

    if decision.reason == "performance":
        row = performance_row(decision.scheme, sources)
    else:
        row = row_for_url(sources, educational_url) or amc_row(sources)

    return Template([TEXTS[decision.reason]], row.url if row else "", row.fetched_at if row else "")


def below_threshold(scheme: str | None, sources: list[SourceRow]) -> Template:
    row = scheme_row(scheme, sources) if scheme else None
    row = row or amc_row(sources)
    return Template(
        [TEXTS["below_threshold"]],
        row.url if row else "",
        row.fetched_at if row else "",
    )


def performance_row(scheme: str | None, sources: list[SourceRow]) -> SourceRow | None:
    if scheme is None:
        return amc_row(sources)
    factsheet = next(
        (
            row
            for row in sources
            if "factsheet" in row.why_included.lower() and matches_scheme(row, scheme)
        ),
        None,
    )
    return factsheet or scheme_row(scheme, sources) or amc_row(sources)


def scheme_row(scheme: str | None, sources: list[SourceRow]) -> SourceRow | None:
    if scheme is None:
        return None
    return next((row for row in sources if matches_scheme(row, scheme)), None)


def amc_row(sources: list[SourceRow]) -> SourceRow | None:
    for row in sources:
        if row.id == "hdfc-amc" or "hdfc mutual fund" in row.scheme_or_topic.lower():
            return row
    return sources[0] if sources else None


def row_for_url(sources: list[SourceRow], url: str) -> SourceRow | None:
    return next((row for row in sources if row.url == url), None)


def matches_scheme(row: SourceRow, scheme: str) -> bool:
    topic = row.scheme_or_topic.lower()
    if scheme == "large_cap":
        return "large cap" in topic
    if scheme == "flexi_cap":
        return "flexi cap" in topic
    if scheme == "elss":
        return "elss" in topic or "tax saver" in topic
    if scheme == "mid_cap":
        return "mid cap" in topic
    if scheme == "amc":
        return "hdfc mutual fund" in topic
    return False
