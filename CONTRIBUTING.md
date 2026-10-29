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

## How to contribute a change

`main` is protected: every change goes in through a pull request from a fork, and CI must pass before it can
be merged.

### 1. Fork and clone

Click **Fork** on [github.com/mpk-droid/SimCrew](https://github.com/mpk-droid/SimCrew), then:

```bash
git clone https://github.com/<your-username>/SimCrew.git
cd SimCrew
git remote add upstream https://github.com/mpk-droid/SimCrew.git
```

### 2. Create a branch

Start from the latest upstream `main`, one branch per change:

```bash
git fetch upstream
git switch -c my-change upstream/main
```

### 3. Make your change and run the checks

See [Local Development](README.md#local-development) for running the app, and [AGENTS.md](AGENTS.md) for the
repo layout and conventions. Before you push, run the same checks CI runs:

```bash
# Backend: lint and tests
cd backend && uv run --extra dev ruff check app && uv run --extra dev pytest -q && cd ..

# Frontend: clean install, type check, build
cd frontend && npm ci && npx tsc --noEmit && npm run build && cd ..

# Helm chart (if you changed chart/)
helm lint chart
```

To validate a change end to end, use the built-in smoke test: the **Smoke Test Journey** with the
**Alex**, **Blake**, and **Casey** test personas against
`https://github.com/mpk-droid/synthetic-users-smoke-test.git`. It's faster and cheaper than the full DX
evaluation.

### 4. Commit with a sign-off

Every commit must be signed off to certify the [Developer Certificate of Origin](https://developercertificate.org/)
(that you wrote the change or have the right to submit it under the project's license). Use `-s`:

```bash
git commit -s -m "Explain what changed and why"
```

The sign-off must match the commit author's name and email (`git config user.name` and `user.email`). CI
checks every commit in the pull request.

Forgot to sign off? Fix the commits on your branch and push again:

```bash
git rebase --signoff upstream/main
git push --force-with-lease
```

### 5. Push to your fork and open a pull request

```bash
git push -u origin my-change
```

GitHub prints a link to open the pull request, or use **Contribute → Open pull request** on your fork. Target
`mpk-droid/SimCrew` `main`. Fill in the template: what changed, why, and how you tested it. Update the README
or docs if you change behavior, configuration, or the API.

### 6. CI and review

- CI runs four checks: `backend`, `frontend`, `chart`, and `dco`. All four must pass.
- On your first pull request, CI waits until the maintainer approves the run. That's a GitHub safeguard for
  new contributors, not a problem with your change.
- The maintainer is requested for review automatically. Address comments by pushing more commits to the
  same branch (signed off). All review conversations must be resolved before merging.
- If `main` moves on, update your branch with `git fetch upstream && git rebase upstream/main`, then
  `git push --force-with-lease`.

The maintainer merges once checks pass and review is done.

## License

By contributing, you agree that your contributions are licensed under the [Apache License 2.0](LICENSE),
the same license as the project.

## Code of conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you agree to uphold it.
