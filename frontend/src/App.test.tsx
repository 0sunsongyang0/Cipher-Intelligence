import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import * as api from "./lib/api";

vi.mock("./lib/api", () => ({
  checkSession: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
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
    vi.clearAllMocks();
  });

  it("shows a loading state, restores the session, and redirects unauthenticated chat visits to login", async () => {
    const checkSession = vi.mocked(api.checkSession);
    let resolveSession: ((value: Awaited<ReturnType<typeof api.checkSession>>) => void) | undefined;

    checkSession.mockReturnValue(
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

    expect(await screen.findByTestId("login-shell-card")).toBeInTheDocument();
  });

  it("does not treat anonymous legacy sessions as authenticated", async () => {
    vi.mocked(api.checkSession).mockResolvedValue({ authenticated: true, user: null });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByTestId("login-shell-card")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Cipher AI" })).not.toBeInTheDocument();
  });

  it("rejects inconsistent unauthenticated sessions even when a user payload is present", async () => {
    vi.mocked(api.checkSession).mockResolvedValue({
      authenticated: false,
      user: { id: 9, username: "alice", isAdmin: false },
    });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByTestId("login-shell-card")).toBeInTheDocument();
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
    expect(screen.getByTestId("login-shell-card")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Cipher AI" })).not.toBeInTheDocument();
  });

  it("submits username and password for login and redirects to chat", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue({ authenticated: false, user: null });
    vi.mocked(api.login).mockResolvedValue({
      authenticated: true,
      user: { id: 1, username: "alice", isAdmin: false },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByTestId("login-shell-card");
    await user.type(document.getElementById("login-username") as HTMLElement, "alice");
    await user.type(document.getElementById("login-password") as HTMLElement, "StrongPass123!");
    await user.click(document.querySelector('button[type="submit"]') as HTMLElement);

    expect(api.login).toHaveBeenCalledWith({
      username: "alice",
      password: "StrongPass123!",
    });
    expect(await screen.findByRole("heading", { name: "Cipher AI" })).toBeInTheDocument();
  });

  it("keeps the user on the auth screen when login returns an unauthenticated payload", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue({ authenticated: false, user: null });
    vi.mocked(api.login).mockResolvedValue({
      authenticated: false,
      user: { id: 5, username: "alice", isAdmin: false },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByTestId("login-shell-card");
    await user.type(document.getElementById("login-username") as HTMLElement, "alice");
    await user.type(document.getElementById("login-password") as HTMLElement, "StrongPass123!");
    await user.click(document.querySelector('button[type="submit"]') as HTMLElement);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Login succeeded but did not return an authenticated session."
    );
    expect(screen.queryByRole("heading", { name: "Cipher AI" })).not.toBeInTheDocument();
  });

  it("submits invite-code registration and redirects to chat", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue({ authenticated: false, user: null });
    vi.mocked(api.register).mockResolvedValue({
      authenticated: true,
      user: { id: 2, username: "new-user", isAdmin: false },
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByTestId("login-shell-card");
    await user.click(screen.getAllByRole("button")[1]!);
    await user.type(document.getElementById("register-username") as HTMLElement, "new-user");
    await user.type(document.getElementById("register-password") as HTMLElement, "StrongPass123!");
    await user.type(document.getElementById("register-confirm-password") as HTMLElement, "StrongPass123!");
    await user.type(document.getElementById("register-invite-code") as HTMLElement, "SMBU@2014520uu-");
    await user.click(document.querySelector('button[type="submit"]') as HTMLElement);

    expect(api.register).toHaveBeenCalledWith({
      username: "new-user",
      password: "StrongPass123!",
      inviteCode: "SMBU@2014520uu-",
    });
    expect(await screen.findByRole("heading", { name: "Cipher AI" })).toBeInTheDocument();
  });

  it("keeps the user on the auth screen when registration returns an invalid session", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue({ authenticated: false, user: null });
    vi.mocked(api.register).mockResolvedValue({
      authenticated: true,
      user: null,
    });

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    await screen.findByTestId("login-shell-card");
    await user.click(screen.getAllByRole("button")[1]!);
    await user.type(document.getElementById("register-username") as HTMLElement, "new-user");
    await user.type(document.getElementById("register-password") as HTMLElement, "StrongPass123!");
    await user.type(document.getElementById("register-confirm-password") as HTMLElement, "StrongPass123!");
    await user.type(document.getElementById("register-invite-code") as HTMLElement, "SMBU@2014520uu-");
    await user.click(document.querySelector('button[type="submit"]') as HTMLElement);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Registration succeeded but did not return an authenticated session."
    );
    expect(screen.queryByRole("heading", { name: "Cipher AI" })).not.toBeInTheDocument();
  });

  it("renders the campus shell for authenticated chat visits with a real user", async () => {
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

  it("logs out from the authenticated shell and returns to login", async () => {
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
    expect(await screen.findByTestId("login-shell-card")).toBeInTheDocument();
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

    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(await screen.findByRole("alert")).toHaveTextContent("logout failed");
    expect(screen.getByRole("heading", { name: "Cipher AI" })).toBeInTheDocument();
  });
});
