#!/usr/bin/env python3
"""Bulk fix G004 errors by converting f-string logging to lazy % formatting."""

from pathlib import Path
import re
import sys


def fix_file_content(content: str) -> str:
    """Fix all f-string logging patterns in content."""

    # Pattern 1: Simple single-line: logger.method(f"text {var}")
    def replace_simple(match):
        logger_call = match.group(1)
        fstring = match.group(2)

        # Extract all variables
        vars_found = re.findall(r"\{([^}]+)\}", fstring)
        if not vars_found:
            return f'{logger_call}("{fstring}")'

        # Replace {var} with %s
        format_str = re.sub(r"\{[^}]+\}", "%s", fstring)
        var_args = ", ".join(vars_found)
        return f'{logger_call}("{format_str}", {var_args})'

    # Match logger.method(f"...") on single line
    content = re.sub(
        r'(logger\.(?:debug|info|warning|error|critical|exception))\s*\(f"([^"]*)"\)',
        replace_simple,
        content,
    )

    # Pattern 2: Multi-line with extra parameter
    # logger.method(f"...", extra={...})
    def replace_with_extra(match):
        logger_call = match.group(1)
        fstring = match.group(2)
        extra_part = match.group(3)

        vars_found = re.findall(r"\{([^}]+)\}", fstring)
        if not vars_found:
            return f'{logger_call}("{fstring}", {extra_part}'

        format_str = re.sub(r"\{[^}]+\}", "%s", fstring)
        var_args = ", ".join(vars_found)
        return f'{logger_call}("{format_str}", {var_args}, {extra_part}'

    # Match logger.method(f"...", extra= or , extra=
    content = re.sub(
        r'(logger\.(?:debug|info|warning|error|critical|exception))\s*\(\s*f"([^"]*)"\s*,\s*(extra=)',
        replace_with_extra,
        content,
        flags=re.MULTILINE,
    )

    # Pattern 3: Multi-line f-strings (spanning multiple lines)
    # This is more complex - handle common cases
    lines = content.split("\n")
    result_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this starts a multi-line logger with f-string
        if (
            re.search(
                r"logger\.(?:debug|info|warning|error|critical|exception)\s*\(", line
            )
            and 'f"' in line
        ):
            # Check if it's a multi-line f-string
            if not line.rstrip().endswith('")') and '"' in line:
                # Multi-line f-string - collect until we find the closing
                logger_block = [line]
                j = i + 1
                fstring_open = True

                while j < len(lines) and fstring_open:
                    logger_block.append(lines[j])
                    if '"' in lines[j] and not lines[j].strip().startswith('f"'):
                        # Check if this closes the f-string
                        if '"' in lines[j] and (
                            lines[j].rstrip().endswith('")')
                            or (j + 1 < len(lines) and ")" in lines[j + 1])
                        ):
                            fstring_open = False
                    j += 1

                # Fix the block
                fixed_block = fix_multiline_block("\n".join(logger_block))
                result_lines.append(fixed_block)
                i = j
                continue

        result_lines.append(line)
        i += 1

    return "\n".join(result_lines)


def fix_multiline_block(block: str) -> str:
    """Fix a multi-line logger block with f-string."""
    # Extract the f-string content
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

    # Find variables
    vars_found = re.findall(r"\{([^}]+)\}", fstring_content)

    if not vars_found:
        # No variables
        format_str = fstring_content
        # Find rest of call
        rest_match = re.search(r'f"[^"]*"\s*(,.*?)?\)', block, re.DOTALL)
        if rest_match and rest_match.group(1):
            return f'{indent}{logger_call}("{format_str}"{rest_match.group(1)})'
        return f'{indent}{logger_call}("{format_str}")'

    # Replace variables
    format_str = re.sub(r"\{[^}]+\}", "%s", fstring_content)
    var_args = ", ".join(vars_found)

    # Find rest
    rest_match = re.search(r'f"[^"]*"\s*(,.*?)?\)', block, re.DOTALL)
    if rest_match and rest_match.group(1):
        return f'{indent}{logger_call}("{format_str}", {var_args}{rest_match.group(1)})'

    return f'{indent}{logger_call}("{format_str}", {var_args})'


if __name__ == "__main__":
    # Get all Python files in example_service
    base_path = Path(__file__).parent
    python_files = list(base_path.rglob("example_service/**/*.py"))

    fixed_count = 0
    for file_path in python_files:
        try:
            content = file_path.read_text(encoding="utf-8")
            fixed = fix_file_content(content)

            if fixed != content:
                file_path.write_text(fixed, encoding="utf-8")
                fixed_count += 1
                print(f"Fixed {file_path}")
        except Exception as e:
            print(f"Error processing {file_path}: {e}", file=sys.stderr)

    print(f"\nFixed {fixed_count} files")
