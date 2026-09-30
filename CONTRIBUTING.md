# Contributing to SimCrew

Thanks for your interest in SimCrew. Bug reports, persona and journey ideas, docs fixes, and code are all
welcome.

SimCrew has a single maintainer ([MAINTAINERS.md](MAINTAINERS.md)), so reviews may take a few days. Small,
focused pull requests get merged fastest.

## Reporting issues

- **Bugs:** open a GitHub issue with what you ran, what you expected, and what happened. Include the run ID,
  persona, journey, and target repo if the bug is about a run.
- **Findings SimCrew got wrong:** include the finding text and its evidence. False positives and missed
  bugs are both useful.
- **Security vulnerabilities:** don't open a public issue. See [SECURITY.md](SECURITY.md).

## Before you start on a larger change

Open an issue first for new features, API changes, or anything touching the orchestrator, triage, or scoring.
Agreeing on the approach up front saves you from rework.

## Development setup

See [Local Development](README.md#local-development) in the README, and [AGENTS.md](AGENTS.md) for the repo
layout, commands, and conventions.

Before you open a pull request:

```bash
# Backend lint and format
cd backend && uv run ruff check app/ && uv run ruff format --check app/

# Frontend build (includes type checking)
cd frontend && npm run build
```

When you validate a change end to end, use the built-in smoke test (the **Smoke Test Journey** with the
**Alex**, **Blake**, and **Casey** test personas) instead of the full DX evaluation. It's faster and cheaper.

## Pull requests

- Branch from `main` and keep each PR to one logical change.
- Explain what changed and why, and how you tested it.
- Update the README or docs if you change behavior, configuration, or the API.
- Sign off every commit to certify the [Developer Certificate of Origin](https://developercertificate.org/):

  ```bash
  git commit -s -m "Your message"
  ```

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE),
the same license as the project.

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.
