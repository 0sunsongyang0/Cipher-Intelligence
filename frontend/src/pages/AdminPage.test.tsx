import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../lib/api";
import { AdminPage } from "./AdminPage";

vi.mock("../lib/api", () => ({
  clearAdminFileCache: vi.fn(),
  controlAdminService: vi.fn(),
  createAdminInvite: vi.fn(),
  deleteAdminInvite: vi.fn(),
  getAdminInvites: vi.fn(),
  getAdminOverview: vi.fn(),
  getAdminPrompt: vi.fn(),
  resetAdminPrompt: vi.fn(),
  saveAdminPrompt: vi.fn(),
  toggleAdminInvite: vi.fn()
}));

describe("AdminPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
  });

  it("shows service, access, model, and file overview sections", async () => {
    vi.mocked(api.getAdminOverview).mockResolvedValue({
      services: {
        backend: { running: true, label: "running", detail: "Backend service is running." },
        tunnel: { running: false, label: "stopped", detail: "Cloudflare tunnel is stopped." },
        autostartEnabled: true
      },
      access: {
        localUrl: "http://127.0.0.1:8000/chat",
        publicUrl: "https://[private-host]/chat"
      },
      models: {
        providers: [
          { provider: "DeepSeek", healthy: 2, total: 2 },
          { provider: "OpenAI", healthy: 4, total: 4 },
          { provider: "Claude", healthy: 6, total: 6 }
        ]
      },
      files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 3 }
    });

    render(
      <MemoryRouter>
        <AdminPage onLogout={() => undefined} />
      </MemoryRouter>
    );

    expect(await screen.findByText("Backend service is running.")).toBeInTheDocument();
    expect(screen.getByText("Cloudflare tunnel is stopped.")).toBeInTheDocument();
    expect(screen.getByText("http://127.0.0.1:8000/chat")).toBeInTheDocument();
    expect(screen.getByText("https://[private-host]/chat")).toBeInTheDocument();
    expect(screen.getByText("DeepSeek")).toBeInTheDocument();
    expect(screen.getByText(/10/)).toBeInTheDocument();
  });

  it("sends a backend stop action and refreshes status", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAdminOverview)
      .mockResolvedValueOnce({
        services: {
          backend: { running: true, label: "running", detail: "Backend service is running." },
          tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
          autostartEnabled: true
        },
        access: {
          localUrl: "http://127.0.0.1:8000/chat",
          publicUrl: "https://[private-host]/chat"
        },
        models: { providers: [] },
        files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 0 }
      })
      .mockResolvedValueOnce({
        services: {
          backend: { running: false, label: "stopped", detail: "Backend service is stopped." },
          tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
          autostartEnabled: true
        },
        access: {
          localUrl: "http://127.0.0.1:8000/chat",
          publicUrl: "https://[private-host]/chat"
        },
        models: { providers: [] },
        files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 0 }
      });
    vi.mocked(api.controlAdminService).mockResolvedValue(undefined);

    render(
      <MemoryRouter>
        <AdminPage onLogout={() => undefined} />
      </MemoryRouter>
    );

    const backendDetail = await screen.findByText("Backend service is running.");
    const backendCard = backendDetail.closest("section");

    expect(backendCard).not.toBeNull();

    await user.click(within(backendCard as HTMLElement).getByRole("button"));

    expect(api.controlAdminService).toHaveBeenCalledWith("backend", "stop");
    expect(await screen.findByText("Backend service is stopped.")).toBeInTheDocument();
  });

  it("clears zip cache and refreshes the files section", async () => {
    const user = userEvent.setup();
    vi.mocked(api.getAdminOverview)
      .mockResolvedValueOnce({
        services: {
          backend: { running: true, label: "running", detail: "Backend service is running." },
          tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
          autostartEnabled: true
        },
        access: {
          localUrl: "http://127.0.0.1:8000/chat",
          publicUrl: "https://[private-host]/chat"
        },
        models: { providers: [] },
        files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 3 }
      })
      .mockResolvedValueOnce({
        services: {
          backend: { running: true, label: "running", detail: "Backend service is running." },
          tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
          autostartEnabled: true
        },
        access: {
          localUrl: "http://127.0.0.1:8000/chat",
          publicUrl: "https://[private-host]/chat"
        },
        models: { providers: [] },
        files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 0 }
      });
    vi.mocked(api.clearAdminFileCache).mockResolvedValue({ ok: true, cleared: 3 });

    render(
      <MemoryRouter initialEntries={["/files"]}>
        <AdminPage onLogout={() => undefined} />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole("button", { name: /zip/i }));

    expect(api.clearAdminFileCache).toHaveBeenCalledTimes(1);
    expect(api.getAdminOverview).toHaveBeenCalledTimes(2);
    expect(await screen.findByRole("status")).toHaveTextContent("3");
  });

  it("shows the invites section inside admin navigation", async () => {
    vi.mocked(api.getAdminOverview).mockResolvedValue({
      services: {
        backend: { running: true, label: "running", detail: "Backend service is running." },
        tunnel: { running: true, label: "running", detail: "Cloudflare tunnel is running." },
        autostartEnabled: true
      },
      access: {
        localUrl: "http://127.0.0.1:8000/chat",
        publicUrl: "https://[private-host]/chat"
      },
      models: { providers: [] },
      files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 0 }
    });
    vi.mocked(api.getAdminInvites).mockResolvedValue({ items: [] });

    render(
      <MemoryRouter initialEntries={["/invites"]}>
        <AdminPage onLogout={() => undefined} />
      </MemoryRouter>
    );

    expect(await screen.findByRole("link", { name: "邀请码" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "邀请码管理" })).toBeInTheDocument();
  });
  it("keeps invites usable when overview loading fails", async () => {
    vi.mocked(api.getAdminOverview).mockRejectedValue(new Error("overview unavailable"));
    vi.mocked(api.getAdminInvites).mockResolvedValue({ items: [] });

    render(
      <MemoryRouter initialEntries={["/invites"]}>
        <AdminPage onLogout={() => undefined} />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "邀请码管理" })).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("overview unavailable");
  });
});
