import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import * as api from "./lib/api";

vi.mock("./lib/api", () => ({
  checkSession: vi.fn(),
  login: vi.fn(),
  logout: vi.fn()
}));

vi.mock("./components/webllm/AppShell", () => ({
  AppShell: ({
    onLogout,
    sessionError
  }: {
    onLogout: () => Promise<void> | void;
    sessionError?: string | null;
  }) => (
    <div>
      <h1>WebLLM App Shell</h1>
      {sessionError ? <p role="alert">{sessionError}</p> : null}
      <button type="button" onClick={() => void onLogout()}>
        Logout
      </button>
    </div>
  )
}));

describe("App", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a loading state, restores the session, and redirects unauthenticated chat visits to login", async () => {
    const checkSession = vi.mocked(api.checkSession);
    let resolveSession: ((value: boolean) => void) | undefined;

    checkSession.mockReturnValue(
      new Promise<boolean>((resolve) => {
        resolveSession = resolve;
      })
    );

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(
      screen.getByRole("heading", { name: "正在恢复访问会话" })
    ).toBeInTheDocument();

    resolveSession?.(false);

    expect(
      await screen.findByRole("heading", { name: "兔兔炸弹的大模型助手" })
    ).toBeInTheDocument();
  });

  it("submits login and redirects to chat after a successful login", async () => {
    const user = userEvent.setup();
    const checkSession = vi.mocked(api.checkSession);
    const login = vi.mocked(api.login);

    checkSession.mockResolvedValue(false);
    login.mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>
    );

    await user.type(await screen.findByLabelText("访问口令"), "campus-secret");
    await user.click(screen.getByRole("button", { name: "进入助手" }));

    expect(login).toHaveBeenCalledWith("campus-secret");
    expect(
      await screen.findByRole("heading", { name: "WebLLM App Shell" })
    ).toBeInTheDocument();
  });

  it("renders the webllm shell for authenticated chat visits", async () => {
    vi.mocked(api.checkSession).mockResolvedValue(true);

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    expect(
      await screen.findByRole("heading", { name: "WebLLM App Shell" })
    ).toBeInTheDocument();
  });

  it("logs out from the authenticated shell and returns to login", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue(true);
    vi.mocked(api.logout).mockResolvedValue(undefined);

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole("button", { name: "Logout" }));

    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByRole("heading", { name: "兔兔炸弹的大模型助手" })
    ).toBeInTheDocument();
  });

  it("keeps the authenticated shell active and shows an error when logout fails", async () => {
    const user = userEvent.setup();
    vi.mocked(api.checkSession).mockResolvedValue(true);
    vi.mocked(api.logout).mockRejectedValue(new Error("Logout failed"));

    render(
      <MemoryRouter initialEntries={["/chat"]}>
        <App />
      </MemoryRouter>
    );

    await user.click(await screen.findByRole("button", { name: "Logout" }));

    expect(api.logout).toHaveBeenCalledTimes(1);
    expect(
      await screen.findByRole("heading", { name: "WebLLM App Shell" })
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Logout failed");
  });
});
