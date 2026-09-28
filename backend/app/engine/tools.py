"""Sandboxed tools available to persona agents during journey execution."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


class ToolError(Exception):
    pass


TOOL_SCHEMAS: list[dict] = [
    {
        "name": "read_file",
        "description": (
            "Read a file from the workspace. Path is relative to the repository root."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_directory",
        "description": "List contents of a directory within the workspace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to directory (default: root)",
                    "default": ".",
                },
            },
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a shell command in the workspace directory. "
            "Common dev tools are available: git, make, npm, pip, python, "
            "curl, docker, cargo, go, and standard CLI utilities."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to run",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (optional)",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "http_request",
        "description": (
            "Make an HTTP request to a URL (typically localhost services you started)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "method": {"type": "string", "description": "HTTP method"},
                "url": {"type": "string", "description": "Request URL"},
                "body": {
                    "type": "string",
                    "description": "Request body (optional)",
                },
                "headers": {
                    "type": "object",
                    "description": "Request headers (optional)",
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["method", "url"],
        },
    },
    {
        "name": "report_finding",
        "description": (
            "Report an issue found during evaluation. "
            "Evidence MUST be verbatim text from a prior tool output."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["critical", "needs_attention", "nits"],
                },
                "category": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "evidence": {
                    "type": "string",
                    "description": "Verbatim text from a prior tool output",
                },
                "file_path": {"type": "string"},
                "line_range": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "suggestion": {"type": "string"},
            },
            "required": [
                "severity",
                "category",
                "title",
                "description",
                "evidence",
            ],
        },
    },
    {
        "name": "complete_phase",
        "description": "Signal that the current phase is complete with a summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Summary of what was found in this phase",
                },
            },
            "required": ["summary"],
        },
    },
]

_TOOL_SCHEMA_MAP: dict[str, dict] = {t["name"]: t for t in TOOL_SCHEMAS}

ALLOWLIST_PREFIXES = (
    "make ",
    "cat ",
    "grep ",
    "ls ",
    "find ",
    "head ",
    "tail ",
    "wc ",
    "git ",
    "npm ",
    "npx ",
    "pip ",
    "pip3 ",
    "python ",
    "python3 ",
    "node ",
    "curl ",
    "docker compose",
    "docker run",
    "docker ps",
    "docker logs",
    "cargo ",
    "go ",
    "mvn ",
    "gradle ",
    "oc get",
    "oc logs",
    "oc describe",
    "helm ",
    "uv ",
    "env ",
    "echo ",
    "mkdir ",
    "touch ",
    "cp ",
    "mv ",
    "tar ",
    "unzip ",
    "which ",
    "pwd",
    "whoami",
)

BLOCKLIST_PATTERNS = (
    "rm -rf",
    "sudo",
    "oc delete namespace",
    "oc delete project",
    "curl.*metadata",
    "wget.*metadata",
    "chmod 777",
    "> /dev/",
    "mkfs",
    "dd if=",
)

MAX_FILE_CHARS = 10000
MAX_OUTPUT_CHARS = 5000


def get_all_tools() -> list[dict]:
    """Return all available tool schemas."""
    return list(TOOL_SCHEMAS)


@dataclass
class ToolContext:
    """Runtime context for tool execution during a persona's journey."""

    workspace_dir: str
    command_timeout: int = 120
    build_timeout: int = 300
    findings: list[dict] = field(default_factory=list)


async def execute_tool(
    name: str,
    arguments: dict,
    ctx: ToolContext,
    phase: str,
    persona: str,
) -> tuple[str, bool]:
    """Execute a tool. Returns (result_text, is_complete_phase)."""
    try:
        if name == "read_file":
            result = _tool_read_file(arguments, ctx)
        elif name == "list_directory":
            result = _tool_list_directory(arguments, ctx)
        elif name == "run_command":
            result = await _tool_run_command(arguments, ctx)
        elif name == "http_request":
            result = await _tool_http_request(arguments, ctx)
        elif name == "report_finding":
            result = _tool_report_finding(arguments, ctx, phase, persona)
        elif name == "complete_phase":
            return arguments.get("summary", "Phase complete."), True
        else:
            return f"Unknown tool: {name}", False
    except ToolError as e:
        return f"Tool error: {e}", False
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return f"Tool execution failed: {e}", False

    return result, False


def _tool_read_file(arguments: dict, ctx: ToolContext) -> str:
    path = arguments.get("path", "")
    resolved = _resolve_safe_path(path, ctx.workspace_dir)
    if resolved.is_dir():
        raise ToolError(f"Is a directory, not a file: {path}")
    content = resolved.read_text(errors="replace")
    if len(content) > MAX_FILE_CHARS:
        content = (
            content[:MAX_FILE_CHARS] + f"\n... [truncated at {MAX_FILE_CHARS} chars]"
        )
    return content


def _tool_list_directory(arguments: dict, ctx: ToolContext) -> str:
    path = arguments.get("path", ".")
    resolved = _resolve_safe_path(path, ctx.workspace_dir)
    if not resolved.is_dir():
        raise ToolError(f"Not a directory: {path}")
    entries = []
    for item in sorted(resolved.iterdir()):
        indicator = "/" if item.is_dir() else ""
        entries.append(f"{item.name}{indicator}")
    return "\n".join(entries) if entries else "(empty directory)"


async def _tool_run_command(arguments: dict, ctx: ToolContext) -> str:
    command = arguments.get("command", "")

    for pattern in BLOCKLIST_PATTERNS:
        if pattern in command:
            raise ToolError(f"Blocked command pattern: {pattern}")

    if not any(command.startswith(prefix) for prefix in ALLOWLIST_PREFIXES):
        raise ToolError(
            f"Command not in allowlist. Allowed prefixes: "
            f"{', '.join(ALLOWLIST_PREFIXES)}"
        )

    timeout = arguments.get("timeout", ctx.command_timeout)
    if command.startswith(("make build", "make deploy")):
        timeout = max(timeout, ctx.build_timeout)

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=ctx.workspace_dir,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        output = stdout.decode(errors="replace")
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise ToolError(f"Command timed out after {timeout}s: {command}")

    if len(output) > MAX_OUTPUT_CHARS:
        output = (
            output[:MAX_OUTPUT_CHARS] + f"\n... [truncated at {MAX_OUTPUT_CHARS} chars]"
        )
    return f"{output}\n[exit code: {proc.returncode}]"


async def _tool_http_request(arguments: dict, ctx: ToolContext) -> str:
    method = arguments.get("method", "GET").upper()
    url = arguments.get("url", "")
    body = arguments.get("body")
    headers = arguments.get("headers", {})

    _validate_url(url, ctx)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.request(method, url, content=body, headers=headers)
    result = f"HTTP {response.status_code}\n{response.text}"
    if len(result) > MAX_OUTPUT_CHARS:
        result = (
            result[:MAX_OUTPUT_CHARS] + f"\n... [truncated at {MAX_OUTPUT_CHARS} chars]"
        )
    return result


def _tool_report_finding(
    arguments: dict, ctx: ToolContext, phase: str, persona: str
) -> str:
    from app.models.finding import normalize_severity

    severity = normalize_severity(arguments["severity"]).value

    finding = {
        "severity": severity,
        "category": arguments["category"],
        "title": arguments["title"],
        "description": arguments["description"],
        "evidence": arguments["evidence"],
        "file_path": arguments.get("file_path"),
        "line_range": arguments.get("line_range"),
        "suggestion": arguments.get("suggestion"),
        "phase": phase,
    }
    ctx.findings.append(finding)

    return f"Finding recorded [{arguments['severity']}]: {arguments['title']}" 


def _resolve_safe_path(relative: str, workspace_dir: str) -> Path:
    if ".." in relative.split(os.sep):
        raise ToolError(f"Path traversal not allowed: {relative}")

    root = Path(workspace_dir).resolve()
    resolved = (root / relative).resolve()

    if not resolved.is_relative_to(root):
        raise ToolError(f"Path escapes workspace directory: {relative}")
    if resolved.is_symlink():
        link_target = resolved.resolve()
        if not link_target.is_relative_to(root):
            raise ToolError(f"Symlink target outside workspace: {relative}")
    if not resolved.exists():
        raise ToolError(f"Path does not exist: {relative}")

    return resolved


def _validate_url(url: str, ctx: ToolContext) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""

    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return

    raise ToolError(f"URL not allowed (only localhost URLs): {url}")
