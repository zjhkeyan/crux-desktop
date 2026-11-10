---
description: Build and validate Crux Evolve packages, compare canonical methods fairly, and evaluate candidates in isolated worktrees locally or over SSH.
---

Run the Crux Evolve workflow for: $ARGUMENTS

1. Delegate package construction to @crux-task-author. Use native `crux_evolve` `scaffold_package` with an upstream `tsp`, `knapsack` or `lunarlander` template and fixed `seed`; inspect source boundaries with `advise_blocks`. Use `methods` and `switch_method` for canonical method parameters, rather than hand-writing configuration.
2. Preserve the Unified Component Interface: Planner proposes, Coder edits, Evaluator measures the candidate under `cfg.project_root`. Keep the algorithm's I/O contract and EVOLVE markers stable.
3. Apply the Fair Evaluation Standard: lock `evaluator`, `providers` and `random_seed` across every method comparison, preserving `coder` and enabled `git_worktree` version control too. Use identical data, metric definitions and comparable budgets; report costs alongside scores.
4. Run `evaluate_candidate` before handoff and after each change. It runs `test_evaluator.py` without model calls and measures baseline/candidate samples in temporary Git worktrees. Set `worktree` for a separate candidate or `sshHost` / `remoteDir` to offload the Evaluator via `crux remote`. Remote hosts need Python and the task/runtime dependencies.
5. Use `resumeCheckpoint` to record and replay evaluation with benchmark/seed verification. Actual evolution resumes with the upstream engine's `--resume` and its saved checkpoint; evaluator metadata does not resume a paid search.
6. Reuse `island_plan`, `operator_prompt`, `select_survivors` and `tune_params` for search operations; reevaluate after tuning. Use `sync_views` for the live discovery tree and leaderboard.

Report the package, fixed seed, method, cost estimate, measured results and passing evaluator gate. Start model-backed evolution only when authorized.
