import { gatewayGet } from "./webMode";

export type DiscoveryView = "board" | "tree" | "archive" | "radio" | "head" | "egress";
export type CoralView = DiscoveryView;

export type EgressState = "RUNNING" | "HOLDING" | "PAUSED_NO_EGRESS" | "PAUSED_AUTH" | "PAUSED_BUDGET" | "RESUMING";
export type EgressView = {
  state?: EgressState;
  mode?: "direct" | "tunnel" | "relay";
  since?: string;
  paused_accumulated_sec?: number;
  epoch?: number;
  last_error?: string | null;
  accumulated_cost_usd?: number;
  max_cost_usd?: number | null;
  pinned_node?: string;
  slurm_job_id?: string;
  slurm_remaining?: string;
  gpu_util?: string;
  scratch_free_gb?: number;
  link_latency_ms?: number;
};

export type RemotePreflightReport = {
  hostname: string;
  pinnedNode: string;
  osArch: string;
  gpus: Array<{ name: string; memoryMiB: number }>;
  slurmAvailable: boolean;
  slurmPartitions: string[];
  diskFreeGiB: number;
  scratchPath: string;
  outboundHttps: boolean;
  recommendedEgress: "E1" | "E2" | "E3";
  recommendedSlurmMode: "disabled" | "eval_offload" | "full_swarm";
  hostKeyFingerprint: string;
  homeFreeGiB?: number;
  engineReady?: boolean;
  runtimeReady?: boolean;
};

export type RemoteRunOptions = {
  slurmMode: "disabled" | "eval_offload" | "full_swarm";
  egress: "E1" | "E2" | "E3";
  maxCostUsd?: number;
};

/** Uses the same authentication and origin as the rest of the gateway workbench. */
export async function getDiscoveryView<T>(view: DiscoveryView, runDir: string, commit?: string): Promise<T> {
  const query = new URLSearchParams({ run_dir: runDir });
  if (commit !== undefined) query.set("commit", commit);
  const result = await gatewayGet<T>(`/v1/discovery/${view}?${query}`);
  if (result === null) throw new Error("Crux discovery gateway returned no view");
  return result;
}

export const getCoralView = getDiscoveryView;
