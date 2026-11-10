import { useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { getDiscoveryView, resumeRemoteDiscovery } from "../../lib/tauri";
import type { DiscoveryView, EgressView, RemotePreflightReport, RemoteRunOptions } from "../../lib/gatewayHttp";
import { ConnectWizard, HarvestDialog, PreflightCard, TaskStudio } from "../remote";
import { ComparisonView, EvolutionExperimentView, type ComparisonData } from "../inspector/CruxResearchViews";
import { inputCls } from "../settings/inputCls";

type Row = Record<string, unknown>;
const tabs = ["board", "archive"] as const;
type Tab = typeof tabs[number];
const label = (value: unknown): string =>
  value == null
    ? "—"
    : typeof value === "number"
      ? Number.isInteger(value)
        ? String(value)
        : Number(value.toFixed(4)).toString()
      : typeof value === "object"
        ? JSON.stringify(value)
        : String(value);
function rows(value: unknown): Row[] {
  if (Array.isArray(value)) return value.filter((v): v is Row => v !== null && typeof v === "object");
  if (value && typeof value === "object") return Object.entries(value).map(([id, v]) => ({ id, ...(v && typeof v === "object" ? v : {}) }));
  return [];
}
const metrics = (r: Row): Array<["score" | "yield" | "potential", string]> => [
  ["score", label(r.best_score ?? r.score)],
  ["yield", label(r.yield_value ?? r.yield ?? r.total_credit)],
  ["potential", label(r.potential ?? r.pot)],
];
const nodeId = (row: Row) => label(row.commit ?? row.commit_hash ?? row.id);

/** Public discovery projections; runDir identifies a run in the active workspace. */
export function CruxDiscoveryTile({
  runDir,
  coralDir,
  host,
  className = "",
}: {
  runDir?: string;
  coralDir?: string;
  host?: string;
  className?: string;
}) {
  const targetDir = runDir ?? coralDir ?? "";
  const { t } = useTranslation("session");
  const id = useId();
  const [tab, setTab] = useState<Tab>("board");
  const [reload, setReload] = useState(0);
  const [snapshot, setSnapshot] = useState<{ dir: string; tab: Tab; data: Row; board?: Row; head?: Row; anchorError?: string }>();
  const [egressSnapshot, setEgressSnapshot] = useState<{ dir: string; data: EgressView }>();
  const [operator, setOperator] = useState<"new" | "harvest" | "auth" | "budget">();
  const [connectedHost, setConnectedHost] = useState("");
  const [launchConfig, setLaunchConfig] = useState<{ report: RemotePreflightReport; options: RemoteRunOptions }>();
  const [harvestData, setHarvestData] = useState<{ dir: string; board: Row; archive: Row }>();
  const [operatorError, setOperatorError] = useState<string>();
  const [operatorBusy, setOperatorBusy] = useState(false);
  const [cap, setCap] = useState("");
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    setLoading(true);
    setError(undefined);
    const read = (view: DiscoveryView) => getDiscoveryView<Row>(view, targetDir);
    const poll = async () => {
      const [view, head, egress] = await Promise.allSettled([read(tab), read("head"), read("egress")]);
      if (!active) return;
      setEgressSnapshot(egress.status === "fulfilled" ? { dir: targetDir, data: egress.value as EgressView } : undefined);
      if (view.status === "fulfilled") {
        setError(undefined);
        setSnapshot((previous) => ({
          dir: targetDir,
          tab,
          data: view.value,
          board: tab === "board" ? view.value : previous?.dir === targetDir ? previous.board : undefined,
          head: head.status === "fulfilled" ? head.value : undefined,
          anchorError: head.status === "rejected" ? String(head.reason) : undefined,
        }));
      } else setError(String(view.reason));
      setLoading(false);
      timer = setTimeout(() => void poll(), 5000);
    };
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [targetDir, tab, reload]);
  const data = snapshot?.dir === targetDir && snapshot.tab === tab ? snapshot.data : undefined;
  const board = snapshot?.dir === targetDir ? snapshot.board : undefined;
  const metadata = board?.metadata && typeof board.metadata === "object" ? board.metadata as Row : {};
  const egress = egressSnapshot?.dir === targetDir ? egressSnapshot.data : undefined;
  const telemetry = { ...board, ...metadata, ...egress } as EgressView;
  const discoveredHost = host || (typeof metadata.host === "string" ? metadata.host : typeof board?.host === "string" ? board.host : "");
  const remoteHost = discoveredHost || connectedHost;
  const egressKey = egress?.state === "RUNNING" ? egress.mode === "direct" || egress.mode === "relay" ? "sleepSafe" : egress.mode === "tunnel" ? "keepAwake" : "unknown"
    : egress?.state === "HOLDING" || egress?.state === "PAUSED_NO_EGRESS" ? "paused" : egress?.state === "PAUSED_AUTH" ? "auth" : egress?.state === "PAUSED_BUDGET" ? "budget" : egress?.state === "RESUMING" ? "resuming" : "unknown";
  const telemetryKeys = ["pinned_node", "slurm_job_id", "slurm_remaining", "gpu_util", "scratch_free_gb", "accumulated_cost_usd", "link_latency_ms"] as const;
  const openOperator = (next: typeof operator) => { setOperator(operator === next ? undefined : next); setOperatorError(undefined); };
  const harvest = async () => {
    setOperator("harvest"); setOperatorBusy(true); setOperatorError(undefined); setHarvestData(undefined);
    try {
      const [best, archive] = await Promise.all([getDiscoveryView<Row>("board", targetDir), getDiscoveryView<Row>("archive", targetDir)]);
      setHarvestData({ dir: targetDir, board: best, archive });
    } catch (e) { setOperatorError(String(e)); }
    finally { setOperatorBusy(false); }
  };
  const resume = async () => {
    if (operator === "budget" && (!Number.isFinite(Number(cap)) || Number(cap) <= Math.max(egress?.max_cost_usd ?? 0, egress?.accumulated_cost_usd ?? 0))) { setOperatorError(t("discovery.egress.capTooLow")); return; }
    setOperatorBusy(true); setOperatorError(undefined);
    try {
      const result = await resumeRemoteDiscovery(remoteHost, targetDir, operator === "budget" ? Number(cap) : undefined);
      if (!result.resumed) throw new Error(t("discovery.egress.signInHint"));
      setOperator(undefined); setReload((n) => n + 1);
    } catch (e) { setOperatorError(String(e)); }
    finally { setOperatorBusy(false); }
  };
  const harvestBoard = harvestData?.dir === targetDir ? harvestData.board : undefined;
  const best = harvestBoard?.best && typeof harvestBoard.best === "object" ? harvestBoard.best as Row : undefined;
  const winningCommit = best?.provisional || best?.refuted ? undefined : harvestBoard?.confirmed_best_commit ?? harvestBoard?.best_commit ?? best?.commit;
  const directions = rows(data?.directions);
  const attempts = rows(data?.attempts ?? data?.nodes ?? data?.members ?? data?.leaderboard ?? data?.population);
  const worktrees = rows(data?.worktrees);
  const insights = rows(data?.insights).filter((r) => ["PROMOTED", "CORROBORATED"].includes(label(r.state ?? r.status)));
  const constraints = rows(data?.constraints ?? data?.failure_constraints);
  const tools = rows(data?.tools ?? data?.skills);
  const direction = (r: Row, index: number) => {
    const claims = Array.isArray(r.active_claims) ? (r.active_claims as Row[]) : [];
    const claimedBy = claims.map((c) => label(c.agent_id ?? c.agent)).filter((s) => s !== "—").join(", ");
    return (
      <li key={label(r.id ?? index)} className="rounded border border-border p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <strong>{label(r.name ?? r.direction_id ?? r.id)}</strong>
          {claimedBy ? (
            <span className="rounded border border-border px-1.5 py-0.5 text-xs text-muted">Running · {claimedBy}</span>
          ) : r.elo_rating != null ? (
            <span className="rounded border border-border px-1.5 py-0.5 text-xs text-muted">Elo {label(r.elo_rating)}</span>
          ) : null}
        </div>
        {Boolean(r.description || r.method) && <p className="mt-1 text-xs text-muted">{label(r.description || r.method)}</p>}
        <dl className="mt-2 grid grid-cols-3 gap-2 text-xs">
          {metrics(r).map(([key, value]) => (
            <div key={key}><dt className="text-muted">{t(`discovery.${key}`)}</dt><dd>{value}</dd></div>
          ))}
        </dl>
      </li>
    );
  };
  const badge = (r: Row) => {
    const state = r.refuted ? "REFUTED" : r.provisional ? "PROVISIONAL" : label(r.state ?? r.status);
    return ["PROVISIONAL", "REFUTED", "PROMOTED", "CORROBORATED"].includes(state)
      ? <span className="rounded border border-border px-1 text-xs">{state}</span> : null;
  };
  return (
    <section className={`flex min-h-0 min-w-0 flex-col rounded-xl border border-border bg-surface text-text ${className}`} aria-label={t("discovery.title")}>
      <header className="flex flex-wrap items-center justify-between gap-2 p-3">
        <div className="min-w-0"><h2 className="font-medium">{t("discovery.title")}</h2><p role="status" className="text-xs">{t(`discovery.egress.${egressKey}`)}</p></div>
        <div className="flex flex-wrap gap-2 text-sm">
          {egressKey === "auth" && <button type="button" onClick={() => openOperator("auth")}>{t("discovery.egress.reconnect")}</button>}
          {egressKey === "budget" && <button type="button" onClick={() => openOperator("budget")}>{t("discovery.egress.raiseCap")}</button>}
          <button type="button" aria-expanded={operator === "new"} onClick={() => openOperator("new")}>{t("discovery.remote.newRun")}</button>
          <button type="button" disabled={operatorBusy} aria-expanded={operator === "harvest"} onClick={() => operator === "harvest" ? openOperator(undefined) : void harvest()}>{t("discovery.remote.harvestTitle")}</button>
          <button type="button" className="rounded px-2 py-1 hover:bg-surface-2" onClick={() => setReload((n) => n + 1)}>{t("discovery.refresh")}</button>
        </div>
      </header>
      {telemetryKeys.some((key) => telemetry[key] != null) && <dl role="group" aria-label={t("discovery.telemetry.title")} className="flex flex-wrap gap-x-4 gap-y-1 border-t border-border px-3 py-2 text-xs">
        {telemetryKeys.filter((key) => telemetry[key] != null).map((key) => <div key={key}><dt className="text-muted">{t(`discovery.telemetry.${key}`)}</dt><dd>{label(telemetry[key])}</dd></div>)}
      </dl>}
      {operator && <div className="max-h-[70vh] space-y-3 overflow-auto border-t border-border p-3">
        <button type="button" disabled={operatorBusy} className="text-sm text-muted" onClick={() => setOperator(undefined)}>{t("discovery.remote.close")}</button>
        {operator === "new" && <>
          {!remoteHost && <ConnectWizard onConnected={(value) => { setConnectedHost(value); setLaunchConfig(undefined); }} />}
          {remoteHost && !launchConfig && <PreflightCard host={remoteHost} onContinue={(report, options) => setLaunchConfig({ report, options })} />}
          {remoteHost && launchConfig && <TaskStudio host={remoteHost} preflight={launchConfig.report} options={launchConfig.options} />}
        </>}
        {operator === "harvest" && <>
          {!discoveredHost && <label className="block text-sm">{t("discovery.remote.serverHost")}<input required value={connectedHost} onChange={(e) => setConnectedHost(e.target.value)} className={inputCls("mt-1 w-full")} /></label>}
          {operatorBusy && <p role="status">{t("discovery.loading")}</p>}
          {harvestBoard && <HarvestDialog key={targetDir} host={remoteHost} runDir={targetDir} winningCommit={typeof winningCommit === "string" ? winningCommit : undefined}
            baseline={typeof harvestBoard.baseline_score === "number" ? harvestBoard.baseline_score : undefined} best={typeof harvestBoard.best_score === "number" ? harvestBoard.best_score : typeof best?.score === "number" ? best.score : undefined}
            insights={rows(harvestData?.archive.insights).map((row) => ({ text: label(row.text ?? row.summary ?? row.claim), state: label(row.state ?? row.status) }))} />}
        </>}
        {(operator === "auth" || operator === "budget") && <form className="space-y-2" onSubmit={(event) => { event.preventDefault(); void resume(); }}>
          {!discoveredHost && <label className="block text-sm">{t("discovery.remote.serverHost")}<input required value={connectedHost} onChange={(e) => setConnectedHost(e.target.value)} className={inputCls("mt-1 w-full")} /></label>}
          {operator === "auth" && <><p className="text-sm">{t("discovery.egress.signInHint")}</p><a className="text-sm text-accent" href="/settings/agents">{t("discovery.egress.reconnect")}</a></>}
          {operator === "budget" && <label className="block text-sm">{t("discovery.egress.newCap")}<input required type="number" min="0.01" step="0.01" value={cap} onChange={(e) => setCap(e.target.value)} className={inputCls("mt-1 w-full")} /></label>}
          <button type="submit" disabled={operatorBusy || !remoteHost.trim()} className="rounded bg-accent px-3 py-1 text-sm text-white">{t(`discovery.egress.${operator === "budget" ? "raiseCap" : "resume"}`)}</button>
        </form>}
        {operatorError && <p role="alert" className="text-sm text-error">{t(operator === "harvest" ? "discovery.remote.harvestError" : "discovery.egress.resumeError", { error: operatorError })}</p>}
      </div>}
      <div role="tablist" aria-label={t("discovery.views")} className="flex overflow-x-auto border-b border-border">
        {tabs.map((view, index) => (
          <button key={view} id={`${id}-${view}`} type="button" role="tab" aria-selected={tab === view} aria-controls={`${id}-panel`} tabIndex={tab === view ? 0 : -1}
            onClick={() => setTab(view)} onKeyDown={(event) => {
              const offset = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
              const next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1] : offset ? tabs[(index + offset + tabs.length) % tabs.length] : undefined;
              if (next) { event.preventDefault(); setTab(next); document.getElementById(`${id}-${next}`)?.focus(); }
            }} className={`shrink-0 px-3 py-2 text-sm ${tab === view ? "border-b-2 border-current" : "text-muted"}`}>{t(`discovery.${view}`)}</button>
        ))}
      </div>
      <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${tab}`} aria-busy={loading} className="min-h-0 overflow-auto p-3">
        {loading && <p role="status">{t("discovery.loading")}</p>}
        {error && <p role="alert">{t("discovery.error", { error })}</p>}
        {!loading && !error && data && <>
          {tab === "board" && <>
            {attempts.length > 0 && <EvolutionExperimentView items={attempts} />}
            {worktrees.length > 0 && (
              <div className="mb-3 space-y-2" role="region" aria-label="Crux Worktree Sandboxes">
                <div className="text-xs font-medium text-muted">Worktree 沙箱与分支状态 ({worktrees.length})</div>
                <ul className="grid gap-2 sm:grid-cols-2">
                  {worktrees.map((wt, idx) => (
                    <li key={label(wt.taskId ?? wt.id ?? idx)} className="rounded border border-border bg-surface-2/30 p-2.5 text-xs">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <strong className="font-mono">{label(wt.displayName ?? wt.taskId ?? wt.id)}</strong>
                        <span className="rounded border border-border px-1.5 py-0.5 text-[11px] font-medium">
                          {label(wt.workspaceStatus ?? wt.status)}
                        </span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[11px] text-muted">
                        <span>branch: {label(wt.branch)}</span>
                        {Boolean(wt.baseBranch || wt.parent_hash) && <span>base: {label(wt.baseBranch ?? wt.parent_hash)}</span>}
                        {Boolean(wt.commit ?? wt.commit_hash) && <span>commit: {label(wt.commit ?? wt.commit_hash)}</span>}
                        {Boolean(wt.agent) && <span>agent: {label(wt.agent)}</span>}
                      </div>
                      {Boolean(wt.comment || wt.title) && (
                        <p className="mt-1 text-xs text-muted">{label(wt.comment ?? wt.title)}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            <ul className="grid gap-2 sm:grid-cols-2">{directions.filter((r) => !r.dormant && r.state !== "dormant").map(direction)}</ul>
            <div className="my-2 rounded border border-dashed border-border p-3"><strong>{t("discovery.newArm")}</strong><p className="text-sm text-muted">{label(data.new_arm ?? data.NEW ?? data.new_arm_wanted_seats)}</p></div>
            <details><summary className="cursor-pointer text-sm text-muted">{t("discovery.dormant")}</summary><ul className="mt-2 grid gap-2">{directions.filter((r) => r.dormant || r.state === "dormant").map(direction)}</ul></details>
          </>}
          {tab === "archive" && <>
            {attempts.length > 0 && <EvolutionExperimentView items={attempts} />}
            {(data.comparison && typeof data.comparison === "object") && (
              <ComparisonView data={data.comparison as ComparisonData} />
            )}
            {attempts.length > 0 && <ul className="mb-2 space-y-2">{attempts.map((r, index) => {
              const meta = r.metadata && typeof r.metadata === "object" ? r.metadata as Row : undefined;
              return (
                <li key={label(r.commit_hash ?? r.id ?? index)} className="rounded border border-border p-2">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                    <strong>{nodeId(r)} · {label(r.direction_id ?? r.operator ?? meta?.direction_id)}</strong>
                    <span>{t("discovery.score")}: <strong>{label(r.score)}</strong></span>
                  </div>
                  <p className="text-sm">{label(r.title ?? r.summary ?? r.description ?? r.method ?? meta?.method)}</p>
                </li>
              );
            })}</ul>}
            <ul className="space-y-2">{insights.map((r, index) => <li key={label(r.id ?? index)} className="rounded border border-border p-2">{badge(r)} <p>{label(r.text ?? r.summary ?? r.claim)}</p></li>)}</ul>
            {tools.length > 0 && <ul className="mt-2 space-y-2">{tools.map((r, index) => (
              <li key={label(r.id ?? r.name ?? index)} className="rounded border border-border p-2">
                <strong className="text-xs">{label(r.name ?? r.id)}</strong>
                <p className="text-xs text-muted">{label(r.description ?? r.path)}</p>
              </li>
            ))}</ul>}
            {constraints.length > 0 && <>
              <h3 className="my-2 text-sm font-medium">{t("discovery.constraints")}</h3>
              <ul className="space-y-2">{constraints.map((r, index) => <li key={label(r.id ?? index)} className="rounded border border-border p-2"><p>{label(r.text ?? r.constraint ?? r.message)}</p><p className="text-xs text-muted">{t("discovery.scope")}: {label(r.scope)} · {t("discovery.ttl")}: {label(r.ttl ?? r.expires_at)}</p></li>)}</ul>
            </>}
            {attempts.length === 0 && insights.length === 0 && constraints.length === 0 && tools.length === 0 && <p className="text-muted">{t("discovery.empty")}</p>}
          </>}
        </>}
      </div>
    </section>
  );
}

export const CoralDiscoveryTile = CruxDiscoveryTile;
