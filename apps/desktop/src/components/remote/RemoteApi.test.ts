import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";
import { invoke } from "@tauri-apps/api/core";
import { gatewayPost } from "@/lib/webMode";

const transport = vi.hoisted(() => ({ web: false }));
vi.mock("@tauri-apps/api/core", () => ({ invoke: vi.fn() }));
vi.mock("@/lib/webMode", () => ({
  get isGatewayWeb() { return transport.web; },
  gatewayPost: vi.fn(), gatewayGet: vi.fn(), signedInAccount: vi.fn(),
}));

const windowHost = window as unknown as { __TAURI_INTERNALS__?: object };
windowHost.__TAURI_INTERNALS__ = {};
const api = await import("@/lib/tauri");
afterAll(() => { delete windowHost.__TAURI_INTERNALS__; });
beforeEach(() => { vi.clearAllMocks(); });

const actions = [
  { call: () => api.runRemotePreflight("lab"), command: "run_remote_preflight", path: "preflight", args: { host: "lab" }, response: { hostname: "lab", pinnedNode: "login2" } },
  { call: () => api.pairRemoteHostKey("lab"), command: "pair_remote_host_key", path: "pair", args: { host: "lab" }, response: { paired: true } },
  { call: () => api.unpairRemoteHostKey("lab"), command: "unpair_remote_host_key", path: "unpair", args: { host: "lab" }, response: { unpaired: true } },
  { call: () => api.harvestRemoteRun("lab", "run 1", { applyGitPatch: false, includeCheckpoints: true }), command: "harvest_remote_run", path: "harvest", args: { host: "lab", runDir: "run 1", options: { applyGitPatch: false, includeCheckpoints: true } }, response: { filesCount: 3 } },
];

describe.each([false, true])("remote API in web mode = %s", (web) => {
  beforeEach(() => { transport.web = web; });
  it.each(actions)("routes $command and returns the host result", async ({ call, command, path, args, response }) => {
    vi.mocked(invoke).mockResolvedValue(response);
    vi.mocked(gatewayPost).mockResolvedValue(response);
    expect(await call()).toEqual(response);
    if (web) {
      expect(gatewayPost).toHaveBeenCalledWith(`/v1/remote/${path}`, args);
      expect(invoke).not.toHaveBeenCalled();
    } else {
      expect(invoke).toHaveBeenCalledWith(command, args);
      expect(gatewayPost).not.toHaveBeenCalled();
    }
  });
  it("propagates permission failures without reporting success", async () => {
    vi.mocked(invoke).mockRejectedValue(new Error("approval required"));
    vi.mocked(gatewayPost).mockRejectedValue(new Error("approval required"));
    await expect(api.pairRemoteHostKey("lab")).rejects.toThrow("approval required");
  });
});
