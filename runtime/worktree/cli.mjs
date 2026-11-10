// ../../runtime/worktree/index.ts
import { execFile as execFile2 } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir as mkdir3, readFile as readFile2, writeFile } from "node:fs/promises";
import { join as join3, resolve as resolve4 } from "node:path";
import { promisify as promisify2 } from "node:util";

// ../../runtime/worktree/git-exec-file.ts
import { spawn } from "node:child_process";
function gitOptionsForWorktree(worktreePath, options = {}) {
  return { ...options, cwd: worktreePath };
}
async function gitExecFileAsync(args, options = {}) {
  return await new Promise((resolve5, reject) => {
    const child = spawn("git", [...args], {
      cwd: options.cwd,
      env: options.env ?? process.env,
      stdio: ["pipe", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    const timer = options.timeout && options.timeout > 0 ? setTimeout(() => {
      child.kill("SIGKILL");
    }, options.timeout) : void 0;
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (err) => {
      if (timer) clearTimeout(timer);
      reject(err);
    });
    child.on("close", (code) => {
      if (timer) clearTimeout(timer);
      if (code === 0) {
        resolve5({ stdout, stderr });
        return;
      }
      const error = Object.assign(
        new Error(`git ${args.join(" ")} exited with code ${code}: ${stderr.trim() || stdout.trim()}`),
        { code: code ?? 1, stdout, stderr }
      );
      reject(error);
    });
    if (options.stdin !== void 0) {
      child.stdin.write(options.stdin);
    }
    child.stdin.end();
  });
}

// ../../runtime/worktree/crux-cli-command-name.ts
function getCruxCliCommandNameForPlatform(platform) {
  if (platform === "linux") {
    return "crux-ide";
  }
  if (platform === "win32") {
    return "crux.cmd";
  }
  return "crux";
}
function skipsLinuxCruxCliRename(isRemote) {
  return Boolean(isRemote);
}

// ../../runtime/worktree/tui-agent-config.ts
function resolveTuiAgentConfig(source) {
  return {
    ...source,
    launchCmd: source.launchCmd ?? source.detectCmd,
    expectedProcess: source.expectedProcess ?? source.detectCmd
  };
}
var TUI_AGENT_CONFIG_SOURCE = {
  claude: {
    detectCmd: "claude",
    promptInjectionMode: "argv",
    pasteNeedsTypedRequest: true,
    // Native --prefill avoids paste-after-ready races (https://github.com/ai4s-research/open-science).
    draftPromptFlag: "--prefill",
    preflightTrust: "claude",
    // Why: CLAUDE_CODE_DISABLE_TERMINAL_TITLE drops the `✳` title tui-idle waits on (#22655).
    draftPasteReadySignal: "claude-composer-prompt",
    workerStartReadsComposerMarker: true,
    // Why: Claude decodes CSI-u Ctrl+Enter on local ConPTY; CR made a remapped ctrl+enter act as Enter (#29711).
    ctrlEnterEncoding: "csi-u"
  },
  "claude-agent-teams": {
    // This launch mode uses Crux’s CLI wrapper rather than a separate agent binary.
    detectCmd: "crux",
    detectCmdAliases: ["crux-dev", "crux-ide"],
    // Crux’s always-present shim alone must not report installed Agent Teams without Claude.
    detectRequiredCommands: ["claude"],
    // Windows/WSL use Claude’s in-process fallback, not this native-pane/tmux wrapper.
    detectUnsupportedRuntimes: ["win32", "wsl"],
    launchCmd: "crux claude-teams",
    launchCmdByPlatform: {
      linux: `${getCruxCliCommandNameForPlatform("linux")} claude-teams`,
      win32: `${getCruxCliCommandNameForPlatform("win32")} claude-teams`
    },
    expectedProcess: "claude",
    promptInjectionMode: "stdin-after-start",
    pasteNeedsTypedRequest: true,
    preflightTrust: "claude",
    draftPasteReadySignal: "claude-composer-prompt",
    workerStartReadsComposerMarker: true,
    // Why: runs the same Claude binary, so Ctrl+Enter must match `claude`.
    ctrlEnterEncoding: "csi-u"
  },
  codebuddy: {
    detectCmd: "codebuddy",
    detectCmdAliases: ["cbc"],
    promptInjectionMode: "argv"
  },
  openclaude: {
    detectCmd: "openclaude",
    promptInjectionMode: "argv",
    draftPromptFlag: "--prefill"
  },
  codex: {
    detectCmd: "codex",
    promptInjectionMode: "argv",
    windowsInputRecordPasteNewline: "alt-enter",
    preflightTrust: "codex",
    draftPasteReadySignal: "codex-composer-prompt",
    draftPasteReadyTimeoutMs: 2e4,
    submitRetryDelayMs: 1200
  },
  autohand: { detectCmd: "autohand", promptInjectionMode: "stdin-after-start" },
  ante: {
    detectCmd: "ante",
    // Why: `ante --prompt` is headless (runs once and exits), so launch the bare TUI and inject after startup.
    promptInjectionMode: "stdin-after-start"
  },
  trae: {
    // Use TRAE CN’s unique traecli alias; unrelated bytedance/trae-agent also installs trae-cli.
    detectCmd: "traecli",
    promptInjectionMode: "argv",
    // Cobra’s -- stops subcommands and flags from consuming prompt text such as help/config/-….
    argvPromptSeparator: "--"
  },
  opencode: {
    detectCmd: "opencode",
    promptInjectionMode: "flag-prompt",
    // Why: opencode enables bracketed paste before its composer mounts; wait for the post-\x1b[?2004h show-cursor so paste lands.
    draftPasteReadySignal: "render-cursor-after-bracketed-paste",
    // OpenCode 2 renders input before loading its agent list; only the later agent/model row proves submit readiness.
    submitPasteReadySignal: "opencode-agent-row",
    // Two Windows ConPTY hosts enabled paste at ~4.8s and composer readiness at ~10s; the 8s default pasted blind. Signals arrived reliably (#22479).
    draftPasteReadyTimeoutMs: 2e4,
    // Why: OpenCode decodes CSI-u Ctrl+Enter without local ConPTY kitty negotiation (#25372).
    ctrlEnterEncoding: "csi-u",
    composerReadyCaptures: [
      "opencode-1-18-32-timed-boot-slow",
      "opencode-1-18-32-timed-boot-hidden-pane",
      "opencode-1-18-32-timed-first-launch",
      "opencode-cmd-2-0-21-timed-warm-server"
    ]
  },
  opencode2: {
    detectCmd: "opencode2",
    // The private server inherits this pane's hook endpoint and identity.
    launchCmd: "opencode2 --standalone",
    promptInjectionMode: "flag-prompt",
    draftPasteReadySignal: "render-cursor-after-bracketed-paste",
    submitPasteReadySignal: "opencode-agent-row",
    draftPasteReadyTimeoutMs: 2e4,
    composerReadyCaptures: [
      "opencode-2-0-18-timed-boot-hidden-pane",
      "opencode-2-0-21-timed-cold-standalone",
      "opencode-2-0-21-timed-cold-standalone-hidden-pane",
      "opencode-2-0-21-timed-natural-load-enter-dropped",
      "opencode-2-0-14-timed-cold-standalone"
    ]
  },
  "mimo-code": {
    detectCmd: "mimo",
    promptInjectionMode: "flag-prompt",
    // Mirror OpenCode’s cursor gate by parity; MiMo startup has not been separately validated.
    draftPasteReadySignal: "render-cursor-after-bracketed-paste"
  },
  pi: {
    detectCmd: "pi",
    promptInjectionMode: "argv",
    // Pi has no prefill flag; the managed extension seeds env to avoid its long startup paste race.
    draftPromptEnvVar: "CRUX_PI_PREFILL",
    // Why: Pi decodes CSI-u; Esc+CR submits after tool subprocesses reset live KKP state (#9703).
    windowsShiftEnterEncoding: "csi-u"
  },
  omp: {
    detectCmd: "omp",
    promptInjectionMode: "argv",
    draftPromptEnvVar: "CRUX_OMP_PREFILL",
    // OMP embeds Pi’s CSI-u reader; preserve newline encoding after live Kitty state resets.
    windowsShiftEnterEncoding: "csi-u"
  },
  "prime-agent": {
    detectCmd: "prime-agent",
    promptInjectionMode: "argv",
    // -- forces all later arguments to be messages instead of Prime Agent subcommands/flags.
    argvPromptSeparator: "--",
    // Prime Agent embeds Pi’s CSI-u reader.
    windowsShiftEnterEncoding: "csi-u"
  },
  qoder: {
    detectCmd: "qodercli",
    // The documented `qoder` dispatcher still launches the legacy CLI binary.
    detectCmdAliases: ["qoder"],
    promptInjectionMode: "flag-prompt-interactive",
    preflightTrust: "qoder"
  },
  "qoder-cn": {
    detectCmd: "qoderclicn",
    detectCmdAliases: ["qodercn"],
    promptInjectionMode: "flag-prompt-interactive",
    preflightTrust: "qoder-cn"
  },
  gemini: {
    detectCmd: "gemini",
    promptInjectionMode: "flag-prompt-interactive"
  },
  antigravity: {
    detectCmd: "agy",
    promptInjectionMode: "flag-prompt-interactive",
    // Antigravity trust is exact-path, so every child workspace can show a menu that consumes paste; pre-write trust (agent-trust-presets.ts).
    preflightTrust: "antigravity",
    // The shell's own 2004h armed the quiet window, so a slow agy start got the paste in cooked mode (#18088).
    draftPasteReadySignal: "antigravity-composer-prompt",
    draftPasteReadyTimeoutMs: 2e4,
    // agy 1.2.x expands collapsed multiline pastes over seconds; byte ingest finishing does not prove submit readiness.
    submitLineSettleMsPerLine: 45
  },
  aider: {
    detectCmd: "aider",
    promptInjectionMode: "stdin-after-start"
  },
  goose: {
    detectCmd: "goose",
    promptInjectionMode: "stdin-after-start"
  },
  amp: {
    detectCmd: "amp",
    promptInjectionMode: "stdin-after-start"
  },
  kilo: {
    detectCmd: "kilo",
    promptInjectionMode: "stdin-after-start"
  },
  kiro: {
    // The installer ships kiro-cli; preserve kiro as the stored preference ID.
    detectCmd: "kiro-cli",
    // Kiro trust flags belong to chat, not the top-level command.
    launchCmd: "kiro-cli chat --tui",
    promptInjectionMode: "stdin-after-start"
  },
  crush: {
    detectCmd: "crush",
    promptInjectionMode: "stdin-after-start"
  },
  aug: {
    // The package installs auggie; preserve aug as the stored preference ID.
    detectCmd: "auggie",
    promptInjectionMode: "stdin-after-start"
  },
  cline: {
    detectCmd: "cline",
    promptInjectionMode: "stdin-after-start"
  },
  freebuff: {
    detectCmd: "freebuff",
    promptInjectionMode: "stdin-after-start"
  },
  codebuff: {
    detectCmd: "codebuff",
    promptInjectionMode: "stdin-after-start"
  },
  "command-code": {
    // Avoid cmd alias detection colliding with Windows cmd.exe.
    detectCmd: "command-code",
    // Why: `--trust` skips the first-run trust prompt so it doesn't consume the task text.
    launchCmd: "command-code --trust",
    promptInjectionMode: "argv"
  },
  continue: {
    // Use the actual cn binary; continue resolves to a shell keyword.
    detectCmd: "cn",
    promptInjectionMode: "stdin-after-start"
  },
  cursor: {
    detectCmd: "cursor-agent",
    promptInjectionMode: "argv",
    // Why: first-launch trust menu swallows the bracketed paste; pre-write the .workspace-trusted marker so it skips (agent-trust-presets.ts).
    preflightTrust: "cursor"
  },
  droid: {
    detectCmd: "droid",
    promptInjectionMode: "argv",
    // Why: Droid decodes CSI-u on Windows; the legacy Esc+CR fallback reads as Enter and submits instead of newline.
    windowsShiftEnterEncoding: "csi-u",
    ctrlEnterEncoding: "csi-u"
  },
  kimi: {
    preflightTrust: "kimi",
    // The kimi launcher runs as kimi-code; recognize the alias for reuse and dispatch --inject.
    detectCmd: "kimi",
    detectCmdAliases: ["kimi-code"],
    promptInjectionMode: "stdin-after-start"
  },
  "mistral-vibe": {
    // Installers expose vibe; keep mistral-vibe for wrapped installs.
    detectCmd: "vibe",
    detectCmdAliases: ["mistral-vibe"],
    promptInjectionMode: "stdin-after-start"
  },
  "qwen-code": {
    detectCmd: "qwen",
    promptInjectionMode: "stdin-after-start",
    // Qwen 0.24.7 drops Enter for 500ms after paste on Windows/Node <20; delayed retry is harmless if the first submit landed.
    submitRetryDelayMs: 1200
  },
  rovo: {
    // Rovo is an acli subcommand; passing an instruction there would run one-shot.
    detectCmd: "acli",
    launchCmd: "acli rovodev run",
    promptInjectionMode: "stdin-after-start"
  },
  hermes: {
    detectCmd: "hermes",
    // Bare hermes opens the classic REPL; --tui selects the hosted full-screen interface.
    launchCmd: "hermes --tui",
    // Why: Hermes delivers the prompt via its startup-query contract, submitting only after the composer is ready.
    promptInjectionMode: "hermes-query"
  },
  openclaw: {
    detectCmd: "openclaw",
    promptInjectionMode: "stdin-after-start"
  },
  copilot: {
    detectCmd: "copilot",
    // Why: `--prompt` exits on completion (kills the hosted session); `-i/--interactive` keeps it interactive.
    promptInjectionMode: "flag-interactive",
    // Why: first-launch trust menu swallows the bracketed paste; pre-write trust so it skips (see agent-trust-presets.ts).
    preflightTrust: "copilot",
    draftPasteReadySignal: "copilot-composer-prompt"
  },
  grok: {
    detectCmd: "grok",
    // Why: argv (grok takes a positional prompt) so multi-line/special-char text isn't mangled as raw PTY keystrokes.
    promptInjectionMode: "argv",
    // Why: separator so prompts like `help`/`--version` aren't parsed as Grok CLI syntax.
    argvPromptSeparator: "--",
    // Grok’s shimmering logo never satisfies render quiet; its composer glyph arrives around 0.6s instead of the 8s timeout.
    draftPasteReadySignal: "grok-composer-prompt",
    ctrlEnterEncoding: "csi-u"
  },
  muse: {
    detectCmd: "muse",
    launchCmd: "muse --trust-workspace",
    // Muse 1.3 treats subcommand-shaped prompts as commands even after `--`.
    promptInjectionMode: "stdin-after-start"
  },
  dsh: {
    detectCmd: "dsh-tui",
    detectCmdAliases: ["dst"],
    detectRequiredCommands: ["dsh"],
    // A first bare launch opens the session browser instead of the composer.
    launchCmd: "dsh-tui .",
    expectedProcess: "dsh",
    promptInjectionMode: "stdin-after-start",
    // The whale intro keeps repainting behind the ready composer.
    draftPasteReadySignal: "dsh-composer-prompt",
    // Why: dsh-tui 0.17's launchpad refuses Enter, keeping the draft, until its session opens (1-24 s).
    submitRetryDelayMs: 1e3,
    submitRetryBudgetMs: 3e4
  },
  zcode: {
    detectCmd: "zcode",
    // ZCode sets process.title to zcode-cli; matching only its zcode launch name would reject dispatch as no_agent_detected.
    expectedProcess: "zcode-cli",
    // ZCode treats positional text as subcommands and -p is headless; inject into the running TUI.
    promptInjectionMode: "stdin-after-start",
    // Its banner animates indefinitely; wait for the input box corner instead of render quiet.
    draftPasteReadySignal: "zcode-composer-prompt",
    composerReadyCaptures: ["zcode-composer-ready"]
  },
  // Why: stdin-after-start's follow-up wrote before Devin's input loop existed (#26302); `devin -- <prompt>` submits reliably.
  // prettier-ignore
  devin: { detectCmd: "devin", promptInjectionMode: "argv", argvPromptSeparator: "--" },
  // prettier-ignore
  jcode: { detectCmd: "jcode", launchCmd: "jcode", expectedProcess: "jcode", promptInjectionMode: "stdin-after-start" }
};
var TUI_AGENT_CONFIG = Object.fromEntries(
  Object.entries(TUI_AGENT_CONFIG_SOURCE).map(([agent, source]) => [
    agent,
    resolveTuiAgentConfig(source)
  ])
);
function isTuiAgent(value) {
  return typeof value === "string" && Object.prototype.hasOwnProperty.call(TUI_AGENT_CONFIG, value);
}
function getTuiAgentDetectCommands(config) {
  return [config.detectCmd, ...config.detectCmdAliases ?? []];
}
function getTuiAgentLaunchCommand(config, platform, opts) {
  if (platform === "linux" && skipsLinuxCruxCliRename(opts?.isRemote)) {
    return config.launchCmd;
  }
  return config.launchCmdByPlatform?.[platform] ?? config.launchCmd;
}

// ../../runtime/worktree/tui-agent-detection-commands.ts
var KNOWN_TUI_AGENT_DETECTION_COMMANDS = buildTuiAgentDetectionCommands();
function buildTuiAgentDetectionCommands() {
  return Object.entries(TUI_AGENT_CONFIG).flatMap(
    ([id, config]) => getTuiAgentDetectCommands(config).map(
      (cmd) => buildTuiAgentDetectionCommand(id, cmd, config)
    )
  );
}
function buildTuiAgentDetectionCommand(id, cmd, config) {
  return {
    id,
    cmd,
    ...config.detectRequiredCommands?.length ? { requiredCommands: config.detectRequiredCommands } : {},
    ...config.detectUnsupportedRuntimes?.length ? { unsupportedRuntimes: config.detectUnsupportedRuntimes } : {}
  };
}
function getTuiAgentDetectionProbeCommands(commands, runtime) {
  return [
    ...new Set(
      commands.flatMap(
        (command) => isDetectionUnsupportedInRuntime(command, runtime) ? [] : [command.cmd, ...command.requiredCommands ?? []]
      )
    )
  ];
}
function resolveDetectedTuiAgentIds(commands, foundCommands, runtime) {
  const detected = commands.filter(
    (command) => !isDetectionUnsupportedInRuntime(command, runtime) && foundCommands.has(command.cmd) && (command.requiredCommands ?? []).every((required) => foundCommands.has(required))
  ).map(({ id }) => id);
  return [...new Set(detected)];
}
function isDetectionUnsupportedInRuntime(command, runtime) {
  return command.unsupportedRuntimes?.includes(runtime) === true;
}

// ../../runtime/worktree/tui-agent-display-names.ts
var TUI_AGENT_DISPLAY_NAMES = {
  claude: "Claude",
  "claude-agent-teams": "Claude Agent Teams",
  codebuddy: "CodeBuddy",
  openclaude: "OpenClaude",
  codex: "Codex",
  devin: "Devin",
  ante: "Ante",
  trae: "Trae",
  muse: "Muse",
  dsh: "DeepSeek Harness",
  zcode: "ZCode",
  autohand: "Autohand Code",
  opencode: "OpenCode",
  opencode2: "OpenCode 2",
  "mimo-code": "MiMo Code",
  pi: "Pi",
  omp: "OMP",
  "prime-agent": "Prime Agent",
  qoder: "Qoder CLI",
  "qoder-cn": "Qoder CLI China",
  gemini: "Gemini",
  antigravity: "Antigravity",
  aider: "Aider",
  goose: "Goose",
  amp: "Amp",
  kilo: "Kilocode",
  kiro: "Kiro",
  crush: "Charm",
  aug: "Auggie",
  cline: "Cline",
  codebuff: "Codebuff",
  freebuff: "Freebuff",
  "command-code": "Command Code",
  continue: "Continue",
  cursor: "Cursor",
  droid: "Droid",
  kimi: "Kimi",
  "mistral-vibe": "Mistral Vibe",
  "qwen-code": "Qwen Code",
  rovo: "Rovo Dev",
  hermes: "Hermes",
  openclaw: "OpenClaw",
  copilot: "GitHub Copilot",
  grok: "Grok",
  jcode: "Jcode"
};
var ALL_TUI_AGENTS = Object.keys(TUI_AGENT_DISPLAY_NAMES);
function tuiAgentDisplayName(agent) {
  return Object.entries(TUI_AGENT_DISPLAY_NAMES).find(([id]) => id === agent)?.[1] ?? null;
}

// ../../runtime/worktree/tui-agent-selection.ts
var TUI_AGENT_AUTO_PICK_ORDER = [
  "claude",
  "claude-agent-teams",
  "openclaude",
  "codex",
  "grok",
  "copilot",
  "opencode2",
  "opencode",
  "mimo-code",
  "ante",
  "trae",
  "muse",
  "dsh",
  "qoder",
  "qoder-cn",
  "zcode",
  "pi",
  "omp",
  "prime-agent",
  "gemini",
  "antigravity",
  "aider",
  "goose",
  "amp",
  "kilo",
  "kiro",
  "crush",
  "aug",
  "autohand",
  "cline",
  "codebuff",
  "freebuff",
  "command-code",
  "continue",
  "cursor",
  "droid",
  "kimi",
  "mistral-vibe",
  "qwen-code",
  "rovo",
  "hermes",
  "devin",
  "openclaw",
  "codebuddy",
  "jcode"
];
function pickTuiAgent(preferred, detected, disabled, chosenUsable) {
  if (preferred === "blank") {
    return null;
  }
  const disabledSet = new Set(normalizeDisabledTuiAgents(disabled));
  const detectedSet = detected instanceof Set ? detected : new Set(detected);
  if (preferred && (detectedSet.has(preferred) || chosenUsable?.(preferred)) && !disabledSet.has(preferred)) {
    return preferred;
  }
  for (const agent of TUI_AGENT_AUTO_PICK_ORDER) {
    if (detectedSet.has(agent) && !disabledSet.has(agent)) {
      return agent;
    }
  }
  return null;
}
function normalizeDisabledTuiAgents(value) {
  if (!Array.isArray(value)) {
    return [];
  }
  const seen = /* @__PURE__ */ new Set();
  for (const item of value) {
    if (isTuiAgent(item)) {
      seen.add(item);
    }
  }
  return [...seen];
}

// ../../runtime/worktree/worktree-include-copy-budget.ts
import { lstat, readdir } from "node:fs/promises";
import { join } from "node:path";
var DEFAULT_WORKTREE_COPY_BUDGET = {
  maxBytes: 2 * 1024 * 1024 * 1024,
  maxEntries: 5e4
};
var WORKTREE_COPY_SIZING_HEADROOM = 5;
async function measureCopySize(source, remainingBytes, remainingEntries, remainingWalk) {
  let bytes = 0;
  let entries = 0;
  const pending = [source];
  while (pending.length > 0) {
    const current = pending.pop();
    let stats;
    try {
      stats = await lstat(current);
    } catch {
      continue;
    }
    entries += 1;
    if (entries > Math.min(remainingEntries, remainingWalk)) {
      const reason = remainingWalk < remainingEntries ? "sizing" : "entries";
      return { verdict: { withinBudget: false, reason }, walked: entries };
    }
    if (stats.isSymbolicLink()) {
      continue;
    }
    if (stats.isDirectory()) {
      try {
        for (const name of await readdir(current)) {
          pending.push(join(current, name));
        }
      } catch {
      }
      continue;
    }
    bytes += stats.size;
    if (bytes > remainingBytes) {
      return { verdict: { withinBudget: false, reason: "bytes" }, walked: entries };
    }
  }
  return { verdict: { withinBudget: true, bytes, entries }, walked: entries };
}
function createWorktreeCopyBudgetTracker(budget = DEFAULT_WORKTREE_COPY_BUDGET) {
  let remainingBytes = budget.maxBytes;
  let remainingEntries = budget.maxEntries;
  let remainingWalk = budget.maxEntries * WORKTREE_COPY_SIZING_HEADROOM;
  return {
    admit: async (source, { bytesAreCopied = true } = {}) => {
      if (remainingWalk <= 0) {
        return { withinBudget: false, reason: "sizing" };
      }
      const { verdict, walked } = await measureCopySize(
        source,
        bytesAreCopied ? remainingBytes : Number.POSITIVE_INFINITY,
        remainingEntries,
        remainingWalk
      );
      remainingWalk -= walked;
      if (verdict.withinBudget) {
        if (bytesAreCopied) {
          remainingBytes -= verdict.bytes;
        }
        remainingEntries -= verdict.entries;
      }
      return verdict;
    },
    chargeBytes: (bytes) => {
      if (bytes > remainingBytes) {
        return false;
      }
      remainingBytes -= bytes;
      return true;
    }
  };
}
function formatByteLimit(maxBytes) {
  const gigabytes = maxBytes / (1024 * 1024 * 1024);
  if (gigabytes >= 1) {
    return `${Number(gigabytes.toFixed(1))} GB`;
  }
  return `${Math.max(1, Math.round(maxBytes / (1024 * 1024)))} MB`;
}
var MAX_NAMED_SKIPPED_ENTRIES = 5;
function formatWorktreeIncludeCopyWarning(skipped, budget = DEFAULT_WORKTREE_COPY_BUDGET) {
  if (skipped.length === 0) {
    return void 0;
  }
  const nameList = (entries) => {
    const shown = entries.slice(0, MAX_NAMED_SKIPPED_ENTRIES);
    const names = shown.map((entry) => `"${entry.path}"`).join(", ");
    const rest = entries.length - shown.length;
    return rest > 0 ? `${names} and ${rest.toLocaleString("en-US")} more` : names;
  };
  const describe = (entries) => {
    const subject = entries.length === 1 ? "entry" : "entries";
    const verb = entries.length === 1 ? "was" : "were";
    return `.worktreeinclude ${subject} ${nameList(entries)} ${verb} not copied into the new workspace`;
  };
  const pronoun = (count) => count === 1 ? "it" : "them";
  const overBudget = skipped.filter((entry) => entry.reason !== "sizing");
  const unsized = skipped.filter((entry) => entry.reason === "sizing");
  const sentences = [];
  if (overBudget.length > 0) {
    sentences.push(
      `${describe(overBudget)}: copying ${pronoun(overBudget.length)} would exceed the ${formatByteLimit(budget.maxBytes)} / ${budget.maxEntries.toLocaleString("en-US")} file limit that keeps workspace creation responsive.`
    );
  }
  const partial = skipped.filter((entry) => entry.mayBePartial);
  if (unsized.length > 0) {
    sentences.push(
      `${describe(unsized)}: earlier entries used up the budget for measuring what to copy.`
    );
  }
  if (partial.length > 0) {
    sentences.push(
      `${nameList(partial)} may hold a partial copy from the interrupted attempt \u2014 check ${pronoun(partial.length)} before reusing this workspace.`
    );
  }
  sentences.push(
    `Copy ${pronoun(skipped.length)} in manually if this workspace needs ${pronoun(skipped.length)}.`
  );
  return sentences.join(" ");
}

// ../../runtime/worktree/worktree-include-file.ts
import { lstat as lstat2, readFile } from "node:fs/promises";
import { isAbsolute, join as join2 } from "node:path";

// ../../runtime/worktree/nul-delimited-fields.ts
function* iterateNulDelimitedFields(value) {
  let start = 0;
  while (start <= value.length) {
    const end = value.indexOf("\0", start);
    if (end === -1) {
      yield value.slice(start);
      return;
    }
    yield value.slice(start, end);
    start = end + 1;
  }
}

// ../../runtime/worktree/git-check-ignore-stdio.ts
var GIT_CHECK_IGNORE_TIMEOUT_MS = 15e3;
var GIT_CHECK_IGNORE_STDIN_CHUNK_BYTES = 1024 * 1024;
var GIT_CHECK_IGNORE_STDIN_ARGS = [
  "-c",
  "core.quotePath=false",
  "check-ignore",
  "-z",
  "--stdin"
];
function encodeGitCheckIgnorePaths(paths) {
  return `${paths.join("\0")}\0`;
}
function splitGitCheckIgnorePathsByStdinBytes(paths, maxBytes = GIT_CHECK_IGNORE_STDIN_CHUNK_BYTES) {
  const encoder = new TextEncoder();
  const chunks = [];
  let chunk = [];
  let chunkBytes = 0;
  for (const path of paths) {
    const pathBytes = encoder.encode(path).byteLength + 1;
    if (chunk.length > 0 && chunkBytes + pathBytes > maxBytes) {
      chunks.push(chunk);
      chunk = [];
      chunkBytes = 0;
    }
    chunk.push(path);
    chunkBytes += pathBytes;
  }
  if (chunk.length > 0) {
    chunks.push(chunk);
  }
  return chunks;
}
function parseGitCheckIgnorePaths(stdout) {
  const paths = [];
  for (const path of iterateNulDelimitedFields(stdout)) {
    if (path) {
      paths.push(path);
    }
  }
  return paths;
}

// ../../runtime/worktree/check-ignored-paths.ts
async function runCheckIgnoredPaths(worktreePath, relativePaths, options) {
  try {
    const { stdout } = await gitExecFileAsync([...GIT_CHECK_IGNORE_STDIN_ARGS], {
      ...gitOptionsForWorktree(worktreePath, options),
      stdin: encodeGitCheckIgnorePaths(relativePaths),
      timeout: GIT_CHECK_IGNORE_TIMEOUT_MS
    });
    return parseGitCheckIgnorePaths(stdout);
  } catch (error) {
    const gitError = error;
    if (gitError.code === 1) {
      return parseGitCheckIgnorePaths(gitError.stdout ?? "");
    }
    throw error;
  }
}
async function checkIgnoredPaths(worktreePath, relativePaths, options = {}) {
  if (relativePaths.length === 0) {
    return [];
  }
  const ignored = /* @__PURE__ */ new Set();
  for (const chunk of splitGitCheckIgnorePathsByStdinBytes(relativePaths)) {
    for (const ignoredPath of await runCheckIgnoredPaths(worktreePath, chunk, options)) {
      ignored.add(ignoredPath);
    }
  }
  return Array.from(ignored);
}

// ../../runtime/worktree/map-with-concurrency.ts
function mapWithConcurrency(items, limit, fn) {
  const workerCount = concurrencyWorkerCount(limit, items.length);
  if (items.length <= workerCount) {
    return Promise.all(items.map(fn));
  }
  const results = [];
  let nextIndex = 0;
  return Promise.all(
    Array.from({ length: workerCount }, async () => {
      while (nextIndex < items.length) {
        const index = nextIndex;
        nextIndex += 1;
        results[index] = await fn(items[index], index);
      }
    })
  ).then(() => results);
}
function concurrencyWorkerCount(limit, itemCount) {
  const normalizedLimit = limit === Number.POSITIVE_INFINITY ? itemCount : Number.isFinite(limit) ? Math.floor(limit) : 1;
  return Math.max(1, Math.min(normalizedLimit, itemCount));
}

// ../../runtime/worktree/worktree-include-file.ts
var WORKTREE_INCLUDE_FILE = ".worktreeinclude";
var WORKTREE_INCLUDE_MAX_FILE_BYTES = 256 * 1024;
var WORKTREE_INCLUDE_MAX_ENTRIES = 1e3;
var WORKTREE_INCLUDE_PATH_STAT_CONCURRENCY = 8;
function parseWorktreeIncludeFile(content) {
  const seen = /* @__PURE__ */ new Set();
  const entries = [];
  for (const rawLine of content.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) {
      continue;
    }
    const normalized = line.replace(/\\/g, "/").replace(/^\.\//, "").replace(/\/+$/, "");
    if (!normalized || seen.has(normalized)) {
      continue;
    }
    seen.add(normalized);
    entries.push(normalized);
  }
  return entries;
}
function isUnsupportedPattern(entry) {
  return entry.startsWith("!") || entry.includes("*") || entry.includes("?");
}
function isSafeIncludePath(relativePath) {
  if (!relativePath || isAbsolute(relativePath)) {
    return false;
  }
  const segments = relativePath.split("/");
  return !segments.includes("..") && !segments.includes("") && segments[0] !== ".git";
}
async function readWorktreeIncludeFile(repoPath) {
  const includePath = join2(repoPath, WORKTREE_INCLUDE_FILE);
  try {
    const stats = await lstat2(includePath);
    if (!stats.isFile() || stats.size > WORKTREE_INCLUDE_MAX_FILE_BYTES) {
      return null;
    }
    return await readFile(includePath, "utf8");
  } catch {
    return null;
  }
}
async function resolveWorktreeIncludePaths(repoPath, options = {}) {
  try {
    const content = await readWorktreeIncludeFile(repoPath);
    if (content === null) {
      return [];
    }
    const candidates = [];
    for (const entry of parseWorktreeIncludeFile(content)) {
      if (candidates.length >= WORKTREE_INCLUDE_MAX_ENTRIES) {
        console.warn(
          `[worktree-include] ${WORKTREE_INCLUDE_FILE} lists more than ${WORKTREE_INCLUDE_MAX_ENTRIES} entries; ignoring the rest`
        );
        break;
      }
      if (isUnsupportedPattern(entry)) {
        console.warn(
          `[worktree-include] Skipping unsupported ${WORKTREE_INCLUDE_FILE} pattern "${entry}" (only literal files and directories are supported)`
        );
        continue;
      }
      if (!isSafeIncludePath(entry)) {
        console.warn(`[worktree-include] Skipping unsafe ${WORKTREE_INCLUDE_FILE} path "${entry}"`);
        continue;
      }
      candidates.push(entry);
    }
    if (candidates.length === 0) {
      return [];
    }
    const existence = await mapWithConcurrency(
      candidates,
      WORKTREE_INCLUDE_PATH_STAT_CONCURRENCY,
      async (relativePath) => {
        try {
          await lstat2(join2(repoPath, relativePath));
          return relativePath;
        } catch {
          return null;
        }
      }
    );
    const existing = existence.filter(
      (relativePath) => relativePath !== null
    );
    if (existing.length === 0) {
      return [];
    }
    const ignored = new Set(await checkIgnoredPaths(repoPath, existing, options));
    return existing.filter((relativePath) => ignored.has(relativePath)).sort();
  } catch (error) {
    console.warn(`[worktree-include] Failed to resolve ${WORKTREE_INCLUDE_FILE} paths:`, error);
    return [];
  }
}

// ../../runtime/worktree/worktree-lineage.ts
async function persistWorktreeCreationBase(worktreePath, branch, effectiveBase, options = {}) {
  const configKey = `branch.${branch}.base`;
  try {
    await gitExecFileAsync(["config", "--local", "--replace-all", configKey, effectiveBase], {
      ...gitOptionsForWorktree(worktreePath, options)
    });
  } catch (error) {
    console.warn(`addWorktree: failed to set ${configKey} for ${worktreePath}`, error);
    try {
      await gitExecFileAsync(["config", "--local", "--unset-all", configKey], {
        ...gitOptionsForWorktree(worktreePath, options)
      });
    } catch (unsetError) {
      console.warn(
        `addWorktree: failed to unset stale ${configKey} for ${worktreePath}`,
        unsetError
      );
    }
  }
}
async function configurePushAutoSetupRemote(worktreePath, options = {}) {
  try {
    let alreadySet = false;
    try {
      await gitExecFileAsync(["config", "--get", "push.autoSetupRemote"], {
        ...gitOptionsForWorktree(worktreePath, options)
      });
      alreadySet = true;
    } catch (readError) {
      const code = readError?.code;
      if (code !== 1) {
        throw readError;
      }
    }
    if (!alreadySet) {
      await gitExecFileAsync(["config", "--local", "push.autoSetupRemote", "true"], {
        ...gitOptionsForWorktree(worktreePath, options)
      });
    }
  } catch (error) {
    console.warn(`addWorktree: failed to set push.autoSetupRemote for ${worktreePath}`, error);
  }
}

// ../../runtime/worktree/worktree-symlinks.ts
import { symlink, mkdir as mkdir2, stat as stat2, lstat as lstat3, unlink, cp, realpath } from "node:fs/promises";
import { dirname as dirname2, resolve as resolve3 } from "node:path";

// ../../runtime/worktree/worktree-apfs-clone.ts
import { execFile } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, stat, rm, link, rmdir, chmod } from "node:fs/promises";
import { dirname, resolve, sep } from "node:path";
import { promisify } from "node:util";
var execFileAsync = promisify(execFile);
var APFS_FILESYSTEM_PROBE_TIMEOUT_MS = 5e3;
var defaultApfsCloneDeps = {
  execFileAsync,
  randomUUID
};
var ApfsCloneUnavailableError = class extends Error {
  constructor(message) {
    super(message);
    this.name = "ApfsCloneUnavailableError";
  }
};
var WorktreeLinkedPathTargetExistsError = class extends Error {
  constructor(target) {
    super(`Worktree linked path target already exists: ${target}`);
    this.name = "WorktreeLinkedPathTargetExistsError";
  }
};
function isAlreadyExistsError(error) {
  return error?.code === "EEXIST";
}
async function getDarwinFilesystemInfo(path, deps) {
  const { stdout: dfOutput } = await deps.execFileAsync("/bin/df", ["-P", path], {
    timeout: APFS_FILESYSTEM_PROBE_TIMEOUT_MS
  });
  const device = dfOutput.trim().split(/\r?\n/)[1]?.trim().split(/\s+/)[0];
  if (!device) {
    throw new Error(`Could not resolve filesystem device for ${path}`);
  }
  const { stdout: diskutilOutput } = await deps.execFileAsync(
    "/usr/sbin/diskutil",
    ["info", "-plist", device],
    { timeout: APFS_FILESYSTEM_PROBE_TIMEOUT_MS }
  );
  const filesystemNameMatch = /<key>FilesystemName<\/key>\s*<string>([^<]+)<\/string>/u.exec(
    diskutilOutput
  );
  return {
    device,
    filesystemName: filesystemNameMatch?.[1] ?? ""
  };
}
async function getCachedDarwinFilesystemInfo(path, deps, cache) {
  const deviceId = (await stat(path)).dev;
  const cached = cache.get(deviceId);
  if (cached) {
    return cached;
  }
  const pending = getDarwinFilesystemInfo(path, deps);
  cache.set(deviceId, pending);
  return pending;
}
async function isSameApfsVolume(source, targetDirectory, deps, cache) {
  const [sourceInfo, targetInfo] = await Promise.all([
    getCachedDarwinFilesystemInfo(source, deps, cache),
    getCachedDarwinFilesystemInfo(targetDirectory, deps, cache)
  ]);
  return sourceInfo.device === targetInfo.device && sourceInfo.filesystemName === "APFS" && targetInfo.filesystemName === "APFS";
}
async function assertSameApfsVolume(source, target, deps, cache) {
  if (!await isSameApfsVolume(source, dirname(target), deps, cache)) {
    throw new ApfsCloneUnavailableError(
      "APFS clone-copy requires source and target on the same APFS volume"
    );
  }
}
async function canCloneWithApfs(source, targetDirectory, deps = defaultApfsCloneDeps, filesystemCache = /* @__PURE__ */ new Map()) {
  try {
    return await isSameApfsVolume(source, targetDirectory, deps, filesystemCache);
  } catch {
    return false;
  }
}
async function cloneFileWithApfs(source, target, deps) {
  const tempTarget = resolve(dirname(target), `.crux-apfs-clone-${deps.randomUUID()}`);
  try {
    await deps.execFileAsync("/bin/cp", ["-c", source, tempTarget]);
    try {
      await link(tempTarget, target);
    } catch (error) {
      if (isAlreadyExistsError(error)) {
        throw new WorktreeLinkedPathTargetExistsError(target);
      }
      throw error;
    }
  } finally {
    await rm(tempTarget, { force: true }).catch(() => void 0);
  }
}
async function cloneDirectoryWithApfs(source, target, deps) {
  const sourceMode = (await stat(source)).mode & 511;
  try {
    await mkdir(target);
  } catch (error) {
    if (isAlreadyExistsError(error)) {
      throw new WorktreeLinkedPathTargetExistsError(target);
    }
    throw error;
  }
  try {
    await deps.execFileAsync("/bin/cp", ["-n", "-c", "-R", `${source}${sep}.`, target]);
    await chmod(target, sourceMode);
  } catch (error) {
    await rmdir(target).catch(() => void 0);
    throw error;
  }
}
async function cloneWorktreePathWithApfs(source, target, sourceIsDirectory, deps = defaultApfsCloneDeps, filesystemCache = /* @__PURE__ */ new Map()) {
  await mkdir(dirname(target), { recursive: true });
  await assertSameApfsVolume(source, target, deps, filesystemCache);
  await (sourceIsDirectory ? cloneDirectoryWithApfs(source, target, deps) : cloneFileWithApfs(source, target, deps));
}

// ../../runtime/worktree/worktree-symlink-detection.ts
import { resolve as resolve2, sep as sep2 } from "node:path";
var WINDOWS_DRIVE_DESIGNATOR = /^[a-zA-Z]:/;
function getSafeRelativePath(rawPath) {
  const rel = rawPath.trim().replace(/^[\\/]+/, "");
  const segments = rel.split(/[\\/]/).filter((segment) => segment !== "" && segment !== ".");
  if (segments.length === 0 || WINDOWS_DRIVE_DESIGNATOR.test(segments[0]) || segments.includes("..")) {
    return { safe: false };
  }
  const gitRel = sep2 === "\\" ? segments.join("/") : rel.split("/").filter((segment) => segment !== "" && segment !== ".").join("/");
  return gitRel ? { safe: true, rel: gitRel } : { safe: false };
}

// ../../runtime/worktree/worktree-symlinks.ts
function worktreeSymlinkTypeCandidates(platform, sourceIsDirectory) {
  if (!sourceIsDirectory) {
    return ["file"];
  }
  return platform === "win32" ? ["junction", "dir"] : ["dir"];
}
async function symlinkWorktreePath(source, target, sourceIsDirectory, platform) {
  await mkdir2(dirname2(target), { recursive: true });
  const candidates = worktreeSymlinkTypeCandidates(platform, sourceIsDirectory);
  for (let index = 0; index < candidates.length; index++) {
    try {
      await symlink(source, target, candidates[index]);
      return;
    } catch (error) {
      if (index === candidates.length - 1) {
        throw error;
      }
    }
  }
}
async function copyWorktreePath(source, target) {
  await mkdir2(dirname2(target), { recursive: true });
  await cp(source, target, { recursive: true, force: false, errorOnExist: false });
}
var WorktreeCopyBudgetFallbackError = class extends Error {
  constructor(target) {
    super(`APFS clone failed and a real copy of "${target}" would exceed the copy budget`);
    this.name = "WorktreeCopyBudgetFallbackError";
  }
};
async function createWorktreeLinkedPath(source, copySource, target, sourceIsDirectory, sourceIsSymbolicLink, mode, options, apfsFilesystemCache, realCopyFallbackAllowed) {
  if (mode !== "share" && options.platform === "darwin" && (!sourceIsSymbolicLink || mode === "copy")) {
    try {
      const cloneWorktreePath = options.cloneWorktreePath ?? ((cloneSource, cloneTarget, cloneSourceIsDirectory) => cloneWorktreePathWithApfs(
        cloneSource,
        cloneTarget,
        cloneSourceIsDirectory,
        options.apfsCloneDeps ?? defaultApfsCloneDeps,
        apfsFilesystemCache
      ));
      await cloneWorktreePath(copySource, target, sourceIsDirectory);
      return;
    } catch (error) {
      if (error instanceof WorktreeLinkedPathTargetExistsError) {
        return;
      }
      if (!(error instanceof ApfsCloneUnavailableError)) {
        console.warn(`[worktree-symlinks] APFS clone-copy unavailable for "${target}":`, error);
        if (mode === "copy" && !realCopyFallbackAllowed()) {
          throw new WorktreeCopyBudgetFallbackError(target);
        }
      }
    }
  }
  if (mode === "copy") {
    await copyWorktreePath(copySource, target);
    return;
  }
  await symlinkWorktreePath(source, target, sourceIsDirectory, options.platform ?? process.platform);
}
async function copyIsCopyOnWrite(source, worktreePath, options, apfsFilesystemCache) {
  if (options.platform !== "darwin") {
    return false;
  }
  if (options.cloneWorktreePath) {
    return true;
  }
  return await canCloneWithApfs(
    source,
    worktreePath,
    options.apfsCloneDeps ?? defaultApfsCloneDeps,
    apfsFilesystemCache
  );
}
async function targetExists(target) {
  try {
    await lstat3(target);
    return true;
  } catch {
    return false;
  }
}
async function materializeWorktreePaths(primaryPath, worktreePath, paths, mode, options = {}) {
  const effectiveOptions = { platform: process.platform, ...options };
  const apfsFilesystemCache = /* @__PURE__ */ new Map();
  const copyBudget = createWorktreeCopyBudgetTracker(options.copyBudget);
  const skipped = [];
  for (const rawPath of paths) {
    const safePath = getSafeRelativePath(rawPath);
    if (!safePath.safe) {
      console.warn(`[worktree-symlinks] Skipping unsafe path "${rawPath}"`);
      continue;
    }
    const source = resolve3(primaryPath, safePath.rel);
    const target = resolve3(worktreePath, safePath.rel);
    let sourceIsDirectory = false;
    let sourceIsSymbolicLink = false;
    try {
      sourceIsSymbolicLink = (await lstat3(source)).isSymbolicLink();
      const s = await stat2(source);
      sourceIsDirectory = s.isDirectory();
    } catch {
      continue;
    }
    if (await targetExists(target)) {
      continue;
    }
    let copySource = source;
    let bytesAreCopied = true;
    let measuredBytes = 0;
    if (mode === "copy") {
      try {
        if (sourceIsSymbolicLink) {
          copySource = await realpath(source);
        }
        bytesAreCopied = !await copyIsCopyOnWrite(
          copySource,
          worktreePath,
          effectiveOptions,
          apfsFilesystemCache
        );
        const verdict = await copyBudget.admit(copySource, { bytesAreCopied });
        if (!verdict.withinBudget) {
          skipped.push({ path: safePath.rel, reason: verdict.reason });
          console.warn(
            `[worktree-symlinks] Skipping "${safePath.rel}": copy exceeds the worktree copy budget (${verdict.reason})`
          );
          continue;
        }
        measuredBytes = verdict.bytes;
      } catch (error) {
        console.error(`[worktree-symlinks] Failed to size "${safePath.rel}" (${source}):`, error);
        continue;
      }
    }
    try {
      await createWorktreeLinkedPath(
        source,
        copySource,
        target,
        sourceIsDirectory,
        sourceIsSymbolicLink,
        mode,
        effectiveOptions,
        apfsFilesystemCache,
        () => bytesAreCopied || copyBudget.chargeBytes(measuredBytes)
      );
    } catch (error) {
      if (error instanceof WorktreeCopyBudgetFallbackError) {
        skipped.push({
          path: safePath.rel,
          reason: "bytes",
          ...sourceIsDirectory ? { mayBePartial: true } : {}
        });
        console.warn(`[worktree-symlinks] Skipping "${safePath.rel}": ${error.message}`);
        continue;
      }
      console.error(
        `[worktree-symlinks] Failed to link "${safePath.rel}" (${source} -> ${target}):`,
        error
      );
    }
  }
  return skipped;
}
async function createWorktreeCopiedPaths(primaryPath, worktreePath, paths, options = {}) {
  return await materializeWorktreePaths(primaryPath, worktreePath, paths, "copy", options);
}
async function createWorktreeSharedPaths(primaryPath, worktreePath, paths, options = {}) {
  await materializeWorktreePaths(primaryPath, worktreePath, paths, "share", options);
}
async function removeWorktreeLinkedPaths(worktreePath, paths) {
  for (const rawPath of paths) {
    const safePath = getSafeRelativePath(rawPath);
    if (!safePath.safe) {
      continue;
    }
    const target = resolve3(worktreePath, safePath.rel);
    try {
      const s = await lstat3(target);
      if (s.isSymbolicLink()) {
        await unlink(target);
      }
    } catch (error) {
      if (error?.code !== "ENOENT") {
        console.error(`[worktree-symlinks] Failed to remove "${safePath.rel}" (${target}):`, error);
      }
    }
  }
}
async function removeWorktreeSymlinks(worktreePath, paths) {
  await removeWorktreeLinkedPaths(worktreePath, paths);
}

// ../../runtime/worktree/index.ts
var execFileAsync2 = promisify2(execFile2);
function shellQuote(value) {
  if (/^[A-Za-z0-9_./:@=-]+$/.test(value)) {
    return value;
  }
  return `'${value.replace(/'/g, `'\\''`)}'`;
}
function buildCruxAgentLaunchCommand(agent, prompt = "", opts = {}) {
  const platform = opts.platform ?? process.platform;
  const envParts = [];
  if (opts.accountDir) {
    if (agent === "claude" || agent === "claude-agent-teams" || agent === "openclaude") {
      envParts.push(`CLAUDE_CONFIG_DIR=${shellQuote(opts.accountDir)}`);
    } else if (agent === "codex") {
      envParts.push(`CODEX_HOME=${shellQuote(opts.accountDir)}`);
    }
  }
  if (!isTuiAgent(agent)) {
    const base = shellQuote(agent);
    const cmd = prompt ? `${base} ${shellQuote(prompt)}` : base;
    return envParts.length > 0 ? `${envParts.join(" ")} ${cmd}` : cmd;
  }
  const config = TUI_AGENT_CONFIG[agent];
  if (prompt && config.draftPromptEnvVar) {
    envParts.push(`${config.draftPromptEnvVar}=${shellQuote(prompt)}`);
  }
  const launchCmd = getTuiAgentLaunchCommand(config, platform, { isRemote: opts.isRemote });
  const prefix = envParts.length > 0 ? `${envParts.join(" ")} ` : "";
  if (!prompt) {
    return `${prefix}${launchCmd}`;
  }
  const qPrompt = shellQuote(prompt);
  switch (config.promptInjectionMode) {
    case "argv": {
      const sep3 = config.argvPromptSeparator ? ` ${config.argvPromptSeparator}` : "";
      return `${prefix}${launchCmd}${sep3} ${qPrompt}`;
    }
    case "flag-prompt":
    case "flag-prompt-interactive":
      return `${prefix}${launchCmd} --prompt ${qPrompt}`;
    case "flag-interactive":
      return `${prefix}${launchCmd} -i ${qPrompt}`;
    default:
      return `${prefix}${launchCmd}`;
  }
}
async function detectInstalledCruxAgents(platform = process.platform) {
  const probes = getTuiAgentDetectionProbeCommands(KNOWN_TUI_AGENT_DETECTION_COMMANDS, platform);
  const found = /* @__PURE__ */ new Set();
  await Promise.all(
    probes.map(async (cmd) => {
      try {
        await execFileAsync2("which", [cmd]);
        found.add(cmd);
      } catch {
      }
    })
  );
  const detectedIds = resolveDetectedTuiAgentIds(
    KNOWN_TUI_AGENT_DETECTION_COMMANDS,
    found,
    platform
  );
  const detectedSet = new Set(detectedIds);
  const preferredDefault = pickTuiAgent(null, detectedIds);
  const catalog = Object.keys(TUI_AGENT_CONFIG).map((id) => {
    const cfg = TUI_AGENT_CONFIG[id];
    return {
      id,
      displayName: TUI_AGENT_DISPLAY_NAMES[id],
      detectCmd: cfg.detectCmd,
      launchCmd: getTuiAgentLaunchCommand(cfg, platform),
      promptInjectionMode: cfg.promptInjectionMode,
      installed: detectedSet.has(id)
    };
  });
  return { detectedIds, preferredDefault, catalog };
}
async function ensureGitRepository(repoRoot) {
  await mkdir3(repoRoot, { recursive: true });
  try {
    await gitExecFileAsync(["rev-parse", "--is-inside-work-tree"], { cwd: repoRoot });
  } catch {
    await gitExecFileAsync(["init", "-b", "main"], { cwd: repoRoot });
  }
  try {
    await gitExecFileAsync(["rev-parse", "--verify", "HEAD"], { cwd: repoRoot });
  } catch {
    await gitExecFileAsync(["commit", "--allow-empty", "-m", "chore: initialize repository"], {
      cwd: repoRoot
    });
  }
  try {
    const { stdout } = await gitExecFileAsync(["symbolic-ref", "--short", "HEAD"], {
      cwd: repoRoot
    });
    return stdout.trim() || "HEAD";
  } catch {
    return "HEAD";
  }
}
function registryPath(repoRoot) {
  return join3(repoRoot, ".crux", "crux-worktrees.json");
}
async function loadRegistry(repoRoot) {
  const file = registryPath(repoRoot);
  if (!existsSync(file)) {
    return {};
  }
  const raw = JSON.parse(await readFile2(file, "utf8"));
  return raw.tasks ?? {};
}
async function saveRegistry(repoRoot, tasks) {
  const file = registryPath(repoRoot);
  await mkdir3(join3(repoRoot, ".crux"), { recursive: true });
  await writeFile(
    file,
    `${JSON.stringify({ schemaVersion: 1, tasks }, null, 2)}
`,
    "utf8"
  );
}
var DEFAULT_SHARED_DIRS = ["tools", "MEMORY.md", ".openscience/memory"];
async function spawnCruxWorktreeTask(args) {
  const repoRoot = resolve4(args.repoRoot);
  const taskId = args.taskId.trim();
  if (!taskId || taskId.includes("/") || taskId.includes("..")) {
    throw new Error(`Invalid taskId: ${args.taskId}`);
  }
  const detectedBase = await ensureGitRepository(repoRoot);
  const baseBranch = args.baseBranch || detectedBase;
  const branch = `crux/${taskId}`;
  const worktreePath = join3(repoRoot, ".worktrees", taskId);
  await mkdir3(join3(repoRoot, ".worktrees"), { recursive: true });
  if (!existsSync(worktreePath)) {
    let branchExists = false;
    try {
      await gitExecFileAsync(["show-ref", "--verify", `refs/heads/${branch}`], { cwd: repoRoot });
      branchExists = true;
    } catch {
    }
    if (branchExists) {
      await gitExecFileAsync(["worktree", "add", worktreePath, branch], { cwd: repoRoot });
    } else {
      await gitExecFileAsync(["worktree", "add", "-b", branch, worktreePath, baseBranch], {
        cwd: repoRoot
      });
    }
  }
  await persistWorktreeCreationBase(worktreePath, branch, baseBranch);
  await configurePushAutoSetupRemote(worktreePath);
  const includePaths = await resolveWorktreeIncludePaths(repoRoot);
  const skipped = includePaths.length > 0 ? await createWorktreeCopiedPaths(repoRoot, worktreePath, includePaths) : [];
  const includeWarning = formatWorktreeIncludeCopyWarning(skipped);
  const sharedPaths = args.sharedDirs ?? DEFAULT_SHARED_DIRS;
  await createWorktreeSharedPaths(repoRoot, worktreePath, sharedPaths);
  const agent = args.agent ?? "claude";
  const host = args.host ?? "local";
  const launchCommand = buildCruxAgentLaunchCommand(agent, args.prompt ?? "", {
    isRemote: host !== "local",
    accountDir: args.accountDir
  });
  let screenId;
  let paneId;
  if (host !== "local") {
    const rRoot = `/tmp/crux-remote-${taskId}`;
    await execFileAsync2("crux", [
      "remote",
      "exec",
      host,
      "--",
      "bash",
      "-lc",
      `mkdir -p ${shellQuote(rRoot)}`
    ]).catch(() => void 0);
  } else if (args.openPane) {
    const fullCmd = `cd ${shellQuote(worktreePath)} && ${launchCommand}`;
    const res = await execFileAsync2("crux", [
      "screen",
      "new",
      "--terminals",
      "1",
      "--run",
      fullCmd,
      "--name",
      `Crux \xB7 ${taskId} (${tuiAgentDisplayName(agent) ?? agent})`,
      "--directory",
      worktreePath,
      "--json"
    ]).catch(() => null);
    if (res?.stdout) {
      try {
        const parsed = JSON.parse(res.stdout);
        screenId = parsed.id;
        paneId = parsed.pane;
      } catch {
      }
    }
  }
  const nowIso = (/* @__PURE__ */ new Date()).toISOString();
  const initialStatus = args.workspaceStatus ?? "in-progress";
  const initialComment = args.comment?.trim() ?? "";
  const record = {
    taskId,
    agent,
    displayName: tuiAgentDisplayName(agent) ?? agent,
    worktreePath,
    branch,
    baseBranch,
    host,
    ...args.accountDir ? { accountDir: args.accountDir } : {},
    ...screenId ? { screenId } : {},
    ...paneId ? { paneId } : {},
    status: "running",
    workspaceStatus: initialStatus,
    ...initialComment ? { comment: initialComment } : {},
    ...args.parentWorktree ? { parentWorktree: args.parentWorktree } : {},
    checkpoints: initialComment ? [{ timestamp: nowIso, workspaceStatus: initialStatus, comment: initialComment }] : [],
    launchCommand,
    ...includeWarning ? { includeWarning } : {},
    updatedAt: nowIso
  };
  const tasks = await loadRegistry(repoRoot);
  tasks[taskId] = record;
  await saveRegistry(repoRoot, tasks);
  return record;
}
async function resolveCurrentCruxWorktree(repoRoot, cwd = process.cwd()) {
  const root = resolve4(repoRoot);
  const target = resolve4(cwd);
  const tasks = await loadRegistry(root);
  for (const rec of Object.values(tasks)) {
    const wt = resolve4(rec.worktreePath);
    if (target === wt || target.startsWith(`${wt}/`)) {
      return rec;
    }
  }
  return null;
}
async function setCruxWorktreeMetadata(args) {
  const root = resolve4(args.repoRoot);
  const tasks = await loadRegistry(root);
  let resolvedId = args.taskId?.trim();
  if (!resolvedId || resolvedId === "current" || resolvedId === "active") {
    const current = await resolveCurrentCruxWorktree(root, args.cwd ?? root);
    if (!current) {
      throw new Error(
        "Could not infer worktree from current directory. Pass taskId explicitly."
      );
    }
    resolvedId = current.taskId;
  }
  const record = tasks[resolvedId];
  if (!record) {
    throw new Error(`Unknown worktree taskId: ${resolvedId}`);
  }
  const nowIso = (/* @__PURE__ */ new Date()).toISOString();
  if (typeof args.displayName === "string" && args.displayName.trim()) {
    record.displayName = args.displayName.trim();
  }
  if (typeof args.workspaceStatus === "string") {
    record.workspaceStatus = args.workspaceStatus;
    if (args.workspaceStatus === "completed" && record.status === "running") {
      record.status = "running";
    }
  }
  if (args.parentWorktree !== void 0) {
    if (args.parentWorktree === null || args.parentWorktree === "null" || args.parentWorktree === "") {
      delete record.parentWorktree;
    } else if (typeof args.parentWorktree === "string") {
      record.parentWorktree = args.parentWorktree;
    }
  }
  if (typeof args.comment === "string") {
    const trimmed = args.comment.trim();
    if (!trimmed) {
      delete record.comment;
    } else {
      record.comment = trimmed;
      const checkpoints = record.checkpoints ?? [];
      checkpoints.push({
        timestamp: nowIso,
        workspaceStatus: record.workspaceStatus ?? "in-progress",
        comment: trimmed
      });
      record.checkpoints = checkpoints;
    }
  }
  record.updatedAt = nowIso;
  tasks[resolvedId] = record;
  await saveRegistry(root, tasks);
  return record;
}
async function removeCruxWorktreeTask(args) {
  const root = resolve4(args.repoRoot);
  const tasks = await loadRegistry(root);
  const record = tasks[args.taskId];
  if (!record) {
    throw new Error(`Unknown worktree taskId: ${args.taskId}`);
  }
  const sharedPaths = args.sharedDirs ?? DEFAULT_SHARED_DIRS;
  if (existsSync(record.worktreePath)) {
    await removeWorktreeSymlinks(record.worktreePath, sharedPaths).catch(() => void 0);
    await gitExecFileAsync(["worktree", "remove", "--force", record.worktreePath], {
      cwd: root
    }).catch(() => void 0);
  }
  let branchDeleted = false;
  if (args.deleteBranch) {
    await gitExecFileAsync(["branch", "-D", record.branch], { cwd: root }).then(() => {
      branchDeleted = true;
    }).catch(() => void 0);
  }
  delete tasks[args.taskId];
  await saveRegistry(root, tasks);
  return { removed: args.taskId, branchDeleted };
}
async function inspectCruxWorktreeDiff(repoRoot, taskId, includePatch = true) {
  const tasks = await loadRegistry(resolve4(repoRoot));
  const record = tasks[taskId];
  if (!record) {
    throw new Error(`Unknown worktree taskId: ${taskId}`);
  }
  if (!existsSync(record.worktreePath)) {
    return { record, dirtyFiles: [], commitsAhead: 0, diffStat: "", patch: "" };
  }
  const { stdout: statusOut } = await gitExecFileAsync(["status", "--porcelain"], {
    cwd: record.worktreePath
  });
  const dirtyFiles = statusOut.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  const { stdout: aheadOut } = await gitExecFileAsync(
    ["rev-list", "--count", `${record.baseBranch}..HEAD`],
    { cwd: record.worktreePath }
  ).catch(() => ({ stdout: "0" }));
  const commitsAhead = Number.parseInt(aheadOut.trim(), 10) || 0;
  const { stdout: diffStat } = await gitExecFileAsync(["diff", "--stat", record.baseBranch], {
    cwd: record.worktreePath
  }).catch(() => ({ stdout: "" }));
  const { stdout: patch } = includePatch ? await gitExecFileAsync(["diff", record.baseBranch], { cwd: record.worktreePath }).catch(
    () => ({ stdout: "" })
  ) : { stdout: "" };
  return {
    record,
    dirtyFiles,
    commitsAhead,
    diffStat: diffStat.trim(),
    patch
  };
}
async function mergeCruxWorktreeTask(args) {
  const repoRoot = resolve4(args.repoRoot);
  const tasks = await loadRegistry(repoRoot);
  const record = tasks[args.taskId];
  if (!record) {
    throw new Error(`Unknown worktree taskId: ${args.taskId}`);
  }
  const sharedPaths = args.sharedDirs ?? DEFAULT_SHARED_DIRS;
  await removeWorktreeSymlinks(record.worktreePath, sharedPaths);
  try {
    const { stdout: porcelain } = await gitExecFileAsync(["status", "--porcelain"], {
      cwd: record.worktreePath
    });
    if (porcelain.trim()) {
      await gitExecFileAsync(["add", "-A"], { cwd: record.worktreePath });
      await gitExecFileAsync(
        ["commit", "-m", `feat(${record.taskId}): finalize work from ${record.agent}`],
        { cwd: record.worktreePath }
      );
    }
    await createWorktreeSharedPaths(repoRoot, record.worktreePath, sharedPaths);
    if (args.verifyCmd) {
      try {
        await execFileAsync2("bash", ["-lc", args.verifyCmd], { cwd: record.worktreePath });
      } catch (error) {
        record.status = "failed";
        record.updatedAt = (/* @__PURE__ */ new Date()).toISOString();
        tasks[record.taskId] = record;
        await saveRegistry(repoRoot, tasks);
        const msg = error instanceof Error ? error.message : String(error);
        throw new Error(`Pre-merge verification failed (${args.verifyCmd}): ${msg}`);
      }
    }
  } finally {
    if (existsSync(record.worktreePath)) {
      await removeWorktreeSymlinks(record.worktreePath, sharedPaths);
    }
  }
  const diffInfo = await inspectCruxWorktreeDiff(repoRoot, record.taskId, false);
  await gitExecFileAsync(
    [
      "merge",
      "--no-ff",
      record.branch,
      "-m",
      `Merge Crux worktree ${record.branch} (${record.displayName})`
    ],
    { cwd: repoRoot }
  );
  const { stdout: headOut } = await gitExecFileAsync(["rev-parse", "--short", "HEAD"], {
    cwd: repoRoot
  });
  if (args.cleanup) {
    await gitExecFileAsync(["worktree", "remove", "--force", record.worktreePath], {
      cwd: repoRoot
    }).catch(() => void 0);
  } else if (existsSync(record.worktreePath)) {
    await createWorktreeSharedPaths(repoRoot, record.worktreePath, sharedPaths);
  }
  record.status = "merged";
  record.updatedAt = (/* @__PURE__ */ new Date()).toISOString();
  tasks[record.taskId] = record;
  await saveRegistry(repoRoot, tasks);
  return {
    record,
    mergedCommit: headOut.trim(),
    diffStat: diffInfo.diffStat
  };
}
async function listCruxWorktreeStatus(repoRoot) {
  const root = resolve4(repoRoot);
  const tasks = await loadRegistry(root);
  const out = [];
  for (const taskId of Object.keys(tasks)) {
    const info = await inspectCruxWorktreeDiff(root, taskId, false);
    out.push({
      ...info.record,
      dirtyCount: info.dirtyFiles.length,
      commitsAhead: info.commitsAhead,
      diffStat: info.diffStat
    });
  }
  return out;
}

// ../../runtime/worktree/cli.ts
async function main() {
  const raw = process.argv[2];
  if (!raw) {
    throw new Error("Usage: node cli.mjs <json-payload>");
  }
  const payload = JSON.parse(raw);
  const repoRoot = payload.repoRoot || process.cwd();
  switch (payload.sub) {
    case "agents": {
      const res = await detectInstalledCruxAgents();
      console.log(JSON.stringify(res, null, 2));
      return;
    }
    case "create":
    case "spawn": {
      const taskId = payload.taskId || payload.displayName;
      if (!taskId) {
        throw new Error("usage: crux worktree create <task-id|--name N> [--agent A] [--prompt P] [--status S] [--comment C]");
      }
      const rec = await spawnCruxWorktreeTask({
        repoRoot,
        taskId,
        agent: payload.agent ?? void 0,
        prompt: payload.prompt ?? void 0,
        baseBranch: payload.baseBranch ?? void 0,
        host: payload.host ?? void 0,
        accountDir: payload.accountDir ?? void 0,
        openPane: payload.openPane ?? void 0,
        workspaceStatus: payload.workspaceStatus ?? void 0,
        comment: payload.comment ?? void 0,
        parentWorktree: payload.parentWorktree ?? void 0
      });
      console.log(JSON.stringify(rec, null, 2));
      return;
    }
    case "set": {
      const rec = await setCruxWorktreeMetadata({
        repoRoot,
        taskId: payload.taskId ?? void 0,
        cwd: payload.cwd ?? process.cwd(),
        displayName: payload.displayName ?? void 0,
        workspaceStatus: payload.workspaceStatus ?? void 0,
        comment: payload.comment ?? void 0,
        parentWorktree: payload.parentWorktree === null ? void 0 : payload.parentWorktree
      });
      console.log(JSON.stringify(rec, null, 2));
      return;
    }
    case "current": {
      const rec = await resolveCurrentCruxWorktree(repoRoot, payload.cwd ?? process.cwd());
      console.log(JSON.stringify({ current: rec }, null, 2));
      return;
    }
    case "ps":
    case "ls":
    case "list":
    case "status": {
      const rows = await listCruxWorktreeStatus(repoRoot);
      console.log(JSON.stringify(rows, null, 2));
      return;
    }
    case "diff": {
      let tid = payload.taskId;
      if (!tid || tid === "current" || tid === "active") {
        const cur = await resolveCurrentCruxWorktree(repoRoot, payload.cwd ?? process.cwd());
        tid = cur?.taskId;
      }
      if (!tid) {
        throw new Error("usage: crux worktree diff <task-id|current>");
      }
      const diff = await inspectCruxWorktreeDiff(repoRoot, tid, true);
      console.log(JSON.stringify(diff, null, 2));
      return;
    }
    case "merge": {
      let tid = payload.taskId;
      if (!tid || tid === "current" || tid === "active") {
        const cur = await resolveCurrentCruxWorktree(repoRoot, payload.cwd ?? process.cwd());
        tid = cur?.taskId;
      }
      if (!tid) {
        throw new Error("usage: crux worktree merge <task-id|current> [--verify CMD] [--cleanup]");
      }
      const res = await mergeCruxWorktreeTask({
        repoRoot,
        taskId: tid,
        verifyCmd: payload.verifyCmd,
        cleanup: payload.cleanup
      });
      console.log(JSON.stringify(res, null, 2));
      return;
    }
    case "rm":
    case "remove": {
      if (!payload.taskId) {
        throw new Error("usage: crux worktree rm <task-id> [--cleanup]");
      }
      const res = await removeCruxWorktreeTask({
        repoRoot,
        taskId: payload.taskId,
        deleteBranch: payload.cleanup
      });
      console.log(JSON.stringify(res, null, 2));
      return;
    }
    default:
      throw new Error(
        `unknown worktree verb ${JSON.stringify(payload.sub)} \u2014 try create, set, current, ps, diff, merge, rm, or agents`
      );
  }
}
main().catch((err) => {
  console.error(err instanceof Error ? err.message : String(err));
  process.exit(1);
});
