import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CaseAnalysisPanel } from "./CaseAnalysisPanel";
import { getCaseAnalysis } from "../../lib/api";

vi.mock("../../lib/api", () => ({ getCaseAnalysis: vi.fn() }));

const analysis = {
  caseId: 7,
  events: [
    { id: "cape:1:network:0", type: "network", title: "网络连接 command.example", detail: "https", occurredAt: "2026-08-08T01:03:00Z", timeAccuracy: "estimated" as const, timeNote: "源数据未提供事件时间", source: "cape", sourceLabel: "CAPE 网络行为", risk: "high" as const, evidence: { label: "CAPE Task #1", href: "/api/cape/tasks/1/summary" }, metadata: {} },
    { id: "case:2", type: "created", title: "Case 已创建", detail: null, occurredAt: "2026-08-08T01:00:00Z", timeAccuracy: "exact" as const, timeNote: null, source: "case", sourceLabel: "Case 审计", risk: "medium" as const, evidence: null, metadata: {} },
  ],
  graph: {
    nodes: [
      { id: "case:7", type: "case", label: "Case #7", risk: "medium" as const, detail: { status: "open" }, evidence: null },
      { id: "domain:command.example", type: "domain", label: "command.example", risk: "high" as const, detail: { protocol: "https" }, evidence: { label: "CAPE Task #1", href: "/api/cape/tasks/1/summary" } },
    ],
    edges: [{ id: "edge", source: "case:7", target: "domain:command.example", relation: "observes", evidence: null }],
  },
  coverage: { sources: ["cape", "case"], exactTimes: 1, estimatedTimes: 1, notes: [] },
};

describe("CaseAnalysisPanel", () => {
  beforeEach(() => vi.mocked(getCaseAnalysis).mockResolvedValue(analysis));

  it("filters timeline events and explains estimated time", async () => {
    const user = userEvent.setup(); render(<CaseAnalysisPanel caseId={7}/>);
    expect(await screen.findByText("网络连接 command.example")).toBeInTheDocument();
    expect(screen.getByText(/推定时间 1 条/)).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("来源"), "case");
    expect(screen.queryByText("网络连接 command.example")).not.toBeInTheDocument();
    expect(screen.getByText("Case 已创建")).toBeInTheDocument();
  });

  it("supports graph zoom and node details", async () => {
    const user = userEvent.setup(); render(<CaseAnalysisPanel caseId={7}/>);
    await screen.findByRole("heading", { name: "事件关系图" });
    await user.click(screen.getByRole("button", { name: "放大" }));
    expect(screen.getByText("120%")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /command\.example/ }));
    await waitFor(() => expect(screen.getByText("protocol")).toBeInTheDocument());
    expect(screen.getAllByRole("link", { name: /CAPE Task #1/ }).at(-1)).toHaveAttribute("href", "/api/cape/tasks/1/summary");
  });
});
