# Crux Desktop — Architecture & Agent Navigation Guide

Brand name: **Crux Desktop** (`Crux`) — "Local-first, model-agnostic AI research workbench for macOS, Windows & Linux." Formerly Open Science Desktop.
- **Bundle identifier**: `com.crux.desktop` (macOS Computer Use helper: `com.crux.desktop.computer-use`, `Crux Computer Use.app`)
- **CLI binary & sidecar**: `crux` (`crux.exe` / `crux.cmd`); state directory env var: `CRUX_STATE_DIR` (falls back to `OSD_STATE_DIR`)
- **Internal build seams**: Workspace packages (`@ai4s/desktop`, `@ai4s/sdk`, `@ai4s/shared`, `@ai4s/ui`), Cargo crates (`osd-core`, `osd-cli`, `ai4s-workbench`), and bundled resource marker (`osd-plugin`) remain unchanged.

`CLAUDE.md` is a symlink to this file — edit only `AGENTS.md`.

---

## 1. System Topology & Host Modes

Crux runs the **same server core and React workbench** across two host modes (Desktop Tauri and Headless `crux server`) and four client surfaces:

```text
Client Surfaces
├── Desktop React UI (Tauri WebView) ──► Tauri invoke + OpenCodeClient
├── Gateway Web UI (Browser / Mobile) ─► HTTP /v1/* + SSE /v1/events
├── crux CLI Client (crates/osd-cli) ──► HTTP /v1/* (Unix socket / loopback)
└── External Editor (Zed / IDE) ───────► ACP JSON-RPC stdio (runtime/acp-server/acp-server.mjs)
        │
        ▼
Host Layer
├── Desktop Host (apps/desktop/src-tauri) — Tauri commands + GUI-only services (Kernel, Jupyter, Browser, Keychain, ACP Client)
└── HTTP + SSE Gateway (crates/osd-core/src/gateway.rs) — /v1/* REST API, /v1/events SSE, /v1/opencode/* proxy, static Web UI
        │
        ▼
Server Core (crates/osd-core — Zero Tauri / GUI dependency)
├── env.rs              Env handle (data_dir, resource_dir, document_dir, CRUX_STATE_DIR)
├── runtime.rs          Spawns & supervises bundled `opencode serve` sidecar
├── crux_bridge.rs      Syncs Crux model/XDG profile into engine bindings (`~/.config/crux/engine-agents.yaml`) & `<runtime>/bin/{crux-engine,coral,crux-opencode}`
├── crux_views.rs       Read-only `.crux/public/views` (and `.coral/` fallback) projections with provenance HMAC verification
├── opencode_config.rs  Generates per-workspace opencode.json profile & provider config
├── termd.rs            Persistent PTY daemon; terminal_read.rs parses screen & Claude/Codex transcripts
└── project.rs, git_snapshot.rs, provenance.rs, screens.rs, specialists.rs
        │
        ▼
Agent & Tool Execution
├── OpenCode Sidecar    Pinned single-binary agent runtime (HTTP + SSE)
├── runtime/osd-plugin  Host tools (`present_artifact`, `computer`, `ssh_connect`), browser lease, OSD_ORIGIN_SESSION tag
├── runtime/computer    Cross-platform Computer Use host ► native/computer-use-{macos,linux,windows}
└── runtime/skills      Core (`osd-agents`, `computer-use`, `publication-figures`, `remote-compute`) & external skills
```

---

## 2. Module & File Map

| Layer | Path | Key Entrypoints & Responsibilities |
| :--- | :--- | :--- |
| **Server Core** | `crates/osd-core/src/` | `lib.rs` (crate root), `env.rs` (`Env`, `IDENTIFIER`), `runtime.rs` (sidecar lifecycle), `crux_bridge.rs` (Crux discovery engine CLI shims & `engine-agents.yaml` sync), `crux_views.rs` (`.crux/public` view readers), `opencode_config.rs` (profile generation), `gateway.rs` (`/v1/*` HTTP/SSE server incl. `/v1/discovery/*`), `termd.rs` & `terminal_read.rs` (persistent PTYs), `specialists.rs` (subagent definitions), `git_snapshot.rs` (debounced workspace git commits), `provenance.rs` & `runs.rs` (`.provenance/runs.jsonl`). |
| **CLI & Headless** | `crates/osd-cli/src/` | `main.rs` (`crux` CLI router), `discovery.rs` (Crux discovery front-door verbs & allowlist agent guard), `server.rs` (`crux server` headless daemon), `client.rs` (gateway discovery & auth), `commands.rs` (`sessions`, `send`, `messages`, `permission`), `screens.rs` (`crux screen` canvas control), `auth.rs` & `settings.rs`. |
| **Desktop Shell** | `apps/desktop/src-tauri/src/` | `lib.rs` (`EnvState`, Tauri command registration), `cli_shim.rs` (`~/.local/bin/crux` / `crux.cmd` PATH wrapper), `computer.rs` (`Crux Computer Use.app` TCC permission bridge), `acp.rs` (drives external `claude`/`codex`/`gemini` over ACP), `kernel.rs` & `jupyter.rs` (local notebooks), `browser.rs` (`agent-browser` lifecycle). |
| **React Workbench** | `apps/desktop/src/` | `lib/runtime.ts` (Zustand session/turn/approval store), `lib/tauri.ts` (unified host bridge routing to Tauri `invoke` or `lib/gatewayHttp.ts` when `isGatewayWeb` is true), `components/canvas/` (spatial canvas), `components/thread/` (chat & tool cards), `components/settings/` (providers, specialists, remote access, computer use, CLI shim), `i18n/locales/{en,zh-Hans,ja,ko,fr,de,es}/`. |
| **SDK & ACP Server** | `packages/sdk/src/` | `index.ts` (`OpenCodeClient`), `acp/server.ts` (`AGENT_NAME = "crux"`, `AGENT_TITLE = "Crux"`), `acp/serve-stdio.ts` (bundled by `scripts/build-acp-server.mjs` into `runtime/acp-server/acp-server.mjs`). |
| **Shared Contracts** | `packages/shared/src/` | `index.ts` (Artifact, Provenance, Session, and Runtime TypeScript schemas). |
| **Runtime & Plugins** | `runtime/` | `osd-plugin/index.ts` (`present_artifact`, `computer`, `ssh_connect`, browser lease, `OSD_ORIGIN_SESSION`), `computer/` (Computer Use host & macOS Unix socket client), `skills/core/` (first-party skills), `skills/crux/` (Crux multi-agent discovery skills `skills-crux/`), `opencode-profile/` (agent prompts incl. `reviewer`, `crux-task-author`, `crux-run-doctor`, & commands). |
| **Native Providers** | `native/` | `computer-use-macos/` (`Crux Computer Use.app` Swift Accessibility + ScreenCaptureKit helper), `computer-use-linux/runtime.py` (AT-SPI), `computer-use-windows/runtime.ps1` (UI Automation). Staged by `scripts/dev/build-computer-use.mjs`. |

---

## 3. Core Domain Vocabulary

- **`Env` (`osd_core::Env`)**: Immutable runtime handle holding `data_dir`, `resource_dir`, `document_dir`, and version. Shared across Tauri commands and the HTTP gateway.
- **Gateway Web Client (`isGatewayWeb`)**: The React SPA running in a browser against `crux server` or Desktop Remote Access rather than inside Tauri WebView. Calls `gatewayHttp.ts` (`/v1/*`) instead of Tauri `invoke`.
- **Host Plugin (`runtime/osd-plugin`)**: Loaded into every OpenCode session. Exposes direct host tools (`options: { codemode: false }`) and tags spawned shell commands with `OSD_ORIGIN_SESSION=<sessionID>` so `crux` CLI calls are audited and rate-limited by `gateway.rs`.
- **Canvas (`screens`)**: Infinite spatial workspace (`crates/osd-core/src/screens.rs`, `crux screen`) arranging session cards, terminal panes, browser tiles, and notes.
- **Terminal Host (`termd`)**: Persistent PTY multiplexer (`crates/osd-core/src/termd.rs`, `crux term`) keeping shell and CLI agent panes alive across UI reloads.
- **Specialist**: Subagent role managed by `crates/osd-core/src/specialists.rs` (`# Managed by Crux Desktop (Specialists)`) and materialized into the OpenCode profile.

---

## 4. Task-to-File Routing ("Where to Edit")

1. **Add a backend capability (Desktop + Web/CLI)**:
   - Implement display-free logic in `crates/osd-core/src/`.
   - Expose HTTP endpoint in `crates/osd-core/src/gateway.rs` and Tauri command in `apps/desktop/src-tauri/src/`.
   - Wire both paths in `apps/desktop/src/lib/tauri.ts` and `apps/desktop/src/lib/gatewayHttp.ts`.
2. **Add or update a `crux` CLI subcommand**:
   - Update parser/help in `crates/osd-cli/src/main.rs` & `args.rs`, implement in `commands.rs` / `screens.rs` / `auth.rs` / `settings.rs`, and update `runtime/skills/core/osd-agents/SKILL.md`.
3. **Add or update UI copy / i18n**:
   - Edit all 7 locales under `apps/desktop/src/i18n/locales/{en,zh-Hans,ja,ko,fr,de,es}/`. Keep the brand name **`Crux`** in English across every locale.
4. **Modify ACP stdio server (`Crux` in external editors)**:
   - Edit `packages/sdk/src/acp/server.ts` or `serve-stdio.ts`, then run `node scripts/build-acp-server.mjs` to update `runtime/acp-server/acp-server.mjs`.
5. **Add a bundled resource**:
   - Register in **both** `apps/desktop/src-tauri/tauri.conf.json` (`bundle.resources`) **and** `scripts/release/package-osd.sh` (`copy_resource`).

---

## 5. Architecture Guardrails & Safety Defaults

- **`osd-core` stays display-free**: never add Tauri or GUI dependencies to `crates/osd-core`.
- **Single SDK seam**: the UI never calls OpenCode directly — always go through `packages/sdk` (`OpenCodeClient`). Pin `OPENCODE_VERSION` and bundle OpenCode as a sidecar.
- **Desktop & Gateway Web parity**: every feature must work on Windows, macOS, Linux, AND in `isGatewayWeb` (including phone-width viewports). If a feature fundamentally cannot work over the web (local kernels, native dialogs, host filesystem pickers), hide it behind `isGatewayWeb`.
- **Workspace isolation & Git snapshots**: the agent may only access the active workspace. New session workspaces are initialized as local git repos by `git_snapshot.rs` with best-effort local commits (`Crux Desktop <crux-desktop@local>`); never set a remote or push.
- **Approval & credential safety**: command execution, file deletion, dependency install, Computer Use, and remote connections require approval (`manual` default; never ship `off`). API keys live only in the OS keychain or local auth store — never in provenance, logs, git, or exports.

---

## 6. Working Conventions & Verification

- Discussion language: Chinese; **all repository files, code, and comments must be in English**.
- Milestones: append one line per milestone (`YYYY-MM-DD HH:MM` + one-sentence conclusion, newest on top) to `PROGRESS.md`. Avoid adding extra Markdown docs unless requested.
- Related specs in `docs/`: `docs/PRD.md`, `docs/TECHNICAL_DESIGN.md`, `docs/REQUIREMENTS.md`, `docs/APP_OPERATOR.md`, `docs/CONNECT_YOUR_TOOLS.md`.

### Verification & Build Commands
```bash
# Rebuild ACP stdio bundle (required after editing packages/sdk/src/acp/*)
node scripts/build-acp-server.mjs

# Frontend verification (typecheck + lint + Vitest suite)
pnpm typecheck && pnpm lint && pnpm test

# Single frontend test file (tight feedback loop)
pnpm --filter @ai4s/desktop exec vitest run src/test/acp-server.test.ts

# Rust core & CLI verification (no display server required)
cargo test -p osd-core -p osd-cli

# Stage sidecars & package headless `crux` archive
node scripts/dev/build-computer-use.mjs
bash scripts/dev/build-osd-sidecar.sh "$(rustc -vV | awk '/^host:/ { print $2 }')"
bash scripts/release/package-osd.sh "$(rustc -vV | awk '/^host:/ { print $2 }')"
```
