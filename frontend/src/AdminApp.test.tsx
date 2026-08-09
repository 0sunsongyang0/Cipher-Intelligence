import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminApp } from "./AdminApp";
import * as api from "./lib/api";

vi.mock("./lib/api", () => ({
  checkSession: vi.fn(),
  getCasdoorAuthConfig: vi.fn(),
  clearAdminFileCache: vi.fn(),
  controlAdminService: vi.fn(),
  getAdminObservability: vi.fn(),
  getAdminOverview: vi.fn(),
  getAdminQuality: vi.fn(),
  logout: vi.fn(),
}));

function LocationProbe() {
  const location = useLocation();

  return <output data-testid="admin-location">{location.pathname}</output>;
}

describe("AdminApp", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getCasdoorAuthConfig).mockResolvedValue({
      enabled: true,
      provider: "casdoor",
      displayName: "Casdoor",
      managementUrl: "http://127.0.0.1:7001",
    });
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
        publicUrl: "https://chat.example.invalid/chat",
      },
      models: {
        providers: [
          { provider: "Cipher 轻量", healthy: 2, total: 2 },
          { provider: "Cipher 均衡", healthy: 4, total: 4 },
          { provider: "Cipher 深研", healthy: 6, total: 6 },
        ],
      },
      files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 3 },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <AdminApp />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "系统管理" })).toBeInTheDocument();
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
    expect(await screen.findByRole("alert")).toHaveTextContent("没有 Cipher 管理权限");
    expect(screen.queryByRole("heading", { name: "系统管理" })).not.toBeInTheDocument();
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
    expect(await screen.findByTitle("Casdoor 登录")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "系统管理" })).not.toBeInTheDocument();
  });

  it("keeps admin section links and section detection relative to a non-root mount path", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: true,
      user: { id: 4, username: "admin", isAdmin: true },
    });
    vi.mocked(api.getAdminOverview).mockResolvedValue({
      services: {
        backend: { running: true, label: "running", detail: "Backend service is running." },
        tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
        autostartEnabled: true,
      },
      access: {
        localUrl: "http://127.0.0.1:8000/chat",
        publicUrl: "https://chat.example.invalid/chat",
      },
      models: {
        providers: [{ provider: "Cipher 轻量", healthy: 2, total: 2 }],
      },
      files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 3 },
    });

    render(
      <MemoryRouter initialEntries={["/admin.html/models"]}>
        <AdminApp />
        <LocationProbe />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "系统管理" })).toBeInTheDocument();
    expect(await screen.findByText("Cipher 轻量")).toBeInTheDocument();
    expect(screen.queryByText("http://127.0.0.1:8000/chat")).not.toBeInTheDocument();
    expect(screen.getByTestId("admin-location")).toHaveTextContent("/admin.html/models");

    await user.click(screen.getByRole("link", { name: "服务" }));

    expect(await screen.findByText("http://127.0.0.1:8000/chat")).toBeInTheDocument();
    expect(screen.getByTestId("admin-location")).toHaveTextContent("/admin.html/services");
  });

  it("keeps admin login and logout navigation on the non-root mount path", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession)
      .mockResolvedValueOnce({ authenticated: false, user: null })
      .mockResolvedValueOnce({
        authenticated: true,
        user: { id: 5, username: "admin", isAdmin: true },
      });
    vi.mocked(api.getAdminOverview).mockResolvedValue({
      services: {
        backend: { running: true, label: "running", detail: "Backend service is running." },
        tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
        autostartEnabled: true,
      },
      access: {
        localUrl: "http://127.0.0.1:8000/chat",
        publicUrl: "https://chat.example.invalid/chat",
      },
      models: {
        providers: [{ provider: "Cipher 轻量", healthy: 2, total: 2 }],
      },
      files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 3 },
    });
    vi.mocked(api.logout).mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/admin.html"]}>
        <AdminApp />
        <LocationProbe />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "进入管理后台" })).toBeInTheDocument();
    const frame = (await screen.findByTitle("Casdoor 登录")) as HTMLIFrameElement;
    window.dispatchEvent(
      new MessageEvent("message", {
        origin: window.location.origin,
        source: frame.contentWindow,
        data: { type: "cipher:casdoor-auth", status: "success" },
      })
    );

    expect(await screen.findByRole("heading", { name: "系统管理" })).toBeInTheDocument();
    expect(screen.getByTestId("admin-location")).toHaveTextContent("/admin.html");

    await user.click(screen.getByRole("button", { name: "退出登录" }));

    expect(await screen.findByRole("heading", { name: "进入管理后台" })).toBeInTheDocument();
    expect(screen.getByTestId("admin-location")).toHaveTextContent("/admin.html");
  });

  it("preserves the requested admin subsection after a successful login", async () => {
    vi.mocked(api.checkSession)
      .mockResolvedValueOnce({ authenticated: false, user: null })
      .mockResolvedValueOnce({
        authenticated: true,
        user: { id: 6, username: "admin", isAdmin: true },
      });
    vi.mocked(api.getAdminOverview).mockResolvedValue({
      services: {
        backend: { running: true, label: "running", detail: "Backend service is running." },
        tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
        autostartEnabled: true,
      },
      access: {
        localUrl: "http://127.0.0.1:8000/chat",
        publicUrl: "https://chat.example.invalid/chat",
      },
      models: {
        providers: [{ provider: "Cipher 轻量", healthy: 2, total: 2 }],
      },
      files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 3 },
    });

    render(
      <MemoryRouter initialEntries={["/admin.html/models"]}>
        <AdminApp />
        <LocationProbe />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "进入管理后台" })).toBeInTheDocument();
    const frame = (await screen.findByTitle("Casdoor 登录")) as HTMLIFrameElement;
    window.dispatchEvent(
      new MessageEvent("message", {
        origin: window.location.origin,
        source: frame.contentWindow,
        data: { type: "cipher:casdoor-auth", status: "success" },
      })
    );

    expect(await screen.findByText("Cipher 轻量")).toBeInTheDocument();
    expect(screen.queryByText("http://127.0.0.1:8000/chat")).not.toBeInTheDocument();
    expect(screen.getByTestId("admin-location")).toHaveTextContent("/admin.html/models");
  });

  it("shows a session restore error instead of silently treating admin backend failures as logged out", async () => {
    vi.mocked(api.checkSession).mockRejectedValue(new Error("session backend unavailable"));

    render(
      <MemoryRouter initialEntries={["/admin.html/models"]}>
        <AdminApp />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "进入管理后台" })).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("session backend unavailable");
    expect(screen.queryByRole("heading", { name: "系统管理" })).not.toBeInTheDocument();
  });
});
