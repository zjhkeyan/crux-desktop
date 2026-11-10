// Open Science Desktop's OpenCode plugin: what the app adds to every session.
//
// - The host tools: present_artifact, ssh_connect, computer.
// - The host UI contract (how to display an artifact) on every model request.
// - The browser lease: one browser per conversation, launched as Settings say.
// - The conversation a shell command runs for, as OSD_ORIGIN_SESSION, so `osd`
//   called from inside a conversation says where it comes from. The gateway
//   records it in the audit log and limits how fast one conversation may
//   message others, so two agents cannot talk to each other without end.
//
// OpenCode supplies `@opencode/plugin` to the plugins it loads; nothing here is
// installed from npm.
import { Plugin } from "@opencode/plugin";
import { ARTIFACT_PRESENTATION_SYSTEM, presentArtifact, presentArtifactTool, type PresentInput } from "./artifact";
import { applyBrowserLease } from "./browser";
import { ShellOrigins } from "./origin";
import { computerTool, runComputer } from "./computer";
import { sshConnect, sshConnectTool } from "./ssh";
import { runWorktree, worktreeTool } from "./worktree";
import {
  cruxDiscoveryTool,
  cruxEvolveTool,
  memoryDreamTool,
  runCruxDiscovery,
  runCruxEvolve,
  runMemoryDream,
  runSciResearch,
  sciResearchTool,
} from "./research-tools";
import { loadWorkspaceMemorySystemPrompt } from "./memory";

type ToolContext = {
  sessionID: string;
  agent: string;
  messageID: string;
  id: string;
  signal?: AbortSignal;
};

export default Plugin.define({
  id: "open-science-desktop",
  async setup(ctx: any) {
    // The folder a session works in: tools run for many sessions, and the
    // plugin's own location is only where it was loaded.
    const workspaceOf = async (sessionID: string): Promise<string> => {
      const session = await ctx.session.get({ sessionID });
      const directory = session?.location?.directory;
      if (typeof directory !== "string" || !directory) throw new Error("this session has no workspace folder");
      return directory;
    };

    await ctx.tool.transform((editor: any) => {
      // Called directly, never through Code Mode: the app recognizes these
      // calls by name to act on them (show the artifact, open the sign-in).
      editor.add({
        ...presentArtifactTool,
        options: { codemode: false },
        execute: async (input: PresentInput, context: ToolContext) => ({
          content: await presentArtifact(await workspaceOf(context.sessionID), input),
        }),
      });
      editor.add({
        ...sshConnectTool,
        options: { codemode: false },
        execute: async (input: { host: string }, context: ToolContext) => ({
          content: await sshConnect(input, context.signal),
        }),
      });
      editor.add({
        ...worktreeTool,
        options: { codemode: false },
        execute: async (input: Record<string, unknown>, context: ToolContext) => ({
          content: await runWorktree(await workspaceOf(context.sessionID), input),
        }),
      });
      editor.add({
        ...sciResearchTool,
        options: { codemode: false },
        execute: async (input: Record<string, unknown>, context: ToolContext) => ({
          content: await runSciResearch(await workspaceOf(context.sessionID), input),
        }),
      });
      editor.add({
        ...cruxDiscoveryTool,
        options: { codemode: false },
        execute: async (input: Record<string, unknown>, context: ToolContext) => ({
          content: await runCruxDiscovery(await workspaceOf(context.sessionID), input),
        }),
      });
      editor.add({
        ...memoryDreamTool,
        options: { codemode: false },
        execute: async (input: Record<string, unknown>, context: ToolContext) => ({
          content: await runMemoryDream(await workspaceOf(context.sessionID), input),
        }),
      });
      editor.add({
        ...cruxEvolveTool,
        options: { codemode: false },
        execute: async (input: Record<string, unknown>, context: ToolContext) => ({
          content: await runCruxEvolve(await workspaceOf(context.sessionID), input),
        }),
      });
      editor.add({
        ...computerTool,
        options: { codemode: false },
        execute: async (input: Record<string, unknown>, context: ToolContext) => {
          // Reading the screen is reading the user's mail and messages, so the
          // whole tool is gated: the rules decide (approve mode asks once,
          // "always" saves it), and a deny blocks it.
          await ctx.permission.assert({
            sessionID: context.sessionID,
            agent: context.agent,
            source: { type: "tool", messageID: context.messageID, id: context.id },
            action: "computer",
            resources: [String(input.app ?? input.action ?? "*")],
            save: ["*"],
          });
          const { output, screenshotPath } = await runComputer(input);
          return screenshotPath
            ? { content: [{ type: "text", text: output }, { type: "file", uri: `file://${screenshotPath}`, mime: "image/png" }] }
            : { content: output };
        },
      });
    });

    // Isolate the scientific workbench from host-level developer/coding-agent
    // skills (`~/.agents/skills`, `~/.claude/skills`), OpenCode internal
    // meta-skills (`/builtin/opencode.md`, `/builtin/report.md`), and retired
    // overlapping skill IDs so sessions only see curated scientific skills.
    const RETIRED_SKILL_IDS = new Set([
      "opencode",
      "report",
      "literature-survey",
      "integrity-auditor",
      "crux-quickstart",
      "setting-up-crux",
      "creating-a-crux-task",
      "running-crux-experiments",
      "ai4s-agent",
      "research-explorer",
      "experiment-suite",
    ]);
    if (ctx.skill && typeof ctx.skill.transform === "function") {
      await ctx.skill.transform((editor: any) => {
        const list = typeof editor?.list === "function" ? editor.list() : [];
        for (const skill of list) {
          const id = String(skill?.id ?? "");
          const skillPath = String(skill?.path ?? "");
          if (
            RETIRED_SKILL_IDS.has(id) ||
            skillPath.startsWith("/builtin/") ||
            skillPath.includes("/.agents/skills/") ||
            skillPath.includes("/.claude/skills/")
          ) {
            editor.remove(id);
          }
        }
      });
    }

    await ctx.session.hook("context", async (event: any) => {
      event.system.push({ type: "text", text: ARTIFACT_PRESENTATION_SYSTEM });
      const dir =
        typeof event?.sessionID === "string" && event.sessionID
          ? await workspaceOf(event.sessionID).catch(() => null)
          : null;
      event.system.push({ type: "text", text: loadWorkspaceMemorySystemPrompt(dir) });
    });

    // A shell command's session is known to the tool call, not to the shell it
    // creates (OpenCode sets OPENCODE_SESSION_ID only after this hook runs).
    // The tool call is the step just before, so it leaves the command and its
    // session here and the shell picks them up by command text. Two sessions
    // starting the identical command in the same instant could swap; that
    // costs a mislabelled audit line, never a command.
    const shellOrigins = new ShellOrigins();

    await ctx.tool.hook("execute.before", (event: any) => {
      applyBrowserLease(event.tool, event.input, event.sessionID);
      if (event.tool === "shell") shellOrigins.expect(event.input?.command, event.sessionID);
    });

    // `osd` reads OSD_ORIGIN_SESSION. A terminal the user opens has none.
    await ctx.shell.hook("create.before", (event: any) => {
      const session = shellOrigins.take(event.command);
      if (session && event.env) event.env.OSD_ORIGIN_SESSION = session;
    });
  },
});
