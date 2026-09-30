# Security Policy

## Supported versions

SimCrew is pre-1.0. Only the latest commit on `main` receives security fixes.

## Reporting a vulnerability

Don't open a public issue for security problems. Report them privately through
[GitHub private vulnerability reporting](https://github.com/mpk-droid/SimCrew/security/advisories/new).

Include what's affected, steps to reproduce, and the impact you see. The maintainer will acknowledge the
report within a few business days and keep you updated until it's resolved.

## Scope notes

SimCrew clones untrusted repositories and runs LLM-driven agents that execute shell commands inside
containers. Reports about container isolation, credential exposure (for example, LLM API keys reaching agent
containers or run logs), and injection through target repository content are especially welcome.
