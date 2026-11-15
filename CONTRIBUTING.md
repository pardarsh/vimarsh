# Contributing to Vimarsh

Thanks for helping make parliamentary bills easier to read. Please follow the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules

* **Official sources only.** Bill listings and texts come from sansad.in. Do
  not add third-party summaries or aggregators as sources.
* **Provenance is not optional.** Every analysis records the official
  document URL, SHA-256 hashes of the document and extracted text, the
  provider and exact model, the prompt and schema versions and the time. Do
  not remove or weaken these fields.
* **Version what the model sees.** Any change to `SYSTEM_PROMPT`,
  `build_prompt` or `AnalysisResult` in `src/vimarsh/providers/base.py` must
  bump `PROMPT_VERSION` or `SCHEMA_VERSION`.
* **Neutrality.** The prompt asks the model to describe, not judge. Keep it
  that way, and do not add labels or rankings that imply a verdict on a bill.
* **Never crash the daily run.** A bad bill or a provider outage leaves the
  bill `pending` (or `failed`) in `data/manifest.json`; it must not stop
  other bills or the commit step.
* **Keys stay secret.** API keys live only in GitHub Actions secrets and are
  read only in `src/vimarsh/config.py`.

## Setup

```bash
python -m venv .venv
```

```bash
.venv/bin/pip install -e ".[dev]"
```

Install the git hooks once:

```bash
pre-commit install
```

This runs file-hygiene checks, ruff (lint and format) and djLint on the Jinja
templates on commit, and `pytest` on push.

## Adding a provider

Subclass `LLMProvider` in `src/vimarsh/providers/`, map the SDK's errors to
`TransientProviderError` (429/503), `InputTooLargeError` (413) or
`ProviderError`, validate the response with `parse_result`, and register it in
`build_providers` in `router.py`. Add tests with a fake client; tests never
call a real API.

## Before opening a pull request

```bash
pre-commit run --all-files
```

```bash
pytest
```

CI runs the same commands on Python 3.12 and 3.13, plus a site build.

## Commits and reviews

Use conventional commit prefixes (`feat:`, `fix:`, `docs:`, `chore:`, `ci:`,
`refactor:`, `test:`) with an imperative summary. Keep pull requests focused.

## Security

Do not report vulnerabilities in public issues; see [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contributions are licensed under the MIT
License (see `LICENSE.txt`).
