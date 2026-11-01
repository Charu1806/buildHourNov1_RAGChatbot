# Implementation: HDFC Mutual Fund Facts FAQ

**Source:** `architecture.md`  
**Stack:** Python 3.11, FastAPI, BeautifulSoup, `sentence-transformers/all-MiniLM-L6-v2`, Chroma, one LLM provider (Groq by default).

Ingestion writes each stage to disk and does not call an LLM. A question is classified before retrieval. The model runs only when the question is an in-scope fact and a retrieved chunk is above the score threshold.

```
sources.csv → data/scraped → data/raw → data/chunks → data/chroma → POST /api/ask → UI
```

Commands:

```
python -m src.scrape
python -m src.load
python -m src.chunk
python -m src.embed
python -m src.app
```

Paths resolve from the repo root. `.env` is gitignored. Ingestion runs without an API key. `src.app` requires `LLM_MODEL` and the key for `llm_provider`.

---

## 1. Creating the directory

```
config.yaml
.env.example
sources.csv
requirements.txt
src/__init__.py
src/config.py
src/sources.py
src/scrape.py
src/load.py
src/chunk.py
src/embed.py
src/retrieve.py
src/guard.py
src/prompts.py
src/llm.py
src/generate.py
src/app.py
src/static/index.html
data/scraped/
data/raw/
data/chunks/
data/embeddings/
data/chroma/          gitignored
tests/
```

`requirements.txt`: `pyyaml`, `python-dotenv`, `httpx`, `beautifulsoup4`, `lxml`, `pypdf`, `sentence-transformers`, `chromadb`, `fastapi`, `uvicorn`, `groq`, `openai`, `anthropic`, `google-genai`, `mistralai`, `pytest`.

`.gitignore`: `.env`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `data/chroma/`, `.cache/`.

`config.yaml`:

```yaml
embedding_model: sentence-transformers/all-MiniLM-L6-v2
chroma_path: data/chroma
chroma_collection: hdfc_mf_facts
chunk_strategy: section_prefix_v1
chunk_max_tokens: 180
chunk_overlap_tokens: 40
top_k: 4
score_threshold: 0.35
llm_provider: groq          # groq | gemini | openai | anthropic | mistral
llm_temperature: 0.1
llm_max_tokens: 300
sources_path: sources.csv
educational_url: ""         # set to the SEBI or AMFI row in sources.csv
max_answer_sentences: 3
rebuild_index: false
allowed_hosts:
  - groww.in
  - hdfcfund.com
  - sebi.gov.in
  - investor.sebi.gov.in
  - amfiindia.com
  - camsonline.com
  - kfintech.com
```

`.env.example`:

```
GROQ_API_KEY=
LLM_MODEL=qwen/qwen3.8-27b
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
MISTRAL_API_KEY=
```

`src/config.py` exposes `load_settings(require_llm=False)`. Scrape, load, chunk, and embed pass `False`. The app passes `True`, and then requires a non-empty `LLM_MODEL`, the matching API key, an `educational_url` that appears in `sources.csv`, and an embedding manifest whose model id matches config.

Provider keys: Groq `GROQ_API_KEY`, Gemini `GEMINI_API_KEY`, OpenAI `OPENAI_API_KEY`, Anthropic `ANTHROPIC_API_KEY`, Mistral `MISTRAL_API_KEY`. No model id is hardcoded in Python.

---

## 2. Scraping documents

`src/scrape.py` fetches only the rows in `sources.csv` and saves the response body. It does not parse, chunk, or follow links. Cap the file at 25 data rows.

Columns: `id`, `title`, `url`, `publisher`, `scheme_or_topic`, `fetched_at`, `why_included`.

Seed rows:

| id | url | why_included |
| --- | --- | --- |
| `hdfc-amc` | https://groww.in/mutual-funds/amc/hdfc-mutual-funds | `seed` |
| `hdfc-large-cap` | https://groww.in/mutual-funds/hdfc-large-cap-fund-direct-growth | `seed` |
| `hdfc-flexi-cap` | https://groww.in/mutual-funds/hdfc-equity-fund-direct-growth | `seed` |
| `hdfc-elss` | https://groww.in/mutual-funds/hdfc-elss-tax-saver-fund-direct-plan-growth | `seed` |
| `hdfc-mid-cap` | https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth | `seed` |

After the first scrape, add official rows by hand until there are 15–25 URLs: scheme facts missing from a seed (`scheme-fact`), a factsheet or SID PDF (`factsheet`), a statement-download help page (`statement-help`), and one SEBI or AMFI education page (`education`). Set `educational_url` to that education URL. Hosts outside `allowed_hosts` are skipped.

For each row:

1. Pause 0.5s. GET with `httpx` (timeout 20s, follow redirects, browser User-Agent). Retry once on 429 or 5xx.
2. If the final host is not allowlisted, record `error` / `off-host` and write no body file.
3. On success, save the bytes unchanged: `data/scraped/<id>.html` or `data/scraped/<id>.pdf`.
4. A timeout or HTTP error is `error`. Write no body file.

`data/scraped/manifest.json` lists every CSV id once with `url`, `status` (`ok` or `error`), `source_type` (`html` or `pdf`), `path`, and `fetched_at`. Re-running scrape overwrites the same file. Write `fetched_at` back onto the ok rows in `sources.csv`.

---

## 3. Loading the document

`src/load.py` runs after scrape and before chunking. It reads `data/scraped/` and writes one cleaned document per page to `data/raw/<id>.json`. Chunking reads only these documents. It does not open the network.

For each manifest row with `status: ok`:

1. PDF: extract text with `pypdf`. Use outline titles as headings, or one section per page named `Page N`.
2. HTML: parse with BeautifulSoup. Drop `script`, `style`, `nav`, `footer`, and cookie banners. Headings `h1`–`h3` start sections. Tables become `cell: cell` lines.
3. If the extracted text is at least 200 characters, write the document. If it is shorter, record `thin` and do not write a body file.

Document fields: `id`, `url`, `title`, `publisher`, `scheme_or_topic`, `fetched_at` (UTC `YYYY-MM-DD`), `source_type` (`html` or `pdf`), `text`, `sections` (`heading`, `text`), `content_hash` (sha256 of `text`).

`data/raw/manifest.json` lists every scraped id once with `status` `ok`, `thin`, or `error`. Re-running load overwrites the same `<id>.json`.

A Groww page that is only a script shell stays `thin`. Add the official AMC or factsheet URL to the CSV, scrape again, then load again.

---

## 4. Chunking

`src/chunk.py` reads ok documents from `data/raw/` and writes `data/chunks/chunks.jsonl` and `data/chunks/stats.json`. Strategy name: `section_prefix_v1`. Token counts use the MiniLM tokenizer, not a character estimate.

For each section:

1. If the heading is generic (`Article`, `Overview`, `Fund details`) and a line is a single fact, split that line into its own section. Fact labels: expense ratio, exit load, minimum SIP, lock-in, riskometer, benchmark.
2. Prefix every chunk:

```text
AMC: HDFC Mutual Fund | Scheme: {scheme_or_topic} | Section: {heading} | Source: {url}
```

3. `text` is `prefix + "\n" + body`. If that is within `chunk_max_tokens` (180), emit one chunk.
4. Otherwise split the body on paragraphs, then sentences, then token windows. Start the next chunk with the last `chunk_overlap_tokens` (40) of the previous body, and repeat the prefix.
5. Drop empty bodies, cookie or “download the app” lines, and the standard market-risk sentence when it contains no fact label.
6. `scheme` on the chunk is always the parent document’s `scheme_or_topic`. Two schemes never share a chunk.

`chunk_id` is `{doc_id}#{heading-slug}#{n}`.

JSONL fields: `chunk_id`, `doc_id`, `text`, `scheme`, `section`, `source_url`, `fetched_at`, `token_count`.

`stats.json`: `strategy`, `chunk_count`, `skipped_docs`, `per_scheme`, `min_tokens`, `median_tokens`, `max_tokens`. Exit with an error if `max_tokens` is above the cap or there are zero chunks.

The prefix counts toward the 180-token cap so MiniLM’s 256-token window does not cut off a number.

---

## 5. Embedding

`src/embed.py` embeds locally. Corpus text is not sent to Groq, Gemini, OpenAI, Anthropic, or Mistral.

1. Read `chunks.jsonl` in order.
2. `chunk_set_hash` is sha256 of `chunk_id + sha256(text)` for each row.
3. Skip the encode when `rebuild_index` is false, the manifest model id matches config, the chunk count matches, `chunk_set_hash` matches, and the Chroma collection count matches. Print `skip`.
4. Otherwise `SentenceTransformer(embedding_model).encode(..., normalize_embeddings=True)` on CPU, batch size 32.
5. Require shape `(n, 384)`. A failed download or a wrong dimension leaves the existing collection untouched.

`data/embeddings/manifest.json`:

```json
{
  "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
  "dimension": 384,
  "chunk_count": 0,
  "chunk_set_hash": "",
  "chroma_collection": "hdfc_mf_facts",
  "created_at": ""
}
```

Vectors are not written to a second file. Changing `embedding_model` always rebuilds.

---

## 6. Storing data in the vector DB

Chroma persistent client at `chroma_path`, collection `hdfc_mf_facts`, space `cosine` (`hnsw:space = cosine`).

| Chroma field | Value |
| --- | --- |
| id | `chunk_id` |
| document | prefixed `text` |
| metadata | `chunk_id`, `scheme`, `section`, `source_url`, `fetched_at`, `doc_id` (all strings) |

Rebuild writes collection `{name}__next` first. Only after its count equals the chunk count does the code delete the live collection, recreate it, and add the same in-memory vectors. Then it deletes `__next` and writes the manifest. A crash during encode does not delete the live index.

Add in batches of 64.

---

## 7. Retrieval logic

`src/retrieve.py` loads MiniLM from the manifest. If that id differs from `config.yaml`, the app exits and tells the user to re-run `src.embed`.

1. Encode the raw question. Do not add the chunk prefix.
2. Query top `k` (4) with documents, metadatas, and distances.
3. `similarity = 1 - distance`.
4. Drop hits whose `source_url` is not in `sources.csv`.
5. Sort by similarity descending.

If the best similarity is below `score_threshold` (0.35), do not call the LLM. Reply that the fact was not in the fetched pages. Cite the named scheme’s seed row, or the AMC overview when no scheme was named.

If the score passes, `src/generate.py` sends `src/prompts.py` plus the question and the four chunks to `src/llm.py`. Temperature `0.1`, max tokens `300`. One provider, selected by `llm_provider`. No fallback.

The model must return at most three sentences, one `Source:` URL copied from the chunks, and `Last updated from sources: YYYY-MM-DD` equal to that chunk’s `fetched_at`. `check_draft` rejects the draft when:

- there is more than one URL, or the URL was not retrieved
- the date does not match `fetched_at`
- a number in the body is not a substring of the cited chunk
- there are more than three sentences

On failure, retry once with the check errors appended. A second failure becomes HTTP 503. The failed draft is not returned. The displayed source title comes from `sources.csv`.

`python -m src.retrieve "question"` prints hits and does not call the LLM.

---

## 8. UI

`src/app.py` serves `src/static/index.html` on `127.0.0.1:8000`. No frontend build. The page talks only to its own origin.

| Method | Path | Role |
| --- | --- | --- |
| `GET /` | The page | |
| `POST /api/ask` | `{"question": "..."}` | |
| `GET /sources.csv` | Source list linked from the error state | |

Page order, one column, max width `40rem`:

1. `Ask a factual question about HDFC mutual fund schemes.`
2. Disclaimer, always above the input: `Facts-only. No investment advice. Answers are short quotations from official public pages, with one source link. This is not a recommendation to buy, sell, or hold any scheme.`
3. Three buttons that only fill the input:
   - What is the expense ratio of HDFC Large Cap Fund Direct Growth?
   - What is the lock-in for HDFC ELSS Tax Saver Fund?
   - How do I download a capital-gains statement?
4. One text field. Enter submits.
5. Answer: sentences, one `Source:` link, `Last updated from sources:` line.
6. `<details>` titled `How this answer was built`, closed by default. Shows route, reason, embedding model, LLM model, and each chunk’s snippet (400 chars), scheme, section, URL, and similarity.

Empty question: HTTP 400, `Enter a question.` Provider or checker failure: HTTP 503, `I could not produce a sourced answer just now.` and a link to `/sources.csv`.

Response JSON:

```json
{
  "route": "answer",
  "reason": "in_scope",
  "sentences": [],
  "source": {"title": "", "url": ""},
  "last_updated": "YYYY-MM-DD",
  "trace": {
    "question": "",
    "route": "answer",
    "reason": "in_scope",
    "embedding_model": "",
    "llm_model": "",
    "chunks": []
  }
}
```

`route` is `answer` or `refuse`. When `reason` is `pii`, `trace` is `null`.

Ask-path order inside `POST /api/ask`:

1. `guard.classify`
2. PII, advice, performance, or out-of-scope: return the template. Do not retrieve. Do not call the LLM.
3. Else retrieve.
4. Below threshold: template, include the weak hits in the trace.
5. Else generate and check.

Refusal sentences:

| Reason | Text | Link |
| --- | --- | --- |
| `pii` | Please resend your question without account numbers, identity numbers, email addresses, or phone numbers. | `educational_url` |
| `advice` | I can only share published facts about HDFC schemes, not whether you should buy, sell, or hold. | `educational_url` |
| `out_of_scope` | I only cover published facts for HDFC Mutual Fund and its Large Cap, Flexi Cap, ELSS Tax Saver, and Mid Cap direct schemes. | `educational_url` |
| `performance` | I do not calculate or compare returns. Published performance figures are on the official factsheet. | That scheme’s `factsheet` row, else its scheme page, else the AMC page |
| `below_threshold` | I could not find that fact in the fetched official pages. | Named scheme page, or the AMC page |

`last_updated` on a template is the `fetched_at` of the cited CSV row.

---

## 9. Guardrails: edge cases and test cases

`src/guard.py` classifies in this order. First match wins. The LLM does not classify.

| Order | Reason | Match |
| --- | --- | --- |
| 1 | `pii` | Email, Indian mobile, PAN `AAAAA9999A`, 12-digit Aadhaar, a 9+ digit account run, or `otp` next to 4–8 digits |
| 2 | `advice` | should I, buy, sell, hold, switch, invest, is this good, which is best, allocate, portfolio, recommend |
| 3 | `performance` | return, CAGR, performance, alpha, ranking, beating, higher return, did better, outperform |
| 4 | `out_of_scope` | Another AMC is named (SBI, ICICI, Axis, Nippon, Kotak, Mirae, Parag Parikh, Quant, UTI, Tata, Aditya Birla, DSP, Franklin, Motilal), or no HDFC scheme is named |
| 5 | `in_scope` | Anything left, including expense ratio, exit load, minimum SIP, lock-in, riskometer, benchmark, and statement download |

Statement download (`statement` plus `download`, `capital gain`, or `cas`) stays `in_scope` even with no scheme name. `compare` alone is not a performance match, so an expense-ratio question is not refused as returns.

Scheme aliases: `large cap`, `flexi cap`, `equity fund` (same flexi-cap scheme as the seed URL), `elss` / `tax saver`, `mid cap`, `hdfc mutual fund`.

PII handling: do not embed the question, do not put it in the response, do not write it under `data/`. Log only `refused_pii` and a timestamp.

No code path computes CAGR, ranking, or a “higher return” string.

### Cases the tests must cover

`tests/test_guard.py`, in-memory source list, no network:

| Question | Expected reason | Also assert |
| --- | --- | --- |
| `Should I buy HDFC Flexi Cap?` | `advice` | Body does not say yes or no. Link is the education URL. |
| `Is HDFC Mid Cap a good hold?` | `advice` | `hold` matches even though a scheme is named. |
| `Which of these had higher returns?` | `performance` | Link is a factsheet or scheme page. No percentage is added by the template. |
| `What is the CAGR of HDFC Large Cap?` | `performance` | Checked before the fact path. |
| `Expense ratio of HDFC Large Cap, my PAN is ABCDE1234F` | `pii` | PAN is checked before the fact path. `repr(decision)` does not contain the PAN. |
| `Call me on 9876543210 about the exit load` | `pii` | |
| `OTP is 123456` | `pii` | |
| `What is the exit load of SBI Bluechip?` | `out_of_scope` | |
| `What is an exit load?` | `out_of_scope` | No scheme named. |
| `What is the lock-in for HDFC ELSS Tax Saver?` | `in_scope` | |
| `How do I download a capital-gains statement?` | `in_scope` | No scheme required. |
| `Compare the expense ratio of HDFC Large Cap and HDFC Mid Cap` | `in_scope` | Not treated as a returns question. The later answer check still allows only one URL. |

`tests/test_answer_check.py`:

| Draft | Expected |
| --- | --- |
| ≤3 sentences, one retrieved URL, matching `fetched_at`, number present in that chunk | Accept |
| Two URLs | Reject |
| URL that was not retrieved | Reject |
| Date other than the chunk’s `fetched_at` | Reject |
| A number that does not appear in the cited chunk | Reject |
| Four sentences | Reject |

`tests/test_app.py` uses FastAPI `TestClient` with `Retriever.search` and `ChatModel.complete` patched:

| Case | Expected |
| --- | --- |
| Advice question | `route: refuse`, `reason: advice`, education URL, `complete` not called |
| PAN question | `trace: null`, response body has no PAN, `search` not called |
| Patched retrieval below 0.35 | `reason: below_threshold`, `complete` not called |
| Patched good hit and a valid draft | `route: answer`, one source link |
| `complete` raises, or the draft fails twice | HTTP 503, body is the fixed error sentence, draft text absent |

`tests/test_chunk.py` uses a fixture file, no network: every chunk’s token count is within the cap, the prefix contains the scheme and URL, and a two-scheme fixture never produces a chunk that contains both scheme names.
