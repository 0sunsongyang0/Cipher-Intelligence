import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LocalConversation } from "../../types";
import { CaseWorkspaceDrawer } from "./CaseWorkspaceDrawer";

const conversation: LocalConversation = {
  id: "42",
  title: "可疑样本事件",
  caseStatus: "investigating",
  severity: "high",
  assignee: "SOC 一线",
  tags: ["恶意软件"],
  caseSummary: "正在确认持久化行为。",
  createdAt: "2026-08-06T08:00:00.000Z",
  updatedAt: "2026-08-06T08:10:00.000Z",
  messages: [
    {
      id: "m1",
      role: "assistant",
      content: "该域名存在风险 [W1]。",
      createdAt: "2026-08-06T08:10:00.000Z",
      evidence: [
        {
          citation: "W1",
          sourceType: "web",
          title: "Threat advisory",
          url: "https://example.test/advisory"
        }
      ]
    }
  ],
  capeCases: [
    {
      id: 8,
      conversationId: 42,
      taskId: 88,
      sampleName: "sample.exe",
      status: "reported",
      completed: true,
      score: 8.1,
      targetFilename: "sample.exe",
      machine: "win10",
      sha256: "a".repeat(64),
      reusedExistingTask: false,
      summary: {
        taskId: 88,
        status: "reported",
        score: 8.1,
        submittedFilename: "sample.exe",
        sha256: "a".repeat(64),
        iocs: { domains: ["evil.example"], ips: [], urls: [] },
        tactics: [],
        droppedFiles: [],
        signatures: []
      },
      createdAt: "2026-08-06T08:00:00.000Z",
      updatedAt: "2026-08-06T08:10:00.000Z"
    }
  ]
};

describe("CaseWorkspaceDrawer", () => {
  it("saves case metadata and exposes the evidence ledger", async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined);

    render(
      <CaseWorkspaceDrawer
        open
        conversation={conversation}
        onClose={vi.fn()}
        onUpdate={onUpdate}
        onExport={vi.fn().mockResolvedValue(undefined)}
      />
    );

    expect(screen.getByText("证据台账")).toBeInTheDocument();
    expect(screen.getByText("[W1] Threat advisory")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("研判摘要"), { target: { value: "已确认恶意持久化。" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 Case" }));

    await waitFor(() => {
      expect(onUpdate).toHaveBeenCalledWith("42", expect.objectContaining({
        caseStatus: "investigating",
        severity: "high",
        caseSummary: "已确认恶意持久化。"
      }));
    });
  });

  it("exports a complete CAPE evidence bundle", async () => {
    const onExport = vi.fn().mockResolvedValue(undefined);
    render(
      <CaseWorkspaceDrawer
        open
        conversation={conversation}
        onClose={vi.fn()}
        onUpdate={vi.fn().mockResolvedValue(undefined)}
        onExport={onExport}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /完整证据包/ }));
    await waitFor(() => expect(onExport).toHaveBeenCalledWith(8, "bundle"));
  });
});
