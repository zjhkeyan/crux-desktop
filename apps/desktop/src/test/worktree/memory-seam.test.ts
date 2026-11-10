import { execFileSync } from "node:child_process";
import { existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  MAX_MEMORY_BYTES,
  MAX_MEMORY_LINES,
  loadWorkspaceMemorySystemPrompt,
  truncateMemoryHeader,
} from "../../../../../runtime/osd-plugin/memory";
import {
  coralDiscoveryTool,
  memoryDreamTool,
  runCoralDiscovery,
  runMemoryDream,
  sciResearchTool,
} from "../../../../../runtime/osd-plugin/research-tools";
import {
  mergeCruxWorktreeTask,
  removeCruxWorktreeTask,
  resolveCurrentCruxWorktree,
  setCruxWorktreeMetadata,
  spawnCruxWorktreeTask,
} from "../../../../../runtime/worktree/index";

const tempDirs: string[] = [];
function makeTempDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tempDirs.push(dir);
  return dir;
}

afterEach(() => {
  while (tempDirs.length > 0) {
    const d = tempDirs.pop()!;
    rmSync(d, { recursive: true, force: true });
  }
});

describe("Anthropic Agent Memory Seam (MEMORY.md + Worktree Sharing + Dream Adapter)", () => {
  it.each([
    {
      name: "keeps short MEMORY.md intact",
      input: "# Rules\n- Use pytest -q\n- Never mock internal helpers",
      expectedTruncated: false,
    },
    {
      name: "truncates MEMORY.md exceeding 200 lines",
      input: Array.from({ length: 260 }, (_, i) => `line-${i + 1}`).join("\n"),
      expectedTruncated: true,
    },
    {
      name: "truncates MEMORY.md exceeding 25 KB",
      input: Array.from({ length: 50 }, (_, i) => `line-${i}-${"x".repeat(700)}`).join("\n"),
      expectedTruncated: true,
    },
  ])("$name", ({ input, expectedTruncated }) => {
    const res = truncateMemoryHeader(input, MAX_MEMORY_LINES, MAX_MEMORY_BYTES);
    expect(res.truncated).toBe(expectedTruncated);
    expect(res.content.split("\n").length).toBeLessThanOrEqual(MAX_MEMORY_LINES);
    expect(Buffer.byteLength(res.content, "utf8")).toBeLessThanOrEqual(MAX_MEMORY_BYTES);
  });

  it("injects MEMORY.md and .openscience/memory/_index.md into session context and shares them across Crux worktrees", async () => {
    const repo = makeTempDir("crux-memory-wt-");
    execFileSync("git", ["init", "-b", "main"], { cwd: repo });
    execFileSync("git", ["config", "user.email", "test@crux.local"], { cwd: repo });
    execFileSync("git", ["config", "user.name", "Crux Test"], { cwd: repo });
    writeFileSync(join(repo, "README.md"), "# Seed\n", "utf8");
    execFileSync("git", ["add", "README.md"], { cwd: repo });
    execFileSync("git", ["commit", "-m", "init"], { cwd: repo });

    // Create untracked repo-level MEMORY.md and .openscience/memory/_index.md
    writeFileSync(join(repo, "MEMORY.md"), "# Auto Memory\n- Rule 1: use B3LYP-D3BJ\n", "utf8");
    mkdirSync(join(repo, ".openscience", "memory"), { recursive: true });
    writeFileSync(
      join(repo, ".openscience", "memory", "_index.md"),
      "# Index\n## DFT\n[[b3lyp-basis]] — Dispersion correction notes\n",
      "utf8",
    );

    const sysPrompt = loadWorkspaceMemorySystemPrompt(repo);
    expect(sysPrompt).toContain("<workspace_memory path=\"MEMORY.md\">");
    expect(sysPrompt).toContain("Rule 1: use B3LYP-D3BJ");
    expect(sysPrompt).toContain("<consolidated_memory_index path=\".openscience/memory/_index.md\">");
    expect(sysPrompt).toContain("[[b3lyp-basis]]");

    // Spawn an Crux worktree and confirm MEMORY.md & .openscience/memory are shared via symlinks
    const task = await spawnCruxWorktreeTask({
      repoRoot: repo,
      taskId: "mem-share",
      agent: "claude",
      prompt: "Check memory",
      workspaceStatus: "in-progress",
      comment: "Initial worktree checkout",
    });
    expect(lstatSync(join(task.worktreePath, "MEMORY.md")).isSymbolicLink()).toBe(true);
    expect(lstatSync(join(task.worktreePath, ".openscience", "memory")).isSymbolicLink()).toBe(true);
    expect(task.workspaceStatus).toBe("in-progress");
    expect(task.checkpoints?.length).toBe(1);

    // Resolve current worktree from inside the worktree directory and update progress checkpoint
    const current = await resolveCurrentCruxWorktree(repo, task.worktreePath);
    expect(current?.taskId).toBe("mem-share");
    const updated = await setCruxWorktreeMetadata({
      repoRoot: repo,
      taskId: "current",
      cwd: task.worktreePath,
      workspaceStatus: "in-review",
      comment: "Completed baseline DFT run, ready for diff review",
      displayName: "Claude · DFT Baseline",
    });
    expect(updated.workspaceStatus).toBe("in-review");
    expect(updated.displayName).toBe("Claude · DFT Baseline");
    expect(updated.checkpoints?.length).toBe(2);

    // Modifying code in the worktree and merging must unlink the memory symlinks so they are never committed
    writeFileSync(join(task.worktreePath, "README.md"), "# Updated\n", "utf8");
    const merged = await mergeCruxWorktreeTask({ repoRoot: repo, taskId: "mem-share" });
    expect(merged.diffStat).toContain("README.md");
    expect(merged.diffStat).not.toContain("MEMORY.md");
    const committedFiles = execFileSync("git", ["diff", "--name-only", "HEAD~1..HEAD"], {
      cwd: repo,
      encoding: "utf8",
    }).trim().split("\n");
    expect(committedFiles).toEqual(["README.md"]);

    const removed = await removeCruxWorktreeTask({ repoRoot: repo, taskId: "mem-share", deleteBranch: true });
    expect(removed.removed).toBe("mem-share");
  });

  it(
    "reuses anthropic_agent_memory, SciMuse Elo (IDE), and EvoScientist MuseMemoryBank (IVE/ESE) via native tools",
    async () => {
    const ws = makeTempDir("crux-dream-adapter-");
    const adapterScript = resolve(__dirname, "../../../../../runtime/skills/core/agent-memory/dream_adapter.py");
    const corpusDir = join(ws, "papers");
    mkdirSync(corpusDir, { recursive: true });
    writeFileSync(
      join(corpusDir, "note1.md"),
      "# Catalyst Note\nOPENAI_API_KEY = sk-1234567890abcdefghijklmnop\nVerified turnover frequency is 42 s^-1.\n",
      "utf8",
    );

    const prepOut = JSON.parse(
      execFileSync(
        "python3",
        [adapterScript, "prepare-corpus", "--workspace", ws, "--corpus-dir", corpusDir, "--wiki-slug", "catalyst-wiki"],
        { encoding: "utf8" },
      ),
    );
    expect(prepOut.wiki_slug).toBe("catalyst-wiki");
    expect(prepOut.staged_files.length).toBe(1);
    const stagedContent = readFileSync(prepOut.staged_files[0], "utf8");
    expect(stagedContent).not.toContain("sk-1234567890abcdefghijklmnop");
    expect(stagedContent).toContain("# Provenance Header");

    const curator = readFileSync(resolve(__dirname, "../../../../../runtime/opencode-profile/agent/memory-curator.md"), "utf8");
    expect(curator).toContain("Phase 1");
    expect(curator).toContain("Phase 2");
    expect(curator).toContain("validate_store");
    expect(readFileSync(resolve(__dirname, "../../../../../runtime/opencode-profile/command/dream.md"), "utf8")).toContain("@memory-curator");

    // Simulate the curator's output with a MOVED TO stub and a real topic note
    const skillDir = prepOut.skill_dir as string;
    writeFileSync(join(skillDir, "old-note.md"), "MOVED TO [[tof-kinetics]]\n", "utf8");
    writeFileSync(
      join(skillDir, "tof-kinetics.md"),
      "---\nname: tof-kinetics\ndescription: Verified turnover frequency measurements\n---\n\nTOF is 42 s^-1.\n",
      "utf8",
    );

    const valOut = JSON.parse(
      execFileSync(
        "python3",
        [adapterScript, "validate-store", "--workspace", ws, "--mem-dir", skillDir, "--skill-name", "catalyst-wiki"],
        { encoding: "utf8" },
      ),
    );
    expect(valOut.removed_stubs).toEqual(["old-note.md"]);
    expect(existsSync(join(skillDir, "old-note.md"))).toBe(false);
    expect(existsSync(join(skillDir, "SKILL.md"))).toBe(true);
    expect(existsSync(join(skillDir, "_index.md"))).toBe(true);
    expect(readFileSync(join(skillDir, "SKILL.md"), "utf8")).toContain("name: catalyst-wiki");
    expect(readFileSync(join(ws, "MEMORY.md"), "utf8")).toContain("[[tof-kinetics]]");
    expect(sciResearchTool.name).toBe("sci_research");
    expect(coralDiscoveryTool.name).toBe("crux_discovery");
    expect(memoryDreamTool.name).toBe("memory_dream");
    expect(typeof runMemoryDream).toBe("function");

    // Verify EMA (IDE + IVE + ESE) fusion through `runCoralDiscovery`
    const runDir = "work/ema-fusion";
    const solverFile = join(ws, "solver.py");
    writeFileSync(solverFile, "def spectral_precond(x):\n    return x * 0.95\n", "utf8");

    await runCoralDiscovery(ws, { action: "init", runDir, name: "EMA Fusion Test", goalDirection: "maximize", seats: 2 });
    await runCoralDiscovery(ws, { action: "claim", runDir, agent: "agent-a", direction: "dir-spectral", method: "Spectral preconditioning" });
    await runCoralDiscovery(ws, { action: "claim", runDir, agent: "agent-b", direction: "dir-naive", method: "Naive unpreconditioned step" });

    // 1. Baseline & ESE improvement on dir-spectral
    await runCoralDiscovery(ws, {
      action: "record",
      runDir,
      agent: "agent-a",
      direction: "dir-spectral",
      commit: "1000001a",
      score: 0.75,
      title: "Initial spectral baseline",
      method: "Spectral preconditioning",
      codeFile: "solver.py",
    });
    await runCoralDiscovery(ws, {
      action: "record",
      runDir,
      agent: "agent-a",
      direction: "dir-spectral",
      commit: "2000002a",
      parent: "1000001a",
      score: 0.92,
      title: "Chebyshev polynomial damping",
      method: "Spectral preconditioning",
      insight: "Chebyshev damping eliminates high-frequency eigenmode oscillation",
      codeFile: "solver.py",
    });

    // 2. IVE Implementation Failure on dir-spectral (must NOT falsify direction or drop its Elo)
    const implOut = JSON.parse(
      await runCoralDiscovery(ws, {
        action: "record",
        runDir,
        agent: "agent-a",
        direction: "dir-spectral",
        commit: "2000003a",
        parent: "2000002a",
        score: 0.0,
        title: "CUDA OOM batch size 4096",
        failureType: "implementation",
        constraint: "OOM at batch_size=4096; reduce to 512",
      }),
    );
    expect(implOut.ive_classification).toBe("implementation");
    expect(implOut.directive).toBe("RETRY_IMPLEMENTATION");

    // 3. IVE Fundamental Direction Failure on dir-naive (must circuit-break direction in board.json & MEMORY.md)
    await runCoralDiscovery(ws, {
      action: "record",
      runDir,
      agent: "agent-b",
      direction: "dir-naive",
      commit: "3000001b",
      score: 0.12,
      title: "Unpreconditioned divergence",
      failureType: "fundamental",
      constraint: "Condition number > 1e8 guarantees divergence without preconditioning",
    });

    const summary = await runCoralDiscovery(ws, { action: "summary", runDir });
    expect(summary).toContain("SciMuse Elo=");
    expect(summary).toContain("FALSIFIED (DEAD-END — DO NOT RETRY)");
    expect(summary).toContain("[IVE:IMPLEMENTATION_FAILURE]");
    expect(summary).toContain("Chebyshev damping eliminates high-frequency eigenmode oscillation");
    expect(readFileSync(join(ws, "MEMORY.md"), "utf8")).toContain("[FALSIFIED · `dir-naive`]");
  }, 15_000);
});
