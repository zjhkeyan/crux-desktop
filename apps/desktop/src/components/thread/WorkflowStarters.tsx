import { useTranslation } from "react-i18next";
import { Atom, ChevronRight, FlaskConical, Orbit } from "lucide-react";
import { toast } from "@/lib/toast";
import { cn } from "@/lib/cn";

export interface WorkflowStarter {
  id: string;
  icon: React.ReactNode;
  /** Sent to the agent as-is — content, not UI copy, so it is never translated.
   *  The card's display title/description live in `session:starters.<id>.*`. */
  prompt: string;
  /** Side effect to run before sending the prompt (e.g. install example files). */
  prepare?: () => Promise<void>;
}

/** One-click full-workflow prompts (P0-1): computational chemistry & algorithm
 *  optimization workflows that carry the agent through code → verification → figure → report. */
export const WORKFLOW_STARTERS: WorkflowStarter[] = [
  {
    id: "demo",
    icon: <Atom size={17} strokeWidth={1.75} />,
    prompt:
      "Run a first-principles computational chemistry transition-state (TS) and activation barrier workflow: " +
      "set up reactant/product structures, run saddle-point optimization (Sella / GPU4PySCF or harmonic TS model), " +
      "verify the single imaginary frequency (nu^‡ < 0) and IRC path connectivity, compute Delta E^‡ and Delta G^‡, " +
      "save a publication-grade reaction energy profile as ts_analysis/figure1.png, and write ts_analysis/report.md " +
      "with every barrier and frequency traced to the calculation output.",
  },
  {
    id: "analyze",
    icon: <FlaskConical size={17} strokeWidth={1.75} />,
    prompt:
      "Run a molecular property prediction (QSAR / ADMET) and Bayesian reaction optimization workflow on the dataset " +
      "in the workspace: build physicochemical and fingerprint descriptors, benchmark surrogate models with cross-validation, " +
      "propose next-batch candidate conditions via Expected Improvement / UCB, save parity and acquisition plots as PNGs, " +
      "and write report.md with all metrics traced to the execution logs.",
  },
  {
    id: "example-climate",
    icon: <Orbit size={17} strokeWidth={1.75} />,
    prompt:
      "Run a high-precision non-convex geometric optimization and exact certification workflow (modeled on `work/pack26` N=26 circle packing " +
      "r* = 0.09628641 and `work/thomson15` Tammes-15 spherical code d* = 0.902656188): combine multi-start L-BFGS-B / SLSQP basin-hopping " +
      "with a symmetry ansatz, verify pairwise and boundary constraints to 60 decimal places with `mpmath`, render the contact-graph figure, " +
      "and write a concise optimality report.",
  },
];

/**
 * Empty-session welcome: a quiet, centered composition in the app's paper
 * aesthetic. The conversation is the point, so the copy invites a message
 * first; the starters below are an optional on-ramp, not a dashboard.
 */
export function WorkflowStarters({
  onPick,
  showCards = true,
}: {
  onPick: (prompt: string) => void;
  /** False when the pane is too short for the cards (a stacked split): only
   *  the invitation stays, and nothing makes the welcome scroll. */
  showCards?: boolean;
}) {
  const { t } = useTranslation(["session", "common"]);
  // Display copy per starter id — t()'s generated key type rejects a dynamic
  // `starters.${id}.title` template, so each card's copy is looked up by id
  // from this literal-keyed map instead.
  const starterCopy: Record<string, { title: string; description: string }> = {
    demo: { title: t("starters.demo.title"), description: t("starters.demo.description") },
    analyze: { title: t("starters.analyze.title"), description: t("starters.analyze.description") },
    audit: { title: t("starters.audit.title"), description: t("starters.audit.description") },
    "example-climate": {
      title: t("starters.example-climate.title"),
      description: t("starters.example-climate.description"),
    },
  };
  return (
    <div className={cn("flex flex-col items-center justify-center", showCards ? "min-h-[62vh]" : "py-6")}>
      <div className="w-full max-w-[500px]">
        <div className="text-center">
          <div className="text-[10.5px] font-medium uppercase tracking-[0.2em] text-muted">
            {t("starters.newSession")}
          </div>
          <h2 className="mt-2.5 font-serif text-[26px] leading-tight text-text">
            {t("starters.heading")}
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-muted">
            {showCards ? t("starters.subheading") : t("starters.subheadingNoCards")}
          </p>
        </div>

        {showCards && (

        <div className="mt-7 overflow-hidden rounded-card border border-border bg-surface shadow-card">
          {WORKFLOW_STARTERS.map((s) => (
            <button
              key={s.id}
              onClick={() => {
                void (async () => {
                  try {
                    await s.prepare?.();
                  } catch (e) {
                    toast.error(
                      t("starters.error.setup", {
                        message: e instanceof Error ? e.message : String(e),
                      }),
                    );
                    return;
                  }
                  onPick(s.prompt);
                })();
              }}
              className="group flex w-full items-center gap-3.5 border-t border-border px-4 py-3.5 text-left transition-colors first:border-t-0 hover:bg-surface-2"
            >
              <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-surface-2 text-accent ring-1 ring-border transition-colors group-hover:bg-surface">
                {s.icon}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block text-[13.5px] font-medium text-text">
                  {starterCopy[s.id]?.title}
                </span>
                <span className="mt-0.5 block text-xs leading-snug text-muted">
                  {starterCopy[s.id]?.description}
                </span>
              </span>
              <ChevronRight
                size={16}
                className="shrink-0 text-muted/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-muted"
              />
            </button>
          ))}
        </div>
        )}
      </div>
    </div>
  );
}
