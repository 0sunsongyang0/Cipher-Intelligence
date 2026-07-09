import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminApp } from "./AdminApp";
import * as api from "./lib/api";

vi.mock("./lib/api", () => ({
  checkSession: vi.fn(),
  clearAdminFileCache: vi.fn(),
  controlAdminService: vi.fn(),
  getAdminOverview: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));

describe("AdminApp", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not reload admin overview data when switching between admin sections", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: true,
      user: { id: 1, username: "admin", isAdmin: true },
    });
    vi.mocked(api.getAdminOverview).mockResolvedValue({
      services: {
        backend: { running: true, label: "running", detail: "Backend service is running." },
        tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
        autostartEnabled: true,
      },
      access: {
        localUrl: "http://127.0.0.1:8000/chat",
        publicUrl: "https://[private-host]/chat",
      },
      models: {
        providers: [
          { provider: "DeepSeek", healthy: 2, total: 2 },
          { provider: "OpenAI", healthy: 4, total: 4 },
          { provider: "Claude", healthy: 6, total: 6 },
        ],
      },
      files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 3 },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AdminApp />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "后端管理" })).toBeInTheDocument();
    await waitFor(() => {
      expect(api.getAdminOverview).toHaveBeenCalledTimes(1);
    });

    await user.click(screen.getByRole("link", { name: "模型" }));

    await waitFor(() => {
      expect(screen.queryByText("访问状态")).not.toBeInTheDocument();
    });
    expect(api.getAdminOverview).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("link", { name: "服务" }));

    await waitFor(() => {
      expect(screen.getByText("访问状态")).toBeInTheDocument();
    });
    expect(api.getAdminOverview).toHaveBeenCalledTimes(1);
  });

  it("rejects non-admin users and keeps them on the admin login page", async () => {
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: true,
      user: { id: 2, username: "alice", isAdmin: false },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AdminApp />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "进入管理后台" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Admin access required");
    expect(screen.queryByRole("heading", { name: "后端管理" })).not.toBeInTheDocument();
  });

  it("rejects inconsistent unauthenticated admin sessions even with a user payload", async () => {
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: false,
      user: { id: 3, username: "admin", isAdmin: true },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AdminApp />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "进入管理后台" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Admin access required");
    expect(screen.queryByRole("heading", { name: "后端管理" })).not.toBeInTheDocument();
  });
});
