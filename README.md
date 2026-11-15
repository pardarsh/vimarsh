# Vimarsh

Vimarsh (विमर्श, "deliberation") publishes neutral, plain-language analysis of
bills in the Parliament of India. A daily GitHub Actions job reads the
official bill listings on [sansad.in](https://sansad.in), downloads the latest
official text of each new or amended bill, extracts the text locally, asks a
language model for a structured analysis, and commits the result to this
repository. A second workflow builds a static site, an RSS feed and a JSON
index, and publishes them on GitHub Pages.

In keeping with [Pardarsh](https://github.com/pardarsh), every analysis is
attributed and checkable: each file records the official document URL, the
SHA-256 of the document and of the extracted text, the provider, the requested
and served model, the response ID, generation settings (temperature, thinking
level), token usage including thinking tokens, latency, attempts and any
fallback, the prompt and schema versions with a hash of both (the prompt itself
is published on the site's Method page), software versions, a link to the
GitHub Actions run, and the model's own summary of its reasoning when the
provider returns one.

## How it works

```text
sansad.in listings ──► sources.py ──► data/manifest.json (state, in git)
                                         │ pending bills (max 15 per run)
                                         ▼
official PDF ──► extract.py ──► providers/router.py ──► Gemini ─(429/503 ×3)─► Groq
                                         │
                                         ▼
                      content/bills/<year>/<bill-id>.md (YAML frontmatter + Markdown)
                                         │  deploy workflow
                                         ▼
                      public/ (index, bill pages, feed.xml, bills.json) ──► GitHub Pages
```

* **Sources.** Only sansad.in. `api_rs/legislation/getBills` lists bills from
  both houses; `api_ls/legislation/getBills` is also read and skipped with a
  warning if it fails. For each bill the most recent text is used (passed by
  both houses, passed by one house, or as introduced).
* **State.** `data/manifest.json` tracks each bill's `status` (`pending`,
  `processed`, `failed`, `skipped_oversized`), `version_hash` (SHA-256 of the
  document), `source_url`, attempts, last error and `last_updated`. A bill is
  analysed again only when a new document is published and its bytes differ,
  so reruns cost nothing. When only a bill's listing details change (for
  example its status goes from Passed to Assented), its page is updated
  without calling the model again.
* **Providers.** `LLMProvider.analyze_bill(text, schema) -> AnalysisResult`
  in `src/vimarsh/providers/base.py`, with adapters for Gemini
  (`google-genai`) and Groq (`groq`). Output is validated with Pydantic.
  Transient errors (429, 503) are retried three times with exponential
  backoff, then the fallback provider is tried. If every provider fails, the
  bill stays `pending` and is retried on the next run; the run never crashes.
* **Guardrails.** Calls are spaced by `REQUEST_DELAY_SECONDS`. Tokens are
  estimated locally (about four characters per token) before each call. Text
  over a provider's input budget is cut to its beginning and end (clauses,
  Statement of Objects and Reasons, Financial Memorandum) and the result is
  marked `partial_analysis: true`.

## Configuration

Set these as repository variables (Settings → Secrets and variables →
Actions → Variables); all are optional.

| Variable | Default | Meaning |
| --- | --- | --- |
| `PRIMARY_PROVIDER` | `gemini` | First provider (`gemini` or `groq`) |
| `FALLBACK_PROVIDER` | `groq` | Second provider, or `none` |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Gemini model id |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model id |
| `GEMINI_THINKING_LEVEL` | `low` | Gemini thinking level; `none` to omit it |
| `REQUEST_TIMEOUT_SECONDS` | `300` | Give up on a model call after this long (then retry or fall back); also Gemini's server-side deadline |
| `MAX_CONSECUTIVE_FAILURES` | `2` | Stop a run after this many bills in a row fail on every provider |
| `REQUEST_DELAY_SECONDS` | `12` | Minimum gap between API calls |
| `MAX_BILLS_PER_RUN` | `15` | Bills analysed per run; the rest stay pending |
| `MAX_RETRIES` | `3` | Retries on 429/503 before falling back |
| `SINCE_DATE` | `2026-01-01` | Ignore bills introduced earlier |
| `GEMINI_MAX_INPUT_TOKENS` | `120000` | Truncate above this for Gemini |
| `GROQ_MAX_INPUT_TOKENS` | `8000` | Truncate above this for Groq |
| `SITE_URL` | `https://vimarsh.pardarsh.9th.fun/` | Absolute URL used in the feed |

API keys go only in **secrets**: `GEMINI_API_KEY` and `GROQ_API_KEY`. They are
never written to the repository or the site. Only public bill texts are sent
to the providers.

## Run it locally

```bash
python -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

```bash
GEMINI_API_KEY=... MAX_BILLS_PER_RUN=1 vimarsh run
```

```bash
vimarsh build --out public
```

Open `public/index.html` in a browser.

## Deploying

1. In Settings → Pages, set the source to **GitHub Actions** and the custom
   domain to `vimarsh.pardarsh.9th.fun` (the `CNAME` file), with a DNS
   `CNAME` record pointing `vimarsh.pardarsh` at `pardarsh.github.io`. Tick
   **Enforce HTTPS** once the certificate is issued.
2. Add the `GEMINI_API_KEY` (and optionally `GROQ_API_KEY`) secrets.
3. Run **Analyze bills (daily)** once by hand, or wait for its daily run at
   02:30 UTC (08:00 IST).

There are three workflows:

* **Analyze bills (daily)** (`analyze.yml`): every day, and by hand, analyses
  up to `MAX_BILLS_PER_RUN` pending bills, newest first, introduced on or
  after `SINCE_DATE`.
* **Analyze specific bills** (`analyze-bills.yml`): by hand only. Enter bill
  IDs (the file name under `content/bills/`, for example `ls-2026-97`), tick
  **force** to redo an already-analysed bill, and set **since_date** for bills
  introduced before `SINCE_DATE`. Locally: `vimarsh run --bill ls-2026-97 --force`.
* **Deploy site** (`deploy.yml`): runs after either of the above and on pushes
  to `master`; it never commits, so it cannot trigger an analysis loop.

Both analysis workflows run the same job (`_analyze.yml`), never at the same
time, and commit only `data/` and `content/`: at most once per run, and only
when at least one bill was analysed.

## Test

```bash
pytest
```

```bash
pre-commit run --all-files
```

## License

MIT; see [LICENSE.txt](LICENSE.txt). Bill texts are published by the
Parliament of India.
