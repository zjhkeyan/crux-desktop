import { useId, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  Circle,
  GitBranch,
  Layers,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Trophy,
  Users,
  XCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/cn";

/* eslint-disable i18next/no-literal-string -- defaultValue fallbacks & SVG attributes */

const MAX_COLOR = "#00d4ff";
const GEN_MAX_COLOR = "#a66cff";
const ISLAND_COLORS = [
  "#00d4ff",
  "#ff6b6b",
  "#ffd93d",
  "#6bcb77",
  "#a66cff",
  "#ff8c42",
  "#e84393",
  "#00b894",
  "#fd79a8",
  "#74b9ff",
];

export type ExperimentTab = "simulation" | "trend";

export interface EvoNode {
  id: string;
  generation: number;
  island: number;
  rawScore: number;
  score: number;
  name: string;
  parentIds: string[];
  unscored: boolean;
}

export interface ExpData {
  scored: EvoNode[];
  unscored: EvoNode[];
  islandCount: number;
  maxGeneration: number;
  population: number;
  bestScore: number | null;
  gens: { g: number; max: number; genMax: number }[];
}

export function buildExpData(items: Record<string, unknown>[]): ExpData {
  const scored: EvoNode[] = [];
  const unscored: EvoNode[] = [];
  const directionIslands = new Map<string, number>();
  for (let idx = 0; idx < items.length; idx++) {
    const raw = items[idx];
    const d = (raw.data && typeof raw.data === "object" ? raw.data : raw) as Record<string, unknown>;
    const meta = (d.metadata && typeof d.metadata === "object" ? d.metadata : undefined) as
      | Record<string, unknown>
      | undefined;
    const evaluation = (d.evaluation && typeof d.evaluation === "object" ? d.evaluation : undefined) as
      | Record<string, unknown>
      | undefined;
    const rawVal =
      (typeof d.score === "number" ? d.score : undefined) ??
      (typeof evaluation?.score === "number" ? evaluation.score : undefined) ??
      (typeof evaluation?.objective === "number" ? evaluation.objective : undefined) ??
      (typeof evaluation?.fitness === "number" ? evaluation.fitness : undefined);
    const parentSingle = d.parent_id ?? d.parent ?? d.parent_hash;
    const parentIds = Array.isArray(d.parent_ids)
      ? d.parent_ids.map(String)
      : typeof parentSingle === "string" && parentSingle
        ? [parentSingle]
        : [];
    const dirId = typeof d.direction_id === "string"
      ? d.direction_id
      : typeof meta?.direction_id === "string"
        ? meta.direction_id
        : undefined;
    let fallbackIsland = 0;
    if (dirId) {
      let existing = directionIslands.get(dirId);
      if (existing === undefined) {
        existing = directionIslands.size;
        directionIslands.set(dirId, existing);
      }
      fallbackIsland = existing;
    }
    const id = String(d.id ?? d.commit ?? d.commit_hash ?? `gen_${idx}`);
    const node: EvoNode = {
      id,
      generation: Number(d.generation ?? idx),
      island: Number(d.island_id ?? d.island ?? fallbackIsland),
      rawScore: typeof rawVal === "number" && Number.isFinite(rawVal) ? rawVal : 0,
      score: 0,
      name: String(d.name ?? d.title ?? d.summary ?? id),
      parentIds,
      unscored: typeof rawVal !== "number" || !Number.isFinite(rawVal),
    };
    if (node.unscored) unscored.push(node);
    else scored.push(node);
  }

  if (scored.length > 0) {
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    for (const n of scored) {
      if (n.rawScore < min) min = n.rawScore;
      if (n.rawScore > max) max = n.rawScore;
    }
    const range = max - min;
    for (const n of scored) {
      n.score = range > 0 ? (n.rawScore - min) / range : 0.5;
    }
  }

  const all = [...scored, ...unscored];
  const islandCount = new Set(all.map((n) => n.island)).size || 1;
  let maxGeneration = 0;
  for (const n of all) {
    if (n.generation > maxGeneration) maxGeneration = n.generation;
  }
  let bestScore: number | null = null;
  for (const n of scored) {
    if (bestScore === null || n.rawScore > bestScore) bestScore = n.rawScore;
  }

  const genMap = new Map<number, number[]>();
  for (const n of scored) {
    if (!genMap.has(n.generation)) genMap.set(n.generation, []);
    genMap.get(n.generation)?.push(n.rawScore);
  }
  const genKeys = [...genMap.keys()].sort((a, b) => a - b);
  const gens: { g: number; max: number; genMax: number }[] = [];
  let runningMax = Number.NEGATIVE_INFINITY;
  for (const g of genKeys) {
    const genScores = genMap.get(g) ?? [];
    const genMax = genScores.length ? Math.max(...genScores) : runningMax;
    if (genMax > runningMax) runningMax = genMax;
    gens.push({ g, max: runningMax, genMax });
  }

  return {
    scored,
    unscored,
    islandCount,
    maxGeneration,
    population: all.length,
    bestScore,
    gens,
  };
}

function fmt(v: number): string {
  if (!Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1000) return `${(v / 1000).toFixed(1)}k`;
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(2);
}

function niceNum(range: number, round: boolean): number {
  const exp = Math.floor(Math.log10(range || 1));
  const frac = (range || 1) / 10 ** exp;
  let nf: number;
  if (round) {
    nf = frac < 1.5 ? 1 : frac < 3 ? 2 : frac < 7 ? 5 : 10;
  } else {
    nf = frac <= 1 ? 1 : frac <= 2 ? 2 : frac <= 5 ? 5 : 10;
  }
  return nf * 10 ** exp;
}

function niceScale(
  min: number,
  max: number,
  maxTicks = 4,
): { niceMin: number; niceMax: number; ticks: number[] } {
  let lo = min;
  let hi = max;
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const range = niceNum(hi - lo, false);
  const step = niceNum(range / Math.max(1, maxTicks - 1), true) || 1;
  const niceMin = Math.floor(lo / step) * step;
  const niceMax = Math.ceil(hi / step) * step;
  const ticks: number[] = [];
  for (let v = niceMin; v <= niceMax + step * 0.5; v += step) ticks.push(v);
  return { niceMin, niceMax, ticks };
}

function pickIndices(len: number, n: number): number[] {
  if (len <= n) return Array.from({ length: len }, (_, i) => i);
  const out: number[] = [];
  for (let i = 0; i < n; i++) out.push(Math.round((i * (len - 1)) / (n - 1)));
  return [...new Set(out)];
}

export function EvolutionExperimentView({ items }: { items: Record<string, unknown>[] }) {
  const { t } = useTranslation(["inspector", "session"]);
  const [tab, setTab] = useState<ExperimentTab>("simulation");
  const data = useMemo(() => buildExpData(items), [items]);
  const target: ExperimentTab = tab === "simulation" ? "trend" : "simulation";
  const TargetIcon = target === "simulation" ? Activity : TrendingUp;
  const targetLabel =
    target === "simulation"
      ? t("cruxResearch.experiment.simulation", { defaultValue: "Island Simulation" })
      : t("cruxResearch.experiment.trend", { defaultValue: "Score Trend" });

  if (data.population === 0) return null;

  return (
    <div className="mb-3 rounded-lg border border-border bg-surface-2/40 p-2.5">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-text">
          {tab === "simulation"
            ? t("cruxResearch.experiment.simulationTitle", { defaultValue: "Multi-Island Evolution & Lineage" })
            : t("cruxResearch.experiment.trendTitle", { defaultValue: "Cumulative & Generation Score Curve" })}
        </span>
        <button
          type="button"
          onClick={() => setTab(target)}
          aria-label={`Switch to ${targetLabel}`}
          className="inline-flex shrink-0 items-center gap-1 rounded border border-border bg-surface px-2 py-0.5 text-[11px] text-muted transition-colors hover:text-text"
        >
          <TargetIcon className="h-3 w-3" />
          {targetLabel}
        </button>
      </div>
      {tab === "simulation" ? <SimulationView data={data} /> : <TrendView data={data} />}
    </div>
  );
}

function SimulationView({ data }: { data: ExpData }) {
  const all = useMemo(() => [...data.scored, ...data.unscored], [data.scored, data.unscored]);

  const layout = useMemo(() => {
    const islands = [...new Set(all.map((n) => n.island))].sort((a, b) => a - b);
    const islandIdx = new Map(islands.map((is, i) => [is, i]));
    const laneCount = Math.max(1, islands.length);

    const W = 300;
    const PAD_L = 24;
    const PAD_R = 10;
    const PAD_T = 6;
    const PAD_B = 6;
    const LANE_H = 34;
    const H = PAD_T + PAD_B + laneCount * LANE_H;
    const iw = W - PAD_L - PAD_R;
    const gmax = Math.max(1, data.maxGeneration);
    const xOf = (g: number) => PAD_L + (g / gmax) * iw;
    const laneTop = (is: number) => PAD_T + (islandIdx.get(is) ?? 0) * LANE_H;
    const laneCenter = (is: number) => laneTop(is) + LANE_H / 2;

    const groups = new Map<string, EvoNode[]>();
    for (const n of all) {
      const k = `${n.generation}-${n.island}`;
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k)?.push(n);
    }
    const pos = new Map<string, { x: number; y: number; node: EvoNode }>();
    for (const [k, nodes] of groups) {
      const [g, is] = k.split("-").map(Number);
      const cx = xOf(g);
      const cy = laneCenter(is);
      const gap = Math.min(9, (LANE_H - 6) / Math.max(1, nodes.length));
      nodes.forEach((n, i) => {
        pos.set(n.id, {
          x: cx,
          y: cy + (i - (nodes.length - 1) / 2) * gap,
          node: n,
        });
      });
    }

    const links: { x1: number; y1: number; x2: number; y2: number }[] = [];
    for (const n of all) {
      const cp = pos.get(n.id);
      if (!cp) continue;
      for (const pid of n.parentIds) {
        const pp = pos.get(pid);
        if (pp) links.push({ x1: pp.x, y1: pp.y, x2: cp.x, y2: cp.y });
      }
    }

    return { islands, laneTop, W, H, PAD_L, PAD_R, LANE_H, pos, links };
  }, [all, data.maxGeneration]);

  const bestId = useMemo(() => {
    let best: EvoNode | null = null;
    for (const n of data.scored) {
      if (best == null || n.rawScore > best.rawScore) best = n;
    }
    return best?.id ?? null;
  }, [data.scored]);

  const metrics = [
    { key: "current", icon: GitBranch, label: "Gen", value: `${data.maxGeneration}` },
    { key: "population", icon: Users, label: "Pop", value: `${data.population}` },
    { key: "islands", icon: Layers, label: "Islands", value: `${data.islandCount}` },
    { key: "best", icon: Trophy, label: "Best", value: data.bestScore != null ? fmt(data.bestScore) : "—" },
  ];

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-4 gap-1.5">
        {metrics.map((m) => {
          const Icon = m.icon;
          return (
            <div
              key={m.key}
              title={`${m.label}: ${m.value}`}
              className="flex items-center justify-center gap-1 rounded border border-border bg-surface px-1.5 py-1"
            >
              <Icon className="h-3 w-3 shrink-0 text-accent" />
              <span className="truncate text-xs font-semibold tabular-nums text-text">{m.value}</span>
            </div>
          );
        })}
      </div>

      <div className="rounded border border-border bg-surface p-1.5">
        <svg
          viewBox={`0 0 ${layout.W} ${layout.H}`}
          className="h-auto w-full"
          role="img"
          aria-label="island evolution graph"
        >
          <title>island evolution</title>
          {layout.islands.map((is, i) => (
            <g key={is}>
              <rect
                x={layout.PAD_L}
                y={layout.laneTop(is)}
                width={layout.W - layout.PAD_L - layout.PAD_R}
                height={layout.LANE_H}
                fill={ISLAND_COLORS[is % ISLAND_COLORS.length]}
                opacity={i % 2 === 0 ? 0.08 : 0.04}
              />
              <text
                x={layout.PAD_L - 4}
                y={layout.laneTop(is) + layout.LANE_H / 2}
                textAnchor="end"
                dominantBaseline="middle"
                fontSize={8}
                fontWeight={600}
                fill={ISLAND_COLORS[is % ISLAND_COLORS.length]}
              >
                {is + 1}
              </text>
            </g>
          ))}
          {layout.links.map((l, idx) => (
            <line
              key={idx}
              x1={l.x1}
              y1={l.y1}
              x2={l.x2}
              y2={l.y2}
              stroke="currentColor"
              strokeWidth={0.6}
              className="text-muted/40"
            />
          ))}
          {data.unscored.map((n) => {
            const p = layout.pos.get(n.id);
            if (!p) return null;
            return <circle key={n.id} cx={p.x} cy={p.y} r={2} className="fill-muted/40" />;
          })}
          {data.scored.map((n) => {
            const p = layout.pos.get(n.id);
            if (!p) return null;
            const isBest = n.id === bestId;
            return (
              <circle
                key={n.id}
                cx={p.x}
                cy={p.y}
                r={isBest ? 4.5 : 2.8}
                fill={ISLAND_COLORS[n.island % ISLAND_COLORS.length]}
                opacity={isBest ? 1 : 0.85}
              />
            );
          })}
        </svg>
      </div>
    </div>
  );
}

function TrendView({ data }: { data: ExpData }) {
  const gid = useId();
  const W = 300;
  const H = 120;
  const PL = 34;
  const PR = 10;
  const PT = 12;
  const PB = 20;
  const iw = W - PL - PR;
  const ih = H - PT - PB;
  const gmax = Math.max(1, data.maxGeneration);

  const vals = data.gens.flatMap((d) => [d.max, d.genMax]);
  const rawMin = vals.length ? Math.min(...vals) : 0;
  const rawMax = vals.length ? Math.max(...vals) : 1;
  const { niceMin: yMin, niceMax: yMax, ticks: yTicks } = niceScale(rawMin, rawMax, 4);
  const yRange = yMax - yMin || 1;
  const xOf = (g: number) => PL + (g / gmax) * iw;
  const yOf = (v: number) => PT + (1 - (v - yMin) / yRange) * ih;
  const maxPts = data.gens.map((d) => `${xOf(d.g)},${yOf(d.max)}`).join(" ");
  const genMaxPts = data.gens.map((d) => `${xOf(d.g)},${yOf(d.genMax)}`).join(" ");
  const xTickIdx = pickIndices(data.gens.length, 4);

  if (data.gens.length === 0) {
    return <p className="py-4 text-center text-xs text-muted">No scored individuals yet.</p>;
  }

  return (
    <div className="rounded border border-border bg-surface p-1.5">
      <svg viewBox={`0 0 ${W} ${H}`} className="h-auto w-full" role="img" aria-label="evolution trend">
        <title>evolution trend</title>
        {yTicks.map((v) => (
          <g key={v}>
            <line
              x1={PL}
              y1={yOf(v)}
              x2={W - PR}
              y2={yOf(v)}
              stroke="currentColor"
              strokeWidth={0.5}
              className="text-border"
            />
            <text
              x={PL - 4}
              y={yOf(v)}
              textAnchor="end"
              dominantBaseline="middle"
              className="fill-muted"
              fontSize={7}
            >
              {fmt(v)}
            </text>
          </g>
        ))}
        {xTickIdx.map((i) => {
          const g = data.gens[i].g;
          const anchor = i === 0 ? "start" : i === data.gens.length - 1 ? "end" : "middle";
          return (
            <text
              key={`x-${g}`}
              x={xOf(g)}
              y={H - PB + 10}
              textAnchor={anchor}
              className="fill-muted"
              fontSize={7}
            >
              {g}
            </text>
          );
        })}
        <polyline
          points={genMaxPts}
          fill="none"
          stroke={GEN_MAX_COLOR}
          strokeWidth={1.4}
          strokeDasharray="5 3"
        />
        <polyline points={maxPts} fill="none" stroke={MAX_COLOR} strokeWidth={2} />
        {data.gens.map((d) => (
          <circle key={`${gid}-${d.g}`} cx={xOf(d.g)} cy={yOf(d.max)} r={1.6} fill={MAX_COLOR} />
        ))}
      </svg>
      <div className="mt-1 flex items-center justify-center gap-3 text-[10px] text-muted">
        <span className="inline-flex items-center gap-1">
          <span className="h-0.5 w-3 rounded-full" style={{ backgroundColor: MAX_COLOR }} />
          Cumulative Best (max)
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-0 w-3 border-t border-dashed" style={{ borderColor: GEN_MAX_COLOR }} />
          Generation Best (genMax)
        </span>
      </div>
    </div>
  );
}

// ── Stage 13 crux_evolve_comparison.json View ─────────────────────────────────────

export interface ComparisonAlgorithm {
  baseline?: number | null;
  evolved?: number | null;
  delta_pct?: number | null;
  promoted?: boolean | null;
  failed?: boolean | null;
  n_instances_compared?: number | null;
  n_instances_total?: number | null;
  lost_instances?: number | null;
  reason?: string | null;
}

export interface ComparisonData {
  generated?: string | null;
  metric_direction?: string | null;
  base?: string | null;
  n_promoted?: number | null;
  algorithms?: Record<string, ComparisonAlgorithm> | null;
}

function formatCompareValue(value: number | null | undefined, digits = 6): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toFixed(digits);
}

function formatDeltaPct(pct: number): string {
  return `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function formatTick(value: number): string {
  return value.toFixed(4).replace(/\.?0+$/, "");
}

export function ComparisonView({ data }: { data: ComparisonData }) {
  const entries = Object.entries(data.algorithms ?? {});
  const direction = (data.metric_direction ?? "maximize").toLowerCase();
  const promotedCount = data.n_promoted ?? entries.filter(([, a]) => a.promoted === true).length;
  const failedCount = entries.filter(([, a]) => a.failed === true).length;

  const scores = entries
    .flatMap(([, a]) => [a.baseline, a.evolved])
    .filter((v): v is number => v != null && Number.isFinite(v));
  const rawMin = scores.length ? Math.min(...scores) : 0;
  const rawMax = scores.length ? Math.max(...scores) : 1;
  const pad = Math.max((rawMax - rawMin) * 0.6, Math.abs(rawMax) * 0.002, 1e-9);
  const domain = { min: rawMin - pad, max: rawMax + pad };

  const maxAbsDelta = entries.reduce(
    (m, [, a]) => (a.delta_pct != null && Number.isFinite(a.delta_pct) ? Math.max(m, Math.abs(a.delta_pct)) : m),
    0,
  );
  const sorted = [...entries].sort((a, b) => (b[1].delta_pct ?? -Infinity) - (a[1].delta_pct ?? -Infinity));
  const hasCoverageGap = entries.some(([, a]) => {
    const total = a.n_instances_total ?? 0;
    const compared = a.n_instances_compared ?? 0;
    return (a.lost_instances ?? 0) > 0 || (total > 0 && compared < total);
  });

  return (
    <div className="space-y-3 p-3 text-text" aria-label="Algorithm Evolution Comparison">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-accent" />
          <div>
            <h3 className="text-sm font-semibold">Algorithm Promotion & Evaluator Comparison</h3>
            <p className="text-xs text-muted">
              Direction: <span className="font-mono">{direction}</span> · Base: <span className="font-mono">{data.base || "baseline"}</span>
            </p>
          </div>
        </div>
        <span className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 text-xs font-medium">
          Promoted: {promotedCount}/{entries.length}
          {failedCount > 0 ? ` · Failed: ${failedCount}` : ""}
        </span>
      </div>

      {sorted.length > 0 && (
        <div className="space-y-2">
          {sorted.map(([name, item]) => (
            <AlgorithmCompareRow key={name} name={name} item={item} domain={domain} maxAbsDelta={maxAbsDelta} />
          ))}
        </div>
      )}

      {sorted.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-3" role="group" aria-label="Algorithm comparison dumbbell chart">
          <div className="mb-2 text-xs font-medium text-muted">Shared-Axis Baseline vs Evolved Dumbbell</div>
          <ComparisonDumbbell rows={sorted} domain={domain} />
        </div>
      )}

      {hasCoverageGap && (
        <div className="rounded-lg border border-border bg-surface p-3">
          <div className="mb-2 text-xs font-medium text-muted">Evaluator Instance Coverage</div>
          <InstanceCoverage rows={sorted} />
        </div>
      )}
    </div>
  );
}

function AlgorithmCompareRow({
  name,
  item,
  domain,
  maxAbsDelta,
}: {
  name: string;
  item: ComparisonAlgorithm;
  domain: { min: number; max: number };
  maxAbsDelta: number;
}) {
  const failed = item.failed === true;
  const promoted = item.promoted === true;
  const delta = item.delta_pct ?? null;
  const span = Math.max(domain.max - domain.min, Number.EPSILON);
  const pctOf = (v: number | null | undefined) =>
    v == null || !Number.isFinite(v) ? 0 : ((v - domain.min) / span) * 100;
  const baselinePct = pctOf(item.baseline);
  const evolvedPct = pctOf(item.evolved);
  const deltaRatio =
    delta == null || maxAbsDelta <= 0 ? 0 : Math.max(-1, Math.min(1, delta / maxAbsDelta));
  const deltaWidth = Math.abs(deltaRatio) * 50;
  const StatusIcon = failed ? XCircle : promoted ? CheckCircle2 : Circle;
  const badgeText = failed ? "FAILED" : promoted ? "PROMOTED" : "RETAINED BASELINE";

  return (
    <div className="rounded-lg border border-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-xs font-semibold">{name}</span>
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium",
              failed
                ? "border-error/40 bg-error/10 text-error"
                : promoted
                  ? "border-ok/40 bg-ok/10 text-ok"
                  : "border-border bg-surface-2 text-muted",
            )}
          >
            <StatusIcon className="h-3 w-3" />
            {badgeText}
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <div className="relative hidden h-1.5 w-16 overflow-hidden rounded-full bg-surface-2 sm:block">
            <div className="absolute inset-y-0 left-1/2 w-px bg-border" />
            {deltaRatio !== 0 && (
              <div
                className={cn(
                  "absolute top-0 h-full rounded-full",
                  deltaRatio > 0 ? "left-1/2 bg-ok" : "right-1/2 bg-warn",
                )}
                style={{ width: `${deltaWidth}%` }}
              />
            )}
          </div>
          <span className="font-mono text-xs font-semibold tabular-nums">
            {delta == null ? "—" : formatDeltaPct(delta)}
          </span>
        </div>
      </div>

      <div className="mt-2.5 space-y-1.5">
        <div className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-[10px] uppercase text-muted">Baseline</span>
          <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-2">
            <div className="h-full rounded-full bg-muted/60" style={{ width: `${baselinePct}%` }} />
          </div>
          <span className="w-20 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted">
            {formatCompareValue(item.baseline)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-[10px] uppercase text-muted">Evolved</span>
          <div className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-2">
            <div
              className={cn("h-full rounded-full", failed ? "bg-error" : promoted ? "bg-ok" : "bg-accent")}
              style={{ width: `${evolvedPct}%` }}
            />
          </div>
          <span className="w-20 shrink-0 text-right font-mono text-[11px] font-semibold tabular-nums">
            {formatCompareValue(item.evolved)}
          </span>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-muted">
        {item.reason && <span>{item.reason}</span>}
        {item.n_instances_compared != null && (
          <span className="font-mono tabular-nums">
            Instances: {item.n_instances_compared}/{item.n_instances_total ?? item.n_instances_compared}
          </span>
        )}
        {(item.lost_instances ?? 0) > 0 && (
          <span className="font-medium text-error">Lost instances: {item.lost_instances}</span>
        )}
      </div>
    </div>
  );
}

function ComparisonDumbbell({
  rows,
  domain,
}: {
  rows: [string, ComparisonAlgorithm][];
  domain: { min: number; max: number };
}) {
  const span = Math.max(domain.max - domain.min, Number.EPSILON);
  const xOf = (v: number) => ((v - domain.min) / span) * 100;

  return (
    <div className="space-y-1">
      {rows.map(([name, item]) => {
        const b = item.baseline != null && Number.isFinite(item.baseline) ? item.baseline : null;
        const e = item.evolved != null && Number.isFinite(item.evolved) ? item.evolved : null;
        const x1 = b == null ? null : xOf(b);
        const x2 = e == null ? null : xOf(e);
        return (
          <div key={name} className="flex items-center gap-2">
            <span className="w-24 shrink-0 truncate text-right font-mono text-[11px] text-muted">{name}</span>
            <div className="relative h-6 min-w-0 flex-1">
              <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-border" />
              {x1 != null && x2 != null && x1 !== x2 && (
                <div
                  className={cn(
                    "absolute top-1/2 h-0.5 -translate-y-1/2 rounded-full",
                    item.promoted ? "bg-ok" : "bg-muted",
                  )}
                  style={{ left: `${Math.min(x1, x2)}%`, width: `${Math.abs(x2 - x1)}%` }}
                />
              )}
              {x1 != null && (
                <div
                  className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border border-muted bg-surface-2"
                  style={{ left: `${x1}%` }}
                  title={`Baseline: ${formatCompareValue(b)}`}
                />
              )}
              {x2 != null && (
                <div
                  className={cn(
                    "absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2",
                    item.failed ? "border-error bg-error" : item.promoted ? "border-ok bg-ok" : "border-muted bg-muted",
                  )}
                  style={{ left: `${x2}%` }}
                  title={`Evolved: ${formatCompareValue(e)}`}
                />
              )}
            </div>
            <span className="w-20 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted">
              {formatCompareValue(item.evolved)}
            </span>
          </div>
        );
      })}
      <div className="flex items-center gap-2 pt-0.5">
        <span className="w-24 shrink-0" />
        <div className="relative h-3.5 min-w-0 flex-1 text-[10px] tabular-nums text-muted">
          <span className="absolute left-0">{formatTick(domain.min)}</span>
          <span className="absolute left-1/2 -translate-x-1/2">{formatTick((domain.min + domain.max) / 2)}</span>
          <span className="absolute right-0">{formatTick(domain.max)}</span>
        </div>
        <span className="w-20 shrink-0" />
      </div>
    </div>
  );
}

function InstanceCoverage({ rows }: { rows: [string, ComparisonAlgorithm][] }) {
  return (
    <div className="space-y-2">
      {rows.map(([name, item]) => {
        const total = item.n_instances_total ?? 0;
        if (total <= 0) return null;
        const compared = item.n_instances_compared ?? 0;
        const lost = item.lost_instances ?? 0;
        const skipped = Math.max(0, total - compared - lost);
        return (
          <div key={name} className="flex items-center gap-2">
            <span className="w-24 shrink-0 truncate font-mono text-[11px]">{name}</span>
            <div className="flex h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-2">
              {compared - lost > 0 && (
                <div className="h-full bg-ok" style={{ width: `${((compared - lost) / total) * 100}%` }} />
              )}
              {lost > 0 && <div className="h-full bg-error" style={{ width: `${(lost / total) * 100}%` }} />}
              {skipped > 0 && <div className="h-full bg-warn" style={{ width: `${(skipped / total) * 100}%` }} />}
            </div>
            <span className="w-14 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted">
              {compared}/{total}
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── Stage 23 verification_report.json View ───────────────────────────────────

export interface CitationResult {
  cite_key?: string | null;
  title?: string | null;
  status?: string | null;
  confidence?: number | null;
  method?: string | null;
  details?: string | null;
  relevance_score?: number | null;
  matched_paper?: {
    title?: string | null;
    authors?: string[] | null;
    year?: number | null;
    source?: string | null;
  } | null;
}

export interface VerificationData {
  summary?: {
    total?: number | null;
    verified?: number | null;
    suspicious?: number | null;
    hallucinated?: number | null;
    skipped?: number | null;
    integrity_score?: number | null;
  } | null;
  results?: CitationResult[] | null;
}

export function VerificationView({ data }: { data: VerificationData }) {
  const summary = data.summary ?? {};
  const results = data.results ?? [];
  const nVerified = summary.verified ?? 0;
  const nSuspicious = summary.suspicious ?? 0;
  const nHallucinated = summary.hallucinated ?? 0;
  const nSkipped = summary.skipped ?? 0;
  const total = summary.total ?? results.length;
  const integrity = summary.integrity_score;
  const share = (n: number) => (total > 0 ? (n / total) * 100 : 0);

  return (
    <div className="space-y-3 p-3 text-text" aria-label="Citation Verification Report">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-surface p-3">
        <div className="flex items-center gap-2">
          <ShieldCheck className="h-4 w-4 text-ok" />
          <div>
            <h3 className="text-sm font-semibold">Literature & Citation Anti-Hallucination Report</h3>
            <p className="text-xs text-muted">
              Verified: {nVerified}/{total} · Suspicious: {nSuspicious} · Hallucinated: {nHallucinated}
            </p>
          </div>
        </div>
        <span className="rounded-full border border-border bg-surface-2 px-2.5 py-0.5 font-mono text-xs">
          Integrity: {integrity != null ? integrity.toFixed(2) : "N/A"}
        </span>
      </div>

      {total > 0 && (
        <div className="rounded-lg border border-border bg-surface p-3">
          <div className="flex h-2 w-full overflow-hidden rounded-full bg-surface-2">
            {nVerified > 0 && <div className="h-full bg-ok" style={{ width: `${share(nVerified)}%` }} />}
            {nSuspicious > 0 && <div className="h-full bg-warn" style={{ width: `${share(nSuspicious)}%` }} />}
            {nHallucinated > 0 && <div className="h-full bg-error" style={{ width: `${share(nHallucinated)}%` }} />}
            {nSkipped > 0 && <div className="h-full bg-muted" style={{ width: `${share(nSkipped)}%` }} />}
          </div>
        </div>
      )}

      <div className="space-y-2">
        {results.map((item, idx) => {
          const st = (item.status ?? "unknown").toLowerCase();
          const Icon =
            st === "verified" ? CheckCircle2 : st === "suspicious" ? AlertTriangle : st === "hallucinated" ? XCircle : Circle;
          return (
            <div key={idx} className="rounded-lg border border-border bg-surface p-3">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-xs font-semibold">{item.title || item.cite_key || "—"}</div>
                  {item.cite_key && <div className="font-mono text-[11px] text-muted">{item.cite_key}</div>}
                </div>
                <span
                  className={cn(
                    "inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-medium uppercase",
                    st === "verified"
                      ? "border-ok/40 bg-ok/10 text-ok"
                      : st === "suspicious"
                        ? "border-warn/40 bg-warn/10 text-warn"
                        : st === "hallucinated"
                          ? "border-error/40 bg-error/10 text-error"
                          : "border-border bg-surface-2 text-muted",
                  )}
                >
                  <Icon className="h-3 w-3" />
                  {st}
                </span>
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
                {item.method && <span>Method: <strong className="font-mono">{item.method}</strong></span>}
                {item.confidence != null && <span>Confidence: {(item.confidence * 100).toFixed(0)}%</span>}
                {item.relevance_score != null && <span>Relevance: {item.relevance_score.toFixed(2)}</span>}
              </div>
              {item.matched_paper?.title && (
                <div className="mt-2 rounded border border-border bg-surface-2/60 px-2.5 py-1.5 text-xs">
                  <div className="font-medium">{item.matched_paper.title}</div>
                  <div className="text-[11px] text-muted">
                    {(item.matched_paper.authors ?? []).slice(0, 3).join(", ")}
                    {item.matched_paper.year ? ` (${item.matched_paper.year})` : ""}
                    {item.matched_paper.source ? ` · ${item.matched_paper.source}` : ""}
                  </div>
                </div>
              )}
              {item.details && <p className="mt-1.5 text-[11px] text-muted">{item.details}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CruxResearchArtifactView({ filename, text }: { filename: string; text: string }) {
  const parsed = useMemo<Record<string, unknown> | null>(() => {
    try {
      const obj = JSON.parse(text);
      return obj && typeof obj === "object" ? (obj as Record<string, unknown>) : null;
    } catch {
      return null;
    }
  }, [text]);

  if (!parsed) {
    return <div className="p-4 text-sm text-muted">Invalid JSON in {filename}</div>;
  }

  const lower = (filename.split(/[\\/]/).pop() ?? filename).toLowerCase();
  if (lower.includes("verification_report") || (parsed.summary && Array.isArray(parsed.results))) {
    return <VerificationView data={parsed as unknown as VerificationData} />;
  }
  if (lower.includes("comparison") || (parsed.algorithms && typeof parsed.algorithms === "object")) {
    return <ComparisonView data={parsed as unknown as ComparisonData} />;
  }
  const nodes = (parsed.population ?? parsed.individuals ?? parsed.nodes ?? parsed.history) as
    | Record<string, unknown>[]
    | undefined;
  if (Array.isArray(nodes)) {
    return (
      <div className="p-3">
        <EvolutionExperimentView items={nodes} />
        {Boolean(parsed.comparison && typeof parsed.comparison === "object") && (
          <ComparisonView data={parsed.comparison as ComparisonData} />
        )}
      </div>
    );
  }
  return <div className="p-4 font-mono text-xs text-muted">{text}</div>;
}
