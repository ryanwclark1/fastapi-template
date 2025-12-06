#!/usr/bin/env python3
"""Check that API endpoints have proper OpenAPI documentation.

All router endpoints should have:
- summary: Short description of what the endpoint does
- description: Detailed explanation (can be multi-line markdown)
- responses: Dict of non-2xx response codes with descriptions (optional but recommended)

Usage:
    python tools/linting/openapi_checks.py [file ...]

Exit codes:
    0: All checks passed (or warnings only)
    1: Critical documentation issues found

Note:
    This check produces warnings for missing descriptions but doesn't fail.
    Missing summaries are treated as errors.
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys

# HTTP decorator names that define endpoints
HTTP_DECORATORS = {"get", "post", "put", "patch", "delete", "head", "options"}


class OpenAPIDocChecker(ast.NodeVisitor):
    """AST visitor that checks endpoint documentation."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.errors: list[tuple[int, str]] = []
        self.warnings: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Check function decorators for router endpoint definitions."""
        self._check_async_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Check async function decorators for router endpoint definitions."""
        self._check_async_function(node)
        self.generic_visit(node)

    def _check_async_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Check if function is a router endpoint and validate docs."""
        for decorator in node.decorator_list:
            # Check for @router.get, @router.post, etc.
            if isinstance(decorator, ast.Call):
                func = decorator.func
                if isinstance(func, ast.Attribute) and func.attr in HTTP_DECORATORS:
                    self._check_endpoint_docs(node, decorator)

    def _check_endpoint_docs(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        decorator: ast.Call,
    ) -> None:
        """Check that endpoint has proper documentation."""
        has_summary = False
        has_description = False

        for keyword in decorator.keywords:
            if keyword.arg == "summary":
                has_summary = True
            elif keyword.arg == "description":
                has_description = True

        if not has_summary:
            self.errors.append(
                (
                    node.lineno,
                    f"Endpoint '{node.name}' missing 'summary' parameter",
                )
            )

        if not has_description:
            self.warnings.append(
                (
                    node.lineno,
                    f"Endpoint '{node.name}' missing 'description' parameter",
                )
            )


def check_file(filepath: Path) -> tuple[list[str], list[str]]:
    """Check a single file for documentation issues.

    Args:
        filepath: Path to the Python file to check.

    Returns:
        Tuple of (errors, warnings) - lists of message strings.
    """
    errors = []
    warnings = []

    try:
        content = filepath.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(filepath))
    except SyntaxError as e:
        return [f"{filepath}:{e.lineno}: SyntaxError: {e.msg}"], []

    checker = OpenAPIDocChecker(str(filepath))
    checker.visit(tree)

    for lineno, message in checker.errors:
        errors.append(f"{filepath}:{lineno}: {message}")

    for lineno, message in checker.warnings:
        warnings.append(f"{filepath}:{lineno}: {message}")

    return errors, warnings


def main(files: list[str] | None = None) -> int:
    """Run the OpenAPI documentation check on specified files.

    Args:
        files: List of file paths to check. If None, checks all router files.

    Returns:
        Exit code: 0 if no errors (warnings OK), 1 if errors found.
    """
    if files is None:
        files = sys.argv[1:]

    if not files:
        # Default: check all router files
        base_path = Path("example_service/features")
        if base_path.exists():
            files = [str(p) for p in base_path.glob("**/router.py")]
        else:
            print("No files specified and default path not found", file=sys.stderr)
            return 1

    all_errors = []
    all_warnings = []

    for filepath in files:
        path = Path(filepath)
        if not path.exists():
            continue
        if path.suffix != ".py":
            continue

        errors, warnings = check_file(path)
        all_errors.extend(errors)
        all_warnings.extend(warnings)

    if all_warnings:
        print("OpenAPI documentation warnings:", file=sys.stderr)
        for warning in all_warnings:
            print(f"  WARNING: {warning}", file=sys.stderr)
        print(file=sys.stderr)

    if all_errors:
        print("OpenAPI documentation errors:", file=sys.stderr)
        print(
            "All endpoints should have at minimum a 'summary' parameter.",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        for error in all_errors:
            print(f"  ERROR: {error}", file=sys.stderr)
        return 1

    if not all_errors and not all_warnings:
        print("All endpoint documentation checks passed!", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
