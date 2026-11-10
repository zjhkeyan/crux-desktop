import { useState } from "react";
import { useTranslation } from "react-i18next";
import { harvestRemoteRun } from "@/lib/tauri";

export function HarvestDialog({ host, runDir, winningCommit, baseline, best, insights = [], onClose }: {
  host: string;
  runDir: string;
  winningCommit?: string;
  baseline?: number;
  best?: number;
  insights?: Array<{ text: string; state: string }>;
  onClose?: () => void;
}) {
  const { t } = useTranslation("session", { keyPrefix: "discovery.remote" });
  const runId = runDir.split(/[\\/]/).filter(Boolean).slice(-1)[0] ?? "run";
  const [applyGitPatch, setApplyGitPatch] = useState(false);
  const [includeCheckpoints, setIncludeCheckpoints] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [result, setResult] = useState<Awaited<ReturnType<typeof harvestRemoteRun>>>();
  const verified = insights.filter((item) => ["PROMOTED", "CORROBORATED"].includes(item.state));
  const harvest = async () => {
    setBusy(true); setError(undefined); setResult(undefined);
    try { setResult(await harvestRemoteRun(host, runDir, { applyGitPatch: applyGitPatch && !!winningCommit, includeCheckpoints })); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  };
  return <section className="space-y-3 rounded-xl border border-border bg-surface p-3" aria-label={t("harvestTitle")}>
    <div className="flex items-center justify-between gap-2"><h3 className="font-medium">{t("harvestTitle")}</h3>{onClose && <button type="button" disabled={busy} onClick={onClose}>{t("close")}</button>}</div>
    <dl className="grid gap-2 text-sm"><div><dt className="text-muted">{t("winningCommit")}</dt><dd className="break-all font-mono">{winningCommit || t("notAvailable")}</dd></div><div><dt className="text-muted">{t("improvement")}</dt><dd>{`${baseline ?? "—"} → ${best ?? "—"}`}</dd></div></dl>
    <h4 className="text-sm font-medium">{t("verifiedInsights")}</h4>
    {verified.length ? <ul className="list-inside list-disc text-sm">{verified.map((item, i) => <li key={i}>{item.text}</li>)}</ul> : <p className="text-sm text-muted">{t("noInsights")}</p>}
    <fieldset disabled={busy} className="space-y-2 text-sm">
      <label className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={applyGitPatch && !!winningCommit} disabled={!winningCommit} onChange={(e) => setApplyGitPatch(e.target.checked)} />{t("applyPatch", { runId })}</label>
      {!winningCommit && <p className="text-xs text-muted">{t("verifiedOnly")}</p>}
      <label className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={includeCheckpoints} onChange={(e) => setIncludeCheckpoints(e.target.checked)} />{t("checkpoints")}</label>
      <button type="button" disabled={busy || !host.trim() || !runDir} onClick={() => void harvest()} className="rounded bg-accent px-3 py-2 text-white">{t((busy ? "working" : "harvest"))}</button>
    </fieldset>
    {error && <p role="alert" className="text-sm text-error">{t("harvestError", { error })}</p>}
    {result && <p role="status" className="break-words text-sm">{t("harvested", { count: result.filesCount, branch: result.branch ?? "—", report: result.reportPath ?? "—" })}</p>}
  </section>;
}
