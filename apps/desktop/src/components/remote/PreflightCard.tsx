import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { inputCls } from "@/components/settings/inputCls";
import { runRemotePreflight } from "@/lib/tauri";
import type { RemotePreflightReport, RemoteRunOptions } from "@/lib/gatewayHttp";

export function PreflightCard({ host, agents = 1, onContinue }: {
  host: string;
  agents?: number;
  onContinue?: (report: RemotePreflightReport, options: RemoteRunOptions) => void;
}) {
  const { t } = useTranslation("session", { keyPrefix: "discovery.remote" });
  const [snapshot, setSnapshot] = useState<{ host: string; report: RemotePreflightReport }>();
  const [retry, setRetry] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string>();
  const [mode, setMode] = useState<RemoteRunOptions["slurmMode"]>();
  const [egress, setEgress] = useState<RemoteRunOptions["egress"]>();
  const [budget, setBudget] = useState("");
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    setSnapshot(undefined);
    setMode(undefined);
    setEgress(undefined);
    void runRemotePreflight(host).then((report) => { if (active) setSnapshot({ host, report }); })
      .catch((e) => { if (active) setError(String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [host, retry]);
  const report = snapshot?.host === host ? snapshot.report : undefined;
  const slurmMode = mode ?? (report?.slurmAvailable ? agents > 2 ? "full_swarm" : report.recommendedSlurmMode === "disabled" ? "eval_offload" : report.recommendedSlurmMode : "disabled");
  const aiMode = egress ?? (report?.recommendedEgress === "E1" && !report.outboundHttps ? "E2" : report?.recommendedEgress ?? "E2");
  const gpuNames = [...new Set(report?.gpus.map((gpu) => gpu.name))];
  const engineReady = report?.engineReady === true && report.runtimeReady === true;
  const engineMissing = report?.engineReady === false || report?.runtimeReady === false;
  return <section className="space-y-3 rounded-xl border border-border p-3" aria-label={t("preflightTitle")} aria-busy={loading}>
    <h3 className="font-medium">{t("preflightTitle")}</h3>
    {loading && <p role="status">{t("checking")}</p>}
    {error && <div role="alert"><p>{t("preflightError", { error })}</p><button type="button" onClick={() => setRetry((n) => n + 1)}>{t("retry")}</button></div>}
    {report && <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); onContinue?.(report, { slurmMode, egress: aiMode, ...(budget ? { maxCostUsd: Number(budget) } : {}) }); }}>
      <p className="break-words text-xs text-muted">{report.pinnedNode} · {report.osArch}</p>
      <dl className="divide-y divide-border text-sm">
        <div className="py-2"><dt className="font-medium">{t("gpus")}</dt><dd>{gpuNames.length ? gpuNames.map((name) => t("gpuSummary", { count: report.gpus.filter((gpu) => gpu.name === name).length, name })).join(" · ") : t("cpuOnly")}</dd></div>
        <div className="space-y-1 py-2"><dt className="font-medium">{t("scheduler")}</dt><dd>{report.slurmAvailable ? report.slurmPartitions.join(", ") : t("noSlurm")}
          {report.slurmAvailable && <><label className="mt-1 block">{t("slurmMode")}<select className={inputCls("mt-1 w-full")} value={slurmMode} onChange={(e) => setMode(e.target.value as typeof slurmMode)}>
            <option value="eval_offload">{t("evalOffload")}</option><option value="full_swarm">{t("fullSwarm")}{agents > 2 ? ` · ${t("recommended")}` : ""}</option>
          </select></label>{slurmMode === "eval_offload" && <p className="text-xs text-warning">{t("loginWarning")}</p>}</>}
        </dd></div>
        <div className="py-2"><dt className="font-medium">{t("storage")}</dt><dd>{t("diskFree", { free: report.diskFreeGiB, path: report.scratchPath })}{(report.homeFreeGiB ?? report.diskFreeGiB) < 5 && <p className="text-xs text-warning">{t("relocated")}</p>}</dd></div>
        <div className="py-2"><dt className="font-medium">{t("runtime")}</dt><dd>{t((engineReady ? "runtimeReady" : engineMissing ? "runtimeMissing" : "runtimeUnknown"))}</dd></div>
        <div className="py-2"><dt className="font-medium">{t("aiAccess")}</dt><dd><label className="block">{t("egressMode")}<select className={inputCls("mt-1 w-full")} value={aiMode} onChange={(e) => setEgress(e.target.value as typeof aiMode)}>
          <option value="E1" disabled={!report.outboundHttps}>{t("direct")}</option><option value="E2">{t("tunnel")}</option><option value="E3">{t("relay")}</option>
        </select></label>{!report.outboundHttps && <p className="mt-1 text-xs text-muted">{t("noOutbound")}</p>}
          {aiMode !== "E3" && <label className="mt-2 block">{t("budget")}<input type="number" min="0.01" step="0.01" value={budget} onChange={(e) => setBudget(e.target.value)} className={inputCls("mt-1 w-full")} /></label>}
        </dd></div>
      </dl>
      {onContinue && <button type="submit" disabled={engineMissing} className="rounded bg-accent px-3 py-2 text-sm text-white">{t("continue")}</button>}
    </form>}
  </section>;
}
