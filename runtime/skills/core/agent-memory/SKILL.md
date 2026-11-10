---
name: agent-memory
description: Use when consolidating past sessions into long-term memory ("dreaming"), building a grounded Knowledge Wiki skill (`.opencode/skills/<wiki-slug>/`) from a folder of scientific papers/documents, or maintaining `<workspace>/MEMORY.md` (<200 lines / 25 KB). Directly reuses `/root/anthropic_agent_memory` (`memory_distill_utils.py`, `log_review_utils.py`, `dreaming_nightly.py`, and official `Analyzer` + `Organizer` prompts).
---

# Agent Memory: Dreaming, Knowledge Wiki & `MEMORY.md`

This skill connects Open Science Desktop (Crux) directly to `/root/anthropic_agent_memory` (*The Components of Agent Memory*) without reinventing any storage or prompt logic:

1. **Working & Auto-Memory (`<workspace>/MEMORY.md`)**:
   - `runtime/osd-plugin/memory.ts` automatically injects the first **200 lines / 25 KB** of `<workspace>/MEMORY.md` and `<workspace>/.openscience/memory/_index.md` into every session's system prompt.
   - `runtime/worktree/index.ts` automatically shares `MEMORY.md` and `.openscience/memory` across all parallel Crux Git worktrees (`.worktrees/<taskId>`) via symlinks and unlinks them before `git add -A`.
2. **Dynamic Dual-Agent Dreaming (`memory-analyzer` + `memory-organizer` subagents)**:
   - Reuses `memory_distill_utils.render_text` and `log_review_utils.SECRET_NAME` to export local OpenCode sessions (`opencode.db`) and experiment runs (`.openscience/runs.jsonl`) into clean transcripts, then runs the `memory-analyzer` and `memory-organizer` subagents.
3. **Knowledge Wiki Corpus Distillation (`.opencode/skills/<wiki-slug>/`)**:
   - Extracts scientific PDFs/DOCX/notes with MinerU `[pX:bY]` locators (`crux_sci_research.py`) and distills them into `<workspace>/.opencode/skills/<wiki-slug>/` (`SKILL.md` + `_index.md` + `[[slug]].md`), which Open Science Desktop's `workspace_skill_dirs` automatically discovers as a native skill!

---

## Workflow 1: Consolidate Workspace Sessions ("Dreaming")

Call the native **`memory_dream` tool** directly (no long script paths needed):

```json
{ "action": "export_transcripts", "limit": 10 }
```
Then delegate each exported transcript in `.openscience/transcripts/*.txt` to the `memory-analyzer` subagent and once to the `memory-organizer` subagent on `.openscience/memory/`, followed by:

```json
{ "action": "validate_store", "memDir": ".openscience/memory" }
```

---

## Workflow 2: Distill a Scientific Corpus into a Grounded Knowledge Wiki Skill

Call the native **`memory_dream` tool** to stage PDFs/DOCX/Markdown papers with MinerU `[pX:bY]` provenance headers:

```json
{ "action": "prepare_corpus", "corpusDir": "papers", "wikiSlug": "catalysis-wiki" }
```
Then run `memory-analyzer` on the staged documents into `.opencode/skills/catalysis-wiki/`, run `memory-organizer` once to merge duplicates and write `SKILL.md` + `_index.md`, and validate:

```json
{ "action": "validate_store", "memDir": ".opencode/skills/catalysis-wiki", "skillName": "catalysis-wiki" }
```

---

## Workflow 3: Managed Agents Cloud Dreams API / Nightly Cron (`dreaming_nightly.py`)

When `ANTHROPIC_API_KEY`, `COOKBOOK_AGENT_ID`, and `COOKBOOK_STORE_ID` are set for Anthropic Managed Agents:

```bash
python3 /root/anthropic_agent_memory/cookbooks/dreaming_nightly.py
```
