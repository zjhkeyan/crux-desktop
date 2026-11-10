---
name: crux-evolve
description: "Crux Evolve — the dedicated Algorithm Design & Heuristic Evolution module integrated with Crux Discovery. Activate ONLY when the user wants to optimize an algorithm, evolve a heuristic/solver, improve mathematical bounds, or runs `/algo-optimize`. Provides 10 evolutionary search methods (EoH, ReEvo, MCTS-AHD, MEoH, Diverse Island GA, Island GA, FunSearch, DyCA, NSGA-II, MOEA/D), evolvable block advising (`# EVOLVE_START` / `# EVOLVE_END`), and Sobol QMC bounded parameter tuning (`crux_evolve_adapter.py`). Users doing literature review or survey stay on `literature-review` without loading this module."
---

# Crux Evolve: Automated Algorithm Design & Heuristic Evolution

**Crux Evolve** combines **Crux Discovery**'s Git-worktree multi-agent execution engine with structured evolutionary search operators (`EoH`, `ReEvo`, `MCTS-AHD`, `MEoH`, `Diverse Island GA`, `FunSearch`, `DyCA`, `NSGA-II`, `MOEA/D`) and numerical parameter search (`Sobol QMC + Coordinate Pattern Search`).

> **Clean Track Separation**:
> - **Literature & Survey Track**: Users asking for paper search, reading, or synthesis use `literature-review` + `agent-memory` only.
> - **Algorithm Optimization Track (`Crux Evolve × Crux Discovery`)**: Activate this skill when the user asks to optimize code/kernels/solvers, discover better heuristics or mathematical bounds, or invokes `/algo-optimize`.

---

## Package Contracts and Reproducibility

1. **Unified Component Interface**: Planner proposes, Coder edits and Evaluator measures. The algorithm keeps its function signature, JSON CLI and `# EVOLVE_START` / `# EVOLVE_END` boundaries. A custom `BaseEvaluator` implements `name`, `metrics` and `async evaluate(cfg)`; it reads data from `cfg.data_path`, locates the candidate under `cfg.project_root`, honors `cfg.timeout`, and rejects invalid or missing candidates.
2. **Fair Evaluation Standard**: lock `evaluator`, `providers` and `random_seed` across method comparisons. `switch_method` replaces only `evolution` and `planner.type`, preserving `coder` and `version_control` too. Use identical instances, metric definitions and comparable budgets; compare measured scores and reported cost estimates together.
3. **Git Worktree + Checkpoint reproducibility**: use enabled `git_worktree` version control and fixed seeds. `evaluate_candidate` snapshots package files into temporary Git worktrees, runs `test_evaluator.py`, and measures baseline/candidate samples with the upstream evaluator dispatcher. `--resume-checkpoint` records evaluation metadata and verifies benchmark/seed identity before replaying; actual evolution resumes through the upstream engine's `--resume`. Offload the Evaluator through `--ssh-host` using `crux remote`; remote Python and runtime/task dependencies must be available.

Prefer the native `crux_evolve` tool in OpenCode:

| Action | Inputs | Result |
|---|---|---|
| `scaffold_package` | `template: tsp\|knapsack\|lunarlander`, new/empty `projectDir`, optional `projectName`, `seed` | Copies an upstream package, enables worktrees, checks requirements and runs its zero-token self-test. |
| `switch_method` | `projectDir`, `methodName`, optional matching `seed` | Loads canonical upstream method parameters, validates configuration, and reports costs and validation errors. |
| `evaluate_candidate` | `projectDir`, optional algorithm `worktree`, `sshHost`, `remoteDir`, `resumeCheckpoint` | Runs the evaluator gate and returns structured local or SSH results. Local evaluation includes per-instance baseline/candidate scores and rejects an empty candidate. |

Supported switches: `island_ga`, `diverse_island_ga`, `dyca`, `eoh`, `reevo`, `meoh`, `mcts_ahd`; hyphenated spellings are accepted too. A supplied switch seed must match the existing package seed. Invalid configurations are reported without overwriting `config.yaml`. `methods --name <method>` also returns the rebranded upstream task-package contract.

CLI equivalents, from the directory containing `crux_evolve_adapter.py`:

```bash
python3 crux_evolve_adapter.py scaffold-package --template knapsack --dest work/knapsack --project-name knapsack-study --seed 42
python3 crux_evolve_adapter.py switch-method --project-dir work/knapsack --method reevo --seed 42
python3 crux_evolve_adapter.py evaluate-candidate --project-dir work/knapsack --resume-checkpoint work/evaluation.json
python3 crux_evolve_adapter.py evaluate-candidate --project-dir work/knapsack --worktree work/candidate --ssh-host lab --remote-dir crux-evaluation
```

Never hand-write a configuration from scratch when scaffolding and method switching suffice. Adapt the copied algorithm/evaluator/data to the actual domain, then require `status: passed` and `test_evaluator_passed: true` before handing back the package. Template self-tests consume no model tokens; full evolution requires separate authorization and model configuration.

## 1. Choose the Right Crux Evolve Method

Inspect any method's full operator guide and recommended YAML parameters with:

```bash
python3 "${XDG_CONFIG_HOME:-$HOME/.local/share/com.crux.desktop/runtime/xdg-config}/opencode/skills/crux-evolve/crux_evolve_adapter.py" \
  methods --name eoh
```

| Method (`--name`) | Core Mechanism | Best For |
| :--- | :--- | :--- |
| **`diverse-island-ga`** | Continuous exploitation↔exploration island spectrum + stagnation-gated migration + token diversity | Default multi-agent Crux Discovery runs (`num_islands` = agent count) |
| **`eoh`** | Evolution of Heuristics (`I1` init, `E1` explore crossover, `E2` backbone crossover, `M1` structural mutation, `M2` parametric mutation) | Combinatorial optimization, scheduling, routing, fast heuristic design |
| **`reevo`** | Reflective Evolution (short-term worse-vs-better parent reflection + long-term accumulated verbal gradient) | Complex codebases where understanding *why* an attempt failed matters |
| **`mcts-ahd`** | Monte Carlo Tree Search with UCT (`Q-value` + exploration bonus) and progressive widening | Deep multi-step structural search where greedy truncation gets trapped |
| **`meoh` / `nsga2` / `moead`** | Pareto non-dominated sorting + CodeBLEU syntactic dissimilarity + Hypervolume (HV) | Multi-objective optimization (e.g. accuracy vs. latency / memory) |
| **`funsearch`** | Multi-island program database with best-shot prompting | Mathematical constructions, extremal bounds, packing & coding theory |
| **`dyca`** | Dynamic instance clustering + specialist/generalist algorithm pools | Heterogeneous benchmark suites with distinct instance regimes |

---

## 2. Search Operators (`Crux Evolve × Crux Discovery`)

### Step 1: Locate `# EVOLVE_START` / `# EVOLVE_END` Boundaries (`advise-blocks`)

Scan the target source file to detect existing `# EVOLVE_START` / `# EVOLVE_END` markers or rank the highest-leverage functions to evolve:

```bash
python3 "${XDG_CONFIG_HOME:-$HOME/.local/share/com.crux.desktop/runtime/xdg-config}/opencode/skills/crux-evolve/crux_evolve_adapter.py" \
  advise-blocks --file path/to/solver.py
```

### Step 2: Assign Diverse Island Roles & Operator Prompts (`island-plan` & `operator-prompt`)

When running $N$ parallel agents in Crux Discovery (or Crux worktrees), assign each island a distinct position on the exploitation↔exploration spectrum and generate structured `EoH` / `ReEvo` prompts:

```bash
# Compute exploration/exploitation & memory policy for 3 parallel islands
python3 "${XDG_CONFIG_HOME:-$HOME/.local/share/com.crux.desktop/runtime/xdg-config}/opencode/skills/crux-evolve/crux_evolve_adapter.py" \
  island-plan --islands 3 --generation 2 --stagnation 1

# Generate an EoH E1/E2/M1/M2 or ReEvo reflection prompt from parent candidates
python3 "${XDG_CONFIG_HOME:-$HOME/.local/share/com.crux.desktop/runtime/xdg-config}/opencode/skills/crux-evolve/crux_evolve_adapter.py" \
  operator-prompt --operator e2 --task "Minimize TSP tour length" --parents-json parents.json
```

### Step 3: Filter Survivors by Quality + Code Token Diversity (`select-survivors`)

Prevent premature convergence by retaining both top-scoring elites and syntactically novel candidates:

```bash
python3 "${XDG_CONFIG_HOME:-$HOME/.local/share/com.crux.desktop/runtime/xdg-config}/opencode/skills/crux-evolve/crux_evolve_adapter.py" \
  select-survivors --candidates candidates.json --count 4 --novelty-ratio 0.25
```

### Step 4: Tune Continuous Parameters (`tune-params`) & Sync Live Discovery UI (`sync-views`)

LLMs excel at discrete structural changes (`E1/E2/M1`) but are imprecise at continuous constants. Run Sobol QMC + shrinking coordinate pattern search on bounded parameters (`{"initial": x0, "lower": lo, "upper": hi}`), then project the state into `.crux/public/views/` for the live UI pane:

```bash
# Tune bounded numeric parameters in-place
python3 "${XDG_CONFIG_HOME:-$HOME/.local/share/com.crux.desktop/runtime/xdg-config}/opencode/skills/crux-evolve/crux_evolve_adapter.py" \
  tune-params --candidate seed/solution.py --eval-cmd "python3 grader/score_once.py" --max-evals 64 --apply

# Project evolution state into .crux/public/views/{board,tree,archive}.json for `crux screen add --discovery`
python3 "${XDG_CONFIG_HOME:-$HOME/.local/share/com.crux.desktop/runtime/xdg-config}/opencode/skills/crux-evolve/crux_evolve_adapter.py" \
  sync-views --state-file state/evolution_state.json --run-dir work/optimize
```
