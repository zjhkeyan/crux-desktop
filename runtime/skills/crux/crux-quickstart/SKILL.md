---
name: crux-quickstart
description: The fast path from zero to a running Crux experiment — what Crux is and when to reach for it, installing the `crux` CLI, registering a runtime with `crux setup`, and the `.crux_workspace/` convention for pointing Crux at code you already have and want optimized. Use this whenever the user asks "what is crux", "should I use crux for this", wants to install or get crux set up, hits a "command not found" for crux or doesn't have it installed yet, or says "use crux to optimize / speed up / improve this code" and you need the end-to-end onboarding from install to a launched run. Hands off to `setting-up-crux` (runtime bindings), `creating-a-crux-task` (grader authoring), and `running-crux-experiments` (operating a run) for depth.
---

# Crux quickstart

**Crux** is infrastructure for autonomous coding agents: you give it a codebase (`seed/`) and a grader (turns a commit into a number), and it spawns agents in isolated git worktrees that edit code, submit commits, and get scored on a shared leaderboard — looping to push the score up. The agents *are* the optimizer; your grader defines "better".

## When to reach for Crux

**Good fit:**
- You can express success as a **number** — accuracy, runtime ratio, pass rate, or a rubric-judge score for open-ended work.
- The work is **iterative search**: many attempts at one well-scoped problem (kernel/algorithm optimization, benchmark solving, prompt/program tuning, "make this function faster").
- You want **parallel agents** exploring independently and sharing what works.

**Not a fit:**
- One-shot tasks with no measurable objective.
- Work that needs a human judging every attempt (use a rubric-judge grader if a *model* can score it).

## How a run is shaped

```
you provide:   seed/ (starter code)  +  a grader (commit → number)
crux spawns:  N agents, each in its own git worktree
each agent:    edit code → `crux eval` → grader scores it → read leaderboard → repeat
shared state:  attempts, notes, and skills are visible across agents in real time
```

Two things you build (`seed/` + grader) and one thing you tune (how many agents, which model). Worktrees, scoring daemon, shared state, and restarts are handled for you.

## Get running — four steps

### 1. Install the CLI

In **Crux Desktop**, `crux` and the `crux-opencode` binding in
`~/.config/crux/agents.yaml` are pre-configured automatically from Crux's active
model. Use `agents.binding: crux-opencode` with an API-key provider through the
Crux gateway and isolated per-agent profiles; OAuth-only providers are not supported. When `tmux` is not installed, use
`run.session: local` (`run.session=local` as a CLI override).

```bash
curl -fsSL https://raw.githubusercontent.com/Crux-Discovery/crux-engine/main/install.sh | sh
# or, if you have uv:
uv tool install git+https://github.com/Crux-Discovery/crux-engine.git
crux --help      # verify
```

The installer grabs the **latest `crux` release** by default — that's what you want. (Only pin a specific release with `Crux_VERSION=<tag>` before the curl if you have a reason to.)

### 2. Register a runtime (`crux setup`)

In **Crux Desktop**, `crux` and the `crux-opencode` binding in
`~/.config/crux/agents.yaml` are pre-configured automatically from Crux's active
model. Use `agents.binding: crux-opencode` with an API-key provider through the
Crux gateway and isolated per-agent profiles; OAuth-only providers are not supported. When `tmux` is not installed, use
`run.session: local` (`run.session=local` as a CLI override).

The setup below is for additional runtimes or standalone installations.

`crux` shells out to a coding-agent CLI (Claude Code, Codex, Cursor, Kiro, OpenCode) — each installed and authenticated separately. Tell crux which to use:

```bash
crux setup            # scans PATH, wizard to create named runtime bindings
crux discovery agents doctor    # validates them, incl. a live auth ping
```

If `doctor`'s live ping fails (expired auth, model typo, "runtime not found" at start) → the `setting-up-crux` skill has the full troubleshooting matrix.

### 3. Build a task — use a `.crux_workspace/`

When the user wants Crux to optimize **code they already have**, keep every bit of Crux scaffolding (task config, seed, grader, results) inside a `.crux_workspace/` directory at the root of their project. This keeps crux out of their actual source tree and is trivially gitignored.

> **Act — never answer "optimize this" with a menu.** A request like "use crux to optimize this" (in any language) is a build instruction, not a question. The failure mode to avoid is a process menu like *"1. point me to a task  2. create one  3. optimize outside crux"* — **do not produce that.** A repo with no `task.yaml` isn't ambiguous; it just means you build the task from the current repo. So:
> 1. **Dig for what's already measurable.** Research/framework repos (like SAGA) almost always ship an eval/benchmark script, a test suite, or a headline metric in the README/paper. Find it — that's your optimization target and metric.
> 2. **If no single number is obvious, construct one** by wrapping the repo's existing evaluation. Don't give up and ask just because there's no Crux scaffold.
> 3. **Scaffold the most plausible target and start building** — a `.crux_workspace/` + draft grader is cheap and reversible. State your assumption in one line ("Optimizing SAGA's <metric> from <script> — building it now; redirect me if you meant something else") and proceed.
> 4. **Last resort only:** if you've actually read the repo and it exposes nothing scorable, propose 2-3 **concrete** targets you found (each with a metric), pick the most likely, and scaffold it — still not a process menu.
>
> Stop before `crux discovery start` (a paid run); everything up to a validated task is autonomous. On Claude Code, delegate this whole grind to the `crux-task-author` subagent.

The mechanical boilerplate (gitignore + `crux discovery init` + copy the code into `seed/`) is bundled as a script — run it from the project root:

```bash
"${XDG_CONFIG_HOME:-$HOME/.config}/opencode/skills/crux-quickstart/scripts/new-crux-workspace.sh" optimize path/to/their_module.py
```

It scaffolds `.crux_workspace/optimize/` and copies the file into `seed/solution.py`, leaving only the grader for you to write. (Equivalent by hand:)

```bash
# from the user's project root
echo ".crux_workspace/" >> .gitignore
mkdir -p .crux_workspace && cd .crux_workspace
crux discovery init optimize && cd optimize
cp ../../path/to/their_module.py seed/solution.py   # the code to optimize
```

Then make the task fit the user's goal — two edits:
- **`task.yaml`** → set `task.description` to what the agents should optimize and the program file's contract (e.g. "`solution.py` must define `run()` and stay correct; we score speedup").
- **the grader** → score the user's actual metric (speedup vs baseline, accuracy on a held-out set, pass rate, …). This is the heart of it → the `creating-a-crux-task` skill walks through grader patterns and the `TaskGrader` API.

### 4. Validate, then launch

```bash
crux discovery validate .                 # confirms the grader scores the seed — the one checkpoint that matters
crux discovery start -c task.yaml         # launch agents (results stay under .crux_workspace/)
crux discovery status                     # watch the leaderboard
```

If `crux discovery validate` succeeds, the grader can score the seed; most "agents are stuck" reports trace to a grader that crashes here. Driving the run from here — monitoring, steering, stopping — is the `running-crux-experiments` skill.

## The workflows (where to go next)

| You want to... | Skill | Commands |
|---|---|---|
| **Set up** runtimes (one-time) | `setting-up-crux` | `crux setup`, `crux discovery agents doctor` |
| **Author** a task / write a grader | `creating-a-crux-task` | `crux discovery init`, `crux discovery validate` |
| **Run / manage** experiments | `running-crux-experiments` | `crux discovery start / status / log / show / resume / stop` |

The eval loop *inside* a run (`crux eval -m "..."` → score → iterate) is driven by the agents themselves — they read it from the `CRUX.md` Crux generates, so you never run it by hand. Docs: https://crux.dev/docs/discovery

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
