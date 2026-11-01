"""Ask the model for a sourced answer and enforce the answer contract."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.config import Settings
from src.prompts import SYSTEM_PROMPT
from src.retrieve import Hit

URL_PATTERN = re.compile(r"https?://[^\s)>\]]+")
NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?%?")
DATE_LINE = re.compile(
    r"Last updated from sources:\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE
)
SOURCE_LINE = re.compile(r"^Source:\s*(\S+)$", re.IGNORECASE)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


class GenerationError(Exception):
    """Both attempts failed the answer check."""


@dataclass(frozen=True)
class Answer:
    sentences: list[str]
    source_url: str
    last_updated: str


def answer(
    question: str,
    hits: list[Hit],
    *,
    chat,
    settings: Settings,
    system_prompt: str = SYSTEM_PROMPT,
) -> Answer:
    base = build_user_message(question, hits)
    feedback = ""
    errors: list[str] = []

    for _ in range(2):
        user = base if not feedback else f"{base}\n\n{feedback}"
        draft = chat.complete(system_prompt, user)
        result, errors = check_draft(draft, hits, settings.max_answer_sentences)
        if result is not None:
            return result
        feedback = (
            "Your previous draft failed these checks. Reply again and fix every item:\n- "
            + "\n- ".join(errors)
        )

    raise GenerationError("; ".join(errors) or "answer check failed")


def build_user_message(question: str, hits: list[Hit]) -> str:
    blocks = [
        (
            f"chunk_id: {hit.chunk_id}\n"
            f"scheme: {hit.scheme}\n"
            f"section: {hit.section}\n"
            f"source_url: {hit.source_url}\n"
            f"fetched_at: {hit.fetched_at}\n"
            f"text:\n{hit.text}"
        )
        for hit in hits
    ]
    return f"Question: {question}\n\nRetrieved chunks:\n\n" + "\n\n---\n\n".join(blocks)


def check_draft(
    draft: str, hits: list[Hit], max_sentences: int
) -> tuple[Answer | None, list[str]]:
    errors: list[str] = []
    text = (draft or "").strip()
    if not text:
        return None, ["the draft is empty"]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None, ["the draft is empty"]

    date_match = DATE_LINE.fullmatch(lines[-1])
    if not date_match:
        errors.append(
            "the last line must be exactly 'Last updated from sources: YYYY-MM-DD'"
        )
        last_updated = ""
    else:
        last_updated = date_match.group(1)

    source_index = next(
        (index for index, line in enumerate(lines) if SOURCE_LINE.match(line)), None
    )
    if source_index is None:
        errors.append("there must be one line 'Source: <URL>' before the date line")
        source_url = ""
        body_lines = lines[:-1]
    else:
        source_url = SOURCE_LINE.match(lines[source_index]).group(1).rstrip(".,;")
        body_lines = lines[:source_index]

    body = " ".join(body_lines).strip()
    sentences = [part for part in SENTENCE_SPLIT.split(body) if part.strip()]
    if not body:
        errors.append("the answer body is empty")
    if len(sentences) > max_sentences:
        errors.append(f"the answer has {len(sentences)} sentences; the limit is {max_sentences}")

    urls = URL_PATTERN.findall(text)
    if len(urls) != 1:
        errors.append(f"the draft must contain exactly one URL, found {len(urls)}")

    cited = [hit for hit in hits if hit.source_url == source_url]
    if not source_url:
        errors.append("the source URL is missing")
    elif not cited:
        errors.append("the source URL was not one of the retrieved chunks")
    elif last_updated and last_updated not in {hit.fetched_at for hit in cited}:
        errors.append("the last-updated date does not match the cited chunk's fetched_at")

    if cited:
        chunk_text = "\n".join(hit.text for hit in cited)
        for number in NUMBER_PATTERN.findall(body):
            if number not in chunk_text:
                errors.append(f"the number {number} is not in the cited chunk")

    if errors:
        return None, errors
    return Answer(sentences, source_url, last_updated), []
