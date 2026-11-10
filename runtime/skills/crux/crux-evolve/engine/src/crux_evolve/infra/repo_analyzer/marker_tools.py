"""EVOLVE marker validation, stripping, and path inspection utilities.

Public API exposed by this module:

- :func:`classify_marker`: classify a single line as ``"START"``, ``"END"``,
  or ``None``.
- :func:`validate_markers`: stack-based pairing of START/END markers in a
  file; reports nesting and unbalanced markers.
- :func:`strip_marker_lines`: drop EVOLVE marker lines from file content,
  preserving the body and surrounding context.
- :func:`inspect_path`: walk a task package directory and return an
  :class:`InspectResult` with discovered blocks and any issues.
- :func:`clean_path`: dry-run or apply marker removal across a directory,
  returning a :class:`CleanResult`.

Designed for two consumers:

- Backend services that ``import`` CruxEvolve and forward results over HTTP —
  every result type carries ``to_dict()`` returning JSON-ready primitives.
- The ``crux_evolve evolve`` CLI subcommand group, which wraps these functions.

Detection logic intentionally reuses :class:`EvolveDetector` for marker
classification and file walking so the inspector stays consistent with
the analyzer used during evolution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from crux_evolve.infra.repo_analyzer.evolve_detector import EvolveDetector

IssueKind = Literal["nested", "unbalanced_start", "unbalanced_end", "unreadable"]


# ----------------------------------------------------------------------
# Result dataclasses
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class BlockSpan:
    """A well-formed EVOLVE block discovered in a single file.

    Attributes:
        line_start: 1-based line number of the START marker.
        line_end: 1-based line number of the END marker.
        comment_style: One of ``"#"``, ``"//"``, ``"/* */"``, ``"<!-- -->"``.
        block_name: Optional name following ``EVOLVE_START``; empty if absent.
    """

    line_start: int
    line_end: int
    comment_style: str
    block_name: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return {
            "line_start": self.line_start,
            "line_end": self.line_end,
            "comment_style": self.comment_style,
            "block_name": self.block_name,
        }


@dataclass(frozen=True)
class MarkerIssue:
    """A problem detected while pairing EVOLVE markers.

    Attributes:
        kind: ``"nested"``, ``"unbalanced_start"``, ``"unbalanced_end"``,
            or ``"unreadable"`` (file-level read failure).
        line: 1-based line number of the offending marker, or ``0`` for
            file-level issues such as ``"unreadable"``.
        related_line: For ``"nested"``, the line of the still-open outer
            START. ``None`` otherwise.
        detail: Optional human-readable detail (used by ``"unreadable"``).
    """

    kind: IssueKind
    line: int
    related_line: int | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        out: dict[str, Any] = {"kind": self.kind, "line": self.line}
        if self.related_line is not None:
            out["related_line"] = self.related_line
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass
class FileReport:
    """Per-file inspection output.

    Attributes:
        path: POSIX-style relative path from the inspected root.
        language: Detected language (e.g. ``"python"``).
        blocks: Well-formed blocks discovered in the file.
        issues: Marker-level issues found in the file.
    """

    path: str
    language: str
    blocks: list[BlockSpan] = field(default_factory=list)
    issues: list[MarkerIssue] = field(default_factory=list)

    def to_dict(self, active_block_id: str | None = None) -> dict[str, Any]:
        """Return a JSON-ready representation.

        Each block carries a stable ``block_id`` and an ``active`` flag
        indicating whether it is the block planners would currently pick
        as ``evolvable_blocks[0]``.

        Args:
            active_block_id: Block id of the active block, used to flag
                the matching entry in this file's ``blocks`` list.
        """
        return {
            "path": self.path,
            "language": self.language,
            "blocks": [
                {
                    **b.to_dict(),
                    "block_id": (bid := _block_id(self.path, b.line_start, b.line_end)),
                    "active": bid == active_block_id,
                }
                for b in self.blocks
            ],
            "issues": [i.to_dict() for i in self.issues],
        }


@dataclass
class InspectResult:
    """Aggregate result for :func:`inspect_path`.

    ``ok`` is ``False`` when the inspected root is unreadable or any
    file reports at least one issue. ``active_block_id`` is the
    ``block_id`` of the block planners would currently feed to the
    coder (i.e. ``evolvable_blocks[0]`` in the analyzer's walk order),
    or ``None`` when no well-formed block was found.
    """

    ok: bool
    root: str
    summary: dict[str, Any]
    files: list[FileReport] = field(default_factory=list)
    active_block_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        summary = dict(self.summary)
        summary["active_block_id"] = self.active_block_id
        return {
            "ok": self.ok,
            "root": self.root,
            "summary": summary,
            "files": [f.to_dict(self.active_block_id) for f in self.files],
        }


@dataclass
class CleanResult:
    """Aggregate result for :func:`clean_path`.

    Per-file entries record the marker line numbers that were (or would be)
    removed and whether the file was actually written.
    """

    ok: bool
    applied: bool
    root: str
    summary: dict[str, Any]
    files: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation."""
        return {
            "ok": self.ok,
            "applied": self.applied,
            "root": self.root,
            "summary": self.summary,
            "files": list(self.files),
        }


# ----------------------------------------------------------------------
# Low-level helpers
# ----------------------------------------------------------------------


def classify_marker(line: str) -> Literal["START", "END"] | None:
    """Classify a line as START, END, or non-marker.

    Thin public re-export of :meth:`EvolveDetector._classify_marker_line`
    so callers do not reach into a private static method.

    Args:
        line: A single source line.

    Returns:
        ``"START"``, ``"END"``, or ``None``.
    """
    return EvolveDetector._classify_marker_line(line)


def validate_markers(lines: list[str]) -> tuple[list[BlockSpan], list[MarkerIssue]]:
    """Pair START/END markers using a stack and report issues.

    Walks the lines once. For each START, pushes a record onto a stack;
    each END pops the most recent open START to emit a :class:`BlockSpan`.
    Nested STARTs are reported but the inner block is still emitted so
    every marker line is accounted for. STARTs left on the stack at EOF
    are reported as ``unbalanced_start``; STARTs missing produce
    ``unbalanced_end`` for the offending END.

    Args:
        lines: File content split into lines (with or without line endings).

    Returns:
        A tuple ``(blocks, issues)`` where ``blocks`` are well-formed
        (or recovered nested) :class:`BlockSpan` instances and ``issues``
        are :class:`MarkerIssue` records.
    """
    stack: list[tuple[int, str]] = []  # list of (start_line, raw_start_line)
    blocks: list[BlockSpan] = []
    issues: list[MarkerIssue] = []

    for idx, raw in enumerate(lines, 1):
        kind = classify_marker(raw)
        if kind == "START":
            if stack:
                outer_line = stack[-1][0]
                issues.append(MarkerIssue("nested", idx, related_line=outer_line))
            stack.append((idx, raw))
        elif kind == "END":
            if not stack:
                issues.append(MarkerIssue("unbalanced_end", idx))
                continue
            start_line, start_raw = stack.pop()
            blocks.append(
                BlockSpan(
                    line_start=start_line,
                    line_end=idx,
                    comment_style=EvolveDetector._detect_comment_style(start_raw),
                    block_name=EvolveDetector._extract_block_name(start_raw),
                )
            )

    for start_line, _ in stack:
        issues.append(MarkerIssue("unbalanced_start", start_line))

    blocks.sort(key=lambda b: (b.line_start, b.line_end))
    issues.sort(key=lambda i: (i.line, i.kind))
    return blocks, issues


def strip_marker_lines(content: str) -> tuple[str, list[int]]:
    """Remove every EVOLVE START/END marker line from ``content``.

    Body content between markers and surrounding context are preserved.
    Original line endings are preserved on the lines that remain.

    Args:
        content: Full file content.

    Returns:
        A tuple ``(new_content, removed_lines)`` where ``removed_lines``
        is the 1-based line numbers that were dropped.
    """
    lines = content.splitlines(keepends=True)
    kept: list[str] = []
    removed: list[int] = []
    for idx, raw in enumerate(lines, 1):
        if classify_marker(raw) is not None:
            removed.append(idx)
        else:
            kept.append(raw)
    return "".join(kept), removed


# ----------------------------------------------------------------------
# High-level path APIs
# ----------------------------------------------------------------------


def _block_id(rel_path: str, line_start: int, line_end: int) -> str:
    """Build a stable block id from relative path and line range."""
    return f"{rel_path}#{line_start}-{line_end}"


def _to_posix_relative(file_path: Path, root: Path) -> str:
    """Return a POSIX, root-relative path string for cross-platform output."""
    return file_path.relative_to(root).as_posix()


def _read_text(path: Path) -> tuple[str | None, str | None]:
    """Read a file as UTF-8, returning ``(content, error)``."""
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError as exc:
        return None, f"unicode: {exc}"
    except (OSError, PermissionError) as exc:
        return None, str(exc)


def inspect_path(
    root: Path | str,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> InspectResult:
    """Walk a task package and validate every file's EVOLVE markers.

    Args:
        root: Directory to inspect (absolute or relative).
        include: Optional list of glob patterns; defaults to
            :class:`EvolveDetector` defaults.
        exclude: Optional list of glob patterns; defaults to
            :class:`EvolveDetector` defaults.

    Returns:
        An :class:`InspectResult`. ``ok`` is ``False`` if the root is
        unreadable or any file reports at least one issue.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        return InspectResult(
            ok=False,
            root=root_path.as_posix(),
            summary={
                "files_scanned": 0,
                "files_with_blocks": 0,
                "blocks": 0,
                "issues": 0,
                "error": f"Path does not exist or is not a directory: {root_path}",
            },
            files=[],
        )

    files: list[FileReport] = []
    files_scanned = 0
    files_with_blocks = 0
    total_blocks = 0
    total_issues = 0
    # Active block = the block planners currently feed to coders as
    # ``evolvable_blocks[0]``. Computed in ``iter_source_files`` walk order
    # (which mirrors :meth:`EvolveDetector.analyze`) before the alphabetical
    # sort below, so ``active_block_id`` matches what the orchestrator picks.
    active_block_id: str | None = None

    for file_path in EvolveDetector.iter_source_files(root_path, include=include, exclude=exclude):
        files_scanned += 1
        rel = _to_posix_relative(file_path, root_path)
        language = EvolveDetector._language_for(file_path)

        content, err = _read_text(file_path)
        if content is None:
            files.append(
                FileReport(
                    path=rel,
                    language=language,
                    blocks=[],
                    issues=[MarkerIssue("unreadable", 0, detail=err or "")],
                )
            )
            total_issues += 1
            continue

        lines = content.splitlines(keepends=True)
        # Skip files with no markers at all to keep output focused.
        if not any(classify_marker(line) for line in lines):
            continue

        blocks, issues = validate_markers(lines)
        files.append(FileReport(path=rel, language=language, blocks=blocks, issues=issues))
        if blocks:
            files_with_blocks += 1
            if active_block_id is None:
                first = blocks[0]
                active_block_id = _block_id(rel, first.line_start, first.line_end)
        total_blocks += len(blocks)
        total_issues += len(issues)

    files.sort(key=lambda f: f.path)

    return InspectResult(
        ok=total_issues == 0,
        root=root_path.as_posix(),
        summary={
            "files_scanned": files_scanned,
            "files_with_blocks": files_with_blocks,
            "blocks": total_blocks,
            "issues": total_issues,
        },
        files=files,
        active_block_id=active_block_id,
    )


def clean_path(
    root: Path | str,
    *,
    apply: bool = False,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> CleanResult:
    """Remove EVOLVE START/END marker lines from every matching file.

    Args:
        root: Directory to clean.
        apply: If ``False`` (default), no files are written; the result
            still reports the lines that *would* be removed. If ``True``,
            modified files are rewritten in place.
        include: Optional list of glob patterns; defaults to
            :class:`EvolveDetector` defaults.
        exclude: Optional list of glob patterns; defaults to
            :class:`EvolveDetector` defaults.

    Returns:
        A :class:`CleanResult` summarizing per-file removals and write
        outcomes. Errors during read or write are recorded per file and
        flip ``ok`` to ``False`` but do not abort the run.
    """
    root_path = Path(root).expanduser().resolve()
    if not root_path.exists() or not root_path.is_dir():
        return CleanResult(
            ok=False,
            applied=apply,
            root=root_path.as_posix(),
            summary={
                "files_changed": 0,
                "lines_removed": 0,
                "errors": 1,
                "error": f"Path does not exist or is not a directory: {root_path}",
            },
            files=[],
        )

    files: list[dict[str, Any]] = []
    files_changed = 0
    lines_removed = 0
    errors = 0

    for file_path in EvolveDetector.iter_source_files(root_path, include=include, exclude=exclude):
        rel = _to_posix_relative(file_path, root_path)
        content, err = _read_text(file_path)
        if content is None:
            files.append({"path": rel, "removed_lines": [], "written": False, "error": err or ""})
            errors += 1
            continue

        new_content, removed = strip_marker_lines(content)
        if not removed:
            continue

        entry: dict[str, Any] = {
            "path": rel,
            "removed_lines": removed,
            "written": False,
        }
        if apply:
            try:
                file_path.write_text(new_content, encoding="utf-8")
                entry["written"] = True
            except OSError as exc:
                entry["error"] = str(exc)
                errors += 1
                files.append(entry)
                continue

        files.append(entry)
        files_changed += 1
        lines_removed += len(removed)

    files.sort(key=lambda f: f["path"])

    return CleanResult(
        ok=errors == 0,
        applied=apply,
        root=root_path.as_posix(),
        summary={
            "files_changed": files_changed,
            "lines_removed": lines_removed,
            "errors": errors,
        },
        files=files,
    )
