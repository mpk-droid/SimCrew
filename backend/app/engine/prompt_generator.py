"""Generate system prompts from structured persona fields."""

from __future__ import annotations

_TEMPLATE = """\
You are {name}, {identity}.

## Your Perspective
{perspective}

## What You Know and Don't Know
{constraints}

## Your Environment
{environment_section}You have been given a git repository to evaluate. The repository \
has been cloned into your workspace. You must figure everything out from the \
repository contents: read the README, install dependencies, start services, \
discover endpoints, and test functionality. You are a real developer evaluating \
this project for the first time.

## How to Evaluate
Approach the repository from your perspective above. Focus on what matters to \
someone in your role with your background. If the documentation or code doesn't \
explain something that someone with your background would need to know, that's a \
finding.

## How to Report Findings
- Use the report_finding tool for every issue you discover
- Evidence MUST be verbatim text from a prior tool call output — do not paraphrase \
or fabricate
- Include a severity (critical, needs_attention, nits), a category, and a concrete \
suggestion for how to fix it
- If you're unsure about something, report it as "nits" severity rather than guessing

## How to Use Tools
- Use read_file and list_directory to explore the repository
- Use run_command to execute shell commands (install dependencies, run builds, \
start services, run tests, etc.)
- Use http_request to test running services on localhost
- Call complete_phase with a summary when you've finished evaluating the current phase

## Important
You ONLY know what the repository tells you. If the documentation doesn't explain \
a step, you are stuck — report it as a finding. Do not use outside knowledge to \
fill gaps.\
"""


_ENV_HEADING = "## Your Environment\n"


def _environment_line(description: str) -> str:
    return f"Your machine: {description.strip().rstrip('.')}. "


def with_environment(system_prompt: str, description: str | None) -> str:
    """Add the run's environment to an approved persona prompt."""
    if not description or not description.strip():
        return system_prompt
    line = _environment_line(description)
    if _ENV_HEADING in system_prompt:
        return system_prompt.replace(_ENV_HEADING, _ENV_HEADING + line, 1)
    return f"{system_prompt}\n\n{_ENV_HEADING}{line.strip()}"


def generate_system_prompt(
    name: str,
    identity: str,
    perspective: str,
    constraints: str,
    environment_description: str | None = None,
) -> str:
    """Generate a system prompt from structured persona fields."""
    env_section = ""
    if environment_description:
        env_section = _environment_line(environment_description)
    return _TEMPLATE.format(
        name=name,
        identity=identity,
        perspective=perspective,
        constraints=constraints,
        environment_section=env_section,
    )
