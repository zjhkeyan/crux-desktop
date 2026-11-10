---
name: multi-agent-orchestration
description: Unified 4-step Crux Discovery workflow — Main Agent acts as Manager + Verifier (Direction Board with direction-relative credit & UCB exploration bonus + Verified Shared Archive + <=3-turn Heartbeat resets), while Sub-Agents act as pure isolated git worktree solver & tool builders.
---

# Unified Crux Discovery Multi-Agent Workflow

Use this streamlined 4-step workflow when tackling multi-direction optimization, mathematical/algorithmic discovery, or parallel experiments.

## Division of Cognitive Labor

- **Main Agent = Manager + Verifier**:
  - Initializes and maintains the **Direction Board** (direction-relative credit Eq. 1, empirical shrinkage yield Eq. 2, UCB exploration potential Eq. 3, and `NEW` arm option pricing Eq. 4) and the **Verified Shared Archive** (verified scored attempts, promoted insights, failure constraints, and reusable `tools/` only) via `crux_discovery` (`crux-discovery-helper`).
  - Tags each attempt's **Direction** (`--direction`) and **Method** (`--method`), runs independent verification, and records verified scores into the archive.
  - Enforces the **<=3-turn sub-agent session cap**: after at most 3 turns per sub-agent session, runs `crux-discovery-helper summary work/<task_slug>` to execute the **Heartbeat (`REFLECT` / `CONSOLIDATE` / `PIVOT`)** and seeds a fresh sub-agent prompt from the bounded Verified Archive Summary (`<= 9,000` chars).
- **Sub-Agents = Pure Isolated `git worktree` Workers (`.worktrees/agent-a`, `.worktrees/agent-b`)**:
  - **ONLY** write solver code, build reusable analysis/verification tools (`tools/`), run the deterministic evaluator, and commit their changes locally.
  - **Zero AgentRadio chat, zero seat claiming, and zero ledger CLI burden** — sub-agents never call `crux-discovery-helper` or `crux discovery`.

---

## Step 1: Initialize the Crux Discovery Ledger, Baseline & Direction Board (Manager)

When the user asks in natural language to explore or compare multiple directions in parallel, **automatically** initialize `crux_discovery`, claim each direction, create a fast deterministic evaluator (`<= 3s` runtime), and **immediately record the `baseline` attempt before dispatching workers** so the Direction Board and Lineage Graph have a root node (`baseline01`) right away:

```json
{ "action": "init", "runDir": "work/<task_slug>", "name": "<Task Title>", "goalDirection": "maximize", "seats": 2 }
{ "action": "claim", "runDir": "work/<task_slug>", "agent": "agent-a", "direction": "<dir_a_slug>", "method": "<Direction A method>" }
{ "action": "claim", "runDir": "work/<task_slug>", "agent": "agent-b", "direction": "<dir_b_slug>", "method": "<Direction B method>" }
{ "action": "record", "runDir": "work/<task_slug>", "agent": "manager", "direction": "baseline", "commit": "baseline01", "score": 100.0, "title": "Deterministic baseline", "method": "Reference baseline", "insight": "Baseline reference score" }
```
*(Or via bash: `crux-discovery-helper init work/<task_slug> --name "<Task Title>" --direction maximize --seats 2`)*

---

## Step 2: Create Isolated `git worktree` Sandboxes, Bind CLI Agents & Track Checkpoints (Manager)

You can manage projects, worktrees, and progress checkpoints either through the OpenCode `worktree` tool (`runtime/osd-plugin/worktree.ts`) **or** directly via the `crux` CLI (`crux project` / `crux worktree`, backed by Crux's worktree engine in `runtime/worktree/`):

### Option A: `crux` CLI (Available to Any Terminal or Sub-Agent)

```bash
# Import an existing folder or Git repository into the workspace (crux repo add equivalent)
crux project add /path/to/repo --mode in-place

# List supported CLI agents (claude, codex, opencode, grok, gemini, cursor, copilot, pi, dsh, antigravity, aider, ...)
crux worktree agents

# Create isolated git worktrees (.worktrees/<name> on branch crux/<name>) & materialize .worktreeinclude + shared tools/
crux worktree create --name agent-a --agent claude --prompt "Implement Direction A solver" --comment "Assigned Direction A"
crux worktree create --name agent-b --agent codex  --prompt "Implement Direction B solver" --parent-worktree agent-a

# Inspect active worktrees, current worktree, or update progress checkpoints & workspace status
crux worktree ps
crux worktree current
crux worktree set --worktree agent-a --status in-review --comment "Passed evaluator with score 0.942"
```

### Option B: OpenCode `worktree` Tool (`runtime/osd-plugin/worktree.ts`)

```json
{ "action": "agents" }
{ "action": "create", "taskId": "agent-a", "agent": "claude", "prompt": "Implement Direction A solver", "openPane": true }
{ "action": "create", "taskId": "agent-b", "agent": "codex",  "prompt": "Implement Direction B solver", "openPane": true }
{ "action": "set", "taskId": "agent-a", "workspaceStatus": "in-review", "comment": "Passed evaluator with score 0.942" }
{ "action": "status" }
```

---

## Step 3: Open Live Split-Screen Canvas & Dispatch `<=3`-Turn Worker Sessions (Manager -> Sub-Agents)

Create a live split-screen canvas containing **2 sub-agent conversation panes** plus the **Crux Discovery** tile (`Direction Board` + `Verified Shared Archive`), then focus it in the user's UI:

```bash
crux screen new --sessions 2 --discovery work/<task_slug> --name "Crux · <Task Title>"
crux screen list
crux screen focus <scr_id>

crux session rename <ses_A> "Agent-A · <dir_a_slug>"
crux session rename <ses_B> "Agent-B · <dir_b_slug>"
```
*(Tip: To attach the Crux Discovery tile to an existing screen `<scr_id>`, run `crux screen add <scr_id> --discovery work/<task_slug>`.)*

Dispatch each sub-agent with a focused **<=3-turn worker prompt** (seeded by `crux-discovery-helper summary work/<task_slug>`). Sub-agents only write solver code + reusable `tools/` and run the deterministic evaluator:

```bash
crux session send <ses_A> "You are Worker agent-a in .worktrees/agent-a (<=3 turns max).
Assigned Direction: <dir_a_slug> | Method: <Direction A method>
1. Implement your solver and any reusable diagnostic script in tools/ inside .worktrees/agent-a.
2. Run the deterministic evaluator to measure the exact score.
3. Commit your verified code in .worktrees/agent-a and report ONLY: commit hash, measured score, tool paths created, and 1-sentence mechanism."

crux session send <ses_B> "You are Worker agent-b in .worktrees/agent-b (<=3 turns max).
Assigned Direction: <dir_b_slug> | Method: <Direction B method>
1. Implement your solver and any reusable diagnostic script in tools/ inside .worktrees/agent-b.
2. Run the deterministic evaluator to measure the exact score.
3. Commit your verified code in .worktrees/agent-b and report ONLY: commit hash, measured score, tool paths created, and 1-sentence mechanism."
```

---

## Step 4: Verify, Record to Shared Archive & Execute Heartbeat Reset (`REFLECT` / `CONSOLIDATE` / `PIVOT`)

As **Manager + Verifier**, independently verify each sub-agent's commit/score (and copy any reusable scripts into `work/<task_slug>/tools/`), then record the finalized attempt into the **Verified Shared Archive** and **Direction Board**:

```bash
# 1. Record baseline node
crux-discovery-helper record work/<task_slug> \
  --agent agent-a \
  --direction baseline \
  --commit 1000001a \
  --score <baseline_score> \
  --title "Baseline reference implementation" \
  --method "Reference baseline" \
  --insight "<Baseline bottleneck analysis>"

# 2. Record Direction A verified attempt (computes direction-relative credit & UCB potential)
crux-discovery-helper record work/<task_slug> \
  --agent agent-a \
  --direction <dir_a_slug> \
  --commit 2000002a \
  --parent 1000001a \
  --score <score_a> \
  --title "<Direction A solver title>" \
  --method "<Direction A method>" \
  --insight "<Verified mechanism behind the score gain>"

# 3. Record Direction B verified attempt (cross-pollinating verified insight/tool from 2000002a)
crux-discovery-helper record work/<task_slug> \
  --agent agent-b \
  --direction <dir_b_slug> \
  --commit 3000003b \
  --parent 2000002a \
  --inspired-by 2000002a \
  --score <score_b> \
  --title "<Direction B solver title>" \
  --method "<Direction B + Direction A synthesis>" \
  --insight "<Why combining Direction B with 2000002a achieved the new global best>"
```

### Heartbeat `Reflect / Consolidate / Pivot` & `<=3`-Turn Session Reset

After each wave (<=3 turns per sub-agent), generate the bounded **Verified Archive Summary + Direction Board + Heartbeat Directive**:

```bash
crux-discovery-helper summary work/<task_slug>
```

- **`REFLECT`**: Distill what caused the measured score delta (or failure constraint `--constraint "..."`) into the Verified Shared Archive before resetting the sub-agent context.
- **`CONSOLIDATE`**: When multiple directions produce verified gains or reusable `tools/`, seed the next `<=3`-turn sub-agent session with the top verified commits (`--inspired-by`) and `tools/` from `crux-discovery-helper summary`.
- **`PIVOT`**: When a direction stalls or the Direction Board's UCB exploration bonus favors `NEW` or an under-explored arm, reassign the sub-agent worktree to a fresh direction.

### Harvesting the Winning Worktree (Crux Diff Review & Verified Merge Gate)

Once the winning commit is verified on the Direction Board and Shared Archive, inspect its unified Diff and merge it back into the main workspace through the pre-merge verification gate (`removeWorktreeSymlinks` safely unlinks shared `tools/` symlinks before staging and merging):

```bash
# Via crux CLI:
crux worktree diff agent-b
crux worktree merge agent-b --verify-cmd "pytest -q" --cleanup
crux worktree rm agent-a --force
```

Or via the `worktree` tool:

```json
{ "action": "diff", "taskId": "agent-b" }
{ "action": "merge", "taskId": "agent-b", "verifyCmd": "pytest -q", "cleanup": true }
{ "action": "rm", "taskId": "agent-a", "force": true }
```

---

## Optional Track: Coupling with **Crux Evolve** (`crux_evolve` Tool) for Evolutionary Algorithm Optimization

- **Lightweight Literature / Survey Track (No Algorithm Evolution Needed)**: When the user only asks for literature retrieval, paper reading, or research surveys, do **not** load `crux-evolve` or `crux_discovery` — use `literature-review` (`sci_research` tool) and `agent-memory` (`memory_dream` tool) directly.
- **Dedicated Algorithm Optimization Track (`Crux Evolve × Crux Discovery`)**: When the user wants heuristic/algorithm evolution or mathematical optimization, combine `crux_discovery` (macro UCB Direction Board) with the **`crux_evolve` tool** (`runtime/skills/crux/crux-evolve/SKILL.md`):
  1. **Island Spectrum & Method Selection**: Call `crux_evolve` (`action: "methods"` / `action: "island_plan"`) to assign continuous exploration/exploitation & memory policy weights (`success_only`, `corrective`, `novelty`) across worktree islands (`.worktrees/agent-a`, `.worktrees/agent-b`, ...).
  2. **Structured Evolutionary Operators**: Call `crux_evolve` (`action: "operator_prompt"`, `operator: "e1" | "e2" | "m1" | "m2" | "reevo-short-reflection" | "reevo-crossover"`) to seed each `<=3`-turn worktree worker prompt.
  3. **Two-Stage Parameter Tuning & Code-Diversity Survivor Selection**: Before recording to `crux_discovery`, run `crux_evolve` (`action: "tune_params"`, `apply: true`) for Sobol QMC + coordinate pattern search on bounded `MODEL_SPEC` parameters, and `crux_evolve` (`action: "select_survivors"`) to retain both top-scoring and structurally novel (`code_fingerprint`) candidates.
