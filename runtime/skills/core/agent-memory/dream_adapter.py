#!/usr/bin/env python3
"""Thin seam adapter connecting Open Science Desktop (Crux) to `/root/anthropic_agent_memory`.

Directly imports and reuses Anthropic's official modules without reinventing them:
- `memory_distill_utils.py` (`compact_events`, `render_text`, `transcript_files`, `estimate_cost`, `load_prompts`, `fill`)
- `log_review_utils.py` (`SECRET_NAME`, `BENIGN_SECRET_NAME`)
- `dreaming_nightly.py` (cron-ready Managed Agents dreaming runner)
- `crux_sci_research.py` (MinerU `[pX:bY]` locator reader for scientific Knowledge Wiki distillation)
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from typing import Any

sys.dont_write_bytecode = True

ANTHROPIC_MEMORY_ROOT = Path(
    os.environ.get("ANTHROPIC_MEMORY_ROOT", "/root/anthropic_agent_memory")
).resolve()
COOKBOOKS_DIR = ANTHROPIC_MEMORY_ROOT / "cookbooks"
MEMORY_DISTILL_PROMPTS_DIR = (
    ANTHROPIC_MEMORY_ROOT
    / "repos"
    / "claude-cookbooks"
    / "managed_agents"
    / "example_data"
    / "memory_distill"
    / "prompts"
)
KNOWLEDGE_WIKI_PROMPTS_DIR = COOKBOOKS_DIR / "knowledge_wiki" / "prompts"

if str(COOKBOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(COOKBOOKS_DIR))

try:
    import anthropic as _anthropic  # type: ignore[import-not-found]
except ImportError:
    import types

    sys.modules["anthropic"] = types.ModuleType("anthropic")
try:
    import regex as _regex  # type: ignore[import-not-found]
except ImportError:
    sys.modules["regex"] = re  # type: ignore[assignment]

import log_review_utils as lr  # type: ignore[import-not-found]
import memory_distill_utils as md  # type: ignore[import-not-found]

MAX_MEMORY_LINES = 200
MAX_MEMORY_BYTES = 25 * 1024
MAX_MEMORY_FILE_BYTES = 100 * 1024

_INLINE_SECRET_VALUE = re.compile(
    r"(?i)\b(sk-ant-[A-Za-z0-9_-]{12,}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,})\b"
)


def scrub_secrets(text: str) -> str:
    """Scrub raw credential tokens and secret assignments using `log_review_utils.SECRET_NAME`."""
    scrubbed = _INLINE_SECRET_VALUE.sub("[REDACTED_SECRET]", text)
    out_lines: list[str] = []
    for line in scrubbed.splitlines():
        if "=" in line or ":" in line:
            sep = "=" if "=" in line else ":"
            key, _, val = line.partition(sep)
            key_clean = key.strip().strip("\"'")
            if (
                lr.SECRET_NAME.search(key_clean)
                and not lr.BENIGN_SECRET_NAME.search(key_clean)
                and len(val.strip()) >= 8
            ):
                out_lines.append(f"{key}{sep} [REDACTED_BY_LOG_REVIEW_UTILS]")
                continue
        out_lines.append(line)
    return "\n".join(out_lines)


def default_opencode_db() -> Path:
    candidates = [
        Path.home() / ".local/share/com.crux.desktop/runtime/xdg-data/opencode/opencode.db",
        Path.home() / ".local/share/ai.openscience.desktop/runtime/xdg-data/opencode/opencode.db",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0]


def _iso_from_ms(ts_ms: Any) -> str:
    if isinstance(ts_ms, (int, float)) and ts_ms > 0:
        return datetime.fromtimestamp(ts_ms / 1000.0, tz=UTC).isoformat()
    return datetime.now(UTC).isoformat()


def export_local_opencode_sessions(
    workspace: Path,
    out_dir: Path,
    db_path: Path | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Export local OpenCode SQLite sessions + `.openscience/runs.jsonl` via `md.render_text`."""
    md.private_dir(out_dir)
    written: list[dict[str, Any]] = []
    ws_str = str(workspace.resolve())

    db = db_path or default_opencode_db()
    if db.is_file():
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = conn.execute(
            """
            SELECT id, title, directory, agent, model, time_created, time_updated
            FROM session_v2
            WHERE directory IS NULL OR directory = ? OR directory LIKE ?
            ORDER BY time_updated DESC
            LIMIT ?
            """,
            (ws_str, f"{ws_str}/%", limit),
        ).fetchall()

        for sid, title, _dir, agent_col, model_col, t_created, t_updated in rows:
            msg_rows = conn.execute(
                "SELECT id, type, data FROM session_message WHERE session_id = ? ORDER BY seq ASC, time_created ASC",
                (sid,),
            ).fetchall()
            part_rows = conn.execute(
                "SELECT message_id, type, call_id, data FROM session_part WHERE session_id = ? ORDER BY ordinal ASC, time_created ASC",
                (sid,),
            ).fetchall()
            parts_by_msg: dict[str, list[tuple[str, str | None, str]]] = {}
            for mid, ptype, call_id, pdata in part_rows:
                parts_by_msg.setdefault(mid, []).append((ptype, call_id, pdata or "{}"))

            raw_events: list[dict[str, Any]] = []
            for mid, mtype, mdata in msg_rows:
                try:
                    parsed = json.loads(mdata) if mdata else {}
                except Exception:
                    parsed = {}
                if mtype == "user":
                    text = parsed.get("text") or ""
                    if text:
                        raw_events.append({"type": "user.message", "content": scrub_secrets(str(text))})
                elif mtype in ("assistant", "agent"):
                    text = parsed.get("text") or ""
                    if text:
                        raw_events.append({"type": "agent.message", "content": scrub_secrets(str(text))})
                for ptype, call_id, pdata in parts_by_msg.get(mid, []):
                    try:
                        pp = json.loads(pdata)
                    except Exception:
                        pp = {}
                    if ptype == "text" and pp.get("text"):
                        raw_events.append(
                            {"type": "agent.message", "content": scrub_secrets(str(pp["text"]))}
                        )
                    elif ptype in ("tool", "tool-invocation", "tool_use"):
                        tname = pp.get("tool") or pp.get("name") or "tool"
                        tid = call_id or pp.get("id") or mid
                        tinput = pp.get("input") or pp.get("args") or {}
                        raw_events.append(
                            {
                                "type": "agent.tool_use",
                                "id": str(tid),
                                "name": str(tname),
                                "input": tinput,
                            }
                        )
                        toutput = pp.get("output") or pp.get("result")
                        if toutput is not None:
                            raw_events.append(
                                {
                                    "type": "agent.tool_result",
                                    "tool_use_id": str(tid),
                                    "content": scrub_secrets(str(toutput)),
                                    "is_error": bool(pp.get("error") or pp.get("isError")),
                                }
                            )

            events = md.compact_events(raw_events)
            if not events:
                continue

            model_name = "opencode"
            if model_col:
                try:
                    mobj = json.loads(model_col)
                    model_name = mobj.get("id") or model_name
                except Exception:
                    model_name = str(model_col)

            export_obj = {
                "log_format": "managed_agents_export",
                "session": {
                    "id": sid,
                    "title": title or sid,
                    "status": "idle",
                    "created_at": _iso_from_ms(t_created),
                    "updated_at": _iso_from_ms(t_updated),
                },
                "agent": {
                    "id": agent_col or "crux",
                    "name": agent_col or "crux",
                    "model": model_name,
                },
                "threads": [
                    {
                        "id": "primary",
                        "parent_thread_id": None,
                        "agent_name": agent_col or "crux",
                        "events": events,
                    }
                ],
            }
            rendered = md.render_text(export_obj)
            safe_id = re.sub(r"[^A-Za-z0-9._-]", "_", str(sid))
            out_file = out_dir / f"{safe_id}.txt"
            md.private_write(out_file, rendered)
            written.append({"session_id": sid, "path": str(out_file), "bytes": out_file.stat().st_size})
        conn.close()

    # Also export `.openscience/runs.jsonl` experiment provenance as a transcript if present
    runs_jsonl = workspace / ".openscience" / "runs.jsonl"
    if runs_jsonl.is_file():
        run_events: list[dict[str, Any]] = []
        for idx, line in enumerate(runs_jsonl.read_text(encoding="utf-8", errors="replace").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            run_id = rec.get("runId") or rec.get("id") or f"run_{idx}"
            cmd = rec.get("command") or rec.get("script") or "experiment"
            run_events.append(
                {
                    "type": "agent.tool_use",
                    "id": str(run_id),
                    "name": "experiment_run",
                    "input": {
                        "command": cmd,
                        "parameters": rec.get("parameters") or rec.get("args") or {},
                        "outputs": rec.get("outputs") or [],
                    },
                }
            )
            stdout_summary = scrub_secrets(str(rec.get("stdout") or rec.get("summary") or "completed"))
            run_events.append(
                {
                    "type": "agent.tool_result",
                    "tool_use_id": str(run_id),
                    "content": stdout_summary,
                    "is_error": bool(rec.get("exitCode", 0) != 0),
                }
            )
        compacted_runs = md.compact_events(run_events)
        if compacted_runs:
            export_runs = {
                "log_format": "managed_agents_export",
                "session": {
                    "id": "openscience_runs",
                    "title": "Workspace Reproducible Experiment Runs (.openscience/runs.jsonl)",
                    "status": "idle",
                    "created_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                "agent": {"id": "crux-runner", "name": "crux-runner", "model": "local"},
                "threads": [
                    {
                        "id": "primary",
                        "parent_thread_id": None,
                        "agent_name": "crux-runner",
                        "events": compacted_runs,
                    }
                ],
            }
            out_file = out_dir / "openscience_runs.txt"
            md.private_write(out_file, md.render_text(export_runs))
            written.append(
                {"session_id": "openscience_runs", "path": str(out_file), "bytes": out_file.stat().st_size}
            )

    files, _skipped = md.transcript_files(out_dir)
    total_usd, _estimate_lines = (
        md.estimate_cost(files, "claude-haiku-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
        if files
        else (0.0, [])
    )
    work_req = ""
    if MEMORY_DISTILL_PROMPTS_DIR.is_dir():
        prompts = md.load_prompts(MEMORY_DISTILL_PROMPTS_DIR)
        if "work_request" in prompts:
            work_req = md.fill(
                prompts["work_request"],
                mem_dir=str(workspace / ".openscience" / "memory"),
                input_paths="\n".join(str(f.path) for f in files),
                analyzer_name="memory-analyzer",
                organizer_name="memory-organizer",
            )
    return written if not files else [
        {
            **w,
            "estimated_usd": round(float(total_usd), 4),
            "work_request_preview": work_req[:400],
        }
        for w in written
    ]


def _load_sci_research_module():
    sci_script = Path(__file__).resolve().parent.parent / "literature-review" / "crux_sci_research.py"
    if not sci_script.is_file():
        return None
    spec = importlib.util.spec_from_file_location("crux_sci_research", sci_script)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["crux_sci_research"] = mod
    spec.loader.exec_module(mod)
    return mod


def prepare_scientific_corpus(
    workspace: Path,
    corpus_dir: Path,
    wiki_slug: str,
    staged_dir: Path | None = None,
) -> dict[str, Any]:
    """Extract PDF/DOCX/MD files with MinerU `[pX:bY]` provenance headers and seed `.opencode/skills/<wiki_slug>/`."""
    slug = re.sub(r"[^a-z0-9-]", "-", wiki_slug.lower()).strip("-")[:64] or "knowledge-wiki"
    for forbidden in ("claude", "anthropic"):
        slug = slug.replace(forbidden, "agent")
    target_skill_dir = workspace / ".opencode" / "skills" / slug
    target_skill_dir.mkdir(parents=True, exist_ok=True)

    stage = staged_dir or (workspace / ".openscience" / "corpus_staged" / slug)
    md.private_dir(stage)

    sci_mod = _load_sci_research_module()
    supported = {".pdf", ".docx", ".md", ".txt", ".tex", ".html"}
    staged_files: list[str] = []

    for src in sorted(corpus_dir.rglob("*")):
        if not src.is_file() or src.suffix.lower() not in supported or src.name.startswith("."):
            continue
        rel = src.relative_to(corpus_dir)
        sha = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
        if sci_mod is not None and src.suffix.lower() in {".pdf", ".docx"}:
            doc = sci_mod.read_scientific_document(str(src), max_blocks=400)
            blocks = doc.get("blocks", [])
            body = "\n\n".join(f"{b.get('locator', '')} {b.get('text', '')}" for b in blocks)
            engine = doc.get("engine", "mineru")
        else:
            body = src.read_text(encoding="utf-8", errors="replace")
            engine = "plain-text"

        header = (
            f"# Provenance Header\n"
            f"- source_path: {rel}\n"
            f"- sha256_prefix: {sha}\n"
            f"- parser_engine: {engine}\n\n"
        )
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", str(rel))
        if not safe_name.endswith(".md") and not safe_name.endswith(".txt"):
            safe_name += ".md"
        dst = stage / safe_name
        md.private_write(dst, scrub_secrets(header + body))
        staged_files.append(str(dst))

    schema_file = target_skill_dir / "_schema.md"
    if not schema_file.exists():
        schema_file.write_text(
            f"# Knowledge Wiki Schema ({slug})\n\n"
            "- Maintain `_index.md` grouped by domain (`## <Domain>`) with `[[slug]] — one-sentence summary`.\n"
            "- Every claim must cite its source document and `[pX:bY]` locator or SHA256 header.\n"
            "- Mark cross-document disagreements as `CONFLICT: <source A, date> vs <source B, date>`.\n",
            encoding="utf-8",
        )

    return {
        "wiki_slug": slug,
        "skill_dir": str(target_skill_dir),
        "staged_dir": str(stage),
        "staged_files": staged_files,
        "prompts_dir": str(KNOWLEDGE_WIKI_PROMPTS_DIR),
    }


def validate_and_promote_store(
    workspace: Path,
    mem_dir: Path,
    skill_name: str | None = None,
    promote_to_memory_md: bool = True,
) -> dict[str, Any]:
    """Clean `MOVED TO [[slug]]` stubs, ensure `_index.md` & `SKILL.md` exist, scrub secrets, and cap `MEMORY.md`."""
    mem_dir.mkdir(parents=True, exist_ok=True)
    removed_stubs: list[str] = []
    oversized_files: list[str] = []
    redacted_files: list[str] = []
    topic_entries: list[tuple[str, str]] = []

    for f in sorted(mem_dir.rglob("*.md")):
        if not f.is_file():
            continue
        raw = f.read_text(encoding="utf-8", errors="replace")
        stripped = raw.strip()
        if stripped.startswith("MOVED TO [[") and len(stripped.splitlines()) == 1:
            f.unlink()
            removed_stubs.append(str(f.relative_to(mem_dir)))
            continue

        scrubbed = scrub_secrets(raw)
        if scrubbed != raw:
            f.write_text(scrubbed, encoding="utf-8")
            redacted_files.append(str(f.relative_to(mem_dir)))
            raw = scrubbed

        if f.stat().st_size > MAX_MEMORY_FILE_BYTES:
            oversized_files.append(str(f.relative_to(mem_dir)))

        if f.name not in ("_index.md", "SKILL.md", "_schema.md"):
            slug = f.stem.lower()
            desc = ""
            m = re.search(r"(?m)^description:\s*(.+)$", raw)
            if m:
                desc = m.group(1).strip().strip("\"'")
            if not desc:
                first_body = next(
                    (
                        ln.strip("# -*")
                        for ln in raw.splitlines()
                        if ln.strip() and not ln.strip().startswith("---")
                    ),
                    slug,
                )
                desc = first_body[:120]
            topic_entries.append((slug, desc))

    index_path = mem_dir / "_index.md"
    if not index_path.is_file() or topic_entries:
        lines = ["# Memory Index", "", "## Consolidated Topics"]
        if topic_entries:
            for slug, desc in topic_entries:
                lines.append(f"[[{slug}]] — {desc}")
        else:
            lines.append("*(No consolidated topic files yet — run `/dream` or `memory_dream` `prepare_corpus` to populate.)*")
        index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Ensure root SKILL.md follows Anthropic's `organizer_system.md` contract so OpenCode auto-discovers it
    skill_path = mem_dir / "SKILL.md"
    inferred_name = re.sub(r"[^a-z0-9-]", "-", (skill_name or mem_dir.name).lower()).strip("-")[:64]
    for forbidden in ("claude", "anthropic"):
        inferred_name = inferred_name.replace(forbidden, "agent")
    if not inferred_name:
        inferred_name = "workspace-memory"

    if not skill_path.is_file():
        skill_desc = (
            f"Grounded knowledge wiki and consolidated memory store ({inferred_name}). "
            f"Read _index.md first to navigate {len(topic_entries)} linked topic notes."
        ).replace("<", "").replace(">", "")[:1000]
        skill_body = (
            f"---\n"
            f"name: {inferred_name}\n"
            f"description: {skill_desc}\n"
            f"---\n\n"
            f"# {inferred_name}\n\n"
            f"1. Start at `_index.md` to scan topics grouped by domain.\n"
            f"2. Follow `[[slug]]` links to read individual `.md` topic files.\n"
            f"3. Entries marked `was X until <date>` record superseded history; entries marked `CONFLICT:` record unresolved contradictions with dated sources.\n"
            f"4. Memory can lag behind reality — re-verify critical facts against primary documents or tool outputs before relying on them.\n"
        )
        skill_path.write_text(skill_body, encoding="utf-8")

    memory_md_path = workspace / "MEMORY.md"
    memory_md_truncated = False
    if promote_to_memory_md:
        existing = memory_md_path.read_text(encoding="utf-8") if memory_md_path.is_file() else "# Workspace Auto-Memory (MEMORY.md)\n"
        existing = scrub_secrets(existing)
        marker = "## Distilled Memory Index"
        base_part = existing.split(marker)[0].rstrip()
        pointer_lines = [
            marker,
            f"- Consolidated store: `{mem_dir.relative_to(workspace) if mem_dir.is_relative_to(workspace) else mem_dir}` (`_index.md`)",
        ]
        for slug, desc in topic_entries[:25]:
            pointer_lines.append(f"- [[{slug}]] — {desc}")
        combined = base_part + "\n\n" + "\n".join(pointer_lines) + "\n"
        lines = combined.splitlines()
        if len(lines) > MAX_MEMORY_LINES:
            lines = lines[:MAX_MEMORY_LINES]
            memory_md_truncated = True
        final_text = "\n".join(lines) + "\n"
        if len(final_text.encode("utf-8")) > MAX_MEMORY_BYTES:
            final_text = final_text.encode("utf-8")[:MAX_MEMORY_BYTES].decode("utf-8", errors="ignore")
            memory_md_truncated = True
        memory_md_path.write_text(final_text, encoding="utf-8")

    return {
        "mem_dir": str(mem_dir),
        "skill_md": str(skill_path),
        "index_md": str(index_path),
        "topic_count": len(topic_entries),
        "removed_stubs": removed_stubs,
        "redacted_files": redacted_files,
        "oversized_files": oversized_files,
        "memory_md": str(memory_md_path) if promote_to_memory_md else None,
        "memory_md_truncated": memory_md_truncated,
    }


def run_nightly_passthrough() -> int:
    """Invoke `/root/anthropic_agent_memory/cookbooks/dreaming_nightly.py` directly."""
    nightly_script = COOKBOOKS_DIR / "dreaming_nightly.py"
    res = subprocess.run([sys.executable, str(nightly_script)], check=False)
    return res.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crux <-> Anthropic Agent Memory Seam Adapter")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_exp = sub.add_parser("export-transcripts", help="Export local OpenCode sessions & runs.jsonl via memory_distill_utils.render_text")
    p_exp.add_argument("--workspace", default=".", help="Workspace directory")
    p_exp.add_argument("--out-dir", default=None, help="Output directory for plain-text transcripts")
    p_exp.add_argument("--db", default=None, help="Optional path to opencode.db")
    p_exp.add_argument("--limit", type=int, default=50)

    p_corp = sub.add_parser("prepare-corpus", help="Prepare scientific PDF/DOCX/MD corpus for Knowledge Wiki distillation")
    p_corp.add_argument("--workspace", default=".", help="Workspace directory")
    p_corp.add_argument("--corpus-dir", required=True, help="Input folder of papers/documents")
    p_corp.add_argument("--wiki-slug", required=True, help="Target skill slug under .opencode/skills/<wiki-slug>")

    p_val = sub.add_parser("validate-store", help="Clean MOVED TO stubs, ensure SKILL.md/_index.md, and cap MEMORY.md")
    p_val.add_argument("--workspace", default=".", help="Workspace directory")
    p_val.add_argument("--mem-dir", default=None, help="Memory directory (default: <workspace>/.openscience/memory)")
    p_val.add_argument("--skill-name", default=None, help="Skill frontmatter name")
    p_val.add_argument("--no-promote", action="store_true", help="Do not update <workspace>/MEMORY.md")

    sub.add_parser("nightly-cloud", help="Run official dreaming_nightly.py for Anthropic Managed Agents")

    args = parser.parse_args(argv)
    if args.cmd == "export-transcripts":
        ws = Path(args.workspace).resolve()
        out = Path(args.out_dir).resolve() if args.out_dir else (ws / ".openscience" / "transcripts")
        db = Path(args.db).resolve() if args.db else None
        res = export_local_opencode_sessions(ws, out, db_path=db, limit=args.limit)
        print(json.dumps({"exported": res, "count": len(res), "out_dir": str(out)}, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "prepare-corpus":
        ws = Path(args.workspace).resolve()
        cdir = Path(args.corpus_dir).resolve()
        res = prepare_scientific_corpus(ws, cdir, args.wiki_slug)
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "validate-store":
        ws = Path(args.workspace).resolve()
        mdir = Path(args.mem_dir).resolve() if args.mem_dir else (ws / ".openscience" / "memory")
        res = validate_and_promote_store(
            ws, mdir, skill_name=args.skill_name, promote_to_memory_md=not args.no_promote
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    if args.cmd == "nightly-cloud":
        return run_nightly_passthrough()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
