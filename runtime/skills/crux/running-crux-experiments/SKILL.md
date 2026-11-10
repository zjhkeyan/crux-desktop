---
name: running-crux-experiments
description: Run and manage Crux experiments from the operator side — launch agents with `crux discovery start` (dotlist overrides, model/count, tmux vs local), monitor with `crux discovery status` / `crux discovery log` / `crux discovery show` / the web dashboard, and drive the loop with `crux discovery resume` (inject instructions, fork from an attempt), `crux discovery heartbeat` (tune reflection cadence), and `crux discovery stop`. Use whenever the user wants to start a Crux run, check on agents, read scores/leaderboard, steer or resume a run, diagnose agents that keep restarting or fail every eval, scale to more agents or islands, or stop a run. Deep references for steering/heartbeat tuning and scaling/troubleshooting live alongside this skill.
---

# Running Crux experiments

You drive a run with five verbs: **start → status → log/show → resume → stop**. Everything else is a flag on those or a deeper topic in the references. Prefer `crux <cmd> --help` over guessing flags.

**Prereq:** a task (`task.yaml` + `seed/` + grader package) that passes `crux discovery validate .`. No task yet → that's the `creating-a-crux-task` skill. Each runtime CLI must be installed and authenticated → the `setting-up-crux` skill.

## 1. Launch

```bash
crux discovery start -c task.yaml                                  # auto-tmux session
crux discovery start -c task.yaml agents.count=4 agents.model=opus # dotlist overrides (no quotes needed)
crux discovery start -c task.yaml run.verbose=true run.ui=true     # verbose logs + web dashboard
crux discovery start -c task.yaml run.session=local                # foreground, no tmux
```

- **Dotlist overrides** (`key.subkey=value`) beat `task.yaml` for this run only — the clean way to sweep count/model without editing the file.
- `run.session`: `tmux` (default, detachable) · `local` (foreground) · `docker`.
- Each run lands in `results/<task-slug>/<timestamp>/`; agents work in isolated git worktrees and the grader daemon scores their commits.

## 2. Monitor

```bash
crux discovery status            # agent health + leaderboard snapshot (the quick pulse)
crux discovery ls              # active runs across tasks; --all includes finished
crux discovery ui --port 8420    # web dashboard: live leaderboard, logs, DAG
```

`crux discovery status` answers "who's alive, how many evals, current best". If it looks healthy but scores never move, jump to budget classes + troubleshooting in [references/scaling-and-ops.md](references/scaling-and-ops.md).

## 3. Read results

```bash
crux discovery log                              # top 20 real attempts by score
crux discovery log -n 5 --recent                # most recent instead of best
crux discovery log --search "kernel" --agent agent-1
crux discovery log --class grader_error         # surface crashing graders (first stop when unhealthy)
crux discovery show <hash>                      # one attempt: score, explanation, files changed
crux discovery show <hash> --diff               # full diff — see exactly what the leader did
```

`<hash>` comes from `crux discovery log`/`crux discovery status`. By default `crux discovery log` hides `tune` and `grader_error` attempts; `--all` shows them, `--class {real|tune|grader_error}` filters to one. What the classes mean → [references/scaling-and-ops.md](references/scaling-and-ops.md).

## 4. Steer and resume (legacy mode)

With discovery enabled, start from a fresh archive summary; the session-restoring examples below apply only to legacy mode.

```bash
crux discovery resume                                   # resume latest run, sessions restored
crux discovery resume -i "Try greedy approaches first"  # inject guidance agents read next loop
crux discovery resume --from <hash> -i "Continue this fork"   # reset an agent to an attempt, then steer
crux discovery export <hash> -b winning-idea            # export an attempt's commit as a git branch
```

`resume -i` is how you nudge a run without restarting from scratch (stop → resume with an instruction). `--from` forks a promising line that later regressed. You can also retune the reflection cadence — `crux discovery heartbeat set/remove/reset` — to make agents reflect less, pivot sooner, etc. Both topics, with worked examples: [references/steering.md](references/steering.md).

## 5. Stop

```bash
crux discovery stop          # stop the current/latest run (picker if several)
crux discovery stop --all    # stop every active run
```

Stopping leaves all results, notes, and the leaderboard on disk — `crux discovery resume` later, or just inspect with `crux discovery log`/`crux discovery show`.

## Typical loop

```bash
crux discovery validate .                            # grader scores the seed (once)
crux discovery start -c task.yaml agents.count=2     # launch
crux discovery status                                # ... check periodically
crux discovery log -n 5 --recent                     # see what agents are trying
crux discovery show <best-hash> --diff               # inspect the leader
crux discovery resume -i "Focus on the inner loop"   # steer if they plateau
crux discovery stop                                  # done
```

## Going deeper

- **Steer / fork / heartbeat tuning** → [references/steering.md](references/steering.md)
- **Budget classes, islands, gateway, troubleshooting matrix** → [references/scaling-and-ops.md](references/scaling-and-ops.md)

Note: `crux eval / diff / revert / checkout / wait` are **agent-side** commands run *inside* a worktree during a run — agents already know them from the generated `CRUX.md`. As the operator you rarely touch them; you drive the verbs above. Full CLI reference: https://crux.dev/docs/discovery

## Discovery and AgentRadio (Table 5)

Before binding, `crux --capabilities` must print `ledger:v1 board radio oracle`.
Crux prefers `Crux_SOURCE_DIR`, bundled sources, or its managed uv tool; the git fallback is pinned to `0123dfb`. An incompatible upstream CLI is refused.

Use API-key providers for multi-agent discovery. Crux passes `Crux_GATEWAY_API_KEYS` and `Crux_GATEWAY_UPSTREAM_*` to the gateway at launch, never to `agents.yaml` or provenance. OAuth-only providers are unavailable. Each agent needs its own XDG config/data/state profile outside `.crux/private`, with only the awareness plugin and its gateway virtual key; never reuse Desktop's `opencode.db` or `osd-plugin`. Keep restricted permissions unless a sandbox or OS-user isolation is active. Sandbox-less autonomy requires an explicit user opt-in.

Run these commands inside the agent worktree:

```bash
crux board --summary
crux direction <id> --insights --page 1
crux claim <id> --method "test one mechanism"
crux claim --new "new direction" --description "mechanism" --method "experiment"
crux claim --paths "src/*.py,tests/*.py" --method "scoped experiment"
crux release
crux eval -m "measured change" --direction <id> --inspired-by c1,c2 --cite N3,tool:name
crux tree show <commit>
crux insight <commit> "reflection grounded in this attempt"
crux review <commit> --verdict SUSPECT --anchor src/kernel.py:42 "request a correctness re-check"
crux radio send mention --anchor <commit> --to <agent> "scoped observation"
crux radio send synthesis --anchor <commit> "candidate synthesis for verification"
crux radio inbox --delta
# Claude hook alternative: crux radio inbox --delta --hook claude
```

Choose directions using wanted versus claimed seats and UCB potential; dormant directions remain available to revive by claim. Declare code ancestry separately from inspired-by and citation provenance. `crux insight` is author-only, once after settlement, with a reflection of at most 600 characters; it creates a DRAFT rather than shared truth. Cross-reviews use `OK`, `SUSPECT`, or `NOTE` and a note of at most 280 characters. They stake demands for evidence and cannot promote knowledge. Radio mention/synthesis notes are also limited to 280 characters and must carry anchors. Read only deltas; typed CLAIM/RELEASE and review messages come from their commands, not invented free-text broadcasts.

Trust PROMOTED/CORROBORATED archive entries within their evidence scope, and respect FailureConstraint scope and TTL. PROVISIONAL nodes are not confirmed bests; REFUTED ancestry needs re-verification. A Crux head badge detects rollback or HMAC substitution against a recorded anchor; a newer head still needs chain verification:

```bash
crux discovery ledger verify
crux discovery ledger head
```

Discovery sessions start fresh from the archive after three continuation prompts; do not use `--continue` or session resume to bypass resets. Retain open claims, assigned reviews, and unanswered mentions across resets. Crux reads `.crux/public` views only and never opens the private ledger. Reviewer output stays in Crux; any re-verification request needs human approval and cannot write Crux knowledge.
