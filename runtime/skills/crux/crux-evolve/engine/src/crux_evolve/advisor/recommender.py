"""Repo-wide block recommender.

Given a repository path and a user goal, discover a small set of
candidate blocks the user might want to evolve, score each with the
Phase 1 advisor, and return them grouped into tiers
(``core`` / ``expanded`` / ``alternatives``).

CruxEvolve can only evolve ONE block per run today — the recommendations
are alternative CHOICES a user can make, not a set to co-evolve. See
the single-block constraint in :mod:`crux_evolve.planner.sampler` (all four
samplers use ``evolvable_blocks[0]``).
"""

from __future__ import annotations

import asyncio
import fnmatch
import re
from pathlib import Path
from typing import Any

from loguru import logger

from crux_evolve.advisor.advice import BlockAdvice, Lang
from crux_evolve.advisor.analyzer import BlockAdvisor, _parse_json_response
from crux_evolve.advisor.prompts import language_directive
from crux_evolve.advisor.recommendation import BlockRecommendation, RepoRecommendations
from crux_evolve.advisor.recommender_prompts import DISCOVER_BLOCKS_PROMPT
from crux_evolve.infra.provider.base import BaseProvider
from crux_evolve.infra.repo_analyzer.base import EvolveBlock
from crux_evolve.infra.repo_analyzer.evolve_detector import EvolveDetector

# ======================================================================
# Defaults — mirror EvolveDetector's filters so the two stay in sync.
# ======================================================================

DEFAULT_INCLUDE = (
    "*.py", "*.cpp", "*.cc", "*.c", "*.h", "*.hpp", "*.java", "*.js",
    "*.ts", "*.go", "*.rs", "*.rb", "*.sh", "*.php", "*.html", "*.xml",
)
DEFAULT_EXCLUDE = (
    ".git/**", ".gitignore", "__pycache__/**", "*.pyc", "node_modules/**",
    "build/**", "dist/**", "*.egg-info/**", ".venv/**", "venv/**",
    ".idea/**", ".vscode/**", "*.log", "*.tmp", "*.bak",
)

DEFAULT_MAX_TOTAL_CHARS = 180_000  # ~45k tokens
DEFAULT_MAX_FILE_BYTES = 200_000   # skip single files larger than this
DEFAULT_MAX_CONCURRENCY = 5

_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


# ======================================================================
# Public API
# ======================================================================

class RepoRecommender:
    """Discover and rank evolve-block candidates for one repo/goal pair.

    The recommender is deliberately stateless aside from its provider so
    long-running frontends can instantiate one per request. Call
    :meth:`recommend` to drive the full flow.
    """

    def __init__(
        self,
        provider: BaseProvider,
        *,
        max_total_chars: int = DEFAULT_MAX_TOTAL_CHARS,
        max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        include_patterns: tuple[str, ...] = DEFAULT_INCLUDE,
        exclude_patterns: tuple[str, ...] = DEFAULT_EXCLUDE,
    ):
        """Wrap a provider with the compaction + advice settings for one request."""
        self._provider = provider
        self._advisor = BlockAdvisor(provider)
        self._max_total_chars = max_total_chars
        self._max_file_bytes = max_file_bytes
        self._max_concurrency = max(1, max_concurrency)
        self._include = include_patterns
        self._exclude = exclude_patterns

    async def recommend(
        self,
        goal: str,
        repo_path: str | Path,
        *,
        include_raw: bool = False,
        lang: Lang = "en",
    ) -> RepoRecommendations:
        """Run the full recommend flow and return the structured result.

        Args:
            goal: User's evolution goal.
            repo_path: Path to the repository to scan.
            include_raw: If True, attach the unparsed discovery LLM text
                to the result for debugging.
            lang: Language for the LLM's free-text fields. ``"en"`` keeps
                today's English output; ``"zh"`` instructs the model to
                respond in Simplified Chinese without changing the JSON
                schema. Threaded through both the discovery call and
                every per-block advice call.
        """
        root = Path(repo_path).expanduser().resolve()
        if not root.exists():
            from crux_evolve.advisor.pipeline import AdvisorError

            raise AdvisorError(f"repo_path does not exist: {root}")
        if not root.is_dir():
            from crux_evolve.advisor.pipeline import AdvisorError

            raise AdvisorError(f"repo_path is not a directory: {root}")

        compacted, unreadable = _compact_repo(
            root,
            goal,
            max_total_chars=self._max_total_chars,
            max_file_bytes=self._max_file_bytes,
            include_patterns=self._include,
            exclude_patterns=self._exclude,
        )

        prompt = DISCOVER_BLOCKS_PROMPT.format(
            lang_directive=language_directive(lang),
            goal=goal.strip(),
            repo_path=str(root),
            file_tree=compacted.tree,
            file_contents=compacted.contents,
        )
        logger.info(
            "Recommender discovery call: {} files shown, {} chars",
            compacted.files_shown,
            len(compacted.contents),
        )
        result = await self._provider.generate(prompt, temperature=0.2)
        parsed = _parse_json_response(result.text)
        if parsed is None:
            from crux_evolve.advisor.pipeline import AdvisorError

            raise AdvisorError(
                "Discovery call returned unparseable output. "
                "Raw text (first 500 chars):\n" + result.text[:500]
            )

        core_raw, expanded_raw, alt_raw = _split_tiers(parsed)

        if core_raw is None:
            from crux_evolve.advisor.pipeline import AdvisorError

            raise AdvisorError(
                "Discovery response is missing a 'core' recommendation."
            )

        dropped: list[dict[str, Any]] = []
        core_block = _validate_candidate(core_raw, root, "core", dropped)
        if core_block is None:
            from crux_evolve.advisor.pipeline import AdvisorError

            raise AdvisorError(
                f"Core candidate failed validation: {dropped[-1] if dropped else 'unknown'}"
            )

        expanded_blocks: list[tuple[EvolveBlock, str]] = []
        for raw in expanded_raw:
            ev = _validate_candidate(raw, root, "expanded", dropped)
            if ev is None:
                continue
            if not _is_superset(ev, core_block):
                dropped.append({
                    "file_path": raw.get("file_path", ""),
                    "line_start": raw.get("line_start"),
                    "line_end": raw.get("line_end"),
                    "tier": "expanded",
                    "reason": "not_superset_of_core",
                })
                continue
            expanded_blocks.append((ev, str(raw.get("rationale", "")).strip()))

        alt_blocks: list[tuple[EvolveBlock, str]] = []
        for raw in alt_raw:
            ev = _validate_candidate(raw, root, "alternative", dropped)
            if ev is None:
                continue
            if _ranges_overlap(ev, core_block):
                dropped.append({
                    "file_path": raw.get("file_path", ""),
                    "line_start": raw.get("line_start"),
                    "line_end": raw.get("line_end"),
                    "tier": "alternative",
                    "reason": "overlaps_core",
                })
                continue
            alt_blocks.append((ev, str(raw.get("rationale", "")).strip()))

        core_rationale = str(core_raw.get("rationale", "")).strip()

        # Advice enrichment — concurrent, tolerant of per-block failure.
        all_blocks: list[tuple[EvolveBlock, str, str, int | None]] = [
            (core_block, core_rationale, "core", None)
        ]
        for idx, (ev, rat) in enumerate(
            sorted(expanded_blocks, key=lambda p: _size(p[0]))
        ):
            all_blocks.append((ev, rat, "expanded", idx))
        for ev, rat in alt_blocks:
            all_blocks.append((ev, rat, "alternative", None))

        advice_results = await self._advise_many(
            goal, [b[0] for b in all_blocks], lang=lang
        )

        recs: list[BlockRecommendation] = []
        for (ev, rationale, tier, variant_idx), (advice, err) in zip(
            all_blocks, advice_results, strict=True
        ):
            recs.append(
                BlockRecommendation(
                    file_path=ev.file_path,
                    line_start=ev.line_start,
                    line_end=ev.line_end,
                    tier=tier,  # type: ignore[arg-type]
                    variant_index=variant_idx,
                    size_lines=_size(ev),
                    discovery_rationale=rationale,
                    advice=advice,
                    advice_error=err,
                )
            )

        core_rec = recs[0]
        expanded_recs = [r for r in recs if r.tier == "expanded"]
        alt_recs = [r for r in recs if r.tier == "alternative"]
        _sort_alternatives(alt_recs)

        return RepoRecommendations(
            goal=goal,
            repo_path=str(root),
            core=core_rec,
            expanded=expanded_recs,
            alternatives=alt_recs,
            unreadable_files=unreadable,
            dropped_candidates=dropped,
            discovery_raw=result.text if include_raw else None,
            lang=lang,
        )

    async def _advise_many(
        self,
        goal: str,
        blocks: list[EvolveBlock],
        *,
        lang: Lang = "en",
    ) -> list[tuple[BlockAdvice | None, str | None]]:
        """Run advice on every block under a concurrency cap."""
        sem = asyncio.Semaphore(self._max_concurrency)

        async def run_one(block: EvolveBlock) -> tuple[BlockAdvice | None, str | None]:
            async with sem:
                try:
                    return await self._advisor.advise(goal, block, lang=lang), None
                except Exception as exc:  # noqa: BLE001 - deliberate catch-all
                    logger.warning(
                        "Advice failed for {}:{}-{}: {}",
                        block.file_path,
                        block.line_start,
                        block.line_end,
                        exc,
                    )
                    return None, f"{type(exc).__name__}: {exc}"

        return await asyncio.gather(*(run_one(b) for b in blocks))


async def recommend_blocks(
    goal: str,
    repo_path: str | Path,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    provider_type: str = "openai_compatible",
    provider_name: str | None = None,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    include_raw: bool = False,
    lang: Lang = "en",
) -> RepoRecommendations:
    """Top-level async entry point — resolves a provider and runs one request."""
    from crux_evolve.advisor.pipeline import _resolve_provider

    provider = _resolve_provider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        provider_type=provider_type,
        provider_name=provider_name,
    )
    recommender = RepoRecommender(provider, max_concurrency=max_concurrency)
    return await recommender.recommend(
        goal, repo_path, include_raw=include_raw, lang=lang
    )


def recommend_blocks_sync(
    goal: str,
    repo_path: str | Path,
    *,
    api_key: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    provider_type: str = "openai_compatible",
    provider_name: str | None = None,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    include_raw: bool = False,
    lang: Lang = "en",
) -> RepoRecommendations:
    """Synchronous wrapper around :func:`recommend_blocks`."""
    return asyncio.run(
        recommend_blocks(
            goal,
            repo_path,
            api_key=api_key,
            model=model,
            base_url=base_url,
            provider_type=provider_type,
            provider_name=provider_name,
            max_concurrency=max_concurrency,
            include_raw=include_raw,
            lang=lang,
        )
    )


# ======================================================================
# Compaction: build file tree + ranked file contents under a char budget.
# ======================================================================

class _Compacted:
    """Lightweight container for compaction output."""

    __slots__ = ("tree", "contents", "files_shown")

    def __init__(self, tree: str, contents: str, files_shown: int):
        self.tree = tree
        self.contents = contents
        self.files_shown = files_shown


def _compact_repo(
    root: Path,
    goal: str,
    *,
    max_total_chars: int,
    max_file_bytes: int,
    include_patterns: tuple[str, ...],
    exclude_patterns: tuple[str, ...],
) -> tuple[_Compacted, list[str]]:
    """Walk the repo, produce (tree + ranked file contents, unreadable list)."""
    files = _collect_files(root, include_patterns, exclude_patterns)
    tree = _render_tree(root, files)

    ranked = _rank_files(files, root, goal)

    parts: list[str] = []
    used = 0
    unreadable: list[str] = []
    shown = 0
    for rel_path in ranked:
        path = root / rel_path
        try:
            size = path.stat().st_size
        except OSError:
            unreadable.append(rel_path)
            continue
        if size > max_file_bytes:
            # Too big to send in full; include a truncated header only.
            header = (
                f"\n--- {rel_path} ({size} bytes, truncated head only) ---\n"
            )
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                unreadable.append(rel_path)
                continue
            body = text[:4000]
            if len(text) > len(body):
                body += "\n# ...file truncated...\n"
        else:
            header = f"\n--- {rel_path} ---\n"
            try:
                body = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                unreadable.append(rel_path)
                continue

        chunk = header + _annotate_with_line_numbers(body)
        if used + len(chunk) > max_total_chars and parts:
            # No room even after already showing something; stop.
            break
        if used + len(chunk) > max_total_chars:
            # This file alone exceeds the budget — truncate hard.
            chunk = chunk[: max_total_chars - used]
            chunk += "\n# ...compaction truncated...\n"
        parts.append(chunk)
        used += len(chunk)
        shown += 1
        if used >= max_total_chars:
            break

    contents = "".join(parts) if parts else "(no file contents fit within budget)"
    return _Compacted(tree=tree, contents=contents, files_shown=shown), unreadable


def _collect_files(
    root: Path,
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> list[str]:
    """Return relative file paths under ``root`` that match filters."""
    results: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            continue
        if _matches_any(rel, exclude):
            continue
        if not _matches_any(rel, include) and not _matches_any(path.name, include):
            continue
        results.append(rel)
    results.sort()
    return results


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    return any(
        fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(Path(path).name, pat)
        for pat in patterns
    )


def _render_tree(root: Path, files: list[str]) -> str:
    """Render the repo as a list of relative file paths, one per line.

    Prior versions rendered only basenames, which caused the LLM to
    guess paths (repeating the repo's root directory name, flattening
    subdirs). Full relative paths let the LLM cite exactly what it
    will later be validated against.
    """
    if not files:
        return "(no matching files)"
    return "\n".join(files)


def _rank_files(files: list[str], root: Path, goal: str) -> list[str]:
    """Order files so the ones most likely to contain goal-relevant code go first."""
    keywords = _extract_keywords(goal)

    def score(rel: str) -> float:
        name = Path(rel).name.lower()
        s = 0.0
        if name.startswith("readme"):
            s += 100
        # Goal-keyword match on path
        lowered = rel.lower()
        for kw in keywords:
            if kw in lowered:
                s += 20
        # Language boost (python-heavy repo is the common case)
        if rel.endswith(".py"):
            s += 10
        # Depth penalty — deeply-nested files less likely to be core
        s -= rel.count("/") * 2
        # Size penalty is applied at read time; here we just prefer shallow
        # named entrypoints like solve.py / main.py / algo.py / policy.py
        if name in {"main.py", "solve.py", "algo.py", "policy.py", "run.py"}:
            s += 30
        return s

    return sorted(files, key=score, reverse=True)


def _extract_keywords(goal: str) -> list[str]:
    """Pull meaningful tokens out of the goal string for file ranking."""
    stopwords = {
        "the", "a", "an", "and", "or", "for", "with", "that", "this", "its",
        "our", "your", "their", "from", "into", "over", "under", "about",
        "against", "between", "through", "during", "before", "after", "above",
        "below", "then", "than", "just", "also", "as", "of", "in", "on", "to",
        "by", "is", "it", "be", "are", "was", "were", "at", "maximize", "minimize",
        "improve", "optimize", "reduce", "increase",
    }
    tokens = _WORD_RE.findall(goal.lower())
    return [t for t in tokens if t not in stopwords]


def _annotate_with_line_numbers(text: str) -> str:
    """Prepend 1-based line numbers so the LLM can cite ranges exactly."""
    lines = text.splitlines()
    width = len(str(len(lines))) if lines else 1
    return "\n".join(f"{idx + 1:>{width}}  {line}" for idx, line in enumerate(lines))


# ======================================================================
# Candidate validation
# ======================================================================

def _split_tiers(
    parsed: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    """Pull the three tier buckets out of the LLM response, tolerating shape drift."""
    core = parsed.get("core")
    if not isinstance(core, dict):
        core = None
    expanded = parsed.get("expanded") or []
    if not isinstance(expanded, list):
        expanded = []
    alt = parsed.get("alternatives") or []
    if not isinstance(alt, list):
        alt = []
    return core, [e for e in expanded if isinstance(e, dict)], [a for a in alt if isinstance(a, dict)]


def _validate_candidate(
    raw: dict[str, Any],
    root: Path,
    tier: str,
    dropped: list[dict[str, Any]],
) -> EvolveBlock | None:
    """Turn a raw ``{file_path, line_start, line_end}`` dict into an EvolveBlock.

    Returns ``None`` and appends to ``dropped`` on any validation failure.
    """
    raw_path = raw.get("file_path")
    raw_start = raw.get("line_start")
    raw_end = raw.get("line_end")

    def drop(reason: str) -> None:
        dropped.append({
            "file_path": raw_path or "",
            "line_start": raw_start,
            "line_end": raw_end,
            "tier": tier,
            "reason": reason,
        })

    if not isinstance(raw_path, str) or not raw_path.strip():
        drop("missing_file_path")
        return None
    try:
        start = int(raw_start)  # type: ignore[arg-type]
        end = int(raw_end)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        drop("invalid_line_numbers")
        return None

    if start < 1 or end < start:
        drop("invalid_range")
        return None

    # Tolerate LLMs that prefix paths with the repo's root-directory name
    # (a common hallucination when the tree shows "myrepo/" as a heading).
    # Normalize separators but preserve ".." so the escape check still fires.
    cleaned_path = raw_path.replace("\\", "/")
    if cleaned_path.startswith("./"):
        cleaned_path = cleaned_path[2:]
    candidate = (root / cleaned_path).resolve()
    if not candidate.is_file():
        repo_prefix = root.name + "/"
        if cleaned_path.startswith(repo_prefix):
            alt = cleaned_path[len(repo_prefix):]
            alt_candidate = (root / alt).resolve()
            if alt_candidate.is_file():
                candidate = alt_candidate
                cleaned_path = alt

    try:
        candidate.relative_to(root)
    except ValueError:
        drop("escaped_repo")
        return None
    if not candidate.is_file():
        drop("file_not_found")
        return None

    try:
        text = candidate.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        drop("file_unreadable")
        return None

    lines = text.splitlines(keepends=True)
    if end > len(lines):
        drop("range_out_of_bounds")
        return None

    original_content = "".join(lines[start - 1 : end]).rstrip("\n")

    detector = EvolveDetector(config={})
    language = detector._detect_language(candidate)
    context_before = detector._get_context_before(lines, start)
    context_after = detector._get_context_after(lines, end)
    comment_style = _default_comment_style(language)

    return EvolveBlock(
        file_path=cleaned_path,
        absolute_path=candidate,
        line_start=start,
        line_end=end,
        comment_style=comment_style,
        block_name="",
        original_content=original_content,
        context_before=context_before,
        context_after=context_after,
        language=language,
    )


def _default_comment_style(language: str) -> str:
    table = {
        "python": "#", "shell": "#", "ruby": "#",
        "c": "//", "cpp": "//", "java": "//",
        "javascript": "//", "typescript": "//",
        "go": "//", "rust": "//", "php": "//",
        "html": "<!-- -->", "xml": "<!-- -->",
    }
    return table.get(language.lower(), "#")


def _size(block: EvolveBlock) -> int:
    return block.line_end - block.line_start + 1


def _is_superset(outer: EvolveBlock, inner: EvolveBlock) -> bool:
    """True iff ``outer`` fully contains ``inner`` and is in the same file."""
    return (
        outer.file_path == inner.file_path
        and outer.line_start <= inner.line_start
        and outer.line_end >= inner.line_end
    )


def _ranges_overlap(a: EvolveBlock, b: EvolveBlock) -> bool:
    """True iff ``a`` and ``b`` share lines in the same file."""
    if a.file_path != b.file_path:
        return False
    return not (a.line_end < b.line_start or b.line_end < a.line_start)


def _sort_alternatives(recs: list[BlockRecommendation]) -> None:
    """Sort alternatives in place by advice score desc, None last."""
    def key(r: BlockRecommendation) -> tuple[int, float]:
        score = r.advice.score if r.advice and r.advice.score is not None else float("-inf")
        # Put scored entries first; then sort by score desc.
        return (0 if score != float("-inf") else 1, -score if score != float("-inf") else 0.0)

    recs.sort(key=key)
