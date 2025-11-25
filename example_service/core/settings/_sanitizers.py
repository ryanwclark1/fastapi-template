"""Helpers to sanitize environment variable values before validation."""

from __future__ import annotations

from typing import Any


def strip_inline_comment(value: str) -> str:
    """Remove inline comments of the form "value  # comment".

    VS Code's env-file parser keeps inline comments, so values like
    ``3600  # 1 hour`` show up in the process environment. We strip the
    comment so the JSON schema/validator can parse the number normally.
    The check on ``value[idx - 1]`` avoids treating strings like
    ``foo#bar`` as comments because there is no preceding whitespace.
    """

    idx = value.find("#")
    if idx == -1:
        return value.strip()
    if idx == 0:
        return ""  # comment-only string
    if not value[idx - 1].isspace():
        return value.strip()
    return value[:idx].strip()


def sanitize_inline_numeric(value: Any) -> Any:
    """Normalize numeric env vars that may include inline comments."""

    if isinstance(value, str):
        cleaned = strip_inline_comment(value)
        if cleaned:
            return cleaned
    return value
