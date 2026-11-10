import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { previewKindForName } from "@/lib/artifacts";
import { CruxResearchArtifactView, EvolutionExperimentView } from "./CruxResearchViews";

describe("CruxResearchViews & Artifact Registry Seam", () => {
  it.each([
    {
      filename: "crux_evolve_comparison.json",
      payload: {
        metric_direction: "maximize",
        base: "stage_13_seed",
        n_promoted: 1,
        algorithms: {
          proposed_eoh: {
            baseline: 0.72,
            evolved: 0.91,
            delta_pct: 26.39,
            promoted: true,
            failed: false,
            n_instances_compared: 10,
            n_instances_total: 10,
            lost_instances: 0,
            reason: "Promoted (+26.39% vs baseline across 10/10 instances)",
          },
          stagnant_algo: {
            baseline: 0.8,
            evolved: 0.75,
            delta_pct: -6.25,
            promoted: false,
            failed: false,
            n_instances_compared: 8,
            n_instances_total: 10,
            lost_instances: 2,
            reason: "Retained baseline (fail_silently): incomplete instance coverage",
          },
        },
      },
      expectedKind: "crux-json",
      expectedTexts: [
        "Algorithm Promotion & Evaluator Comparison",
        "Promoted: 1/2",
        "PROMOTED",
        "RETAINED BASELINE",
        "+26.39%",
        "Evaluator Instance Coverage",
      ],
    },
    {
      filename: "verification_report.json",
      payload: {
        summary: {
          total: 2,
          verified: 1,
          suspicious: 1,
          hallucinated: 0,
          skipped: 0,
          integrity_score: 0.75,
        },
        results: [
          {
            cite_key: "romera2024funsearch",
            title: "Mathematical discoveries from program search with large language models",
            status: "verified",
            confidence: 0.98,
            method: "doi",
            relevance_score: 0.91,
            matched_paper: {
              title: "Mathematical discoveries from program search with large language models",
              authors: ["Romera-Paredes", "Barekatain"],
              year: 2024,
              source: "openalex",
            },
          },
        ],
      },
      expectedKind: "crux-json",
      expectedTexts: [
        "Literature & Citation Anti-Hallucination Report",
        "Integrity: 0.75",
        "romera2024funsearch",
        "doi",
      ],
    },
  ])("routes $filename to $expectedKind and renders rich visual cards", ({ filename, payload, expectedKind, expectedTexts }) => {
    expect(previewKindForName(filename)).toBe(expectedKind);
    render(<CruxResearchArtifactView filename={filename} text={JSON.stringify(payload)} />);
    for (const text of expectedTexts) {
      expect(screen.getAllByText(new RegExp(text.replace(/[+]/g, "\\+"))).length).toBeGreaterThan(0);
    }
  });

  it("renders multi-island lineage graph and switches to cumulative/generation score trend curve", async () => {
    render(
      <EvolutionExperimentView
        items={[
          { id: "g0_i0", generation: 0, island_id: 0, score: 10.5, name: "Seed 0" },
          { id: "g1_i0", generation: 1, island_id: 0, parent_ids: ["g0_i0"], score: 14.2, name: "Mutated 1" },
          { id: "g1_i1", generation: 1, island_id: 1, parent_ids: ["g0_i0"], score: 18.0, name: "Crossed 2" },
        ]}
      />,
    );
    expect(screen.getByRole("img", { name: "island evolution graph" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Switch to Score Trend/i }));
    expect(screen.getByRole("img", { name: "evolution trend" })).toBeInTheDocument();
    expect(screen.getByText("Cumulative Best (max)")).toBeInTheDocument();
    expect(screen.getByText("Generation Best (genMax)")).toBeInTheDocument();
  });
});
