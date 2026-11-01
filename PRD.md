# PRD: HDFC Mutual Fund Facts FAQ

**Status:** Draft for build  
**Source:** `Doc/ProblemStatement.txt`  
**Product type:** Small RAG demo — factual FAQ over official public pages  
**Scope:** HDFC Mutual Fund AMC overview + four HDFC schemes  

## 1. Problem

Retail users and support teams repeatedly ask the same factual questions about mutual fund schemes: expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, and how to download statements. Answers today are scattered across scheme pages. A short assistant should answer those facts from official public pages, attach one source link to every answer, and refuse anything that is advice, a performance claim, or personal data.

## 2. Users

| User | Job to be done |
| --- | --- |
| Retail investor comparing schemes | Look up one fact about a named HDFC scheme without getting a recommendation. |
| Support or content teammate | Answer a repetitive factual question with a citable public link. |

## 3. Goals

1. Answer a factual question about the in-scope AMC or schemes in three sentences or fewer.
2. Attach exactly one citation link to every answer, including refusals (an educational or factsheet link).
3. Show the RAG pipeline as stored artifacts: load, chunk, embed, index, retrieve, answer.
4. Keep models, vector store, and paths in config so they can be changed without code edits.
5. Ship the submission pack: prototype, source list, README, sample Q&A, disclaimer.

## 4. Non-goals

- Investment advice, buy/sell opinions, portfolio construction, or “which fund is better.”
- Computing, ranking, or comparing returns, NAV history, or performance.
- Account servicing. The assistant does not log in, does not download a user’s statement, and does not collect identity.
- Screenshots or data from the Groww app backend.
- Third-party blogs, forums, news, or social posts as sources.
- Full AMC coverage beyond HDFC, or schemes other than the four listed below.
- Chat memory across sessions, user accounts, or personalization.

## 5. In-scope corpus

### 5.1 Seed pages (must scrape)

| # | Page | URL |
| --- | --- | --- |
| 1 | AMC overview — HDFC Mutual Fund | https://groww.in/mutual-funds/amc/hdfc-mutual-funds |
| 2 | Large Cap — HDFC Large Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth |
| 3 | Flexi Cap — HDFC Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth |
| 4 | ELSS — HDFC ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth |
| 5 | Mid Cap — HDFC Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth |

### 5.2 Expansion to 15–25 official URLs

Start from the five seed pages and add only public official URLs needed to answer the question set. Allowed additions:

- Official factsheet, SID, or KIM links published on those Groww pages or on the AMC’s own site.
- Groww help pages that explain how to download account statements or capital-gains statements.
- Registrar pages (CAMS, KFintech) only when they are the official download path described by Groww or the AMC.
- AMFI or SEBI investor-education pages used as the refusal / educational citation.
- One official page per in-scope scheme for riskometer, benchmark, expense ratio, exit load, minimum SIP, and ELSS lock-in, if the seed page does not state the fact in text.

Stop at 25 URLs. Record every URL in `sources.md` (and a CSV twin) with: `id`, `title`, `url`, `publisher`, `scheme_or_topic`, `fetched_at`, `why_included`.

If a page is blocked, empty, or not official, skip it and document the gap in the README. Do not substitute a blog.

## 6. Questions the assistant must handle

**Answer** when the corpus contains the fact:

- Expense ratio of a named in-scope scheme (Direct plan as published).
- Exit load of a named in-scope scheme.
- Minimum SIP of a named in-scope scheme.
- ELSS lock-in for the HDFC ELSS scheme.
- Riskometer and benchmark of a named in-scope scheme.
- How to download a capital-gains or account statement, as a procedure from the official help page. This is generic how-to, not a request for the user’s own statement.

**Refuse** (polite, facts-only, one educational link, no steps that imply a recommendation):

- Buy, sell, hold, switch, “should I,” “is this good,” “which is best,” asset allocation, or tax advice beyond quoting a published lock-in or tax-status label.
- Returns, CAGR, ranking, “is X beating Y,” or any computed performance. Point to the official factsheet instead of calculating.
- Anything outside HDFC AMC and the four schemes, except the statement-download how-to and the educational refusal link.
- Questions that include PAN, Aadhaar, account numbers, OTPs, email addresses, or phone numbers. Do not echo the identifier back.

If the fact is in scope but not in the corpus, say so in one or two sentences and cite the most relevant official page. Do not guess a number.

## 7. Answer contract

Every response, including refusals, must:

1. Be at most **three sentences** of answer text.
2. Include **one** markdown or UI link. Label it `Source:`.
3. End with `Last updated from sources: YYYY-MM-DD`, using the `fetched_at` date of the cited page (corpus build date if several pages were fetched the same day).
4. Quote only figures that appear in the retrieved chunk. Do not round, annualize, or infer a missing field.
5. Name the scheme in the answer when the question names one, so a number is never free-floating.

Example shape (illustrative, not a stored answer):

> HDFC ELSS Tax Saver Fund Direct Plan Growth has a statutory lock-in of 3 years for each SIP installment, as published on the scheme page.  
> Source: [HDFC ELSS Tax Saver Fund Direct Plan Growth](https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth)  
> Last updated from sources: 2026-11-01

Refusal shape:

> I can only share published facts about HDFC schemes, not whether you should buy or sell.  
> Source: [SEBI investor education](https://investor.sebi.gov.in/)  
> Last updated from sources: 2026-11-01

The SEBI URL above is a placeholder. The build must use a live public SEBI or AMFI education URL that was fetched into the corpus, and record it in the source list.

Disclaimer, shown in the UI and copied into the submission:

> Facts-only. No investment advice. Answers are short quotations from official public pages, with one source link. This is not a recommendation to buy, sell, or hold any scheme.

## 8. User interface

A single page. No login.

- Welcome line: `Ask a factual question about HDFC mutual fund schemes.`
- Three example questions, clickable, pre-filling the box:
  1. What is the expense ratio of HDFC Large Cap Fund Direct Growth?
  2. What is the lock-in for HDFC ELSS Tax Saver Fund?
  3. How do I download a capital-gains statement?
- Persistent note under the title: `Facts-only. No investment advice.`
- One text input and a submit button. Enter submits.
- Answer region: sentences, one source link, last-updated line.
- A **RAG trace** disclosure, collapsed by default, so the demo can show stages without crowding the answer:
  - Normalized question and route: `answer` or `refuse` (and the refusal reason).
  - Top retrieved chunks: text snippet, scheme, section, source URL, similarity score.
  - Embedding model and LLM model ids used for that answer.
- Empty state before the first question: the welcome line and examples only.
- Error state if retrieval or the LLM call fails: one sentence, no fabricated fact, and the corpus source list link if the app has one.

Desktop and a narrow mobile width must both keep the disclaimer visible without scrolling past the input.

## 9. RAG pipeline

This is a teaching demo. Each stage writes files that a reviewer can open. The app reads those artifacts; it does not hide the pipeline inside one opaque call.

```
config → load → chunk → embed → chroma → retrieve → guard → generate
```

### 9.1 Phase 1 — Data loading

- Fetch each allowed URL over HTTPS.
- Store one JSON file per page in `data/raw/`.
- Fields: `url`, `title`, `publisher`, `scheme_or_topic`, `fetched_at` (UTC date), `text` (visible article text, not scripts), `content_hash`.
- Keep a `data/raw/manifest.json` listing every file.
- Strip navigation chrome, ads, and cookie banners as far as the parser allows. Keep tables: expense ratio, exit load, min SIP, and lock-in are often tabular.
- PDFs (factsheet, SID, KIM): extract text and store the same JSON shape plus `source_type: pdf`.
- Re-running load overwrites raw files and refreshes `fetched_at`. It does not append duplicates.

### 9.2 Phase 2 — Chunking

**Decision:** section-aware chunks with a metadata prefix, then a size cap. Fixed large windows are a poor fit: the facts are short, must stay tied to a scheme, and the embedding model only uses 256 tokens.

Rules:

1. Split each raw page on headings and on table rows that are self-contained facts.
2. Prefix every chunk with `AMC: HDFC Mutual Fund | Scheme: <name or AMC overview> | Section: <heading> | Source: <url>`.
3. Target chunk body under **180 tokens** so `all-MiniLM-L6-v2` does not silently truncate. If a section is longer, split on paragraph and then sentence boundaries with about **40 tokens** of overlap.
4. Never merge two schemes into one chunk.
5. Drop chunks that are only navigation, disclaimers repeated site-wide, or empty.

Write `data/chunks/chunks.jsonl`, one object per line:

`chunk_id`, `doc_id`, `text` (prefix + body), `scheme`, `section`, `source_url`, `fetched_at`, `token_count`.

Also write `data/chunks/stats.json`: chunk count, per-scheme counts, min/median/max token count, strategy name `section_prefix_v1`.

### 9.3 Phase 3 — Embedding

- Model: `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional vectors).
- The same model id is used for ingestion and query embedding. Both read it from config.
- Run locally. Do not send corpus text to Groq, Gemini, OpenAI, Anthropic, or Mistral for embedding.
- Persist a manifest at `data/embeddings/manifest.json`: model id, dimension, chunk count, chroma collection name, created_at. Vectors themselves live in Chroma so they are not duplicated as a second giant file. The manifest is the inspectable stage output.

### 9.4 Phase 4 — Vector store

- Engine: **ChromaDB**, persistent on disk (`data/chroma/` by default).
- Collection name from config (default `hdfc_mf_facts`).
- Metadata on each record: `chunk_id`, `scheme`, `section`, `source_url`, `fetched_at`, `doc_id`.
- Rebuild flag in config: when true, delete the collection and re-add from `chunks.jsonl`. When false, skip if the collection already matches the chunk count and embedding model in the manifest.
- Changing the embedding model always forces a rebuild.

### 9.5 Phase 5 — Retrieval

- Embed the user question with the same MiniLM model.
- Retrieve top **k = 4** chunks (config).
- Return chunk text, metadata, and distance/similarity.
- A chunk may be used as the citation only if its `source_url` is in the source list.
- If the best score is worse than the config threshold, do not invent an answer. Respond that the corpus does not contain that fact and cite the AMC overview or the matching scheme page.

### 9.6 Phase 6 — Generation

- The LLM sees: system rules (section 7 and section 10), the user question, and the retrieved chunks. It does not see the open web.
- It must select **one** of the retrieved URLs as the citation. It must not introduce a URL that was not retrieved or configured as the educational refusal link.
- Temperature stays low (default `0.1`) so numbers are copied, not paraphrased into new figures.

## 10. Safety and routing

Run these checks **before** the LLM call. Persist the route on the RAG trace.

| Check | If triggered | Stored? |
| --- | --- | --- |
| PII (PAN, Aadhaar, account number, OTP, email, phone) | Refuse. Ask the user to resend the question without the identifier. Cite the educational page. | Do not write the raw question to logs or traces. Store only `refused_pii` and a timestamp. |
| Advice or portfolio opinion | Refuse with the facts-only message. Cite the educational page. | Yes, redacted only if PII was present. |
| Performance, returns, comparison of funds | Refuse to compute. Link the official factsheet for the named scheme when we have one; otherwise the scheme page. | Yes. |
| In-scope fact | Retrieve and answer. | Yes. |

PII patterns are a gate, not a perfect detector. The README must say the gate is best-effort and that the app is not a place to paste identity documents.

No performance math anywhere in code: no CAGR, no ranking, no “higher return” strings produced from numbers in the pages.

## 11. Configuration

All switchable choices live in `config.yaml`. Secrets live only in `.env`, which is gitignored. `.env.example` lists keys without values.

`config.yaml` holds:

- `embedding_model` (default `sentence-transformers/all-MiniLM-L6-v2`)
- `chroma_path`, `chroma_collection`
- `chunk_strategy`, `chunk_max_tokens`, `chunk_overlap_tokens`
- `top_k`, `score_threshold`
- `llm_provider` (default `groq`)
- `corpus_urls` or a path to the source list
- `educational_url` for refusals
- `max_answer_sentences` (3)
- `rebuild_index`

`.env` holds:

- `GROQ_API_KEY` (required for the default provider)
- `LLM_MODEL` (required). The problem statement names `qwen/qwen3.8-27b`. That string is the initial example in `.env.example` and must be replaced with a model id the selected provider actually serves. Code reads `LLM_MODEL`; it does not hardcode the id.
- Optional keys, used only when `llm_provider` is switched: `GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `MISTRAL_API_KEY`.

Supported providers: **Groq (default), Gemini, OpenAI, Anthropic, Mistral.** Switching provider is a config change plus the matching API key. Embedding model and Chroma stay the same unless their config keys change.

If `LLM_MODEL` or the active API key is missing, the app fails at startup with a clear message. It does not fall back to a silent default model.

## 12. Suggested repository layout

```
config.yaml
.env.example
README.md
PRD.md
sources.md
sources.csv
sample_qa.md
data/raw/
data/chunks/
data/embeddings/manifest.json
data/chroma/
src/load.py
src/chunk.py
src/embed.py
src/retrieve.py
src/generate.py
src/guard.py
src/app.py
```

Phase commands, named so a reviewer can run one stage at a time:

1. `python -m src.load`
2. `python -m src.chunk`
3. `python -m src.embed` (writes Chroma + embedding manifest)
4. `python -m src.app` (retrieve + answer)

Each command prints the output path and the record count.

## 13. Submission deliverables

| Deliverable | Acceptance |
| --- | --- |
| Working prototype | Local app starts with the UI in section 8. If it cannot be hosted, a demo video of 3 minutes or less shows load → chunk → one factual answer → one refusal. |
| Source list | `sources.md` and `sources.csv`, 15 to 25 official URLs, including the five seeds. |
| README | Setup, env vars, phase commands, scope (HDFC AMC + four schemes), known limits. |
| Sample Q&A | `sample_qa.md` with 5 to 10 real runs: at least four factual answers and two refusals (one advice, one returns). Each entry has the question, the answer text, the single link, and the last-updated line. |
| Disclaimer | The snippet in section 7, visible in the UI and repeated in the README. |

## 14. Acceptance criteria

1. Asking the expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, or benchmark of an in-scope scheme returns a figure that appears in the cited chunk, with that chunk’s URL as the only link.
2. “Should I buy HDFC Flexi Cap?” returns the refusal shape and an educational link. It does not say yes or no.
3. “Which of these had higher returns?” returns no computed comparison and links a factsheet or scheme page.
4. A question containing a phone number or PAN-like string is refused and the raw string is absent from `data/` and server logs.
5. Answers stay within three sentences plus the source line and the last-updated line.
6. `data/raw`, `data/chunks/chunks.jsonl`, `data/embeddings/manifest.json`, and `data/chroma` all exist after the phase commands, and the UI trace shows the chunks used for the latest answer.
7. Changing `LLM_MODEL` in `.env` or `embedding_model` / `chroma_path` in `config.yaml` is sufficient to retarget those components. An embedding-model change rebuilds the index.
8. No source URL in `sources.md` is a blog, forum, or news article.

## 15. Known limits (also state these in the README)

- Figures go stale when the AMC updates a page. Freshness is the `fetched_at` date, not a live quote.
- Direct-plan pages are in scope. Regular-plan variants are not, unless a seed page states both and the chunk keeps them distinct.
- Statement download steps describe the public help flow. The assistant cannot fetch a user’s statement.
- MiniLM is a small English model. Odd paraphrases may miss. The trace exists so a miss is visible.
- The PII gate is pattern-based and will miss novel formats. Users should still not paste identity data.
- Groww page markup can change. Load failures are reported per URL; the rest of the corpus still indexes.
- The assistant is not a SEBI-registered adviser, and the UI must not look like one.

## 16. Skills this build is meant to show

- **W1 — Thinking like a model:** route each question to answer or refuse before generation; extract the single fact asked.
- **W2 — LLMs and prompting:** short answers, polite refusals, citation wording fixed by the answer contract.
- **W3 — RAG:** small corpus, inspectable chunks, one accurate official citation per answer. No tool use beyond this corpus.

## 17. Implementation order

1. Config, `.env.example`, and source-list skeleton.
2. Load the five seed pages and expand to 15–25 official URLs.
3. Chunk with `section_prefix_v1` and write stats.
4. Embed into Chroma and write the manifest.
5. Guards, then generation against the answer contract.
6. Tiny UI plus collapsed RAG trace.
7. README, disclaimer, and `sample_qa.md` from live runs.
