import { execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  CRUX_EVOLVE_ACTIONS,
  cruxEvolveTool,
  runCruxEvolve,
} from "../../../../../runtime/osd-plugin/research-tools";

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

describe("Crux Evolve Seam (Rebranded Crux Evolve Algorithm Optimization Module)", () => {
  it("scaffolds, switches fair methods, and evaluates isolated candidate snapshots without model calls", async () => {
    const workspace = makeTempDir("crux-evolve-package-");
    const configAt = (project: string) => JSON.parse(execFileSync("python3", ["-c",
      "import json,sys,yaml; print(json.dumps(yaml.safe_load(open(sys.argv[1]))))",
      join(project, "config.yaml")], { encoding: "utf8" }));
    symlinkSync(join(workspace, "..", "missing-crux-target"), join(workspace, "escape"));
    await expect(runCruxEvolve(workspace, {
      action: "scaffold_package", template: "tsp", projectDir: "escape/new",
    })).rejects.toThrow();
    for (const template of ["tsp", "knapsack"]) {
      const projectDir = join(workspace, template);
      const scaffold = JSON.parse(await runCruxEvolve(workspace, {
        action: "scaffold_package", template, projectDir, projectName: `fair-${template}`, seed: 17,
      }));
      expect(scaffold).toMatchObject({ status: "ok", random_seed: 17, self_test_passed: true });
      expect(scaffold.files).toContain("test_evaluator.py");
      expect(scaffold.config_summary_md).toContain("Estimated Token Usage");
      const initial = configAt(projectDir);
      for (const methodName of ["eoh", "reevo", "mcts-ahd", "island_ga", "diverse-island-ga", "meoh", "dyca"]) {
        const switched = JSON.parse(await runCruxEvolve(workspace, {
          action: "switch_method", projectDir, methodName, seed: 17,
        }));
        expect(switched.validation_errors).toEqual([]);
        expect(switched.evolution_type).toBe(methodName.replace(/-/g, "_"));
        const updated = configAt(projectDir);
        for (const key of ["evaluator", "providers", "coder", "version_control", "random_seed"]) {
          expect(updated[key]).toEqual(initial[key]);
        }
      }
      await expect(runCruxEvolve(workspace, {
        action: "switch_method", projectDir, methodName: "eoh", seed: 18,
      })).rejects.toThrow();
      const checkpoint = join(workspace, `${template}-checkpoint.json`);
      const evaluated = JSON.parse(await runCruxEvolve(workspace, {
        action: "evaluate_candidate", projectDir, resumeCheckpoint: checkpoint,
      }));
      expect(evaluated).toMatchObject({ status: "passed", mode: "local_worktree", test_evaluator_passed: true, random_seed: 17 });
      expect(evaluated.candidate.samples).toHaveLength(2);
      expect(JSON.parse(readFileSync(checkpoint, "utf8")).random_seed).toBe(17);
      expect(existsSync(join(projectDir, ".git"))).toBe(false);
      const configText = readFileSync(join(projectDir, "config.yaml"), "utf8");
      writeFileSync(join(projectDir, "config.yaml"), JSON.stringify({ ...configAt(projectDir), random_seed: 18 }));
      await expect(runCruxEvolve(workspace, {
        action: "evaluate_candidate", projectDir, resumeCheckpoint: checkpoint,
      })).rejects.toThrow();
      writeFileSync(join(projectDir, "config.yaml"), configText);
      await expect(runCruxEvolve(workspace, {
        action: "scaffold_package", template, projectDir,
      })).rejects.toThrow();
      await expect(runCruxEvolve(workspace, {
        action: "evaluate_candidate", projectDir: "../outside",
      })).rejects.toThrow("inside the active workspace");
      if (template === "knapsack") {
        expect(evaluated.baseline.samples.map((s: { score: number }) => s.score)).toEqual([44, 79]);
        const candidate = join(workspace, "candidate");
        cpSync(join(projectDir, "algorithm"), candidate, { recursive: true });
        writeFileSync(join(candidate, "solver.py"), "print('{\"selected\": []}')\n");
        const changed = JSON.parse(await runCruxEvolve(workspace, {
          action: "evaluate_candidate", projectDir, worktree: candidate, resumeCheckpoint: checkpoint,
        }));
        expect(changed.candidate.samples.map((s: { score: number }) => s.score)).toEqual([0, 0]);
        expect(changed.baseline.samples.map((s: { score: number }) => s.score)).toEqual([44, 79]);
        const bin = join(workspace, "bin");
        const remote = join(workspace, "remote");
        mkdirSync(bin);
        mkdirSync(remote);
        writeFileSync(join(bin, "crux"), [
          "#!/usr/bin/env python3",
          "import json, os, pathlib, shutil, subprocess, sys",
          `root = pathlib.Path(${JSON.stringify(remote)})`,
          "args = sys.argv[1:]",
          "with (root / 'calls.jsonl').open('a') as log: log.write(json.dumps(args) + '\\n')",
          "assert args[0] == 'remote' and args[2] == 'lab'",
          "if args[1] == 'put':",
          "    assert not pathlib.Path(args[3]).is_absolute()",
          "    shutil.copyfile(args[3], root / args[4])",
          "else:",
          "    assert args[1] == 'exec' and args[3] == '--'",
          "    sys.exit(subprocess.run(args[4:], cwd=root).returncode)",
        ].join("\n"), { mode: 0o755 });
        const originalPath = process.env.PATH;
        try {
          process.env.PATH = `${bin}:${originalPath}`;
          const offloaded = JSON.parse(await runCruxEvolve(workspace, {
            action: "evaluate_candidate", projectDir, worktree: candidate, sshHost: "lab", remoteDir: "evaluation space",
          }));
          expect(offloaded).toMatchObject({ mode: "ssh_remote", status: "passed", test_evaluator_passed: true });
          expect(offloaded.candidate.samples.map((s: { score: number }) => s.score)).toEqual([0, 0]);
          const calls = readFileSync(join(remote, "calls.jsonl"), "utf8").trim().split("\n").map(line => JSON.parse(line));
          expect(calls.map(call => call[1])).toEqual(["put", "exec", "exec"]);
          expect(calls[2].slice(3)).toEqual(["--", "python3", "evaluation space/test_evaluator.py"]);
        } finally {
          process.env.PATH = originalPath;
        }
        symlinkSync(join(workspace, "knapsack-checkpoint.json"), join(candidate, "config.yaml"));
        const before = readFileSync(checkpoint, "utf8");
        await expect(runCruxEvolve(workspace, {
          action: "evaluate_candidate", projectDir, worktree: candidate,
        })).rejects.toThrow();
        expect(readFileSync(checkpoint, "utf8")).toBe(before);
        rmSync(join(candidate, "config.yaml"));
        writeFileSync(join(candidate, "solver.py"), "raise RuntimeError('broken candidate')\n");
        await expect(runCruxEvolve(workspace, {
          action: "evaluate_candidate", projectDir, worktree: candidate,
        })).rejects.toThrow();
      }
    }
  }, 120_000);
  it.each([
    { methodName: undefined, expectedKey: "algo_design_methods" },
    { methodName: "eoh", expectedKey: "skill_guide" },
    { methodName: "reevo", expectedKey: "skill_guide" },
    { methodName: "diverse-island-ga", expectedKey: "skill_guide" },
  ])(
    "lists Crux Evolve methods ($methodName) with complete rebranding and zero upstream brand leaks",
    async ({ methodName, expectedKey }) => {
      const workspace = makeTempDir("crux-evolve-methods-");
      expect(cruxEvolveTool.name).toBe("crux_evolve");
      expect(CRUX_EVOLVE_ACTIONS).toContain("methods");

      const raw = await runCruxEvolve(workspace, {
        action: "methods",
        ...(methodName ? { methodName } : {}),
      });
      expect(raw).not.toMatch(/OpenLoopX/);

      const parsed = JSON.parse(raw);
      expect(parsed).toHaveProperty(expectedKey);
      if (!methodName) {
        expect(parsed.engine).toBe("Crux Evolve");
        expect(parsed.method_count).toBeGreaterThanOrEqual(10);
        expect(parsed.math_benchmark_count).toBeGreaterThanOrEqual(9);
      } else {
        expect(parsed.method).toBe(methodName);
        expect(String(parsed.skill_guide)).toContain("eoh".slice(0, 0));
      }
    },
  );

  it("computes Diverse Island GA exploration spectrum and builds EoH / ReEvo operator prompts", async () => {
    const workspace = makeTempDir("crux-evolve-islands-");
    const planRaw = await runCruxEvolve(workspace, {
      action: "island_plan",
      islands: 3,
      stagnation: 2,
      generation: 4,
    });
    const plan = JSON.parse(planRaw);
    expect(plan.engine).toContain("Crux Evolve");
    expect(plan.islands).toHaveLength(3);
    expect(plan.islands[0].exploration).toBeLessThan(plan.islands[1].exploration);
    expect(plan.islands[1].exploration).toBeLessThan(plan.islands[2].exploration);
    expect(plan.islands[0].memory_policy).toBe("success_only");
    expect(plan.islands[1].memory_policy).toBe("corrective");

    const parentsFile = join(workspace, "parents.json");
    writeFileSync(
      parentsFile,
      JSON.stringify([
        {
          id: "cand-1",
          score: 0.82,
          description: "Greedy distance heuristic with quadratic penalty",
          code: "def score_item(x, w):\n    return x / (w * w + 1e-6)\n",
        },
        {
          id: "cand-2",
          score: 0.88,
          description: "Log-barrier capacity ratio heuristic",
          code: "import math\ndef score_item(x, w):\n    return x * math.log1p(1.0 / (w + 1e-3))\n",
        },
      ]),
      "utf-8",
    );

    const e1Raw = await runCruxEvolve(workspace, {
      action: "operator_prompt",
      operator: "e1",
      task: "Maximize online bin-packing utilization without exceeding bin capacity.",
      candidatesFile: "parents.json",
    });
    const e1 = JSON.parse(e1Raw);
    expect(e1.engine).toBe("Crux Evolve");
    expect(e1.operator).toBe("e1");
    expect(e1.prompt).toContain("Maximize online bin-packing utilization");

    const reevoRaw = await runCruxEvolve(workspace, {
      action: "operator_prompt",
      operator: "reevo-crossover",
      task: "Maximize online bin-packing utilization without exceeding bin capacity.",
      candidatesFile: "parents.json",
      reflection: "Prefer smooth logarithmic slack weighting over sharp quadratic penalties.",
    });
    const reevo = JSON.parse(reevoRaw);
    expect(reevo.operator).toBe("reevo-crossover");
    expect(reevo.prompt).toContain("smooth logarithmic slack weighting");
  }, 30_000);

  it("selects quality + code-diverse survivors from candidate populations", async () => {
    const workspace = makeTempDir("crux-evolve-survivors-");
    const candidatesFile = join(workspace, "candidates.json");
    writeFileSync(
      candidatesFile,
      JSON.stringify([
        {
          id: "elite-1",
          score: 0.95,
          description: "Primary linear slack scorer",
          code: "def priority(rem, size):\n    return -(rem - size) * 1.0\n",
        },
        {
          id: "elite-1-clone",
          score: 0.949,
          description: "Near-identical linear slack scorer",
          code: "def priority(rem, size):\n    return -(rem - size) * 1.0001\n",
        },
        {
          id: "novel-spectral",
          score: 0.89,
          description: "Trigonometric harmonic phase bin-fit scorer",
          code: "import math\ndef priority(rem, size):\n    ratio = size / max(rem, 1e-6)\n    return math.cos(ratio * math.pi) + math.sqrt(ratio)\n",
        },
      ]),
      "utf-8",
    );

    const raw = await runCruxEvolve(workspace, {
      action: "select_survivors",
      candidatesFile: "candidates.json",
      count: 2,
      noveltyRatio: 0.5,
    });
    const res = JSON.parse(raw);
    expect(res.engine).toContain("Crux Evolve");
    expect(res.selected_count).toBe(2);
    const ids = res.survivors.map((s: { id: string }) => s.id);
    expect(ids).toContain("elite-1");
    expect(ids).toContain("novel-spectral");
  });

  it("advises evolvable blocks, tunes bounded MODEL_SPEC parameters via Sobol QMC + pattern search, and syncs Crux Discovery views", async () => {
    const workspace = makeTempDir("crux-evolve-tune-");
    const candidatePath = join(workspace, "candidate_solver.py");
    writeFileSync(
      candidatePath,
      [
        "MODEL_SPEC = {",
        '    "params": {"alpha": 0.2, "beta": -0.5},',
        '    "bounds": {"alpha": [0.0, 4.0], "beta": [-2.0, 2.0]},',
        "}",
        "",
        "# EVOLVE_START: score_candidate",
        "def score_candidate(alpha: float, beta: float) -> float:",
        "    return 10.0 - (alpha - 2.5) ** 2 - (beta - 1.0) ** 2",
        "# EVOLVE_END",
        "",
        "def evaluate_candidate(params: dict) -> float:",
        '    return score_candidate(float(params["alpha"]), float(params["beta"]))',
        "",
      ].join("\n"),
      "utf-8",
    );

    const adviseRaw = await runCruxEvolve(workspace, {
      action: "advise_blocks",
      targetFile: "candidate_solver.py",
    });
    const advise = JSON.parse(adviseRaw);
    expect(advise.has_explicit_evolve_blocks).toBe(true);
    expect(advise.explicit_blocks[0].name).toContain("score_candidate");

    const tuneRaw = await runCruxEvolve(workspace, {
      action: "tune_params",
      targetFile: "candidate_solver.py",
      maxEvals: 36,
      apply: true,
    });
    const tune = JSON.parse(tuneRaw);
    expect(tune.status).toBe("ok");
    expect(tune.patched).toBe(true);
    expect(tune.best_score).toBeGreaterThan(tune.initial_score);
    expect(tune.best_score).toBeGreaterThan(9.5);

    const patchedCode = readFileSync(candidatePath, "utf-8");
    expect(patchedCode).not.toContain('"alpha": 0.2');

    const statePath = join(workspace, "evolution_state.json");
    writeFileSync(
      statePath,
      JSON.stringify({
        metric_direction: "maximize",
        evolve_scope: { categories: ["proposed"] },
        population: [
          { id: "gen0_seed", algorithm: "proposed_solver", island_id: 0, score: tune.initial_score, generation: 0, description: "Initial seed" },
          {
            id: "gen1_tuned",
            algorithm: "proposed_solver",
            island_id: 1,
            parent_id: "gen0_seed",
            score: tune.best_score,
            generation: 1,
            operator: "tune_params",
            description: "Sobol QMC + pattern search tuned candidate",
          },
          {
            id: "baseline_ref",
            algorithm: "naive_baseline",
            category: "baseline",
            score: 1.0,
            generation: 0,
            description: "Excluded baseline reference",
          },
          {
            id: "ablation_ref",
            algorithm: "ablation_no_precond",
            category: "ablation",
            score: 2.0,
            generation: 0,
            description: "Excluded ablation reference",
          },
        ],
      }),
      "utf-8",
    );

    const syncRaw = await runCruxEvolve(workspace, {
      action: "sync_views",
      stateFile: "evolution_state.json",
      runDir: "work/algo-opt",
    });
    const sync = JSON.parse(syncRaw);
    expect(sync.engine).toBe("Crux Evolve");
    expect(sync.node_count).toBe(4);
    expect(sync.n_promoted).toBe(1);
    expect(sync.comparison.algorithms).toHaveProperty("proposed_solver");
    expect(sync.comparison.algorithms).not.toHaveProperty("naive_baseline");
    expect(sync.comparison.algorithms).not.toHaveProperty("ablation_no_precond");
    expect(sync.comparison.algorithms.proposed_solver.promoted).toBe(true);
    expect(sync.comparison.algorithms.proposed_solver.delta_pct).toBeGreaterThan(0);
    expect(existsSync(join(workspace, "work/algo-opt/.crux/public/views/board.json"))).toBe(true);
    expect(existsSync(join(workspace, "work/algo-opt/.crux/public/views/tree.json"))).toBe(true);
    expect(existsSync(join(workspace, "work/algo-opt/.crux/public/views/archive.json"))).toBe(true);
    expect(existsSync(join(workspace, "work/algo-opt/.crux/public/views/comparison.json"))).toBe(true);
    expect(existsSync(join(workspace, "work/algo-opt/crux_evolve_comparison.json"))).toBe(true);
  }, 30_000);
});
