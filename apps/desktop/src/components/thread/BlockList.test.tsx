import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ThreadBlock } from "@ai4s/shared";
import { BlockList } from "./BlockList";
import { useRuntimeStore } from "@/lib/runtime";

// A running task row surfaces its subagent's latest step. The activity is no
// longer threaded through props — the row self-subscribes to the child thread in
// the store (SubagentActivity), so these tests seed that thread directly (#34).
describe("BlockList", () => {
  afterEach(() => {
    useRuntimeStore.setState({ threads: {} });
  });

  it("shows a running task row the live activity of its subagent", () => {
    useRuntimeStore.setState({
      threads: {
        ses_child: {
          blocks: [{ kind: "tool-call", title: "python3 analyze slide-03.jpg", status: "running" }],
          index: {},
          loaded: true,
        },
      },
    });
    render(
      <BlockList
        blocks={[
          { kind: "tool-call", title: "Visual QA for slides", status: "running", childSessionId: "ses_child" },
        ]}
      />,
    );
    expect(screen.getByText("python3 analyze slide-03.jpg")).toBeInTheDocument();
  });

  it("renders a row that spawned no subagent without any activity line", () => {
    render(<BlockList blocks={[{ kind: "tool-call", title: "ls -la", status: "running" }]} />);
    expect(screen.getByText("ls -la")).toBeInTheDocument();
    expect(document.querySelector("[data-subagent-activity]")).toBeNull();
  });

  it("offers a Retry action on a failed history-load line in the live session", async () => {
    const onRetryHistory = vi.fn();
    render(
      <BlockList
        blocks={[
          {
            kind: "status-line",
            text: "Failed to load messages: Load failed",
            tone: "error",
            retry: true,
          },
        ]}
        handlers={{ onRetryHistory }}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(onRetryHistory).toHaveBeenCalledTimes(1);
  });

  it("renders the failed history-load line without a Retry action outside the live session", () => {
    render(
      <BlockList
        blocks={[
          {
            kind: "status-line",
            text: "Failed to load messages: Load failed",
            tone: "error",
            retry: true,
          },
        ]}
      />,
    );
    expect(screen.getByText(/Failed to load messages/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("BlockList · reasoning stays visible", () => {
  it("renders non-empty reasoning in an open, collapsible block and drops empty reasoning", async () => {
    // Kept so the reader can follow how the run reached its answer; dimmed and
    // labelled, so it never reads as something the model SAID.
    const blocks = [
      { kind: "user", text: "go" },
      { kind: "reasoning", text: "Let me look at the workspace" },
      { kind: "reasoning", text: "  \n " },
      { kind: "tool-call", title: "ls -la", status: "success", verb: "Ran" },
      { kind: "agent", markdown: "Done." },
    ] as ThreadBlock[];
    const { container } = render(<BlockList blocks={blocks} />);
    const shown = container.querySelectorAll("details[data-reasoning]");
    expect(shown).toHaveLength(1);
    expect(shown[0]).toHaveAttribute("open");
    expect(shown[0].textContent).toContain("Reasoning");
    expect(shown[0].textContent).toContain("Let me look at the workspace");
    expect(await screen.findByText("Done.")).toBeInTheDocument();
    // The command still folds behind its own line.
    expect(screen.getByRole("button", { name: /Worked/ })).toBeInTheDocument();

    // When multiple reasoning blocks exist, earlier ones collapse while the latest stays open.
    const multi = [
      { kind: "user", text: "go" },
      { kind: "reasoning", text: "First step deliberation" },
      { kind: "tool-call", title: "ls", status: "success", verb: "Ran" },
      { kind: "reasoning", text: "Second step deliberation" },
      { kind: "agent", markdown: "Done." },
    ] as ThreadBlock[];
    const { container: c2 } = render(<BlockList blocks={multi} />);
    const allDetails = c2.querySelectorAll("details[data-reasoning]");
    expect(allDetails).toHaveLength(2);
    expect(allDetails[0]).not.toHaveAttribute("open");
    expect(allDetails[1]).toHaveAttribute("open");
  });

  it("does not make a fold out of a turn whose only work was thinking", () => {
    // Nothing folds away, so there is no fold line.
    const blocks = [
      { kind: "user", text: "go" },
      { kind: "reasoning", text: "thinking about it" },
      { kind: "agent", markdown: "Done." },
    ] as ThreadBlock[];
    render(<BlockList blocks={blocks} />);
    expect(screen.getByText("thinking about it")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Worked/ })).not.toBeInTheDocument();
  });
});

describe("BlockList · a finished turn folds its commands, not its narration", () => {
  const done: ThreadBlock[] = [
    { kind: "user", text: "run the analysis" },
    // Mid-turn narration: the model saying what it is about to do. It stays on
    // screen — only the commands fold.
    { kind: "agent", markdown: "I will simulate the dataset first" },
    { kind: "tool-call", title: "python3 run.py", status: "success", verb: "Ran", startedAt: 1000, endedAt: 3000 },
    { kind: "agent", markdown: "Done. IC50 = 31.8 nM.", created: 3000, completed: 4000 },
  ];

  it("shows the ask, the narration and the answer, and hides the commands behind one line", async () => {
    render(<BlockList blocks={done} />);
    expect(screen.getByText(/run the analysis/)).toBeInTheDocument();
    expect(screen.getByText(/IC50 = 31.8 nM/)).toBeInTheDocument();
    expect(screen.getByText(/simulate the dataset/)).toBeInTheDocument();
    expect(screen.queryByText("python3 run.py")).not.toBeInTheDocument();
    // The line reports the span of the commands it hides.
    expect(await screen.findByRole("button", { name: /Took 2s/ })).toBeInTheDocument();
  });

  it("brings the commands back on a click", async () => {
    render(<BlockList blocks={done} />);
    await userEvent.click(screen.getByRole("button", { name: /Took 2s/ }));
    expect(screen.getByText("python3 run.py")).toBeInTheDocument();
  });

  it("folds nothing while the turn is still running", () => {
    // No answer yet, so there is no finished work to hide — the activity line
    // is the only sign of progress there is.
    const running: ThreadBlock[] = [
      { kind: "user", text: "run the analysis" },
      { kind: "tool-call", title: "python3 run.py", status: "running", verb: "Ran" },
    ];
    render(<BlockList blocks={running} />);
    expect(screen.getByText("python3 run.py")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Worked/ })).not.toBeInTheDocument();
  });
});
