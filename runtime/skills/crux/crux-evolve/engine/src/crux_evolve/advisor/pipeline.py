"""Public pipeline for the evolve-block advisor.

This module exposes the user-facing entry points::

    advise_block(goal, *, repo_path, file_path, line_range, ...) -> AdviseResult
    advise_block_sync(...)
    advise_blocks(goal, *, repo_path, ...) -> AdviseResult       # multi-block
    advise_blocks_sync(...)
    advise_from_config(config_path) -> AdviseResult
    advise_from_config_sync(config_path)

All public entry points return :class:`AdviseResult` so a frontend never
needs to discriminate single-block vs multi-block output. ``advise_block``
produces an envelope with one entry; ``advise_blocks`` (the ``--all``
path) produces N entries plus a per-block ``errors`` list.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from loguru import logger

from crux_evolve.advisor.advice import AdviseResult, BlockAdvice, Lang
from crux_evolve.advisor.analyzer import BlockAdvisor
from crux_evolve.infra.provider.base import BaseProvider
from crux_evolve.infra.repo_analyzer.base import EvolveBlock
from crux_evolve.infra.repo_analyzer.evolve_detector import EvolveDetector


class AdvisorError(Exception):
    """Raised when the advisor cannot run (bad input, no provider, etc.)."""


# ======================================================================
# Public async API
# ======================================================================

async def advise_block(
    goal: str,
    *,
    repo_path: str | Path | None = None,
    code: str | None = None,
    file_path: str | Path | None = None,
    line_range: tuple[int, int] | None = None,
    block_id: str | None = None,
    evolve_block: EvolveBlock | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    provider_type: str = "openai_compatible",
    provider_name: str | None = None,
    lang: Lang = "en",
) -> AdviseResult:
    """Analyze a single candidate evolve block against a user goal.

    Block resolution order (first matching rule wins):

    1. ``evolve_block`` is supplied directly — use it as-is.
    2. ``repo_path`` + ``file_path`` + ``line_range`` — build an
       :class:`EvolveBlock` from the explicit location.
    3. ``repo_path`` + ``block_id`` — look up the block by its
       ``evolve check`` id (``f"{rel_path}#{start}-{end}"``).
    4. ``repo_path`` alone — scan for EVOLVE markers; if exactly one
       block is found, use it; otherwise raise.
    5. ``code`` alone — wrap the snippet as a single-file block.

    Args:
        goal: The user's stated algorithm-evolution goal.
        repo_path: Root of the user's repository.
        code: Raw source snippet; used when no repo is available.
        file_path: File containing the selected block (relative to
            ``repo_path`` or absolute).
        line_range: 1-based ``(start, end)`` line numbers (inclusive).
        block_id: Stable id from ``crux_evolve evolve check`` of the form
            ``f"{rel_posix_path}#{start}-{end}"``. Mutually exclusive
            with ``file_path``/``line_range``/``code``.
        evolve_block: Pre-built block; bypasses all resolution.
        api_key: LLM API key (falls back to ``CRUX_EVOLVE_ADVISE_API_KEY``).
        model: Model name (falls back to ``CRUX_EVOLVE_ADVISE_MODEL`` or
            ``"gpt-4o"``).
        base_url: Provider base URL (falls back to
            ``CRUX_EVOLVE_ADVISE_BASE_URL``).
        provider_type: Provider type identifier.
        provider_name: Name of a provider configured in
            ``~/.crux_evolve/settings.yaml`` (takes precedence over explicit
            ``api_key`` / ``model`` / ``base_url``).
        lang: Language for the LLM's free-text fields. ``"en"`` keeps
            today's English output; ``"zh"`` instructs the model to
            respond in Simplified Chinese without changing the JSON
            schema.

    Returns:
        An :class:`AdviseResult` envelope with exactly one entry in
        ``results`` on success.

    Raises:
        AdvisorError: On missing / ambiguous block, or missing provider
            credentials.
    """
    block = _resolve_block(
        repo_path=repo_path,
        code=code,
        file_path=file_path,
        line_range=line_range,
        block_id=block_id,
        evolve_block=evolve_block,
    )
    provider = _resolve_provider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_type=provider_type,
        provider_name=provider_name,
    )
    logger.info(
        "Running advisor on {}:{}-{} (goal: {}...)",
        block.file_path,
        block.line_start,
        block.line_end,
        goal[:60],
    )
    advisor = BlockAdvisor(provider)
    advice = await advisor.advise(goal, block, lang=lang)
    resolved_repo = (
        str(Path(repo_path).expanduser().resolve()) if repo_path is not None else None
    )
    return AdviseResult.single(
        advice,
        goal=goal,
        repo_path=resolved_repo,
        lang=lang,
    )


def advise_block_sync(
    goal: str,
    *,
    repo_path: str | Path | None = None,
    code: str | None = None,
    file_path: str | Path | None = None,
    line_range: tuple[int, int] | None = None,
    block_id: str | None = None,
    evolve_block: EvolveBlock | None = None,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    provider_type: str = "openai_compatible",
    provider_name: str | None = None,
    lang: Lang = "en",
) -> AdviseResult:
    """Synchronous wrapper around :func:`advise_block`.

    Intended for direct use from the frontend CLI when the caller is
    not already running inside an event loop. All parameters are
    identical to :func:`advise_block`.
    """
    return asyncio.run(
        advise_block(
            goal,
            repo_path=repo_path,
            code=code,
            file_path=file_path,
            line_range=line_range,
            block_id=block_id,
            evolve_block=evolve_block,
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_type=provider_type,
            provider_name=provider_name,
            lang=lang,
        )
    )


# ----------------------------------------------------------------------
# Multi-block fan-out (--all)
# ----------------------------------------------------------------------


async def advise_blocks(
    goal: str,
    repo_path: str | Path,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    provider_type: str = "openai_compatible",
    provider_name: str | None = None,
    max_concurrency: int = 5,
    lang: Lang = "en",
) -> AdviseResult:
    """Analyze every well-formed EVOLVE block in a repo concurrently.

    Files containing any marker issue (nested, unbalanced, unreadable)
    are skipped so the LLM only sees blocks the analyzer can confidently
    pair. Per-block exceptions are caught and recorded in
    ``AdviseResult.errors`` so a single failure does not abort the run.

    Args:
        goal: The user's evolution goal.
        repo_path: Root of the repo to scan.
        api_key: LLM API key (falls back to ``CRUX_EVOLVE_ADVISE_API_KEY``).
        model: Model name (falls back to ``CRUX_EVOLVE_ADVISE_MODEL`` or
            ``"gpt-4o"``).
        base_url: Provider base URL (falls back to
            ``CRUX_EVOLVE_ADVISE_BASE_URL``).
        provider_type: Provider type identifier.
        provider_name: Name of a provider configured in
            ``~/.crux_evolve/settings.yaml`` (takes precedence over explicit
            ``api_key`` / ``model`` / ``base_url``).
        max_concurrency: Maximum simultaneous LLM calls.
        lang: Language for the LLM's free-text fields.

    Returns:
        An :class:`AdviseResult` envelope with ``count`` equal to the
        number of well-formed blocks discovered.

    Raises:
        AdvisorError: When the repo path is missing or contains no
            well-formed blocks.
    """
    root = Path(repo_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise AdvisorError(f"repo_path does not exist or is not a directory: {root}")

    blocks = _resolve_blocks_for_all(root)
    provider = _resolve_provider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_type=provider_type,
        provider_name=provider_name,
    )
    advisor = BlockAdvisor(provider)
    sem = asyncio.Semaphore(max(1, int(max_concurrency)))

    async def run_one(block: EvolveBlock) -> tuple[BlockAdvice | None, dict[str, Any] | None]:
        async with sem:
            try:
                return await advisor.advise(goal, block, lang=lang), None
            except Exception as exc:  # noqa: BLE001 - deliberate per-block guard
                logger.warning(
                    "Advice failed for {}:{}-{}: {}",
                    block.file_path,
                    block.line_start,
                    block.line_end,
                    exc,
                )
                err: dict[str, Any] = {
                    "block_id": f"{block.file_path}#{block.line_start}-{block.line_end}",
                    "file_path": block.file_path,
                    "line_start": block.line_start,
                    "line_end": block.line_end,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                return None, err

    pairs = await asyncio.gather(*(run_one(b) for b in blocks))
    successes: list[BlockAdvice] = [p[0] for p in pairs if p[0] is not None]
    failures: list[dict[str, Any]] = [p[1] for p in pairs if p[1] is not None]

    return AdviseResult(
        goal=goal,
        repo_path=str(root),
        lang=lang,
        count=len(successes),
        results=successes,
        errors=failures,
    )


def advise_blocks_sync(
    goal: str,
    repo_path: str | Path,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    provider_type: str = "openai_compatible",
    provider_name: str | None = None,
    max_concurrency: int = 5,
    lang: Lang = "en",
) -> AdviseResult:
    """Synchronous wrapper around :func:`advise_blocks`."""
    return asyncio.run(
        advise_blocks(
            goal,
            repo_path,
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_type=provider_type,
            provider_name=provider_name,
            max_concurrency=max_concurrency,
            lang=lang,
        )
    )


async def advise_from_config(config_path: str | Path) -> AdviseResult:
    """Run the advisor from an advisor-config YAML file.

    Args:
        config_path: Path to a YAML file produced by
            :func:`generate_advisor_config` and filled in by the user.

    Returns:
        An :class:`AdviseResult` envelope with one entry.
    """
    from crux_evolve.advisor.advisor_config import load_advisor_config

    cfg = load_advisor_config(config_path)
    return await advise_block(
        goal=cfg.task.goal,
        repo_path=cfg.task.repo_path,
        code=cfg.task.code,
        file_path=cfg.task.file_path,
        line_range=cfg.task.line_range,
        api_key=cfg.advisor.api_key,
        model=cfg.advisor.model,
        base_url=cfg.advisor.base_url,
        provider_type=cfg.advisor.type,
    )


def advise_from_config_sync(config_path: str | Path) -> AdviseResult:
    """Synchronous wrapper around :func:`advise_from_config`."""
    return asyncio.run(advise_from_config(config_path))


# ======================================================================
# Block resolution
# ======================================================================

def _resolve_block(
    *,
    repo_path: str | Path | None,
    code: str | None,
    file_path: str | Path | None,
    line_range: tuple[int, int] | None,
    block_id: str | None = None,
    evolve_block: EvolveBlock | None,
) -> EvolveBlock:
    """Resolve caller arguments into a concrete :class:`EvolveBlock`."""
    if evolve_block is not None:
        return evolve_block

    if repo_path is not None:
        root = Path(repo_path).expanduser().resolve()
        if not root.exists():
            raise AdvisorError(f"repo_path does not exist: {root}")

        if file_path is not None and line_range is not None:
            return _block_from_line_range(root, file_path, line_range)

        if file_path is not None or line_range is not None:
            raise AdvisorError(
                "file_path and line_range must be provided together; "
                "got only one."
            )

        if block_id is not None:
            block = find_block_by_id(root, block_id)
            if block is None:
                raise AdvisorError(
                    f"block_id {block_id!r} did not match any EVOLVE block under "
                    f"{root}. Use `crux_evolve evolve check` to list available ids."
                )
            return block

        return _block_from_sole_evolve_marker(root)

    if code is not None:
        return _block_from_raw_code(code)

    raise AdvisorError(
        "No block specified. Pass one of:\n"
        "  evolve_block=EvolveBlock(...)\n"
        "  repo_path=... (+ optional file_path and line_range, or block_id)\n"
        "  code=..."
    )


def find_block_by_id(repo_root: Path, block_id: str) -> EvolveBlock | None:
    """Look up an :class:`EvolveBlock` by its ``evolve check`` id.

    The id format is ``f"{rel_posix_path}#{line_start}-{line_end}"`` —
    the same string ``crux_evolve evolve check --json`` emits. Matching is
    exact on all three components.

    Args:
        repo_root: Root of the repo to scan.
        block_id: Stable id produced by ``evolve check``.

    Returns:
        The matching :class:`EvolveBlock`, or ``None`` if no block in
        the repo matches the id.
    """
    if "#" not in block_id or "-" not in block_id.rsplit("#", 1)[-1]:
        return None
    rel_path, range_str = block_id.rsplit("#", 1)
    try:
        start_str, end_str = range_str.split("-", 1)
        start, end = int(start_str), int(end_str)
    except ValueError:
        return None

    detector = EvolveDetector(config={})
    analyzed = detector.analyze(repo_root)
    for block in analyzed.evolvable_blocks:
        # Detector stores ``file_path`` using OS-native separators
        # (backslashes on Windows); normalize to POSIX so the id
        # comparison is platform-stable and matches ``evolve check``.
        if (
            Path(block.file_path).as_posix() == rel_path
            and block.line_start == start
            and block.line_end == end
        ):
            return block
    return None


def _resolve_blocks_for_all(repo_root: Path) -> list[EvolveBlock]:
    """Discover every well-formed EVOLVE block in the repo for ``--all``.

    Files containing any marker issue (nested, unbalanced, unreadable)
    are skipped: a block produced by greedy pairing in such a file is
    not safe to evolve, so we let the user fix the file via
    ``evolve check`` / ``evolve clean`` first.

    Args:
        repo_root: Resolved absolute path of the repo to scan.

    Returns:
        Ordered list of :class:`EvolveBlock` from clean files.

    Raises:
        AdvisorError: When no well-formed block is available.
    """
    from crux_evolve.infra.repo_analyzer.marker_tools import inspect_path

    inspection = inspect_path(repo_root)
    # ``inspect_path`` exposes POSIX paths; detector keeps OS-native ones.
    # Normalize both to POSIX so the skip-set works on Windows too.
    bad_files = {f.path for f in inspection.files if f.issues}

    detector = EvolveDetector(config={})
    analyzed = detector.analyze(repo_root)
    blocks = [
        b
        for b in analyzed.evolvable_blocks
        if Path(b.file_path).as_posix() not in bad_files
    ]

    if not blocks:
        if bad_files:
            issues = ", ".join(sorted(bad_files))
            raise AdvisorError(
                f"No well-formed EVOLVE blocks under {repo_root}. "
                f"The following files have marker issues — run "
                f"`crux_evolve evolve check` for details: {issues}."
            )
        raise AdvisorError(
            f"No EVOLVE markers found under {repo_root}. "
            f"Add EVOLVE markers to the blocks you want analyzed."
        )
    return blocks


def _block_from_line_range(
    repo_root: Path,
    file_path: str | Path,
    line_range: tuple[int, int],
) -> EvolveBlock:
    """Build an :class:`EvolveBlock` from an explicit file + line range."""
    start_line, end_line = line_range
    if start_line < 1 or end_line < start_line:
        raise AdvisorError(
            f"Invalid line_range={line_range}: expected 1-based "
            f"(start, end) with start <= end."
        )

    target = Path(file_path)
    if not target.is_absolute():
        target = repo_root / target
    target = target.expanduser().resolve()
    if not target.exists():
        raise AdvisorError(f"file_path does not exist: {target}")

    try:
        text = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError) as exc:
        raise AdvisorError(f"Could not read {target}: {exc}") from exc

    lines = text.splitlines(keepends=True)
    if end_line > len(lines):
        raise AdvisorError(
            f"line_range end={end_line} exceeds file length "
            f"{len(lines)} in {target}."
        )

    original_content = "".join(lines[start_line - 1 : end_line]).rstrip("\n")

    detector = EvolveDetector(config={})
    language = detector._detect_language(target)
    context_before = detector._get_context_before(lines, start_line)
    context_after = detector._get_context_after(lines, end_line)
    comment_style = _default_comment_style(language)

    try:
        relative_path = str(target.relative_to(repo_root))
    except ValueError:
        relative_path = str(target)

    return EvolveBlock(
        file_path=relative_path,
        absolute_path=target,
        line_start=start_line,
        line_end=end_line,
        comment_style=comment_style,
        block_name="",
        original_content=original_content,
        context_before=context_before,
        context_after=context_after,
        language=language,
    )


def _block_from_sole_evolve_marker(repo_root: Path) -> EvolveBlock:
    """Scan the repo for EVOLVE markers; require exactly one block."""
    detector = EvolveDetector(config={})
    analyzed = detector.analyze(repo_root)
    blocks = analyzed.evolvable_blocks

    if not blocks:
        raise AdvisorError(
            f"No EVOLVE markers found under {repo_root}.\n"
            "Either add EVOLVE markers to the block you want analyzed, "
            "or pass file_path and line_range explicitly."
        )
    if len(blocks) > 1:
        locations = ", ".join(
            f"{b.file_path}:{b.line_start}-{b.line_end}" for b in blocks
        )
        raise AdvisorError(
            f"Multiple EVOLVE blocks found ({len(blocks)}): {locations}.\n"
            "Disambiguate by passing file_path and line_range."
        )
    return blocks[0]


def _block_from_raw_code(code: str) -> EvolveBlock:
    """Wrap a raw snippet as a single-file, whole-file EvolveBlock."""
    lines = code.splitlines(keepends=True) or [""]
    return EvolveBlock(
        file_path="<snippet>",
        absolute_path=Path("<snippet>"),
        line_start=1,
        line_end=len(lines),
        comment_style="#",
        block_name="",
        original_content=code.rstrip("\n"),
        context_before="",
        context_after="",
        language="text",
    )


def _default_comment_style(language: str) -> str:
    """Pick a sensible comment style when none can be inferred."""
    table = {
        "python": "#",
        "shell": "#",
        "ruby": "#",
        "c": "//",
        "cpp": "//",
        "java": "//",
        "javascript": "//",
        "typescript": "//",
        "go": "//",
        "rust": "//",
        "php": "//",
        "html": "<!-- -->",
        "xml": "<!-- -->",
    }
    return table.get(language.lower(), "#")


# ======================================================================
# Provider resolution
# ======================================================================

def _resolve_provider(
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    provider_type: str = "openai_compatible",
    provider_name: str | None = None,
) -> BaseProvider:
    """Resolve the advisor's LLM provider.

    Resolution order:
      1. ``provider_name`` — load from ``~/.crux_evolve/settings.yaml``.
      2. Explicit ``api_key`` / ``model`` / ``base_url``.
      3. Environment variables ``CRUX_EVOLVE_ADVISE_*``.
    """
    BaseProvider.discover("crux_evolve.infra.provider")

    if provider_name is not None:
        return _resolve_from_global_settings(provider_name)

    resolved_api_key = api_key or os.getenv("CRUX_EVOLVE_ADVISE_API_KEY", "")
    resolved_model = model or os.getenv("CRUX_EVOLVE_ADVISE_MODEL", "gpt-4o")
    resolved_base_url = base_url or os.getenv("CRUX_EVOLVE_ADVISE_BASE_URL")

    if not resolved_api_key:
        raise AdvisorError(
            "No API key provided for the advisor's LLM.\n"
            "Provide one via:\n"
            "  --api-key flag\n"
            "  CRUX_EVOLVE_ADVISE_API_KEY environment variable\n"
            "  --provider <name> (referencing ~/.crux_evolve/settings.yaml)"
        )

    config: dict[str, Any] = {
        "api_key": resolved_api_key,
        "model": resolved_model,
        "timeout": 120.0,
        "max_retries": 3,
    }
    if resolved_base_url:
        config["base_url"] = resolved_base_url

    return BaseProvider.create(provider_type, config=config)


def _resolve_from_global_settings(provider_name: str) -> BaseProvider:
    """Resolve a provider from global settings by name."""
    from crux_evolve.config.settings import load_global_settings

    global_data = load_global_settings()
    global_providers = global_data.get("providers", [])

    if not global_providers:
        raise AdvisorError(
            "No providers found in global settings (~/.crux_evolve/settings.yaml).\n"
            "Either configure global providers or pass --api-key directly."
        )

    providers_by_name = {p.get("name", "default"): p for p in global_providers}
    if provider_name not in providers_by_name:
        available = ", ".join(providers_by_name.keys())
        raise AdvisorError(
            f"Provider '{provider_name}' not found in global settings.\n"
            f"Available: {available}"
        )

    cfg = providers_by_name[provider_name]
    ptype = cfg.get("type", "openai_compatible")
    return BaseProvider.create(ptype, config=cfg)
