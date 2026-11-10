// Project & Auto-Memory injection seam for Open Science Desktop (`runtime/osd-plugin/memory.ts`).
//
// Adapts Anthropic's `MEMORY.md` & Consolidative Memory hierarchy specification
// (`Claude_Code_Memory_System_Docs.md` & `The_Components_of_Agent_Memory_Anthropic_Research.md`):
// - Top-level auto-memory (`<workspace>/MEMORY.md`) is loaded into every session,
//   strictly capped at the first 200 lines or 25 KB so it acts as a fast routing index.
// - Deeper semantic notes live in `<workspace>/.openscience/memory/<slug>.md` (indexed by
//   `<workspace>/.openscience/memory/_index.md`) or as Knowledge Wiki skills under
//   `<workspace>/.opencode/skills/<wiki-slug>/SKILL.md`.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export const MAX_MEMORY_LINES = 200;
export const MAX_MEMORY_BYTES = 25 * 1024;
export const MAX_INDEX_LINES = 120;

export const MEMORY_STEERING_HEADER = `When working in this workspace, you have access to persistent agent memory:
- \`MEMORY.md\` (workspace root, shared across Git worktrees): top-level auto-memory index (only the first 200 lines / 25 KB are injected automatically into every session).
- \`.openscience/memory/\` (with \`_index.md\` and \`[[slug]].md\` topic files) & \`.opencode/skills/<wiki-slug>/\`: consolidated semantic memory and grounded Knowledge Wikis built via \`/dream\` (\`memory-analyzer\` + \`memory-organizer\`).
- Update \`MEMORY.md\` or \`.openscience/memory/\` when the user gives a correction/preference or when you verify a non-obvious rule, command flag, experimental trap, or causal finding that a future session would otherwise have to rediscover. Never write secrets, API keys, or tokens into memory.`;

export function truncateMemoryHeader(
  raw: string,
  maxLines: number = MAX_MEMORY_LINES,
  maxBytes: number = MAX_MEMORY_BYTES,
): { content: string; truncated: boolean } {
  const normalized = raw.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  let truncated = false;
  let slicedLines = lines;
  if (lines.length > maxLines) {
    slicedLines = lines.slice(0, maxLines);
    truncated = true;
  }
  let joined = slicedLines.join("\n");
  if (Buffer.byteLength(joined, "utf8") > maxBytes) {
    truncated = true;
    const buf = Buffer.from(joined, "utf8").subarray(0, maxBytes);
    joined = buf.toString("utf8");
    const lastNewline = joined.lastIndexOf("\n");
    if (lastNewline > 0) {
      joined = joined.slice(0, lastNewline);
    }
  }
  return { content: joined.trimEnd(), truncated };
}

export function loadWorkspaceMemorySystemPrompt(workspaceDir?: string | null): string {
  if (!workspaceDir) return MEMORY_STEERING_HEADER;
  const sections: string[] = [MEMORY_STEERING_HEADER];

  const memoryFile = join(workspaceDir, "MEMORY.md");
  if (existsSync(memoryFile)) {
    try {
      const raw = readFileSync(memoryFile, "utf8");
      if (raw.trim()) {
        const { content, truncated } = truncateMemoryHeader(raw, MAX_MEMORY_LINES, MAX_MEMORY_BYTES);
        const note = truncated
          ? "\n\n[MEMORY.md truncated at 200 lines / 25 KB. Move detailed notes to .openscience/memory/<slug>.md and link them from MEMORY.md.]"
          : "";
        sections.push(`<workspace_memory path="MEMORY.md">\n${content}${note}\n</workspace_memory>`);
      }
    } catch {}
  }

  const indexFile = join(workspaceDir, ".openscience", "memory", "_index.md");
  if (existsSync(indexFile)) {
    try {
      const raw = readFileSync(indexFile, "utf8");
      if (raw.trim()) {
        const { content } = truncateMemoryHeader(raw, MAX_INDEX_LINES, MAX_MEMORY_BYTES);
        sections.push(
          `<consolidated_memory_index path=".openscience/memory/_index.md">\n${content}\n</consolidated_memory_index>`,
        );
      }
    } catch {}
  }

  return sections.join("\n\n");
}
