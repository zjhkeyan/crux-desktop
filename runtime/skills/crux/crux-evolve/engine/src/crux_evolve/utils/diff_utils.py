"""Diff utilities for working with unified diff format.

This module provides functions for generating, applying, and validating diffs
for the diff-based code storage model in Algorithm.
"""

import difflib
import hashlib


def hash_content(content: str) -> str:
    """Generate a SHA-256 hash for content to validate base version in diff mode.

    Args:
        content: The content to hash

    Returns:
        Hexadecimal hash string of the content
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def generate_unified_diff(
    old_content: str, new_content: str, file_path: str, context_lines: int = 3
) -> str:
    """Generate unified diff between old and new content.

    Args:
        old_content: Original content (from parent/base)
        new_content: New content after changes
        file_path: Path to the file being diffed
        context_lines: Number of context lines to include around changes

    Returns:
        Unified diff string in standard git-like format
    """
    old_lines = old_content.splitlines(keepends=True)
    new_lines = new_content.splitlines(keepends=True)

    diff = difflib.unified_diff(
        old_lines, new_lines, fromfile=file_path, tofile=file_path, n=context_lines, lineterm=""
    )

    return "\n".join(diff)


def apply_unified_diff(base_content: str, diff_content: str) -> tuple[str, bool]:
    """Apply unified diff to base content to get new content.

    Args:
        base_content: The original base content to apply diff to
        diff_content: The unified diff to apply

    Returns:
        Tuple of (result_content, success) where:
        - result_content is the content after applying the diff
        - success is True if diff applied successfully, False otherwise
    """
    base_lines = base_content.splitlines(keepends=True)
    diff_lines = diff_content.splitlines(keepends=True)

    # Skip the header lines (---, +++, @@)
    i = 0
    while i < len(diff_lines) and (
        diff_lines[i].startswith("---")
        or diff_lines[i].startswith("+++")
        or diff_lines[i].startswith("@@")
    ):
        i += 1

    # Current position in base_lines
    pos = 0
    result_lines = []

    while i < len(diff_lines):
        line = diff_lines[i].rstrip("\n")

        if line.startswith(" "):
            # Context line - copy from base
            if pos >= len(base_lines):
                return "", False
            if base_lines[pos].rstrip("\n") != line[1:]:
                return "", False
            result_lines.append(base_lines[pos])
            pos += 1
            i += 1
        elif line.startswith("-"):
            # Line removed from base
            if pos >= len(base_lines):
                return "", False
            pos += 1
            i += 1
        elif line.startswith("+"):
            # Line added
            result_lines.append(line[1:] + "\n")
            i += 1
        elif line == "":
            # Empty line
            i += 1
        else:
            # Unknown prefix - should not happen in valid diff
            i += 1

    # Add remaining lines from base that weren't touched by the diff
    while pos < len(base_lines):
        result_lines.append(base_lines[pos])
        pos += 1

    # Join back into content
    result = "".join(result_lines)
    return result, True


def validate_diff(base_content: str, diff_content: str, expected_content: str) -> bool:
    """Validate that applying diff gives expected result.

    Args:
        base_content: The original base content
        diff_content: The unified diff to apply
        expected_content: The expected result after applying the diff

    Returns:
        True if applying diff gives expected content, False otherwise
    """
    result, success = apply_unified_diff(base_content, diff_content)
    if not success:
        return False

    # Normalize line endings for comparison
    result_normalized = result.replace("\r\n", "\n")
    expected_normalized = expected_content.replace("\r\n", "\n")

    return result_normalized == expected_normalized


def parse_diff_stats(diff_content: str) -> tuple[int, int, int]:
    """Parse diff and return statistics about changes.

    Args:
        diff_content: The unified diff to parse

    Returns:
        Tuple of (lines_added, lines_removed, lines_modified)
        Lines that are both removed and added count as modified, not added+removed
    """
    lines_added = 0
    lines_removed = 0
    lines_modified = 0

    lines = diff_content.splitlines()

    i = 0
    # Skip header
    while i < len(lines) and (
        lines[i].startswith("---") or lines[i].startswith("+++") or lines[i].startswith("@@")
    ):
        i += 1

    # We need to detect hunks where we remove a line and immediately add a line in its place - this is modification
    while i < len(lines):
        line = lines[i]
        if line.startswith(" "):
            i += 1
        elif line.startswith("-"):
            # Check if next line is an addition (this is modification)
            if i + 1 < len(lines) and lines[i + 1].startswith("+"):
                lines_modified += 1
                i += 2
            else:
                lines_removed += 1
                i += 1
        elif line.startswith("+"):
            lines_added += 1
            i += 1
        else:
            i += 1

    return lines_added, lines_removed, lines_modified
