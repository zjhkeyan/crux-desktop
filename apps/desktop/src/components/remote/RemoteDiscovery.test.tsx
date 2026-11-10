import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import { useSshStore } from "@/lib/ssh";
import * as remote from "@/lib/tauri";
import { CruxDiscoveryTile } from "../canvas/CruxDiscoveryTile";
import { HarvestDialog } from "./HarvestDialog";
import { TaskStudio } from "./TaskStudio";
import { PreflightCard } from "./PreflightCard";
import type { RemotePreflightReport } from "@/lib/gatewayHttp";
import { ConnectWizard } from "./ConnectWizard";

vi.mock("@/lib/tauri", async (original) => ({
  ...await original<typeof import("@/lib/tauri")>(),
  listSshHosts: vi.fn(),
  inspectRemoteHostKey: vi.fn(),
  connectRemoteHost: vi.fn(),
  runRemotePreflight: vi.fn(),
  pairRemoteHostKey: vi.fn(),
  unpairRemoteHostKey: vi.fn(),
  launchRemoteDiscovery: vi.fn(),
  harvestRemoteRun: vi.fn(),
  resumeRemoteDiscovery: vi.fn(),
  getDiscoveryView: vi.fn(),
}));

afterEach(() => vi.useRealTimers());

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("en");
  vi.mocked(remote.listSshHosts).mockResolvedValue(["lab"]);
});

it("requires fingerprint confirmation before connecting, and pairs and unpairs the pinned server", async () => {
  vi.mocked(remote.inspectRemoteHostKey).mockResolvedValue({ fingerprint: "SHA256:abc", trusted: false });
  vi.mocked(remote.connectRemoteHost).mockResolvedValue({ connected: true, pinnedNode: "login2.lab" });
  vi.mocked(remote.pairRemoteHostKey).mockResolvedValue({ paired: true, pinnedNode: "login2.lab" });
  vi.mocked(remote.unpairRemoteHostKey).mockResolvedValue({ unpaired: true });
  const connected = vi.fn();
  render(<ConnectWizard onConnected={connected} />);
  await userEvent.type(screen.getByLabelText("Server Address"), "user@lab:2222");
  await userEvent.click(screen.getByRole("button", { name: "Connect to Server" }));
  const dialog = await screen.findByRole("alertdialog", { name: "Verify Server Fingerprint" });
  expect(within(dialog).getByText(/SHA256:abc/)).toBeInTheDocument();
  expect(remote.connectRemoteHost).not.toHaveBeenCalled();
  await userEvent.click(within(dialog).getByRole("button", { name: "I verified it" }));
  await waitFor(() => expect(connected).toHaveBeenCalledWith("user@lab:2222", "login2.lab"));
  await userEvent.click(screen.getByRole("button", { name: "Pair Dedicated ed25519 Key" }));
  expect(await screen.findByText(/login2.lab/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Unpair" }));
  expect(remote.unpairRemoteHostKey).toHaveBeenCalledWith("user@lab:2222");
});

it("automatically checks the remote host and recommends a full Slurm swarm for four agents", async () => {
  vi.mocked(remote.runRemotePreflight).mockResolvedValue(report);
  render(<PreflightCard host="lab" agents={4} />);
  expect(await screen.findByText("4× A100")).toBeInTheDocument();
  expect(screen.getByLabelText("Slurm Mode")).toHaveValue("full_swarm");
  expect(screen.getByText(/Low HOME space/)).toBeInTheDocument();
  expect(screen.getByLabelText("AI Connection")).toHaveValue("E2");
  expect(screen.getByRole("option", { name: "Direct (E1 — Sleep-Safe)" })).toBeDisabled();
  expect(screen.getByLabelText("Max Budget Cap ($ USD)")).toBeInTheDocument();
});

const report: RemotePreflightReport = {
  hostname: "lab", pinnedNode: "login2.lab", osArch: "Linux x86_64", gpus: Array.from({ length: 4 }, () => ({ name: "A100", memoryMiB: 81920 })),
  slurmAvailable: true, slurmPartitions: ["gpu", "cpu"], diskFreeGiB: 400, homeFreeGiB: 2, scratchPath: "/scratch/user", outboundHttps: false,
  recommendedEgress: "E2", recommendedSlurmMode: "eval_offload", hostKeyFingerprint: "SHA256:abc", engineReady: true, runtimeReady: true,
};

it("previews the task and launches a server run with the selected model, metric and swarm", async () => {
  vi.mocked(remote.launchRemoteDiscovery).mockResolvedValue({ runDir: "/scratch/run-1" });
  render(<TaskStudio host="lab" preflight={report} models={["test/model"]} />);
  await userEvent.type(screen.getByLabelText("Project Folder"), "/work/project");
  await userEvent.type(screen.getByLabelText("Metric Name"), "latency_ms");
  await userEvent.selectOptions(screen.getByLabelText("Goal Direction"), "minimize");
  await userEvent.selectOptions(screen.getByLabelText("Agent Swarm Size"), "4");
  await userEvent.clear(screen.getByLabelText("Model"));
  await userEvent.type(screen.getByLabelText("Model"), "test/custom");
  expect(screen.getByLabelText("Slurm Mode")).toHaveValue("full_swarm");
  expect(screen.getByLabelText("task.yaml preview")).toHaveTextContent("direction: minimize");
  await userEvent.click(screen.getByRole("button", { name: "Launch Discovery on Server" }));
  expect(await screen.findByText("Discovery launched: /scratch/run-1")).toBeInTheDocument();
  expect(remote.launchRemoteDiscovery).toHaveBeenCalledWith("lab", "/work/project", expect.stringContaining('model: "test/custom"'), expect.objectContaining({ syncLocal: false, slurmMode: "full_swarm" }));
});

it("harvests only with explicitly selected patch and checkpoint options", async () => {
  vi.mocked(remote.harvestRemoteRun).mockResolvedValue({ filesCount: 3, branch: "crux/best-run-1", reportPath: "results/run-1/report.md" });
  render(<HarvestDialog host="lab" runDir="/scratch/run-1" winningCommit="abc123" baseline={10} best={7} insights={[{ text: "verified insight", state: "CORROBORATED" }, { text: "unverified insight", state: "PROVISIONAL" }]} />);
  expect(screen.getByText("10 → 7")).toBeInTheDocument();
  expect(screen.queryByText("unverified insight")).not.toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Apply winning git diff to local branch crux/best-run-1"));
  await userEvent.click(screen.getByLabelText("Include large checkpoints (*.pt, *.safetensors)"));
  await userEvent.click(screen.getByRole("button", { name: "Bring Results to This PC" }));
  await waitFor(() => expect(remote.harvestRemoteRun).toHaveBeenCalledWith("lab", "/scratch/run-1", { applyGitPatch: true, includeCheckpoints: true }));
  expect(await screen.findByText(/Fetched 3 files/)).toBeInTheDocument();
});

it.each([
  ["RUNNING", "direct", "🟢 Sleep-safe: runs on server if PC closes"],
  ["RUNNING", "relay", "🟢 Sleep-safe: runs on server if PC closes"],
  ["RUNNING", "tunnel", "🟡 Keep this PC awake (AI routed through this PC)"],
  ["HOLDING", "tunnel", "⏸ Paused — PC asleep or offline (auto-resumes on reconnect)"],
  ["PAUSED_NO_EGRESS", "tunnel", "⏸ Paused — PC asleep or offline (auto-resumes on reconnect)"],
  ["PAUSED_AUTH", "direct", "🔴 Paused — AI provider sign-in needed"],
  ["PAUSED_BUDGET", "direct", "💰 Paused — Run budget cap reached"],
])("shows the %s / %s egress badge and server telemetry", async (state, mode, text) => {
  vi.mocked(remote.getDiscoveryView).mockImplementation(async <T,>(view: string) => (view === "egress"
    ? { state, mode, pinned_node: "login2.lab", gpu_util: "87%", accumulated_cost_usd: 0, scratch_free_gb: 41 }
    : { directions: [], metadata: { slurm_job_id: "4412" } }) as T);
  render(<CruxDiscoveryTile runDir="run-1" />);
  expect(await screen.findByText(text)).toBeInTheDocument();
  const telemetry = screen.getByRole("group", { name: "Server telemetry" });
  expect(within(telemetry).getByText("login2.lab")).toBeInTheDocument();
  expect(within(telemetry).getByText("4412")).toBeInTheDocument();
  expect(within(telemetry).getByText("0")).toBeInTheDocument();
  expect(screen.getAllByRole("tab")).toHaveLength(2);
});

it("cancels first-use trust without connecting or pairing", async () => {
  vi.mocked(remote.inspectRemoteHostKey).mockResolvedValue({ fingerprint: "SHA256:new", trusted: false });
  render(<ConnectWizard />);
  await userEvent.click(screen.getByRole("button", { name: /Import from/ }));
  await userEvent.selectOptions(await screen.findByLabelText("Saved SSH Host"), "lab");
  await userEvent.click(screen.getByRole("button", { name: "Connect to Server" }));
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(remote.connectRemoteHost).not.toHaveBeenCalled();
  expect(remote.pairRemoteHostKey).not.toHaveBeenCalled();
});

it("shows preflight failures and retries without claiming runtime readiness", async () => {
  vi.mocked(remote.runRemotePreflight).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce({ ...report, engineReady: undefined, runtimeReady: undefined });
  render(<PreflightCard host="lab" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText(/readiness not confirmed/)).toBeInTheDocument();
  expect(screen.queryByText("crux-engine + opencode ready")).not.toBeInTheDocument();
});

it("does not offer a patch before a confirmed winner and excludes large checkpoints by default", async () => {
  vi.mocked(remote.harvestRemoteRun).mockRejectedValueOnce(new Error("offline"));
  render(<HarvestDialog host="lab" runDir="run-2" />);
  expect(screen.getByLabelText(/Apply winning git diff/)).toBeDisabled();
  expect(screen.getByLabelText(/Include large checkpoints/)).not.toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Bring Results to This PC" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("offline");
  expect(remote.harvestRemoteRun).toHaveBeenCalledWith("lab", "run-2", { applyGitPatch: false, includeCheckpoints: false });
});

it("keeps the discovery tabs usable when the optional egress view is unavailable", async () => {
  vi.mocked(remote.getDiscoveryView).mockImplementation(async <T,>(view: string) => {
    if (view === "egress") throw new Error("not installed");
    return { directions: [], messages: [] } as T;
  });
  render(<CruxDiscoveryTile runDir="run-1" />);
  await userEvent.click(screen.getByRole("tab", { name: "Verified Shared Archive" }));
  expect(await screen.findByText("No public entries yet.")).toBeInTheDocument();
  expect(screen.getByText("AI connection status unavailable")).toBeInTheDocument();
});

it("raises a budget cap only above both the current cap and accumulated cost", async () => {
  vi.mocked(remote.getDiscoveryView).mockImplementation(async <T,>(view: string) => ({ ...(view === "egress" ? { state: "PAUSED_BUDGET", mode: "direct", max_cost_usd: 10, accumulated_cost_usd: 11 } : { directions: [] }) }) as T);
  vi.mocked(remote.resumeRemoteDiscovery).mockResolvedValue({ resumed: true });
  render(<CruxDiscoveryTile runDir="run-1" host="lab" />);
  await userEvent.click(await screen.findByRole("button", { name: "Raise Cap & Resume" }));
  const input = screen.getByLabelText("New Budget Cap ($ USD)");
  const form = input.closest("form")!;
  await userEvent.type(input, "10");
  await userEvent.click(within(form).getByRole("button", { name: "Raise Cap & Resume" }));
  expect(screen.getByRole("alert")).toHaveTextContent("above the current cap");
  expect(remote.resumeRemoteDiscovery).not.toHaveBeenCalled();
  await userEvent.clear(input);
  await userEvent.type(input, "20");
  await userEvent.click(within(form).getByRole("button", { name: "Raise Cap & Resume" }));
  await waitFor(() => expect(remote.resumeRemoteDiscovery).toHaveBeenCalledWith("lab", "run-1", 20));
});

it("polls live status and stops polling when its pane unmounts", async () => {
  vi.useFakeTimers();
  let state = "RUNNING";
  vi.mocked(remote.getDiscoveryView).mockImplementation(async <T,>(view: string) => ({ ...(view === "egress" ? { state, mode: "tunnel" } : { directions: [] }) }) as T);
  const pane = render(<CruxDiscoveryTile runDir="run-1" />);
  await act(async () => {});
  expect(screen.getByText(/Keep this PC awake/)).toBeInTheDocument();
  state = "PAUSED_NO_EGRESS";
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByText(/Paused — PC asleep/)).toBeInTheDocument();
  pane.unmount();
  const calls = vi.mocked(remote.getDiscoveryView).mock.calls.length;
  await act(async () => { await vi.advanceTimersByTimeAsync(10000); });
  expect(remote.getDiscoveryView).toHaveBeenCalledTimes(calls);
  vi.useRealTimers();
});

it("uses the existing password and 2FA prompt when the server requests sign-in", async () => {
  vi.mocked(remote.inspectRemoteHostKey).mockResolvedValue({ fingerprint: "SHA256:known", trusted: true });
  vi.mocked(remote.connectRemoteHost).mockResolvedValue({ connected: false, needsSignIn: true });
  const originalConnect = useSshStore.getState().connect;
  const signIn = vi.fn().mockResolvedValue(undefined);
  useSshStore.setState({ connect: signIn });
  try {
    render(<ConnectWizard />);
    await userEvent.type(screen.getByLabelText("Server Address"), "lab");
    await userEvent.click(screen.getByRole("button", { name: "Connect to Server" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Complete the server sign-in prompt");
    expect(signIn).toHaveBeenCalledWith("lab");
    expect(remote.pairRemoteHostKey).not.toHaveBeenCalled();
  } finally { useSshStore.setState({ connect: originalConnect }); }
});

it("keeps the pause reason visible even when the board cannot be read", async () => {
  vi.mocked(remote.getDiscoveryView).mockImplementation(async <T,>(view: string) => {
    if (view === "board") throw new Error("board unavailable");
    return (view === "egress" ? { state: "PAUSED_AUTH", mode: "direct" } : {}) as T;
  });
  render(<CruxDiscoveryTile runDir="run-1" />);
  expect(await screen.findByText("🔴 Paused — AI provider sign-in needed")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reconnect & Sign In" })).toBeInTheDocument();
  expect(screen.getByRole("alert")).toHaveTextContent("board unavailable");
});
