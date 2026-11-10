// Native OpenCode JSON-Schema Tools for Crux Scientific Workflows:
// - `sci_research`: MindSearch / FlowSearch multi-source search, MinerU/pdf-craft PDF reading, and HuixiangDou evidence gate (`crux-sci-research`).
// - `crux_discovery`: Crux Discovery direction board (UCB) & verified shared archive (`crux-discovery-helper`).
// - `memory_dream`: Anthropic Agent Memory session transcript export, Knowledge Wiki corpus staging, and MEMORY.md validation (`dream_adapter.py`).
// - `crux_evolve`: Crux Evolve evolutionary algorithm optimization (10 evolutionary methods, Diverse Island GA spectrum, EoH/ReEvo operators, code-diversity survivor selection, and Sobol QMC + pattern search parameter tuning).
//
// Exposing these as native OpenCode tools prevents LLM flag hallucination and path errors.
import { execFile } from "node:child_process";
import { existsSync, lstatSync, realpathSync } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

function resolveInWorkspace(workspaceDir: string, p: string | undefined, fallback: string): string {
  const raw = (p ?? "").trim() || fallback;
  return isAbsolute(raw) ? raw : resolve(workspaceDir, raw);
}

async function runBin(
  bin: string,
  args: string[],
  cwd: string,
  timeoutMs = 180_000,
): Promise<string> {
  const { stdout, stderr } = await execFileAsync(bin, args, {
    cwd,
    timeout: timeoutMs,
    maxBuffer: 16 * 1024 * 1024,
    env: { ...process.env },
  });
  const out = String(stdout ?? "").trim();
  const err = String(stderr ?? "").trim();
  return out || err || "(ok)";
}

// ---- 1. `sci_research` Tool -------------------------------------------------

export const SCI_RESEARCH_ACTIONS = ["search", "read", "ask", "doctor"] as const;
export type SciResearchAction = (typeof SCI_RESEARCH_ACTIONS)[number];

export const sciResearchTool = {
  name: "sci_research",
  description:
    "Unified scientific literature search, high-fidelity PDF/paper reading, and anti-hallucination evidence verification (powered by MindSearch DAG, FlowSearch, MinerU, pdf-craft, and HuixiangDou).\n\n" +
    "Actions:\n" +
    "- search: multi-source academic retrieval across sciverse, openalex, arxiv, crossref, atlas, and ddg (`mode`: 'fast' | 'dag' | 'flow').\n" +
    "- read: high-fidelity scientific PDF/document parsing preserving dual-column layout, LaTeX formulas, tables, and `[doc:<slug>/page:<p>/block:<b>]` locators.\n" +
    "- ask: verify a scientific claim or question against a parsed corpus directory using HuixiangDou's two-stage reranking and `reject_throttle` evidence gate.\n" +
    "- doctor: check configured search channels and API keys.",
  input: {
    type: "object",
    properties: {
      action: {
        type: "string",
        enum: [...SCI_RESEARCH_ACTIONS],
        description: "Which scientific research action to execute.",
      },
      query: {
        type: "string",
        description: "For `search` or `ask`: the scientific research topic, sub-question, or claim to verify.",
      },
      target: {
        type: "string",
        description: "For `read`: path or URL to the PDF / Markdown paper to parse.",
      },
      mode: {
        type: "string",
        enum: ["fast", "dag", "flow"],
        description: "For `search`: 'fast' (single-node), 'dag' (MindSearch sub-question DAG), or 'flow' (FlowSearch dynamic knowledge flow + gap audit). Default: 'flow'.",
      },
      sources: {
        type: "string",
        description: "For `search`: comma-separated channels (default: 'sciverse,openalex,arxiv,crossref,atlas').",
      },
      pages: {
        type: "string",
        description: "For `read`: page range to parse (e.g. '1-10'). Default: '1-10'.",
      },
      section: {
        type: "string",
        description: "For `read`: optional section or keyword filter.",
      },
      outDir: {
        type: "string",
        description: "For `search` or `read`: workspace-relative output folder (e.g. 'work/topic/literature' or 'work/topic/corpus').",
      },
      corpusDir: {
        type: "string",
        description: "For `ask`: workspace-relative corpus folder containing parsed papers or search results.",
      },
      limit: {
        type: "number",
        description: "For `search` or `ask`: maximum number of results per node / top-k blocks (default: 5).",
      },
      threshold: {
        type: "number",
        description: "For `ask`: HuixiangDou reject_throttle score threshold (default: 0.25).",
      },
    },
    required: ["action"],
    additionalProperties: false,
  },
} as const;

export async function runSciResearch(
  workspaceDir: string,
  args: Record<string, unknown>,
): Promise<string> {
  const action = String(args.action ?? "").trim() as SciResearchAction;
  const bin = existsSync("/usr/local/bin/crux-sci-research")
    ? "/usr/local/bin/crux-sci-research"
    : "crux-sci-research";

  switch (action) {
    case "doctor":
      return runBin(bin, ["doctor"], workspaceDir);
    case "search": {
      const query = String(args.query ?? "").trim();
      if (!query) throw new Error("sci_research search requires `query`");
      const mode = typeof args.mode === "string" && args.mode ? args.mode : "flow";
      const sources =
        typeof args.sources === "string" && args.sources.trim()
          ? args.sources.trim()
          : "sciverse,openalex,arxiv,crossref,atlas";
      const limit = typeof args.limit === "number" && args.limit > 0 ? String(args.limit) : "5";
      const outDir = resolveInWorkspace(
        workspaceDir,
        typeof args.outDir === "string" ? args.outDir : undefined,
        "work/literature",
      );
      return runBin(
        bin,
        ["search", query, "--mode", mode, "--sources", sources, "--limit", limit, "--out", outDir],
        workspaceDir,
      );
    }
    case "read": {
      const targetRaw = String(args.target ?? args.query ?? "").trim();
      if (!targetRaw) throw new Error("sci_research read requires `target` (path or URL to PDF)");
      const target =
        targetRaw.startsWith("http://") || targetRaw.startsWith("https://")
          ? targetRaw
          : resolveInWorkspace(workspaceDir, targetRaw, targetRaw);
      const pages = typeof args.pages === "string" && args.pages.trim() ? args.pages.trim() : "1-10";
      const outDir = resolveInWorkspace(
        workspaceDir,
        typeof args.outDir === "string" ? args.outDir : undefined,
        "work/corpus",
      );
      const cliArgs = ["read", target, "--pages", pages, "--out", outDir];
      if (typeof args.section === "string" && args.section.trim()) {
        cliArgs.push("--section", args.section.trim());
      }
      return runBin(bin, cliArgs, workspaceDir);
    }
    case "ask": {
      const query = String(args.query ?? "").trim();
      if (!query) throw new Error("sci_research ask requires `query`");
      const corpusDir = resolveInWorkspace(
        workspaceDir,
        typeof args.corpusDir === "string"
          ? args.corpusDir
          : typeof args.outDir === "string"
            ? args.outDir
            : undefined,
        "work/corpus",
      );
      const threshold =
        typeof args.threshold === "number" && args.threshold > 0 ? String(args.threshold) : "0.25";
      const topK = typeof args.limit === "number" && args.limit > 0 ? String(args.limit) : "5";
      return runBin(
        bin,
        ["ask", query, "--corpus", corpusDir, "--threshold", threshold, "--top-k", topK],
        workspaceDir,
      );
    }
    default:
      throw new Error(`Unknown sci_research action: ${String(action)}`);
  }
}

// ---- 2. `crux_discovery` Tool ----------------------------------------------

export const CRUX_DISCOVERY_ACTIONS = ["init", "claim", "record", "summary"] as const;
export type CruxDiscoveryAction = (typeof CRUX_DISCOVERY_ACTIONS)[number];
export const CORAL_DISCOVERY_ACTIONS = CRUX_DISCOVERY_ACTIONS;
export type CoralDiscoveryAction = CruxDiscoveryAction;

export const cruxDiscoveryTool = {
  name: "crux_discovery",
  description:
    "Manage the Crux Discovery multi-agent Direction Board (UCB + SciMuse Elo tournament `IDE`), Verified Shared Archive, `IVE` two-class failure attribution (`implementation` vs `fundamental` dead-end circuit breaker), and `ESE` experiment strategy memory (`MuseMemoryBank` L0/L1/L2).\n\n" +
    "Actions:\n" +
    "- init: initialize `.crux` ledger, `tools/`, `board.json`, and `archive.json` in `runDir`.\n" +
    "- claim: register or assign a research direction and mathematical/algorithmic method on the Direction Board.\n" +
    "- record: record a verified attempt (commit hash, measured score, direction, method, insight, optional `failureType: 'implementation' | 'fundamental'`, and optional `codeFile` for ESE AST signature distillation).\n" +
    "- summary: generate the bounded Verified Archive Summary + Direction Board (UCB + SciMuse Elo) + EMA Idea/Experiment Memory ($M_I$ / $M_E$) + Heartbeat directive.",
  input: {
    type: "object",
    properties: {
      action: {
        type: "string",
        enum: [...CRUX_DISCOVERY_ACTIONS],
        description: "Which Crux Discovery manager action to run.",
      },
      runDir: {
        type: "string",
        description: "Workspace-relative experiment folder (e.g. 'work/my-discovery').",
      },
      name: {
        type: "string",
        description: "For `init`: human-readable task title.",
      },
      goalDirection: {
        type: "string",
        enum: ["maximize", "minimize"],
        description: "For `init`: whether higher ('maximize') or lower ('minimize') scores are better.",
      },
      seats: {
        type: "number",
        description: "For `init`: number of parallel worker seats (default: 2).",
      },
      agent: {
        type: "string",
        description: "For `claim` or `record`: sub-agent identifier (e.g. 'agent-a').",
      },
      direction: {
        type: "string",
        description: "For `claim` or `record`: direction slug on the Direction Board (e.g. 'spectral-precond').",
      },
      method: {
        type: "string",
        description: "For `claim` or `record`: mathematical or algorithmic method description.",
      },
      commit: {
        type: "string",
        description: "For `record`: verified Git commit hash.",
      },
      parent: {
        type: "string",
        description: "For `record`: optional parent commit hash.",
      },
      inspiredBy: {
        type: "string",
        description: "For `record`: optional commit hash this attempt cross-pollinated from.",
      },
      score: {
        type: "number",
        description: "For `record`: verified numerical evaluation score.",
      },
      title: {
        type: "string",
        description: "For `record`: short title of the attempt.",
      },
      insight: {
        type: "string",
        description: "For `record`: verified mechanism explaining the score change.",
      },
      constraint: {
        type: "string",
        description: "For `record`: optional negative result or failure boundary constraint.",
      },
      failureType: {
        type: "string",
        enum: ["implementation", "fundamental"],
        description: "For `record` (IVE two-class failure attribution): 'implementation' for code/runtime bug (retries without penalizing direction UCB/Elo) or 'fundamental' for falsified scientific hypothesis (marks direction FALSIFIED in $M_I$ and MEMORY.md).",
      },
      codeFile: {
        type: "string",
        description: "For `record` (ESE experiment strategy memory $M_E$): optional path to the solver file so `MuseMemoryBank` extracts AST code signatures and L0 global rules.",
      },
    },
    required: ["action", "runDir"],
    additionalProperties: false,
  },
} as const;
export const coralDiscoveryTool = cruxDiscoveryTool;

export async function runCruxDiscovery(
  workspaceDir: string,
  args: Record<string, unknown>,
): Promise<string> {
  const action = String(args.action ?? "").trim() as CruxDiscoveryAction;
  const runDir = resolveInWorkspace(
    workspaceDir,
    typeof args.runDir === "string" ? args.runDir : undefined,
    "work/discovery",
  );
  const bin = existsSync("/usr/local/bin/crux-discovery-helper")
    ? "/usr/local/bin/crux-discovery-helper"
    : existsSync("/usr/local/bin/crux-coral-helper")
      ? "/usr/local/bin/crux-coral-helper"
      : "crux-discovery-helper";

  switch (action) {
    case "init": {
      const name = typeof args.name === "string" && args.name.trim() ? args.name.trim() : "Discovery Task";
      const goalDir = args.goalDirection === "minimize" ? "minimize" : "maximize";
      const seats = typeof args.seats === "number" && args.seats > 0 ? String(args.seats) : "2";
      return runBin(
        bin,
        ["init", runDir, "--name", name, "--direction", goalDir, "--seats", seats],
        workspaceDir,
      );
    }
    case "claim": {
      const agent = String(args.agent ?? "agent-a").trim();
      const direction = String(args.direction ?? "").trim();
      if (!direction) throw new Error("crux_discovery claim requires `direction`");
      const method = String(args.method ?? direction).trim();
      return runBin(
        bin,
        ["claim", runDir, "--agent", agent, "--direction", direction, "--method", method],
        workspaceDir,
      );
    }
    case "record": {
      const agent = String(args.agent ?? "agent-a").trim();
      const direction = String(args.direction ?? "baseline").trim();
      const commit = String(args.commit ?? "").trim();
      if (!commit) throw new Error("crux_discovery record requires `commit`");
      if (typeof args.score !== "number" && typeof args.score !== "string") {
        throw new Error("crux_discovery record requires numerical `score`");
      }
      const cliArgs = [
        "record",
        runDir,
        "--agent",
        agent,
        "--direction",
        direction,
        "--commit",
        commit,
        "--score",
        String(args.score),
        "--title",
        String(args.title ?? `${direction} attempt`).trim(),
        "--method",
        String(args.method ?? direction).trim(),
      ];
      if (typeof args.parent === "string" && args.parent.trim()) {
        cliArgs.push("--parent", args.parent.trim());
      }
      if (typeof args.inspiredBy === "string" && args.inspiredBy.trim()) {
        cliArgs.push("--inspired-by", args.inspiredBy.trim());
      }
      if (typeof args.insight === "string" && args.insight.trim()) {
        cliArgs.push("--insight", args.insight.trim());
      }
      if (typeof args.constraint === "string" && args.constraint.trim()) {
        cliArgs.push("--constraint", args.constraint.trim());
      }
      if (args.failureType === "implementation" || args.failureType === "fundamental") {
        cliArgs.push("--failure-type", args.failureType);
      }
      if (typeof args.codeFile === "string" && args.codeFile.trim()) {
        cliArgs.push("--code-file", resolveInWorkspace(workspaceDir, args.codeFile, args.codeFile));
      }
      return runBin(bin, cliArgs, workspaceDir);
    }
    case "summary":
      return runBin(bin, ["summary", runDir], workspaceDir);
    default:
      throw new Error(`Unknown crux_discovery action: ${String(action)}`);
  }
}
export const runCoralDiscovery = runCruxDiscovery;

// ---- 3. `memory_dream` Tool -------------------------------------------------

export const MEMORY_DREAM_ACTIONS = [
  "export_transcripts",
  "prepare_corpus",
  "validate_store",
] as const;
export type MemoryDreamAction = (typeof MEMORY_DREAM_ACTIONS)[number];

export const memoryDreamTool = {
  name: "memory_dream",
  description:
    "Manage Anthropic Agent Memory consolidation ('dreaming'), scientific Knowledge Wiki distillation (`.opencode/skills/<wikiSlug>/`), and `<workspace>/MEMORY.md` maintenance.\n\n" +
    "Actions:\n" +
    "- export_transcripts: export recent OpenCode session transcripts (`opencode.db`) and `.openscience/runs.jsonl` into `.openscience/transcripts/*.txt` with secret scrubbing for `memory-curator`.\n" +
    "- prepare_corpus: stage scientific PDFs/DOCX/Markdown from `corpusDir` with MinerU `[pX:bY]` locators into `.opencode/skills/<wikiSlug>/`.\n" +
    "- validate_store: remove `MOVED TO [[slug]]` stubs, verify `SKILL.md` & `_index.md`, and sync the top-level memory index to `<workspace>/MEMORY.md` (<200 lines / 25 KB).",
  input: {
    type: "object",
    properties: {
      action: {
        type: "string",
        enum: [...MEMORY_DREAM_ACTIONS],
        description: "Which memory consolidation or Knowledge Wiki action to run.",
      },
      corpusDir: {
        type: "string",
        description: "For `prepare_corpus`: folder of scientific PDFs/DOCX/Markdown documents to distill.",
      },
      wikiSlug: {
        type: "string",
        description: "For `prepare_corpus`: target Knowledge Wiki skill slug (e.g. 'catalysis-wiki').",
      },
      memDir: {
        type: "string",
        description: "For `validate_store`: memory directory to validate (default: '.openscience/memory').",
      },
      skillName: {
        type: "string",
        description: "For `validate_store`: optional generated skill name when validating `.opencode/skills/<skillName>`.",
      },
      limit: {
        type: "number",
        description: "For `export_transcripts`: max number of recent sessions to export (default: 10).",
      },
    },
    required: ["action"],
    additionalProperties: false,
  },
} as const;

function locateDreamAdapter(): string {
  const candidates = [
    "/root/.local/share/com.crux.desktop/runtime/xdg-config/opencode/skills/agent-memory/dream_adapter.py",
    "/root/sciencecowork/dist-osd/osd-0.7.1-x86_64-unknown-linux-gnu/resources/skills-core/agent-memory/dream_adapter.py",
    "/root/sciencecowork/runtime/skills/core/agent-memory/dream_adapter.py",
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  throw new Error("dream_adapter.py not found in runtime skills");
}

export async function runMemoryDream(
  workspaceDir: string,
  args: Record<string, unknown>,
): Promise<string> {
  const action = String(args.action ?? "").trim() as MemoryDreamAction;
  const script = locateDreamAdapter();

  switch (action) {
    case "export_transcripts": {
      const cliArgs = [script, "export-transcripts", "--workspace", workspaceDir];
      if (typeof args.limit === "number" && args.limit > 0) {
        cliArgs.push("--limit", String(args.limit));
      }
      return runBin("python3", cliArgs, workspaceDir);
    }
    case "prepare_corpus": {
      const corpusDir = resolveInWorkspace(
        workspaceDir,
        typeof args.corpusDir === "string" ? args.corpusDir : undefined,
        "papers",
      );
      const wikiSlug = String(args.wikiSlug ?? "knowledge-wiki").trim();
      return runBin(
        "python3",
        [
          script,
          "prepare-corpus",
          "--workspace",
          workspaceDir,
          "--corpus-dir",
          corpusDir,
          "--wiki-slug",
          wikiSlug,
        ],
        workspaceDir,
      );
    }
    case "validate_store": {
      const memDir = resolveInWorkspace(
        workspaceDir,
        typeof args.memDir === "string" ? args.memDir : undefined,
        ".openscience/memory",
      );
      const cliArgs = [
        script,
        "validate-store",
        "--workspace",
        workspaceDir,
        "--mem-dir",
        memDir,
      ];
      if (typeof args.skillName === "string" && args.skillName.trim()) {
        cliArgs.push("--skill-name", args.skillName.trim());
      }
      return runBin("python3", cliArgs, workspaceDir);
    }
    default:
      throw new Error(`Unknown memory_dream action: ${String(action)}`);
  }
}

// ---- 4. `crux_evolve` Tool (Rebranded Crux Evolve Algorithm Optimization) ---

export const CRUX_EVOLVE_ACTIONS = [
  "scaffold_package",
  "switch_method",
  "evaluate_candidate",
  "methods",
  "island_plan",
  "select_survivors",
  "operator_prompt",
  "advise_blocks",
  "tune_params",
  "sync_views",
] as const;
export type CruxEvolveAction = (typeof CRUX_EVOLVE_ACTIONS)[number];

export const cruxEvolveTool = {
  name: "crux_evolve",
  description:
    "Crux Evolve — Dedicated Evolutionary Algorithm & Heuristic Optimization module coupled with Coral / Crux Discovery.\n\n" +
    "Actions:\n" +
    "- scaffold_package: copy an upstream `template` into `projectDir`, set `projectName` / `seed`, and run the zero-token evaluator self-test.\n" +
    "- switch_method: set `methodName` in `projectDir` using canonical upstream parameters; evaluator, providers and seed stay locked.\n" +
    "- evaluate_candidate: evaluate `projectDir` in an isolated Git worktree, optionally using `worktree`, `sshHost`, `remoteDir` or `resumeCheckpoint`.\n" +
    "- methods: list all 10 Crux Evolve evolutionary methods (`eoh`, `reevo`, `mcts-ahd`, `meoh`, `diverse-island-ga`, `island-ga`, `funsearch`, `dyca`, `nsga2`, `moead`) or inspect a specific method's recommended parameters & guide (`methodName`).\n" +
    "- island_plan: compute the Diverse Island GA strategy spectrum (continuous exploration/exploitation & memory policy weights) across parallel agent islands.\n" +
    "- select_survivors: select quality + AST/token code-diverse survivors from `candidatesFile` (`count`, `noveltyRatio`).\n" +
    "- operator_prompt: build structured EoH (`i1`, `e1`, `e2`, `m1`, `m2`) or ReEvo (`reevo-short-reflection`, `reevo-crossover`, `reevo-mutation`) operator prompts.\n" +
    "- advise_blocks: inspect a target source file (`targetFile`) for `# EVOLVE_START` / `# EVOLVE_END` blocks or recommend top evolvable functions.\n" +
    "- tune_params: run two-stage Sobol QMC + coordinate pattern search on bounded `MODEL_SPEC` parameters in `targetFile` (`evalCmd`, `maxEvals`, `apply`).\n" +
    "- sync_views: project `stateFile` (`evolution_state.json`) into `.crux/public/views/{board,tree,archive}.json` in `runDir`.",
  input: {
    type: "object",
    properties: {
      action: {
        type: "string",
        enum: [...CRUX_EVOLVE_ACTIONS],
        description: "Which Crux Evolve algorithm optimization action to execute.",
      },
      methodName: {
        type: "string",
        description: "For `methods` or `switch_method`: method slug; hyphens and underscores are accepted when switching.",
      },
      template: { type: "string", enum: ["tsp", "knapsack", "lunarlander"], description: "Upstream task template for scaffold_package." },
      projectDir: { type: "string", description: "Workspace task package directory; scaffold_package requires a new or empty directory." },
      projectName: { type: "string", description: "Optional scaffolded project name." },
      seed: { type: "integer", description: "Scaffold random seed; switch_method only accepts the existing locked seed." },
      worktree: { type: "string", description: "Optional candidate algorithm directory inside the workspace." },
      sshHost: { type: "string", description: "Registered crux remote host for evaluator offloading." },
      remoteDir: { type: "string", description: "New package destination relative to the crux remote workspace for SSH evaluation." },
      resumeCheckpoint: { type: "string", description: "Evaluation checkpoint metadata path; verifies benchmark identity before replaying evaluation." },
      islands: {
        type: "number",
        description: "For `island_plan`: number of parallel evolutionary islands (default: 3).",
      },
      stagnation: {
        type: "number",
        description: "For `island_plan`: stagnation generations counter (default: 0).",
      },
      generation: {
        type: "number",
        description: "For `island_plan`: current generation index (default: 0).",
      },
      candidatesFile: {
        type: "string",
        description: "For `select_survivors` or `operator_prompt`: path to JSON file containing candidate/parent individuals.",
      },
      count: {
        type: "number",
        description: "For `select_survivors`: number of survivors to select (default: 4).",
      },
      noveltyRatio: {
        type: "number",
        description: "For `select_survivors`: fraction of survivor slots reserved for code-novelty selection (default: 0.25).",
      },
      operator: {
        type: "string",
        description: "For `operator_prompt`: 'i1' | 'e1' | 'e2' | 'm1' | 'm2' | 'reevo-short-reflection' | 'reevo-crossover' | 'reevo-mutation'.",
      },
      task: {
        type: "string",
        description: "For `operator_prompt`: algorithm optimization problem description.",
      },
      reflection: {
        type: "string",
        description: "For `operator_prompt`: optional verbal gradient reflection text for ReEvo operators.",
      },
      targetFile: {
        type: "string",
        description: "For `advise_blocks` or `tune_params`: path to the candidate solver file.",
      },
      evalCmd: {
        type: "string",
        description: "For `tune_params`: shell command reading `CRUX_EVOLVE_PARAMS_JSON` and printing JSON `{score: <float>}`.",
      },
      symbol: {
        type: "string",
        description: "For `tune_params`: Python dict symbol holding bounded parameters (default: 'MODEL_SPEC').",
      },
      maxEvals: {
        type: "number",
        description: "For `tune_params`: maximum parameter search evaluations (default: 32).",
      },
      apply: {
        type: "boolean",
        description: "For `tune_params`: whether to patch the best tuned parameters directly back into `targetFile`.",
      },
      stateFile: {
        type: "string",
        description: "For `sync_views`: path to `evolution_state.json`.",
      },
      runDir: {
        type: "string",
        description: "For `sync_views`: experiment directory receiving `.crux/public/views/{board,tree,archive}.json`.",
      },
    },
    required: ["action"],
    additionalProperties: false,
  },
} as const;

function locateCruxEvolveAdapter(): string {
  const candidates = [
    "/root/sciencecowork/runtime/skills/crux/crux-evolve/crux_evolve_adapter.py",
    "/root/.local/share/com.crux.desktop/runtime/xdg-config/opencode/skills/crux-evolve/crux_evolve_adapter.py",
    "/root/sciencecowork/dist-osd/osd-0.7.1-x86_64-unknown-linux-gnu/resources/skills-crux/crux-evolve/crux_evolve_adapter.py",
  ];
  for (const c of candidates) {
    if (existsSync(c)) return c;
  }
  throw new Error("crux_evolve_adapter.py not found in runtime skills");
}

export async function runCruxEvolve(
  workspaceDir: string,
  args: Record<string, unknown>,
): Promise<string> {
  const action = String(args.action ?? "").trim() as CruxEvolveAction;
  const script = locateCruxEvolveAdapter();

  switch (action) {
    case "scaffold_package":
    case "switch_method":
    case "evaluate_candidate": {
      const projectDir = String(args.projectDir ?? "").trim();
      if (!projectDir) throw new Error(`crux_evolve ${action} requires projectDir`);
      const workspace = realpathSync(workspaceDir);
      const workspacePath = (input: string): string => {
        const path = resolve(workspace, input);
        let ancestor = path;
        while (!lstatSync(ancestor, { throwIfNoEntry: false }) && dirname(ancestor) !== ancestor) ancestor = dirname(ancestor);
        for (const candidate of [path, realpathSync(ancestor)]) {
          const rel = relative(workspace, candidate);
          if (rel === ".." || rel.startsWith("../") || rel.startsWith("..\\") || isAbsolute(rel)) {
            throw new Error("crux_evolve paths must stay inside the active workspace");
          }
        }
        return path;
      };
      const cliArgs = [script, action.replace(/_/g, "-"), action === "scaffold_package" ? "--dest" : "--project-dir", workspacePath(projectDir)];
      if (action === "scaffold_package") {
        if (!["tsp", "knapsack", "lunarlander"].includes(String(args.template))) throw new Error("scaffold_package requires a supported template");
        cliArgs.push("--template", String(args.template));
        if (typeof args.projectName === "string" && args.projectName.trim()) cliArgs.push("--project-name", args.projectName.trim());
      } else if (action === "switch_method") {
        if (typeof args.methodName !== "string" || !args.methodName.trim()) throw new Error("switch_method requires methodName");
        cliArgs.push("--method", args.methodName.trim());
      }
      if (action !== "evaluate_candidate" && args.seed !== undefined) {
        if (!Number.isSafeInteger(args.seed)) throw new Error("seed must be a safe integer");
        cliArgs.push("--seed", String(args.seed));
      }
      if (action === "evaluate_candidate") {
        for (const [key, flag] of [["worktree", "--worktree"], ["resumeCheckpoint", "--resume-checkpoint"]]) {
          const value = args[key];
          if (typeof value === "string" && value.trim()) cliArgs.push(flag, workspacePath(value));
        }
        for (const [key, flag] of [["sshHost", "--ssh-host"], ["remoteDir", "--remote-dir"]]) {
          const value = args[key];
          if (typeof value === "string" && value.trim()) cliArgs.push(flag, value.trim());
        }
      }
      return runBin("python3", cliArgs, workspaceDir, 600_000);
    }
    case "methods": {
      const cliArgs = [script, "methods"];
      if (typeof args.methodName === "string" && args.methodName.trim()) {
        cliArgs.push("--name", args.methodName.trim());
      }
      return runBin("python3", cliArgs, workspaceDir);
    }
    case "island_plan": {
      const islands = typeof args.islands === "number" && args.islands > 0 ? String(args.islands) : "3";
      const stagnation =
        typeof args.stagnation === "number" && args.stagnation >= 0 ? String(args.stagnation) : "0";
      const generation =
        typeof args.generation === "number" && args.generation >= 0 ? String(args.generation) : "0";
      return runBin(
        "python3",
        [script, "island-plan", "--islands", islands, "--stagnation", stagnation, "--generation", generation],
        workspaceDir,
      );
    }
    case "select_survivors": {
      const rawPath = String(args.candidatesFile ?? "").trim();
      if (!rawPath) throw new Error("crux_evolve select_survivors requires `candidatesFile`");
      const candidatesFile = resolveInWorkspace(workspaceDir, rawPath, rawPath);
      const count = typeof args.count === "number" && args.count > 0 ? String(args.count) : "4";
      const noveltyRatio =
        typeof args.noveltyRatio === "number" && args.noveltyRatio >= 0
          ? String(args.noveltyRatio)
          : "0.25";
      return runBin(
        "python3",
        [
          script,
          "select-survivors",
          "--candidates",
          candidatesFile,
          "--count",
          count,
          "--novelty-ratio",
          noveltyRatio,
        ],
        workspaceDir,
      );
    }
    case "operator_prompt": {
      const operator = String(args.operator ?? "").trim();
      const task = String(args.task ?? "").trim();
      if (!operator || !task) {
        throw new Error("crux_evolve operator_prompt requires `operator` and `task`");
      }
      const cliArgs = [script, "operator-prompt", "--operator", operator, "--task", task];
      if (typeof args.candidatesFile === "string" && args.candidatesFile.trim()) {
        cliArgs.push(
          "--parents-json",
          resolveInWorkspace(workspaceDir, args.candidatesFile.trim(), args.candidatesFile.trim()),
        );
      }
      if (typeof args.reflection === "string" && args.reflection.trim()) {
        cliArgs.push("--reflection", args.reflection.trim());
      }
      return runBin("python3", cliArgs, workspaceDir);
    }
    case "advise_blocks": {
      const rawFile = String(args.targetFile ?? "").trim();
      if (!rawFile) throw new Error("crux_evolve advise_blocks requires `targetFile`");
      const targetFile = resolveInWorkspace(workspaceDir, rawFile, rawFile);
      return runBin("python3", [script, "advise-blocks", "--file", targetFile], workspaceDir);
    }
    case "tune_params": {
      const rawFile = String(args.targetFile ?? "").trim();
      if (!rawFile) throw new Error("crux_evolve tune_params requires `targetFile`");
      const targetFile = resolveInWorkspace(workspaceDir, rawFile, rawFile);
      const cliArgs = [script, "tune-params", "--candidate", targetFile];
      if (typeof args.evalCmd === "string" && args.evalCmd.trim()) {
        cliArgs.push("--eval-cmd", args.evalCmd.trim());
      }
      if (typeof args.symbol === "string" && args.symbol.trim()) {
        cliArgs.push("--symbol", args.symbol.trim());
      }
      if (typeof args.maxEvals === "number" && args.maxEvals > 0) {
        cliArgs.push("--max-evals", String(args.maxEvals));
      }
      if (args.apply === true) {
        cliArgs.push("--apply");
      }
      return runBin("python3", cliArgs, workspaceDir);
    }
    case "sync_views": {
      const rawState = String(args.stateFile ?? "").trim();
      if (!rawState) throw new Error("crux_evolve sync_views requires `stateFile`");
      const stateFile = resolveInWorkspace(workspaceDir, rawState, rawState);
      const runDir = resolveInWorkspace(
        workspaceDir,
        typeof args.runDir === "string" ? args.runDir : undefined,
        "work/discovery",
      );
      return runBin(
        "python3",
        [script, "sync-views", "--state-file", stateFile, "--run-dir", runDir],
        workspaceDir,
      );
    }
    default:
      throw new Error(`Unknown crux_evolve action: ${String(action)}`);
  }
}
