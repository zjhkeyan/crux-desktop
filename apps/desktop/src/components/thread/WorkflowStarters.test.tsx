import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { WORKFLOW_STARTERS, WorkflowStarters } from "./WorkflowStarters";

// Plain closures instead of vi.fn: tinyspy's result tracking derives an extra
// promise from a rejecting spy, which vitest then reports as unhandled.
const installCalls: string[] = [];
let failInstall = false;
vi.mock("@/lib/tauri", () => ({
  isTauri: true,
  installExample: async (name: string) => {
    installCalls.push(name);
    if (failInstall) throw new Error("resource missing");
    return name;
  },
}));

describe("WorkflowStarters", () => {
  beforeEach(() => {
    installCalls.length = 0;
    failInstall = false;
  });

  it("renders one card per computational chemistry and algorithm optimization starter workflow", () => {
    render(<WorkflowStarters onPick={() => {}} />);
    expect(screen.getByText("Computational Chemistry: DFT transition-state & barrier search")).toBeInTheDocument();
    expect(screen.getByText("Computational Chemistry: QSAR modeling & Bayesian reaction optimization")).toBeInTheDocument();
    expect(screen.getByText("Algorithm Optimization: Non-convex geometric packing & exact certification")).toBeInTheDocument();
    expect(WORKFLOW_STARTERS).toHaveLength(3);
  });

  it("sends the full-workflow prompt on click", async () => {
    const onPick = vi.fn();
    render(<WorkflowStarters onPick={onPick} />);
    await userEvent.click(screen.getByText("Computational Chemistry: DFT transition-state & barrier search"));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(expect.stringContaining("ts_analysis/figure1.png")));
    expect(onPick.mock.calls[0][0]).toContain("ts_analysis/report.md");
    expect(installCalls).toHaveLength(0);
  });

  it("sends the geometric packing optimization prompt on click", async () => {
    const onPick = vi.fn();
    render(<WorkflowStarters onPick={onPick} />);

    await userEvent.click(screen.getByText("Algorithm Optimization: Non-convex geometric packing & exact certification"));
    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));
    expect(onPick.mock.calls[0][0]).toContain("work/pack26");
    expect(onPick.mock.calls[0][0]).toContain("work/thomson15");
  });

  it("does not send the prompt when a starter prepare hook fails", async () => {
    const origPrepare = WORKFLOW_STARTERS[2].prepare;
    WORKFLOW_STARTERS[2].prepare = async () => {
      installCalls.push("pack26");
      throw new Error("resource missing");
    };
    try {
      const onPick = vi.fn();
      render(<WorkflowStarters onPick={onPick} />);

      await userEvent.click(screen.getByText("Algorithm Optimization: Non-convex geometric packing & exact certification"));
      await waitFor(() => expect(installCalls).toHaveLength(1));
      expect(onPick).not.toHaveBeenCalled();
    } finally {
      WORKFLOW_STARTERS[2].prepare = origPrepare;
    }
  });
});
