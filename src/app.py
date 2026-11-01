"""FastAPI page and POST /api/ask. No frontend build."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from src.config import Settings, load_settings
from src.generate import answer as generate_answer
from src.guard import (
    Decision,
    below_threshold as below_threshold_template,
    classify,
    refusal,
    row_for_url,
)
from src.llm import ChatModel
from src.retrieve import Hit, Retriever, passes_threshold
from src.sources import SourceRow, read_sources

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PAGE = STATIC_DIR / "index.html"
ERROR_SENTENCE = "I could not produce a sourced answer just now."

logger = logging.getLogger("uvicorn.error")


class AskRequest(BaseModel):
    question: str = ""


def create_app(
    settings: Settings,
    *,
    retriever=None,
    chat=None,
    sources: list[SourceRow] | None = None,
) -> FastAPI:
    source_rows = sources if sources is not None else read_sources(settings.sources_path)
    retriever = retriever if retriever is not None else Retriever(settings)
    chat = chat if chat is not None else ChatModel(settings)

    app = FastAPI(title="HDFC Mutual Fund Facts FAQ", docs_url=None, redoc_url=None)

    @app.get("/")
    def index_page() -> FileResponse:
        return FileResponse(INDEX_PAGE, media_type="text/html")

    @app.get("/sources.csv")
    def sources_csv() -> FileResponse:
        return FileResponse(settings.sources_path, media_type="text/csv")

    @app.post("/api/ask")
    def ask(payload: AskRequest):
        question = (payload.question or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="Enter a question.")

        decision = classify(question)

        if decision.reason == "pii":
            logger.info(
                "refused_pii %s",
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            )
            template = refusal(decision, source_rows, settings.educational_url)
            return _template_response(decision, template, source_rows, settings, trace=None)

        if decision.route == "refuse":
            template = refusal(decision, source_rows, settings.educational_url)
            return _template_response(
                decision, template, source_rows, settings, trace=_trace(question, decision, settings, [])
            )

        hits = retriever.search(question)

        if not passes_threshold(hits, settings.score_threshold):
            template = below_threshold_template(decision.scheme, source_rows)
            return _template_response(
                decision,
                template,
                source_rows,
                settings,
                trace=_trace(question, Decision("refuse", "below_threshold", decision.scheme), settings, hits),
                reason="below_threshold",
            )

        try:
            result = generate_answer(question, hits, chat=chat, settings=settings)
        except Exception:
            logger.warning("generation_failed")
            return JSONResponse(
                status_code=503,
                content={
                    "route": "error",
                    "sentences": [ERROR_SENTENCE],
                    "sources_url": "/sources.csv",
                },
            )

        row = row_for_url(source_rows, result.source_url)
        return {
            "route": "answer",
            "reason": "in_scope",
            "sentences": result.sentences,
            "source": {
                "title": row.title if row else "",
                "url": result.source_url,
            },
            "last_updated": result.last_updated,
            "trace": _trace(question, decision, settings, hits),
        }

    return app


def _template_response(
    decision: Decision,
    template,
    sources: list[SourceRow],
    settings: Settings,
    *,
    trace: dict | None,
    reason: str | None = None,
) -> dict:
    row = row_for_url(sources, template.url)
    return {
        "route": "refuse",
        "reason": reason or decision.reason,
        "sentences": template.sentences,
        "source": {
            "title": row.title if row else "",
            "url": template.url,
        },
        "last_updated": template.last_updated,
        "trace": trace,
    }


def _trace(
    question: str,
    decision: Decision,
    settings: Settings,
    hits: list[Hit],
) -> dict:
    return {
        "question": question,
        "route": decision.route,
        "reason": decision.reason,
        "embedding_model": settings.embedding_model,
        "llm_model": settings.llm_model,
        "chunks": [hit.to_trace() for hit in hits],
    }


def main() -> None:
    import os

    import uvicorn

    settings = load_settings(require_llm=True)
    app = create_app(settings)
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()
