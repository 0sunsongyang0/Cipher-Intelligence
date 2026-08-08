import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import * as api from "./lib/api";

vi.mock("./lib/api", () => ({
  checkSession: vi.fn(),
  getAccountOverview: vi.fn(),
  getCasdoorAuthConfig: vi.fn(),
  logout: vi.fn(),
  syncAccount: vi.fn(),
  updateAccountProfile: vi.fn(),
}));

vi.mock("./components/webllm/AppShell", () => ({
  AppShell: ({
    onLogout,
    sessionError,
  }: {
    onLogout: () => Promise<void> | void;
    sessionError?: string | null;
  }) => (
    <div>
      <h1>Cipher AI</h1>
      {sessionError ? <p role="alert">{sessionError}</p> : null}
      <button type="button" onClick={() => void onLogout()}>
        Log out
      </button>
    </div>
  ),
}));

describe("App", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(api.getCasdoorAuthConfig).mockResolvedValue({
      enabled: true,
      provider: "casdoor",
      displayName: "Casdoor",
      managementUrl: "",
    });
  });

  it("shows a loading state, restores the session, and redirects anonymous chat visits to Casdoor", async () => {
    let resolveSession: ((value: Awaited<ReturnType<typeof api.checkSession>>) => void) | undefined;
    vi.mocked(api.checkSession).mockReturnValue(
      new Promise((resolve) => {
        resolveSession = resolve;
      })
    );

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(screen.getByRole("heading", { name: "正在恢复会话" })).toBeInTheDocument();
    resolveSession?.({ authenticated: false, user: null });

    expect(await screen.findByTitle("Casdoor 登录")).toBeInTheDocument();
    expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
  });

  it("does not treat anonymous or inconsistent sessions as authenticated", async () => {
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: false,
      user: { id: 9, username: "alice", isAdmin: false },
    });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByTestId("login-auth-surface")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Cipher AI" })).not.toBeInTheDocument();
  });

  it("finishes login from the embedded Casdoor callback and opens chat", async () => {
    vi.mocked(api.checkSession)
      .mockResolvedValueOnce({ authenticated: false, user: null })
      .mockResolvedValueOnce({
        authenticated: true,
        user: { id: 1, username: "alice", isAdmin: false },
      });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    const frame = (await screen.findByTitle("Casdoor 登录")) as HTMLIFrameElement;
    fireEvent(
      window,
      new MessageEvent("message", {
        origin: window.location.origin,
        source: frame.contentWindow,
        data: { type: "cipher:casdoor-auth", status: "success" },
      })
    );

    expect(await screen.findByRole("heading", { name: "Cipher AI" })).toBeInTheDocument();
    expect(api.checkSession).toHaveBeenCalledTimes(2);
  });

  it("keeps the Casdoor surface visible when the callback does not establish a Cipher session", async () => {
    vi.mocked(api.checkSession).mockResolvedValue({ authenticated: false, user: null });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    const frame = (await screen.findByTitle("Casdoor 登录")) as HTMLIFrameElement;
    fireEvent(
      window,
      new MessageEvent("message", {
        origin: window.location.origin,
        source: frame.contentWindow,
        data: { type: "cipher:casdoor-auth", status: "success" },
      })
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Cipher 会话未能建立");
    expect(screen.queryByRole("heading", { name: "Cipher AI" })).not.toBeInTheDocument();
  });

  it("shows an auth-screen error when restoring the session fails", async () => {
    vi.mocked(api.checkSession).mockRejectedValue(new Error("session backend unavailable"));

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("session backend unavailable");
    expect(screen.getByTestId("login-auth-surface")).toBeInTheDocument();
  });

  it("renders the chat shell for an authenticated Casdoor user", async () => {
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: true,
      user: { id: 3, username: "alice", isAdmin: false },
    });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByRole("heading", { name: "Cipher AI" })).toBeInTheDocument();
  });

  it("logs out and returns to the Casdoor-only login surface", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: true,
      user: { id: 4, username: "alice", isAdmin: false },
    });
    vi.mocked(api.logout).mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole("button", { name: "Log out" }));

    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(await screen.findByTitle("Casdoor 登录")).toBeInTheDocument();
  });

  it("keeps the user in chat and shows an error when logout fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: true,
      user: { id: 6, username: "alice", isAdmin: false },
    });
    vi.mocked(api.logout).mockRejectedValue(new Error("logout failed"));

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole("button", { name: "Log out" }));

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("logout failed"));
    expect(screen.getByRole("heading", { name: "Cipher AI" })).toBeInTheDocument();
  });
});
