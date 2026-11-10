import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import { useRuntimeStore } from "@/lib/runtime";
import { AgentModelsCard } from "./AgentModelsCard";

const config = vi.hoisted(() => ({ models: {} as Record<string, string>, efforts: {} as Record<string, string> }));
const setAgentModel = vi.hoisted(() => vi.fn(async (_agent: string, _value: string) => {}));
const setAgentVariant = vi.hoisted(() => vi.fn(async (_agent: string, _value: string) => {}));
vi.mock("@/lib/tauri", () => ({
  getAgentModels: async () => config.models,
  getAgentVariants: async () => config.efforts,
  setAgentModel,
  setAgentVariant,
  isTauri: true,
}));
const providers = [{ id: "test", name: "Test", models: [{ id: "model", name: "Model", variants: ["low", "high"] }] }];

afterEach(async () => { await i18n.changeLanguage("en"); });

beforeEach(() => {
  config.models = {};
  config.efforts = {};
  vi.resetAllMocks();
  useRuntimeStore.setState({
    agents: [{ name: "reviewer", description: "", mode: "subagent" }],
    defaultModel: "test/model",
    reloadRuntimeConfig: async (apply) => { await apply(); },
  });
});

it("normalizes legacy roles and descriptions, deduplicates names, and includes configured roles", async () => {
  useRuntimeStore.setState({ agents: [
    { name: "coral-run-doctor", description: "Diagnose CORAL runs", mode: "subagent" },
    { name: "crux-run-doctor", description: "Diagnose Crux runs", mode: "subagent" },
    { name: "coral-task-author", description: "Write CORAL tasks", mode: "subagent" },
  ] });
  config.models = { "coral-run-doctor": "test/model", analyst: "test/model" };
  config.efforts = { scientist: "high", title: "low", "coral-run-doctor": "high" };
  render(<AgentModelsCard providers={providers} />);
  expect(await screen.findByLabelText("Model for analyst")).toHaveValue("test/model");
  expect(screen.getByLabelText("Reasoning effort for scientist")).toHaveValue("high");
  expect(screen.getAllByLabelText("Model for crux-run-doctor")).toHaveLength(1);
  expect(screen.getByLabelText("Model for crux-run-doctor")).toHaveValue("test/model");
  expect(screen.getByText("Write Crux tasks")).toBeInTheDocument();
  expect(screen.queryByText(/coral-|CORAL/)).not.toBeInTheDocument();
  expect(screen.getAllByLabelText("Model for title")).toHaveLength(1);
  await userEvent.selectOptions(screen.getByLabelText("Reasoning effort for crux-run-doctor"), "low");
  expect(setAgentModel).toHaveBeenCalledWith("crux-run-doctor", "test/model");
  expect(setAgentVariant).toHaveBeenCalledWith("crux-run-doctor", "low");
  expect(setAgentVariant).toHaveBeenCalledWith("coral-run-doctor", "");
  await userEvent.click(screen.getByRole("button", { name: "Reset configuration for crux-run-doctor" }));
  await waitFor(() => expect(setAgentModel).toHaveBeenCalledWith("coral-run-doctor", ""));
  expect(screen.getByLabelText("Model for crux-run-doctor")).toHaveValue("");
});

it.each(["scientist", "constructor", "__proto__"])("adds, configures, and removes custom role %s while rejecting duplicates", async (role) => {
  const user = userEvent.setup();
  render(<AgentModelsCard providers={providers} />);
  const name = await screen.findByRole("textbox", { name: "Role name" });
  const add = screen.getByRole("button", { name: "Add role" });
  expect(add).toBeDisabled();
  await user.type(name, `  ${role}  `);
  await user.click(add);
  await user.selectOptions(screen.getByLabelText(`Model for ${role}`), "test/model");
  await user.selectOptions(screen.getByLabelText(`Reasoning effort for ${role}`), "high");
  expect(setAgentModel).toHaveBeenCalledWith(role, "test/model");
  expect(setAgentVariant).toHaveBeenCalledWith(role, "high");
  await user.type(name, role);
  expect(add).toBeDisabled();
  await user.click(screen.getByRole("button", { name: `Remove role ${role}` }));
  await waitFor(() => expect(screen.queryByLabelText(`Model for ${role}`)).not.toBeInTheDocument());
  expect(setAgentModel).toHaveBeenCalledWith(role, "");
  expect(setAgentVariant).toHaveBeenCalledWith(role, "");
});

it("keeps configured roles removable when their provider is unavailable", async () => {
  config.models = { scientist: "missing/model" };
  render(<AgentModelsCard providers={[]} />);
  expect(await screen.findByLabelText("Model for scientist")).toHaveValue("missing/model");
  await userEvent.click(screen.getByRole("button", { name: "Remove role scientist" }));
  await waitFor(() => expect(screen.queryByLabelText("Model for scientist")).not.toBeInTheDocument());
});

it("shows failed writes and lets the user retry without losing the role", async () => {
  config.models = { scientist: "test/model" };
  setAgentModel.mockRejectedValueOnce(new Error("Could not save configuration"));
  render(<AgentModelsCard providers={providers} />);
  const remove = await screen.findByRole("button", { name: "Remove role scientist" });
  await userEvent.click(remove);
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not save configuration");
  expect(screen.getByLabelText("Model for scientist")).toHaveValue("test/model");
  expect(remove).toBeEnabled();
  await userEvent.click(remove);
  await waitFor(() => expect(screen.queryByLabelText("Model for scientist")).not.toBeInTheDocument());
});

it("localizes built-in descriptions, preserves custom copy, and groups utility roles separately", async () => {
  await i18n.changeLanguage("zh-Hans");
  useRuntimeStore.setState({ agents: [
    { name: "build", description: "The default agent. Executes tools based on configured permissions.", mode: "primary" },
    { name: "plan", description: "", mode: "primary" },
    { name: "reviewer", description: "Reviews only our lab's notebooks.", mode: "subagent" },
    { name: "specialist", description: "Custom scientific specialist.", mode: "subagent" },
    ...["title", "summary", "compaction"].map((name) => ({ name, description: "", mode: "primary" })),
  ] });
  const view = render(<AgentModelsCard providers={providers} />);
  expect(await screen.findByText("执行任务，并根据配置的权限使用工具。")).toBeInTheDocument();
  expect(screen.getByText("分析需求并制定执行计划。")).toBeInTheDocument();
  expect(screen.getByText("Reviews only our lab's notebooks.")).toBeInTheDocument();
  expect(screen.getByText("Custom scientific specialist.")).toBeInTheDocument();
  const utility = screen.getByText("工作台自己调用的").parentElement!.nextElementSibling as HTMLElement;
  for (const name of ["title", "summary", "compaction"]) {
    expect(within(utility).getByLabelText(`${name} 使用的模型`)).toBeInTheDocument();
    expect(screen.getAllByLabelText(`${name} 使用的模型`)).toHaveLength(1);
  }
  expect(within(utility).getByText("根据首条消息给会话命名。")).toBeInTheDocument();
  view.unmount();
});
