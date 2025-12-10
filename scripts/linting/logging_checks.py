#!/usr/bin/env python3
"""Check that services follow standard logging patterns.

Services should either:
1. Inherit from BaseService (which provides self.logger and self._lazy)
2. Define both logger and lazy_logger at module or class level

This ensures consistent logging across the application with:
- Standard logger for INFO/WARNING/ERROR
- Lazy logger for DEBUG (zero overhead when disabled)

Usage:
    python tools/linting/logging_checks.py [file ...]

Exit codes:
    0: All checks passed
    1: Logging pattern issues found
"""

from __future__ import annotations

import ast
from pathlib import Path
import sys


class LoggingPatternChecker(ast.NodeVisitor):
    """AST visitor that checks service logging patterns."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.errors: list[tuple[int, str]] = []
        self.has_base_service_import = False
        self.module_has_logger = False
        self.module_has_lazy_logger = False

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Check for BaseService import."""
        if node.module and "core.services.base" in node.module:
            for alias in node.names:
                if alias.name == "BaseService":
                    self.has_base_service_import = True
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check for module-level logger definitions."""
        for target in node.targets:
            if isinstance(target, ast.Name):
                if target.id == "logger":
                    self.module_has_logger = True
                elif target.id == "lazy_logger":
                    self.module_has_lazy_logger = True
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Check service classes for proper logging setup."""
        # Check if this is a service class (name ends with 'Service')
        if not node.name.endswith("Service"):
            self.generic_visit(node)
            return

        # Check if it inherits from BaseService
        inherits_base_service = False
        for base in node.bases:
            if (isinstance(base, ast.Name) and base.id == "BaseService") or (isinstance(base, ast.Attribute) and base.attr == "BaseService"):
                inherits_base_service = True
                break

        # If inherits BaseService, logging is handled
        if inherits_base_service:
            self.generic_visit(node)
            return

        # Check for class-level logger definitions
        class_has_logger = False
        class_has_lazy_logger = False

        for item in node.body:
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        if target.id == "logger":
                            class_has_logger = True
                        elif target.id == "_lazy" or target.id == "lazy_logger":
                            class_has_lazy_logger = True
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                if item.target.id == "logger":
                    class_has_logger = True
                elif item.target.id in ("_lazy", "lazy_logger"):
                    class_has_lazy_logger = True

        # Check if logging is properly configured
        has_logging = (
            (class_has_logger and class_has_lazy_logger)
            or (self.module_has_logger and self.module_has_lazy_logger)
        )

        if not has_logging:
            self.errors.append(
                (
                    node.lineno,
                    f"Service class '{node.name}' should inherit from BaseService "
                    "or define both logger and lazy_logger",
                )
            )

        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    """Check a single file for logging pattern issues.

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

    checker = LoggingPatternChecker(str(filepath))
    checker.visit(tree)

    for lineno, message in checker.errors:
        errors.append(f"{filepath}:{lineno}: {message}")

    return errors


def main(files: list[str] | None = None) -> int:
    """Run the logging pattern check on specified files.

    Args:
        files: List of file paths to check. If None, checks all service files.

    Returns:
        Exit code: 0 if no issues, 1 if issues found.
    """
    if files is None:
        files = sys.argv[1:]

    if not files:
        # Default: check all service files
        base_path = Path("example_service/features")
        if base_path.exists():
            files = [str(p) for p in base_path.glob("**/service.py")]
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

        errors = check_file(path)
        all_errors.extend(errors)

    if all_errors:
        print("Logging pattern issues found:", file=sys.stderr)
        print(
            "Services should inherit from BaseService or define both logger and lazy_logger.",
            file=sys.stderr,
        )
        print(file=sys.stderr)
        for error in all_errors:
            print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
