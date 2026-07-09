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
        退出登录
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

    expect(await screen.findByLabelText("用户名")).toBeInTheDocument();
  });

  it("does not treat anonymous legacy sessions as authenticated", async () => {
    vi.mocked(api.checkSession).mockResolvedValue({ authenticated: true, user: null });

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(await screen.findByLabelText("用户名")).toBeInTheDocument();
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

    expect(await screen.findByLabelText("用户名")).toBeInTheDocument();
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

    await user.type(await screen.findByLabelText("用户名"), "alice");
    await user.type(screen.getByLabelText("密码"), "StrongPass123!");
    await user.click(screen.getAllByRole("button", { name: "登录" })[1]!);

    expect(api.login).toHaveBeenCalledWith({
      username: "alice",
      password: "StrongPass123!",
    });
    expect(await screen.findByRole("heading", { name: "Cipher AI" })).toBeInTheDocument();
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

    await user.click(await screen.findByRole("button", { name: "注册" }));
    await user.type(screen.getByLabelText("用户名"), "new-user");
    await user.type(screen.getByLabelText("密码"), "StrongPass123!");
    await user.type(screen.getByLabelText("确认密码"), "StrongPass123!");
    await user.type(screen.getByLabelText("邀请码"), "SMBU@2014520uu-");
    await user.click(screen.getByRole("button", { name: "创建账号" }));

    expect(api.register).toHaveBeenCalledWith({
      username: "new-user",
      password: "StrongPass123!",
      inviteCode: "SMBU@2014520uu-",
    });
    expect(await screen.findByRole("heading", { name: "Cipher AI" })).toBeInTheDocument();
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

    await user.click(await screen.findByRole("button", { name: "退出登录" }));

    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(await screen.findByLabelText("用户名")).toBeInTheDocument();
  });
});
