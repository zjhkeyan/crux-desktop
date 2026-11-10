import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { inputCls } from "@/components/settings/inputCls";
import { isTauri, launchRemoteDiscovery, pickFolder } from "@/lib/tauri";
import { isGatewayWeb } from "@/lib/webMode";
import { useRuntimeStore } from "@/lib/runtime";
import type { RemotePreflightReport, RemoteRunOptions } from "@/lib/gatewayHttp";

const commands = { pytorch: "python benchmark.py", python: "python -m pytest", slurm: 'srun --jobid "$SLURM_JOB_ID" --overlap python benchmark.py', custom: "" };
export function TaskStudio({ host: initialHost = "", preflight, options, models, onLaunched }: {
  host?: string;
  preflight?: RemotePreflightReport;
  options?: RemoteRunOptions;
  models?: string[];
  onLaunched?: (runDir: string) => void;
}) {
  const { t } = useTranslation("session", { keyPrefix: "discovery.remote" });
  const id = useId();
  const providers = useRuntimeStore((s) => s.providers);
  const defaultModel = useRuntimeStore((s) => s.defaultModel);
  const availableModels = models ?? providers.flatMap((p) => p.models.map((m) => `${p.id}/${m.id}`));
  const [host, setHost] = useState(initialHost);
  const [project, setProject] = useState("");
  const [syncLocal, setSyncLocal] = useState(false);
  const [preset, setPreset] = useState<keyof typeof commands>("pytorch");
  const [command, setCommand] = useState(commands.pytorch);
  const [goal, setGoal] = useState("maximize");
  const [metric, setMetric] = useState("");
  const [agents, setAgents] = useState(1);
  const [chosenModel, setModel] = useState<string>();
  const model = chosenModel ?? models?.[0] ?? defaultModel ?? availableModels[0] ?? "";
  const [slurmMode, setSlurmMode] = useState<RemoteRunOptions["slurmMode"]>(options?.slurmMode ?? preflight?.recommendedSlurmMode ?? "disabled");
  const [egress, setEgress] = useState<RemoteRunOptions["egress"]>(options?.egress ?? preflight?.recommendedEgress ?? "E2");
  const [budget, setBudget] = useState(options?.maxCostUsd?.toString() ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [runDir, setRunDir] = useState<string>();
  const taskYaml = [
    "task:", `  name: ${JSON.stringify(metric.trim() || "remote-discovery")}`, `  description: ${JSON.stringify(`Optimize ${metric.trim() || "score"} with ${command.trim()}`)}`,
    "grader:", '  entrypoint: "grader.grader:Grader"', `  direction: ${goal}`, "  args:", `    preset: ${preset}`, `    command: ${JSON.stringify(command.trim())}`, `    metric_name: ${JSON.stringify(metric.trim())}`,
    "agents:", `  count: ${agents}`, "  runtime: opencode", `  model: ${JSON.stringify(model)}`, "workspace:", '  repo_path: "./seed"', "",
  ].join("\n");
  const launch = async () => {
    setBusy(true); setError(undefined); setRunDir(undefined);
    try {
      const result = await launchRemoteDiscovery(host.trim(), project.trim(), taskYaml, { syncLocal, slurmMode, egress, ...(budget && egress !== "E3" ? { maxCostUsd: Number(budget) } : {}) });
      setRunDir(result.runDir);
      onLaunched?.(result.runDir);
    } catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  return <section className="space-y-3 rounded-xl border border-border p-3" aria-label={t("taskTitle")}>
    <h3 className="font-medium">{t("taskTitle")}</h3>
    <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); void launch(); }}>
      <fieldset disabled={busy} className="contents">
        {!initialHost && <label className="text-sm sm:col-span-2">{t("serverHost")}<input required value={host} className={inputCls("mt-1 w-full")} onChange={(e) => setHost(e.target.value)} /></label>}
        <label className="text-sm">{t("projectSource")}<select className={inputCls("mt-1 w-full")} value={syncLocal ? "local" : "remote"} onChange={(e) => setSyncLocal(e.target.value === "local")}>
          <option value="remote">{t("remoteFolder")}</option><option value="local" disabled={isGatewayWeb}>{t("localFolder")}</option>
        </select></label>
        <div><label className="text-sm">{t("projectFolder")}<input required value={project} className={inputCls("mt-1 w-full")} onChange={(e) => setProject(e.target.value)} /></label>
          {syncLocal && isTauri && !isGatewayWeb && <button type="button" className="text-sm text-accent" onClick={() => void pickFolder().then((path) => { if (path) setProject(path); }).catch((e) => setError(String(e)))}>{t("chooseFolder")}</button>}
        </div>
        <label className="text-sm">{t("evaluationPreset")}<select value={preset} className={inputCls("mt-1 w-full")} onChange={(e) => { const next = e.target.value as keyof typeof commands; setPreset(next); setCommand(commands[next]); }}>
          {(Object.keys(commands) as Array<keyof typeof commands>).map((p) => <option key={p} value={p}>{t(p)}</option>)}
        </select></label>
        <label className="text-sm">{t("evalCommand")}<input required value={command} className={inputCls("mt-1 w-full font-mono")} onChange={(e) => setCommand(e.target.value)} /></label>
        <label className="text-sm">{t("goal")}<select value={goal} className={inputCls("mt-1 w-full")} onChange={(e) => setGoal(e.target.value)}><option value="maximize">{t("maximize")}</option><option value="minimize">{t("minimize")}</option></select></label>
        <label className="text-sm">{t("metric")}<input required value={metric} className={inputCls("mt-1 w-full")} onChange={(e) => setMetric(e.target.value)} /></label>
        <label className="text-sm">{t("agents")}<select value={agents} className={inputCls("mt-1 w-full")} onChange={(e) => { const count = Number(e.target.value); setAgents(count); if (count > 2 && preflight?.slurmAvailable) setSlurmMode("full_swarm"); }}>{[1, 2, 4, 8].map((count) => <option key={count} value={count}>{count}</option>)}</select></label>
        <label className="text-sm">{t("model")}<input required list={`${id}-models`} value={model} placeholder={t("chooseModel")} className={inputCls("mt-1 w-full")} onChange={(e) => setModel(e.target.value)} /><datalist id={`${id}-models`}>{availableModels.map((m) => <option key={m} value={m} />)}</datalist></label>
        {preflight?.slurmAvailable && <label className="text-sm sm:col-span-2">{t("slurmMode")}<select value={slurmMode} className={inputCls("mt-1 w-full")} onChange={(e) => setSlurmMode(e.target.value as typeof slurmMode)}><option value="eval_offload">{t("evalOffload")}</option><option value="full_swarm">{t("fullSwarm")}{agents > 2 ? ` · ${t("recommended")}` : ""}</option></select></label>}
        <label className="text-sm">{t("egressMode")}<select value={egress} className={inputCls("mt-1 w-full")} onChange={(e) => setEgress(e.target.value as typeof egress)}><option value="E1" disabled={preflight?.outboundHttps === false}>{t("direct")}</option><option value="E2">{t("tunnel")}</option><option value="E3">{t("relay")}</option></select></label>
        {egress !== "E3" && <label className="text-sm">{t("budget")}<input type="number" min="0.01" step="0.01" value={budget} className={inputCls("mt-1 w-full")} onChange={(e) => setBudget(e.target.value)} /></label>}
        <pre aria-label={t("preview")} className="max-h-52 overflow-auto whitespace-pre rounded bg-surface-2 p-3 text-xs sm:col-span-2">{taskYaml}</pre>
        <button type="submit" disabled={busy || !host.trim() || !project.trim() || !metric.trim() || !command.trim() || !model.trim()} className="rounded bg-accent px-3 py-2 text-sm text-white sm:col-span-2">{t((busy ? "working" : "launch"))}</button>
      </fieldset>
    </form>
    {error && <p role="alert" className="text-sm text-error">{t("launchError", { error })}</p>}
    {runDir && <p role="status" className="break-all text-sm">{t("launched", { runDir })}</p>}
  </section>;
}
