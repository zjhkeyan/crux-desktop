// `worktree`: Crux-powered parallel Git worktree isolation, multi-CLI agent
// control plane, progress checkpoint updates (`set`), and post-task diff
// review & verified merge gate.
//
// Directly reuses Crux's `tui-agent-config`, `tui-agent-detection-commands`,
// `worktree-include-file`, `worktree-symlinks`, and `worktree-lineage` modules
// in `../worktree/` (ported from github.com/ai4s-research/open-science, MIT).
import {
  detectInstalledCruxAgents,
  inspectCruxWorktreeDiff,
  listCruxWorktreeStatus,
  mergeCruxWorktreeTask,
  removeCruxWorktreeTask,
  resolveCurrentCruxWorktree,
  setCruxWorktreeMetadata,
  spawnCruxWorktreeTask,
  WORKTREE_VERBS,
  type WorkspaceStatus,
  type WorktreeVerb,
} from "../worktree/index";

export const worktreeTool = {
  name: "worktree",
  description:
    "Manage parallel Git worktrees, progress checkpoints, and heterogeneous CLI coding agents (Claude Code, Codex, OpenCode, Grok, Gemini, Cursor, GitHub Copilot, Pi, DeepSeek Harness, Antigravity, Aider, etc.) using Crux's worktree & TUI agent catalog.\n\n" +
    "Verbs:\n" +
    "- agents: detect installed CLI agents on PATH and show their prompt injection modes.\n" +
    "- spawn / create: create an isolated Git worktree (.worktrees/<taskId> on branch crux/<taskId>), materialize .worktreeinclude + shared tools/MEMORY.md symlinks, and bind a CLI agent (locally or on an SSH host).\n" +
    "- set: update Crux worktree metadata & progress checkpoints (workspaceStatus: todo|in-progress|in-review|completed|blocked, comment/checkpoint note, displayName, parentWorktree).\n" +
    "- current: resolve the enclosing Crux-managed worktree from the current directory.\n" +
    "- status / ps: unified control-plane view across all bound worktrees (taskId, agent, workspaceStatus, latest checkpoint comment, branch, commitsAhead, dirtyCount).\n" +
    "- diff: inspect uncommitted files, commit count ahead of base, diff stat, and unified patch for a task worktree.\n" +
    "- merge: run an optional deterministic verification command (--verify) inside the worktree, safely unlink shared symlinks, and merge the branch (--no-ff) back into the base repository.\n" +
    "- rm: safely unlink shared symlinks and remove a worktree checkout.",
  input: {
    type: "object",
    properties: {
      action: {
        type: "string",
        enum: [...WORKTREE_VERBS],
        description: "Which worktree control-plane verb to run.",
      },
      taskId: {
        type: "string",
        description: "Task identifier for spawn/create, set, diff, merge, or rm (e.g. 'dft-ts-a' or 'current').",
      },
      agent: {
        type: "string",
        description: "CLI agent id from Crux's TUI_AGENT_CONFIG (claude, codex, opencode, grok, gemini, cursor, copilot, pi, dsh, antigravity, aider, etc.).",
      },
      prompt: {
        type: "string",
        description: "Initial task prompt passed to the CLI agent on launch.",
      },
      baseBranch: {
        type: "string",
        description: "Optional base branch to fork the worktree from.",
      },
      host: {
        type: "string",
        description: "Execution host ('local' or an SSH remote host id).",
      },
      accountDir: {
        type: "string",
        description: "Optional isolated account config directory (CLAUDE_CONFIG_DIR or CODEX_HOME).",
      },
      openPane: {
        type: "boolean",
        description: "Open a live GPU-rendered split terminal pane in Crux Screen for this worktree.",
      },
      workspaceStatus: {
        type: "string",
        enum: ["todo", "in-progress", "in-review", "completed", "blocked"],
        description: "For spawn/create or set: Crux board status of the worktree.",
      },
      comment: {
        type: "string",
        description: "For spawn/create or set: progress checkpoint note recorded on the worktree.",
      },
      displayName: {
        type: "string",
        description: "For set: human-readable display name for the worktree.",
      },
      parentWorktree: {
        type: "string",
        description: "For spawn/create or set: parent worktree taskId for lineage tracking (or 'null' to clear).",
      },
      verifyCmd: {
        type: "string",
        description: "For merge: deterministic test/evaluation command that must pass inside the worktree before merging.",
      },
      cleanup: {
        type: "boolean",
        description: "For merge or rm: remove the worktree directory / branch.",
      },
    },
    required: ["action"],
    additionalProperties: false,
  },
} as const;

export async function runWorktree(
  repoRoot: string,
  args: Record<string, unknown>,
): Promise<string> {
  const action = args.action as WorktreeVerb;
  switch (action) {
    case "agents": {
      const res = await detectInstalledCruxAgents();
      return JSON.stringify(res, null, 2);
    }
    case "spawn":
    case "create": {
      const taskId = String(args.taskId ?? "").trim();
      if (!taskId) throw new Error("worktree spawn/create requires taskId");
      const rec = await spawnCruxWorktreeTask({
        repoRoot,
        taskId,
        agent: typeof args.agent === "string" ? args.agent : "claude",
        prompt: typeof args.prompt === "string" ? args.prompt : "",
        baseBranch: typeof args.baseBranch === "string" ? args.baseBranch : undefined,
        host: typeof args.host === "string" ? args.host : "local",
        accountDir: typeof args.accountDir === "string" ? args.accountDir : undefined,
        openPane: args.openPane === true,
        workspaceStatus:
          typeof args.workspaceStatus === "string"
            ? (args.workspaceStatus as WorkspaceStatus)
            : undefined,
        comment: typeof args.comment === "string" ? args.comment : undefined,
        parentWorktree:
          typeof args.parentWorktree === "string" ? args.parentWorktree : undefined,
      });
      return JSON.stringify(rec, null, 2);
    }
    case "set": {
      const rec = await setCruxWorktreeMetadata({
        repoRoot,
        taskId: typeof args.taskId === "string" ? args.taskId : undefined,
        displayName: typeof args.displayName === "string" ? args.displayName : undefined,
        workspaceStatus:
          typeof args.workspaceStatus === "string"
            ? (args.workspaceStatus as WorkspaceStatus)
            : undefined,
        comment: typeof args.comment === "string" ? args.comment : undefined,
        parentWorktree:
          typeof args.parentWorktree === "string" ? args.parentWorktree : undefined,
      });
      return JSON.stringify(rec, null, 2);
    }
    case "current": {
      const rec = await resolveCurrentCruxWorktree(repoRoot);
      return JSON.stringify({ current: rec }, null, 2);
    }
    case "status":
    case "ps": {
      const rows = await listCruxWorktreeStatus(repoRoot);
      return JSON.stringify(rows, null, 2);
    }
    case "diff": {
      const taskId = String(args.taskId ?? "").trim();
      if (!taskId) throw new Error("worktree diff requires taskId");
      const diff = await inspectCruxWorktreeDiff(repoRoot, taskId, true);
      return JSON.stringify(diff, null, 2);
    }
    case "merge": {
      const taskId = String(args.taskId ?? "").trim();
      if (!taskId) throw new Error("worktree merge requires taskId");
      const merged = await mergeCruxWorktreeTask({
        repoRoot,
        taskId,
        verifyCmd: typeof args.verifyCmd === "string" ? args.verifyCmd : undefined,
        cleanup: args.cleanup === true,
      });
      return JSON.stringify(merged, null, 2);
    }
    case "rm": {
      const taskId = String(args.taskId ?? "").trim();
      if (!taskId) throw new Error("worktree rm requires taskId");
      const removed = await removeCruxWorktreeTask({
        repoRoot,
        taskId,
        deleteBranch: args.cleanup === true,
      });
      return JSON.stringify(removed, null, 2);
    }
    default:
      throw new Error(`Unknown worktree action: ${String(action)}`);
  }
}
