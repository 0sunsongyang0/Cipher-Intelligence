import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { InviteCodesPanel } from "./InviteCodesPanel";

vi.mock("../../lib/api", () => ({
  createAdminInvite: vi.fn(),
  deleteAdminInvite: vi.fn(),
  getAdminInvites: vi.fn(),
  toggleAdminInvite: vi.fn()
}));

describe("InviteCodesPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders invite codes and creates a new invite", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAdminInvites)
      .mockResolvedValueOnce({ items: [] })
      .mockResolvedValueOnce({
        items: [
          {
            id: 1,
            code: "SMBU@2014520uu-",
            label: "July batch",
            isActive: true,
            maxUses: 5,
            usedCount: 0,
            expiresAt: null,
            createdAt: "2026-07-09T10:00:00Z"
          }
        ]
      });
    vi.mocked(api.createAdminInvite).mockResolvedValue({
      id: 1,
      code: "SMBU@2014520uu-",
      label: "July batch",
      isActive: true,
      maxUses: 5,
      usedCount: 0,
      expiresAt: null,
      createdAt: "2026-07-09T10:00:00Z"
    });

    render(<InviteCodesPanel />);

    await user.type(await screen.findByLabelText("邀请码"), "SMBU@2014520uu-");
    await user.type(screen.getByLabelText("标签"), "July batch");
    await user.type(screen.getByLabelText("最多使用次数"), "5");
    await user.click(screen.getByRole("button", { name: "创建邀请码" }));

    expect(api.createAdminInvite).toHaveBeenCalledWith({
      code: "SMBU@2014520uu-",
      label: "July batch",
      maxUses: 5,
      expiresAt: null,
      isActive: true
    });
    expect(await screen.findByText("July batch")).toBeInTheDocument();
  });

  it("toggles and deletes an invite, reloading after each action", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAdminInvites)
      .mockResolvedValueOnce({
        items: [
          {
            id: 1,
            code: "SMBU@2014520uu-",
            label: "July batch",
            isActive: true,
            maxUses: 5,
            usedCount: 1,
            expiresAt: null,
            createdAt: "2026-07-09T10:00:00Z"
          }
        ]
      })
      .mockResolvedValueOnce({
        items: [
          {
            id: 1,
            code: "SMBU@2014520uu-",
            label: "July batch",
            isActive: false,
            maxUses: 5,
            usedCount: 1,
            expiresAt: null,
            createdAt: "2026-07-09T10:00:00Z"
          }
        ]
      })
      .mockResolvedValueOnce({ items: [] });
    vi.mocked(api.toggleAdminInvite).mockResolvedValue({
      id: 1,
      code: "SMBU@2014520uu-",
      label: "July batch",
      isActive: false,
      maxUses: 5,
      usedCount: 1,
      expiresAt: null,
      createdAt: "2026-07-09T10:00:00Z"
    });
    vi.mocked(api.deleteAdminInvite).mockResolvedValue(undefined);

    render(<InviteCodesPanel />);

    await user.click(await screen.findByRole("button", { name: "停用" }));

    expect(api.toggleAdminInvite).toHaveBeenCalledWith(1);
    expect(await screen.findByText("已停用")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "删除" }));

    expect(api.deleteAdminInvite).toHaveBeenCalledWith(1);
    await waitFor(() => {
      expect(screen.queryByText("July batch")).not.toBeInTheDocument();
    });
    expect(api.getAdminInvites).toHaveBeenCalledTimes(3);
  });
});
