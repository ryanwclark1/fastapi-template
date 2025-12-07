#!/usr/bin/env python3
"""Simple script to fix G004 errors by converting f-string logging to lazy % formatting."""

from pathlib import Path
import re
import sys


def fix_logging_fstrings(content: str) -> str:
    """Convert f-string logging statements to lazy % formatting."""
    lines = content.split("\n")
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this line contains a logger call with f-string
        if "logger." in line and 'f"' in line and "(" in line:
            # Try to fix single-line cases first
            # Pattern: logger.method(f"text {var}")
            if line.rstrip().endswith(")"):
                # Single line logger call
                fixed = fix_single_line_logger(line)
                result.append(fixed)
                i += 1
                continue
            # Multi-line logger call - collect until closing paren
            logger_lines = [line]
            j = i + 1
            paren_count = line.count("(") - line.count(")")

            while j < len(lines) and paren_count > 0:
                logger_lines.append(lines[j])
                paren_count += lines[j].count("(") - lines[j].count(")")
                j += 1

            # Fix the multi-line block
            fixed_block = fix_multiline_logger("\n".join(logger_lines))
            result.append(fixed_block)
            i = j
            continue

        result.append(line)
        i += 1

    return "\n".join(result)


def fix_single_line_logger(line: str) -> str:
    """Fix a single-line logger call with f-string."""
    # Pattern: logger.method(f"text {var} more text")
    # Extract the f-string content and variables
    match = re.search(
        r'(logger\.(?:debug|info|warning|error|critical|exception))\s*\(f"([^"]*)"\)',
        line,
    )
    if match:
        logger_call = match.group(1)
        fstring_content = match.group(2)

        # Find all variables
        var_pattern = r"\{([^}]+)\}"
        variables = re.findall(var_pattern, fstring_content)

        if not variables:
            # No variables, just remove f
            format_string = fstring_content
            indent = line[: len(line) - len(line.lstrip())]
            return f'{indent}{logger_call}("{format_string}")'

        # Replace {var} with %s
        format_string = re.sub(var_pattern, "%s", fstring_content)
        var_args = ", ".join(variables)
        indent = line[: len(line) - len(line.lstrip())]
        return f'{indent}{logger_call}("{format_string}", {var_args})'

    return line


def fix_multiline_logger(block: str) -> str:
    """Fix a multi-line logger call with f-string."""
    # Find the f-string part
    # Pattern: logger.method(f"...")
    match = re.search(
        r'(\s*)(logger\.(?:debug|info|warning|error|critical|exception))\s*\(\s*f"([^"]*(?:\n[^"]*)*)"',
        block,
        re.DOTALL,
    )

    if not match:
        return block

    indent = match.group(1)
    logger_call = match.group(2)
    fstring_content = match.group(3)

    # Find all variables
    var_pattern = r"\{([^}]+)\}"
    variables = re.findall(var_pattern, fstring_content)

    if not variables:
        # No variables, just remove f
        format_string = fstring_content
        # Find the rest of the call (extra=, etc.)
        rest_match = re.search(r'f"[^"]*"\s*(,.*?)?\)', block, re.DOTALL)
        if rest_match and rest_match.group(1):
            rest = rest_match.group(1)
            return f'{indent}{logger_call}("{format_string}"{rest})'
        return f'{indent}{logger_call}("{format_string}")'

    # Replace {var} with %s
    format_string = re.sub(var_pattern, "%s", fstring_content)
    var_args = ", ".join(variables)

    # Find the rest of the call
    rest_match = re.search(r'f"[^"]*"\s*(,.*?)?\)', block, re.DOTALL)
    if rest_match and rest_match.group(1):
        rest = rest_match.group(1)
        return f'{indent}{logger_call}("{format_string}", {var_args}{rest})'

    return f'{indent}{logger_call}("{format_string}", {var_args})'


if __name__ == "__main__":
    # Get files from ruff output
    import subprocess

    result = subprocess.run(
        ["ruff", "check", "--select", "G004", "."],
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    )

    files_to_fix = set()
    for line in result.stdout.split("\n"):
        if "-->" in line and "example_service" in line:
            parts = line.split("-->")
            if len(parts) > 1:
                file_path_str = parts[1].split(":")[0].strip()
                if file_path_str.startswith("example_service"):
                    files_to_fix.add(Path(file_path_str))

    print(f"Found {len(files_to_fix)} files to fix")

    for file_path in sorted(files_to_fix):
        if not file_path.exists():
            continue

        try:
            content = file_path.read_text(encoding="utf-8")
            fixed = fix_logging_fstrings(content)

            if fixed != content:
                file_path.write_text(fixed, encoding="utf-8")
                print(f"Fixed {file_path}")
        except Exception as e:
            print(f"Error fixing {file_path}: {e}", file=sys.stderr)
