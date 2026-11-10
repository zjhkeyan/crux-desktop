---
description: Consolidate workspace sessions or scientific documents into grounded memory with the unified memory curator.
---

Run the Dreaming or Knowledge Wiki workflow for this workspace.
Scope / arguments: $ARGUMENTS

1. Stage inputs and scrub secrets using native `memory_dream`: `prepare_corpus` with `corpusDir` / `wikiSlug` for documents, or `export_transcripts` for recent sessions and experiment logs. Use the returned paths and target memory directory.
2. Delegate once to @memory-curator with all staged inputs and the target store. It completes Phase 1 (evidence analysis, conflicts and insights) followed by Phase 2 (topic updates, deduplication, `_index.md`, `SKILL.md` and workspace `MEMORY.md` promotion).
3. Require the curator to run `memory_dream` `validate_store`, inspect validation and return the changed paths and unresolved conflicts. Keep one writer per store and report completion only after validation passes.
