#!/usr/bin/env python3
"""Check that routers don't have direct database query operations.

Routers should delegate database queries to services/repositories.
Direct session.execute(), session.scalar(), etc. should not appear in routers.

Allowed operations in routers:
- session.commit() - transaction finalization
- session.rollback() - error handling
- session.add() - adding entities to session (works with repo-created objects)
- session.delete() - marking entities for deletion
- session.refresh() - refreshing entity state after commit

Usage:
    python tools/linting/no_db_in_router.py [file ...]

Exit codes:
    0: All checks passed
    1: Direct DB query operations found in routers
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

# Database QUERY operations that should NOT be in routers
# These represent direct data access that should go through repository layer
FORBIDDEN_DB_METHODS = {
    "execute",  # Direct query execution
    "scalar",  # Single value query
    "scalars",  # Multi-value query
    "scalar_one",  # Single row query
    "scalar_one_or_none",  # Optional single row query
}

# ORM entity operations - allowed in routers
# These work on entities already loaded via repository
ORM_ENTITY_METHODS = {
    "add",  # Add entity to session
    "add_all",  # Add multiple entities
    "delete",  # Mark entity for deletion
    "merge",  # Merge detached entity
    "flush",  # Flush pending changes
    "refresh",  # Refresh entity from DB
    "expire",  # Expire cached state
    "expire_all",  # Expire all cached state
}

# Transaction control - always allowed in routers
ALLOWED_METHODS = {
    "commit",
    "rollback",
    "close",
    "begin",
    "begin_nested",
}


class DirectDBChecker(ast.NodeVisitor):
    """AST visitor that detects direct database operations."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.errors: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Check for session.method() calls."""
        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr

            # Check if this is a forbidden DB method
            if method_name in FORBIDDEN_DB_METHODS:
                # Try to determine if it's called on a session-like object
                if isinstance(node.func.value, ast.Name):
                    obj_name = node.func.value.id.lower()
                    # Common session variable names
                    if "session" in obj_name or obj_name in ("db", "conn", "connection"):
                        self.errors.append(
                            (node.lineno, f"Direct DB operation: {obj_name}.{method_name}()")
                        )
                elif isinstance(node.func.value, ast.Attribute):
                    # Handle self.session.execute() pattern
                    if (
                        isinstance(node.func.value.value, ast.Name)
                        and node.func.value.value.id == "self"
                        and "session" in node.func.value.attr.lower()
                    ):
                        self.errors.append(
                            (
                                node.lineno,
                                f"Direct DB operation: self.{node.func.value.attr}.{method_name}()",
                            )
                        )

        self.generic_visit(node)

    def visit_Await(self, node: ast.Await) -> None:
        """Check awaited expressions for DB operations."""
        # The actual call check happens in visit_Call
        self.generic_visit(node)


def check_file(filepath: Path) -> list[str]:
    """Check a single file for direct database operations.

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

    checker = DirectDBChecker(str(filepath))
    checker.visit(tree)

    for lineno, message in checker.errors:
        errors.append(f"{filepath}:{lineno}: {message}")

    return errors


def main(files: list[str] | None = None) -> int:
    """Run the direct DB check on router files.

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

        # Only check router files
        if "router" not in path.name:
            continue

        errors = check_file(path)
        all_errors.extend(errors)

    if all_errors:
        print("Direct database operations found in routers:", file=sys.stderr)
        print("Move these operations to service or repository layer.", file=sys.stderr)
        print(file=sys.stderr)
        for error in all_errors:
            print(error, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
