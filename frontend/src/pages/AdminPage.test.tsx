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
  getCapeTaskStatus: vi.fn(),
  getCapeTaskSummary: vi.fn(),
  getAdminInvites: vi.fn(),
  getAdminObservability: vi.fn(),
  getAdminOverview: vi.fn(),
  getAdminPrompt: vi.fn(),
  getAdminQuality: vi.fn(),
  submitCapeSample: vi.fn(),
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
          { provider: "Cipher 轻量", healthy: 2, total: 2 },
          { provider: "Cipher 均衡", healthy: 4, total: 4 },
          { provider: "Cipher 深研", healthy: 6, total: 6 }
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
    expect(screen.getByText("Cipher 轻量")).toBeInTheDocument();
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

  it("embeds the Casdoor console in the identity-management section", async () => {
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

    render(
      <MemoryRouter initialEntries={["/identity"]}>
        <AdminPage
          onLogout={() => undefined}
          casdoorManagementUrl="http://127.0.0.1:7001"
        />
      </MemoryRouter>
    );

    expect(await screen.findByRole("link", { name: "身份管理" })).toBeInTheDocument();
    expect(screen.getByTitle("Casdoor 身份管理")).toHaveAttribute(
      "src",
      "http://127.0.0.1:7001"
    );
    expect(screen.queryByText("统一身份管理")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "新窗口打开" })).not.toBeInTheDocument();
    expect(document.querySelector(".admin-console__content--identity")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "邀请码" })).not.toBeInTheDocument();
  });

  it("shows the CAPE section inside admin navigation", async () => {
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

    render(
      <MemoryRouter initialEntries={["/cape"]}>
        <AdminPage onLogout={() => undefined} />
      </MemoryRouter>
    );

    expect(await screen.findByRole("link", { name: "CAPE" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "本地沙箱提交" })).toBeInTheDocument();
  });
  it("keeps identity management usable when overview loading fails", async () => {
    vi.mocked(api.getAdminOverview).mockRejectedValue(new Error("overview unavailable"));

    render(
      <MemoryRouter initialEntries={["/identity"]}>
        <AdminPage
          onLogout={() => undefined}
          casdoorManagementUrl="http://127.0.0.1:7001"
        />
      </MemoryRouter>
    );

    expect(await screen.findByTitle("Casdoor 身份管理")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
