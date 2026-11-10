import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import type { ProviderInfo } from "@ai4s/sdk";
import { useRuntimeStore } from "@/lib/runtime";
import { getAgentModels, getAgentVariants, setAgentModel, setAgentVariant } from "@/lib/tauri";
import { flattenModelOptions, selectableModelOptions, type ModelOption } from "./modelCatalog";
import { Row, Section } from "./Section";
import { buttonCls, chipCls, inputCls } from "./inputCls";
import { cn } from "@/lib/cn";

/** Utility agents the runtime runs on its own behalf — titling a session,
 *  summarizing, compacting context. They do short mechanical work, so a fast
 *  model here is a pure win; they are listed separately from the agents the
 *  user talks to because they never appear in the composer.
 *
 *  Unlike those, they carry no description from the runtime, so the copy for
 *  what each one does lives here — a row labelled only `compaction` tells a
 *  reader nothing, however expert. */
const UTILITY_AGENTS = ["title", "summary", "compaction"] as const;

// Match shipped descriptions exactly so user-written role descriptions stay intact.
const BUILTIN_DESCRIPTIONS = {
  "build": [
    "The default agent. Executes tools based on configured permissions.",
    "Default agent."
  ],
  "plan": [
    "Read-only agent for exploring the codebase and planning work before implementation.",
    "Plan mode. Disallows all edit tools."
  ],
  "general": [
    "General-purpose agent for researching complex questions and executing multi-step tasks. Use this agent to execute multiple units of work in parallel."
  ],
  "explore": [
    "Fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (eg. \"src/components/**/*.tsx\"), search code for keywords (eg. \"API endpoints\"), or answer questions about the codebase (eg. \"how do API endpoints work?\"). When calling this agent, specify the desired thoroughness level: \"quick\" for basic searches, \"medium\" for moderate exploration, or \"very thorough\" for comprehensive analysis across multiple locations and naming conventions."
  ],
  "reviewer": [
    "Reviews finished work in the workspace for scientific rigour — traceability, statistics, units, provenance and reproducibility — and reports findings without changing anything."
  ],
  "crux-run-doctor": [
    "Use this subagent to diagnose a Crux discovery run that's misbehaving — agents restarting, every eval failing, the score plateaued, or \"is this run healthy?\". It reads `crux discovery status` / `crux discovery log` / `crux discovery show` / notes, identifies the pathology, and returns a ranked set of concrete fixes (fix the grader, resume with an instruction, tune heartbeats, fork a regressed line). Read-only on the run — it recommends, it doesn't restart or stop anything.",
    "Use this subagent to diagnose a Crux Discovery or Crux Evolve run that's misbehaving — agents restarting, every eval failing, the score plateaued, or \"is this run healthy?\". It inspects `crux discovery status/log/show` or `crux_evolve` (`evaluate_candidate`, `switch_method`, `--resume`), identifies the pathology, and returns a ranked set of concrete fixes. Read-only on the run — it recommends, it doesn't restart or stop anything."
  ],
  "crux-task-author": [
    "Use this subagent to turn \"optimize / speed up / improve this with Crux\" into a working Crux discovery task. Give it the code (or just a repo and a rough goal) and it acts immediately — explores the repo to infer the optimization target, scaffolds a .crux_workspace/, writes the grader, and iterates `crux discovery validate` until the grader cleanly scores the seed, then hands back a ready-to-launch task. Delegate here whenever the user wants Crux pointed at existing code.",
    "Crux Evolve Task Builder & Method Architect. Build a validated algorithm optimization package (`config.yaml` + `algorithm/` + `<name>_evaluator.py` + `test_evaluator.py`) or Crux Discovery workspace using the unified Planner/Coder/Evaluator contract, fair evaluation lock, and isolated git worktree / SSH remote evaluator."
  ],
  "memory-curator": [
    "Consolidate staged session transcripts, experiment logs and scientific corpora into `.openscience/memory/`, `.opencode/skills/<wiki-slug>/` and `<workspace>/MEMORY.md` in one two-phase pass (extract insights -> organize & prune index)."
  ],
  "title": [],
  "summary": [],
  "compaction": []
};

const roleName = (name: string) => name.replace(/^coral-/, "crux-");
const settingFor = (settings: Record<string, string>, name: string) => {
  const value = settings[name] ?? settings[name.replace(/^crux-/, "coral-")];
  return typeof value === "string" ? value : undefined;
};

async function saveSetting(
  write: (agent: string, value: string) => Promise<void>,
  settings: Record<string, string>,
  name: string,
  value: string,
) {
  await write(name, value);
  const next = { ...settings };
  for (const key of Object.keys(settings)) {
    if (key !== name && roleName(key) === name) {
      await write(key, "");
      delete next[key];
    }
  }
  delete next[name];
  return value ? { ...next, [name]: value } : next;
}

/** Reasoning-effort variant names are provider tokens (the same in every
 *  language), so they are title-cased in place rather than translated —
 *  matching the composer's effort slider. */
function labelVariant(name: string): string {
  if (name === "xhigh") return "X-High";
  return name.charAt(0).toLocaleUpperCase() + name.slice(1);
}

/**
 * One model and one reasoning effort per agent (#63, #71). A reviewer or
 * explorer subagent can run a fast model while the main agent reasons on a
 * strong one; the composer's effort slider only reaches the turn the user
 * sends, so a subagent's effort has to be pinned here. Anything left on
 * "default" follows the global model / the model's own default effort.
 */
export function AgentModelsCard({ providers }: { providers: ProviderInfo[] }) {
  const { t } = useTranslation(["settings", "common"]);
  const agents = useRuntimeStore((s) => s.agents);
  const defaultModel = useRuntimeStore((s) => s.defaultModel);
  // Keeps this card (and the model browser) on screen while the sidecar
  // restarts to pick the change up, instead of collapsing to the connect prompt.
  const reloadRuntimeConfig = useRuntimeStore((s) => s.reloadRuntimeConfig);

  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [efforts, setEfforts] = useState<Record<string, string>>({});
  const [busyAgent, setBusyAgent] = useState<string | null>(null);
  const [addedRoles, setAddedRoles] = useState<string[]>([]);
  const [newRole, setNewRole] = useState("");
  const [error, setError] = useState("");
  // Both come from the same config file; reconciliation below needs BOTH, since
  // an agent's effective model decides which efforts are legal.
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    void Promise.all([getAgentModels(), getAgentVariants()]).then(([models, variants]) => {
      setOverrides(models);
      setEfforts(variants);
      setLoaded(true);
    }).catch((err) => setError(String(err)));
  }, []);

  const options = useMemo(() => flattenModelOptions(providers), [providers]);
  const selectable = useMemo(() => selectableModelOptions(options), [options]);
  // The catalog, grouped by provider. A native <select> shows the chosen
  // OPTION's text, so the option text is what has to be short: listing the full
  // `provider/model` key is what made every row read
  // "Default (kimi-for-coding/kimi-for-coding-hi…" with the answer cut off.
  // The provider moves into the <optgroup> label, where it is said once.
  const byProvider = useMemo(() => {
    const map = new Map<string, { name: string; models: ModelOption[] }>();
    for (const option of selectable) {
      const group = map.get(option.providerID) ?? { name: option.providerName, models: [] };
      group.models.push(option);
      map.set(option.providerID, group);
    }
    return [...map.values()];
  }, [selectable]);
  // Effort levels each model exposes — the vocabulary differs per model, so a
  // row's choices follow whichever model that agent actually runs.
  const variantsByKey = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const p of providers) {
      for (const m of p.models) map.set(`${p.id}/${m.id}`, m.variants ?? []);
    }
    return map;
  }, [providers]);
  // Configured roles can be absent from the runtime catalog. Legacy aliases
  // share one row with their current name; writes migrate their settings.
  const groups = useMemo(() => {
    const conversation = new Map<string, { name: string; description: string; custom: boolean }>();
    for (const agent of agents) {
      const name = roleName(agent.name);
      if (UTILITY_AGENTS.some((utility) => utility === name)) continue;
      if (!conversation.has(name) || agent.name === name) {
        conversation.set(name, { name, description: (agent.description ?? "").replace(/CORAL/g, "Crux"), custom: false });
      }
    }
    for (const key of [...Object.keys(overrides), ...Object.keys(efforts), ...addedRoles]) {
      const name = roleName(key);
      if (!conversation.has(name) && !UTILITY_AGENTS.some((utility) => utility === name)) {
        conversation.set(name, { name, description: "", custom: true });
      }
    }
    return {
      conversation: [...conversation.values()],
      utility: UTILITY_AGENTS.map((name) => ({
        name,
        description: agents.find((agent) => agent.name === name)?.description ?? "",
        custom: false,
      })),
    };
  }, [agents, overrides, efforts, addedRoles]);

  const variantsFor = (agent: string) =>
    variantsByKey.get(settingFor(overrides, agent) ?? defaultModel ?? "") ?? [];

  // A pinned effort can stop existing under the runtime it was chosen for: from
  // 1.18 a model's efforts come from the catalog's own `reasoning_options`, and
  // some models lost levels the previous runtime synthesized (verified on the
  // bundled binaries: `deepseek-v4-flash-free` lost `medium`, two models lost
  // their efforts entirely — #74). The runtime accepts such a value without
  // complaint and then silently applies nothing, so reconcile it away: the row
  // must not display an effort that no longer applies, and the config must not
  // keep one. A model absent from the catalog is left alone — that is a dangling
  // model, not a dropped level, and its effort is still meaningful if it returns.
  useEffect(() => {
    if (!loaded || busyAgent || providers.length === 0) return;
    for (const [agent, effort] of Object.entries(efforts)) {
      if (!effort) continue;
      const known = variantsByKey.get(settingFor(overrides, roleName(agent)) ?? defaultModel ?? "");
      if (!known || known.includes(effort)) continue;
      void setAgentVariant(agent, "");
      setEfforts((prev) => {
        const next = { ...prev };
        delete next[agent];
        return next;
      });
    }
  }, [loaded, busyAgent, providers, efforts, overrides, defaultModel, variantsByKey]);

  const update = async (agent: string, apply: () => Promise<void>) => {
    setBusyAgent(agent);
    setError("");
    try {
      await reloadRuntimeConfig(apply);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusyAgent(null);
    }
  };

  const choose = (agent: string, model: string) =>
    update(agent, async () => {
      setOverrides(await saveSetting(setAgentModel, overrides, agent, model));
      // A pinned effort belongs to the model it was chosen for: the new model
      // may not offer that level at all, and OpenCode would reject the turn.
      // Drop it rather than leave a setting that cannot be honoured.
      const kept = variantsByKey.get(model || defaultModel || "") ?? [];
      const effort = settingFor(efforts, agent);
      const legacy = Object.keys(efforts).some((key) => key !== agent && roleName(key) === agent);
      if (effort && (!kept.includes(effort) || legacy)) {
        setEfforts(await saveSetting(setAgentVariant, efforts, agent, kept.includes(effort) ? effort : ""));
      }
    });

  const chooseEffort = (agent: string, variant: string) =>
    update(agent, async () => {
      if (Object.keys(overrides).some((key) => key !== agent && roleName(key) === agent)) {
        setOverrides(await saveSetting(setAgentModel, overrides, agent, settingFor(overrides, agent) ?? ""));
      }
      setEfforts(await saveSetting(setAgentVariant, efforts, agent, variant));
    });

  const reset = (agent: string) =>
    update(agent, async () => {
      setOverrides(await saveSetting(setAgentModel, overrides, agent, ""));
      setEfforts(await saveSetting(setAgentVariant, efforts, agent, ""));
      setAddedRoles((prev) => prev.filter((name) => name !== agent));
    });

  const anyBusy = !loaded || busyAgent !== null;
  const candidate = roleName(newRole.trim());
  const canAdd = candidate.length > 0 && !groups.conversation.some((agent) => agent.name === candidate)
    && !UTILITY_AGENTS.some((name) => name === candidate);

  /** One agent: what it is on the left, what it runs on the right. */
  const agentRow = (agent: { name: string; description: string; custom: boolean }) => {
    const variants = variantsFor(agent.name);
    const pinned = settingFor(overrides, agent.name);
    const retired = pinned ? options.find((o) => o.key === pinned && !o.available) : undefined;
    return (
      <Row
        key={agent.name}
        title={agent.name}
        hint={roleDescription(t, agent.name, agent.description) || (agent.custom ? t("agentModels.customRole") : undefined)}
        control={
          <div className="flex max-w-full shrink-0 flex-wrap items-center gap-1">
            {busyAgent === agent.name && <Loader2 size={13} className="animate-spin text-muted" />}
            <select
              value={pinned ?? ""}
              disabled={anyBusy}
              onChange={(e) => void choose(agent.name, e.target.value)}
              aria-label={t("agentModels.modelFor", { agent: agent.name })}
              className={chipCls("max-w-[13rem] pr-1 disabled:opacity-50")}
            >
              {/* Just "the default" — the Model section above already names it,
                  and repeating a long model name in every row is what pushed
                  the chosen value past the control's width in the first place. */}
              <option value="">{t("agentModels.followDefault")}</option>
              {/* A model this agent is pinned to but the provider has retired.
                  Dropping it would leave the select with no matching value, so
                  the row would claim "follow the default" while the config
                  still pins a dead model. */}
              {pinned && !options.some((option) => option.key === pinned) && (
                <option value={pinned}>{pinned}</option>
              )}
              {retired && (
                <option value={retired.key}>
                  {t("agentModels.retiredOption", { model: retired.modelName })}
                </option>
              )}
              {byProvider.map((group) => (
                <optgroup key={group.name} label={group.name}>
                  {group.models.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.modelName}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
            {/* Effort only exists for models that expose reasoning levels; for
                the rest there is nothing to choose, so nothing shows. */}
            {variants.length > 0 && (
              <select
                value={settingFor(efforts, agent.name) ?? ""}
                disabled={anyBusy}
                onChange={(e) => void chooseEffort(agent.name, e.target.value)}
                aria-label={t("agentModels.effortFor", { agent: agent.name })}
                className={chipCls("pr-1 text-muted disabled:opacity-50")}
              >
                <option value="">{t("agentModels.defaultEffort")}</option>
                {variants.map((v) => (
                  <option key={v} value={v}>
                    {labelVariant(v)}
                  </option>
                ))}
              </select>
            )}
            {(agent.custom || pinned || settingFor(efforts, agent.name)) && (
              <button
                type="button"
                disabled={anyBusy}
                onClick={() => void reset(agent.name)}
                aria-label={t(agent.custom ? "agentModels.removeRoleFor" : "agentModels.resetRoleFor", { agent: agent.name })}
                className={buttonCls("disabled:opacity-50")}
              >
                {t(agent.custom ? "agentModels.removeRole" : "agentModels.resetRole")}
              </button>
            )}
          </div>
        }
      />
    );
  };

  return (
    <Section title={t("agentModels.title")} hint={t("agentModels.hint")} flush>
      {error && <p role="alert" className="px-4 py-3 text-[13px] text-danger">{error}</p>}
      {selectable.length === 0 && (
        <p className="px-4 py-3 text-[13px] text-muted">{t("agentModels.noModels")}</p>
      )}
      <GroupHeader
        title={t("agentModels.group.conversation")}
        hint={t("agentModels.primaryHint")}
        first
      />
      <div className="divide-y divide-faint">
        {groups.conversation.map((agent) => agentRow(agent))}
      </div>
      <form
        className="flex flex-wrap items-center gap-2 border-t border-faint px-4 py-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!canAdd || anyBusy) return;
          setAddedRoles((prev) => [...prev, candidate]);
          setNewRole("");
        }}
      >
        <input
          value={newRole}
          onChange={(event) => setNewRole(event.target.value)}
          disabled={anyBusy}
          aria-label={t("agentModels.roleName")}
          placeholder={t("agentModels.roleName")}
          className={inputCls("min-w-0 flex-1")}
        />
        <button type="submit" disabled={!canAdd || anyBusy} className={buttonCls("disabled:opacity-50")}>
          {t("agentModels.addRole")}
        </button>
      </form>
      {groups.utility.length > 0 && (
        <>
          <GroupHeader
            title={t("agentModels.group.utility")}
            hint={t("agentModels.utilityHint")}
          />
          <div className="divide-y divide-faint">
            {groups.utility.map((agent) => agentRow(agent))}
          </div>
        </>
      )}
    </Section>
  );
}

function roleDescription(
  t: ReturnType<typeof useTranslation<["settings", "common"]>>["t"],
  name: string,
  fallbackDescription: string,
): string {
  const description = fallbackDescription.replace(/CORAL/g, "Crux");
  if (Object.prototype.hasOwnProperty.call(BUILTIN_DESCRIPTIONS, name)) {
    const role = name as keyof typeof BUILTIN_DESCRIPTIONS;
    const defaults: string[] = BUILTIN_DESCRIPTIONS[role];
    if (!description || defaults.includes(description)) {
      return t(`agentModels.about.${role}`);
    }
  }
  return description;
}

/** A band that says what the rows under it have in common. Without it the two
 *  kinds of agent read as one undifferentiated column of ids. */
function GroupHeader({ title, hint, first }: { title: string; hint: string; first?: boolean }) {
  return (
    <div className={cn("bg-surface-2/50 px-4 py-2", !first && "border-t border-faint")}>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{title}</div>
      <p className="mt-0.5 text-xs leading-relaxed text-muted">{hint}</p>
    </div>
  );
}
