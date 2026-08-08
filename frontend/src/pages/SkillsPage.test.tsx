import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as api from "../lib/api";
import { SkillsPage } from "./SkillsPage";

vi.mock("../lib/api", () => ({
  getSkills: vi.fn(), getSkillHistory: vi.fn(), installSkill: vi.fn(),
  uninstallSkill: vi.fn(), runSkill: vi.fn()
}));

const skill = {
  id: 7, key: "ioc-enrichment", name: "IOC 情报富化", version: "1.0.0",
  description: "汇总外部情报", author: "Cipher", source: "builtin", sourceUrl: null,
  permissions: ["threat_intel.lookup_ioc"], reviewStatus: "verified", enabled: true,
  scanStatus: "clean", category: "threat-intelligence", tags: ["IOC", "MISP"],
  pricing: "included", featured: true, installed: false, installCount: 12, runCount: 40,
  entitlement: { tier: "standard" as const, allowed: true },
  inputs: { required: ["iocs"], properties: { iocs: { type: "array" as const, label: "IOC 列表" } } }
};

describe("SkillsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getSkills).mockResolvedValue({ items: [skill] });
    vi.mocked(api.getSkillHistory).mockResolvedValue({ items: [] });
    vi.mocked(api.installSkill).mockResolvedValue({ ...skill, installed: true, installCount: 13 });
  });

  it("shows marketplace metadata and installs a reviewed skill", async () => {
    const user = userEvent.setup();
    const { container } = render(<SkillsPage onBack={vi.fn()}/>);
    expect(container.querySelector(".skill-market__pixel-background")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "IOC 情报富化" })).toBeInTheDocument();
    expect(screen.getByText("12 次安装 · 40 次运行")).toBeInTheDocument();
    expect(screen.getByText("MISP")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "安装" }));
    await waitFor(() => expect(api.installSkill).toHaveBeenCalledWith(7));
    expect(await screen.findByText("IOC 情报富化 已安装")).toBeInTheDocument();
  });

  it("opens details in a modal and installs from the modal action", async () => {
    const user = userEvent.setup();
    render(<SkillsPage onBack={vi.fn()}/>);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "查看 IOC 情报富化 详情" }));
    const dialog = await screen.findByRole("dialog", { name: "IOC 情报富化" });
    expect(within(dialog).getByText("threat_intel.lookup_ioc")).toBeInTheDocument();
    expect(within(dialog).getByText("当前套餐内含")).toBeInTheDocument();
    expect(document.body.style.overflow).toBe("hidden");
    await user.click(within(dialog).getByRole("button", { name: "安装 Skill" }));
    await waitFor(() => expect(api.installSkill).toHaveBeenCalledWith(7));
    expect(await within(dialog).findByRole("button", { name: "运行 Skill" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "运行 Skill" })).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox"));
    expect(within(dialog).getByRole("button", { name: "运行 Skill" })).toBeEnabled();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(document.body.style.overflow).toBe("");
  });

  it("keeps the marketplace usable when the optional history endpoint is unavailable", async () => {
    vi.mocked(api.getSkillHistory).mockRejectedValue(new Error("Method Not Allowed"));
    render(<SkillsPage onBack={vi.fn()}/>);
    expect(await screen.findByRole("heading", { name: "IOC 情报富化" })).toBeInTheDocument();
    const overview = screen.getByLabelText("Skills 概览");
    expect(within(overview).getByRole("heading", { name: "最近运行" })).toBeInTheDocument();
    expect(within(overview).getByText("暂无运行记录")).toBeInTheDocument();
    expect(screen.queryByText("Method Not Allowed")).not.toBeInTheDocument();
  });
});
