#!/usr/bin/env python3
"""Check that feature routers don't use HTTPException directly.

Feature routers should use the AppException hierarchy from core/exceptions.py
instead of FastAPI's HTTPException. This ensures:
- Consistent RFC 7807 error responses
- Proper error tracking and logging
- Structured error context (type, title, extra fields)

Usage:
    python tools/linting/no_http_exception.py [file ...]

Exit codes:
    0: All checks passed
    1: HTTPException usage found

Example output:
    example_service/features/reminders/router.py:704: HTTPException import found
    example_service/features/reminders/router.py:706: raise HTTPException found
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys


class HTTPExceptionChecker(ast.NodeVisitor):
    """AST visitor that detects HTTPException usage."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.errors: list[tuple[int, str]] = []
        self._in_import_from_fastapi = False

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check for 'from fastapi import HTTPException'."""
        if node.module == "fastapi":
            for alias in node.names:
                if alias.name == "HTTPException":
                    self.errors.append(
                        (node.lineno, "HTTPException import from fastapi")
                    )
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        """Check for 'import fastapi' (then fastapi.HTTPException usage)."""
        # We'll catch actual usage in visit_Attribute
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        """Check for 'raise HTTPException(...)'."""
        if node.exc is not None and isinstance(node.exc, ast.Call):
            func = node.exc.func
            # Direct: raise HTTPException(...)
            if isinstance(func, ast.Name) and func.id == "HTTPException":
                self.errors.append((node.lineno, "raise HTTPException"))
            # Via module: raise fastapi.HTTPException(...)
            elif (
                isinstance(func, ast.Attribute)
                and func.attr == "HTTPException"
                and isinstance(func.value, ast.Name)
                and func.value.id == "fastapi"
            ):
                self.errors.append((node.lineno, "raise fastapi.HTTPException"))
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    """Check a single file for HTTPException usage.

    Args:
        filepath: Path to the Python file to check.

    Returns:
        List of error messages, empty if no issues found.
    """
    errors = []

    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
    except SyntaxError as e:
        return [f"{filepath}:{e.lineno}: SyntaxError: {e.msg}"]

    checker = HTTPExceptionChecker(str(filepath))
    checker.visit(tree)

    for lineno, message in checker.errors:
        errors.append(f"{filepath}:{lineno}: {message}")

    return errors


def main(files: list[str] | None = None) -> int:
    """Run the HTTPException check on specified files.

    Args:
        files: List of file paths to check. If None, checks all feature routers.

    Returns:
        Exit code: 0 if no issues, 1 if issues found.
    """
    if files is None:
        files = sys.argv[1:]

    if not files:
        # Default: check all feature routers
        base_path = Path("example_service/features")
        if base_path.exists():
            files = [str(p) for p in base_path.glob("**/router.py")]
        else:
            print("No files specified and default path not found", file=sys.stderr)
            return 1

    all_errors = []
    for filepath in files:
        path = Path(filepath)
        if not path.exists():
            continue
        if path.suffix != ".py":
            continue

        # Only check feature routers
        if "features" not in str(path):
            continue

        errors = check_file(path)
        all_errors.extend(errors)

    if all_errors:
        print("HTTPException usage found in feature routers:", file=sys.stderr)
        print("Use AppException from core/exceptions.py instead.", file=sys.stderr)
        print(file=sys.stderr)
        for error in all_errors:
            print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
