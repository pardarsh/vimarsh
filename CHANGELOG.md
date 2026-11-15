# Changelog

## 0.1.0 (unreleased)

* Daily discovery of new and amended bills from the official sansad.in
  listings, using the latest official text of each bill.
* Local PDF/HTML text extraction (pypdf, Beautiful Soup).
* Provider-agnostic `LLMProvider` interface with Gemini (default
  `gemini-3.8-flash`) and Groq adapters, structured JSON output validated with
  Pydantic, retries with exponential backoff on 429/503, fallback chain,
  request spacing, per-run cap and token guardrails with partial analyses.
* Idempotent state in `data/manifest.json`; failures stay pending.
* One Markdown file per bill with YAML frontmatter recording source URL,
  document and text hashes, provider, model, prompt and schema versions and
  analysis time.
* Static site, RSS feed and `bills.json` for GitHub Pages.
* Separate analysis and deploy workflows, CI, pre-commit hooks, Dependabot,
  issue and PR templates, CONTRIBUTING, Code of Conduct and SECURITY.
