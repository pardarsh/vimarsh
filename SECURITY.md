# Security policy

## Reporting a vulnerability

Please do not open a public issue. Report privately through GitHub's
[private vulnerability reporting](https://github.com/pardarsh/vimarsh/security/advisories/new),
with steps to reproduce, the affected commit and the impact.

## Supported versions

Vimarsh is pre-release. Only the latest commit on the default branch receives
fixes.

## What is especially sensitive

* Leaking `GEMINI_API_KEY`, `GROQ_API_KEY` or any other secret, for example
  through logs, committed files or the published site.
* Anything that lets a third party change what is published: tampering with
  `data/` or `content/`, a source other than sansad.in, or a workflow that
  runs untrusted code with write permissions.
* Prompt injection through bill text that makes the published analysis
  misrepresent the official text.
