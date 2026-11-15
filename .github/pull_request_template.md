## Summary

<!-- What changes for readers of the site, the feed or the data? -->

## Motivation

<!-- Why is this change needed? Link the issue if there is one. -->

## Changes

<!-- Briefly describe the implementation. -->

## Testing

- [ ] `pre-commit run --all-files`
- [ ] `pytest`
- [ ] `vimarsh build` renders the site

## Checklist

- [ ] Only official, first-party sources (sansad.in) are used
- [ ] Provenance is still recorded for every analysis (source URL, hashes, provider, model, prompt and schema versions, time)
- [ ] `PROMPT_VERSION` / `SCHEMA_VERSION` bumped if the prompt or schema changed
- [ ] No API keys or `.env` files committed
- [ ] `README.md` and `CHANGELOG.md` updated where relevant
