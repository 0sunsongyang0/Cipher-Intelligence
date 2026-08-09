import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../theme";
import { LoginPage } from "./LoginPage";

function renderLogin(overrides: Partial<React.ComponentProps<typeof LoginPage>> = {}) {
  const props: React.ComponentProps<typeof LoginPage> = {
    error: null,
    casdoorEnabled: true,
    casdoorDisplayName: "Cipher SSO",
    onCasdoorAuthenticated: vi.fn(),
    onCasdoorError: vi.fn(),
    ...overrides,
  };

  return { ...render(<LoginPage {...props} />), props };
}

describe("LoginPage", () => {
  it("renders Casdoor directly in the Cipher login surface without local account fields", () => {
    renderLogin();

    expect(screen.getByTestId("gradient-waves-background")).toBeInTheDocument();
    expect(screen.getByTestId("login-auth-surface")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "切换到夜间模式" })).toBeInTheDocument();
    expect(screen.getByText("夜间")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "把复杂线索， 变成清晰行动。" })).toBeInTheDocument();
    expect(screen.getByTitle("Cipher SSO 登录")).toHaveAttribute(
      "src",
      "/api/auth/casdoor/login?return_to=%2Fauth%2Fcasdoor%2Fembedded&theme=light"
    );
    const frame = screen.getByTitle("Cipher SSO 登录");
    expect(frame).toHaveAttribute("scrolling", "no");
    expect(frame.getAttribute("sandbox")?.split(" ")).toContain(
      "allow-top-navigation-by-user-activation"
    );
    expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("密码")).not.toBeInTheDocument();
    expect(screen.queryByText("注册")).not.toBeInTheDocument();
    expect(screen.queryByText("由 Cipher SSO 安全提供")).not.toBeInTheDocument();
  });

  it("shows a configuration error instead of falling back to local login", () => {
    renderLogin({ casdoorEnabled: false });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Casdoor 统一身份认证未配置，请检查服务端 CASDOOR_ENABLED 及应用凭据。"
    );
    expect(screen.queryByLabelText("用户名")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("本地访问密码")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "登录" })).not.toBeInTheDocument();
    expect(screen.queryByTitle(/登录/)).not.toBeInTheDocument();
  });

  it("passes Casdoor theme changes through without returning to a loading state", async () => {
    localStorage.setItem("cipher-theme", "light");
    const props: React.ComponentProps<typeof LoginPage> = {
      error: null,
      casdoorEnabled: true,
      casdoorDisplayName: "Cipher SSO",
      onCasdoorAuthenticated: vi.fn(),
      onCasdoorError: vi.fn(),
    };
    render(
      <ThemeProvider>
        <LoginPage {...props} />
      </ThemeProvider>
    );

    const lightFrame = screen.getByTitle("Cipher SSO 登录");
    window.dispatchEvent(new MessageEvent("message", {
      source: (lightFrame as HTMLIFrameElement).contentWindow,
      data: { type: "cipher:casdoor-ready" },
    }));
    await waitFor(() => {
      expect(screen.queryByText("正在载入统一登录…")).not.toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: "切换到夜间模式" }));
    await waitFor(() => {
      expect(screen.getByTitle("Cipher SSO 登录")).toHaveAttribute(
        "src",
        "/api/auth/casdoor/login?return_to=%2Fauth%2Fcasdoor%2Fembedded&theme=light"
      );
      expect(screen.queryByText("正在载入统一登录…")).not.toBeInTheDocument();
    });
  });

  it("completes the parent login when the embedded callback reports success", async () => {
    const onCasdoorAuthenticated = vi.fn();
    renderLogin({ onCasdoorAuthenticated });
    const frame = screen.getByTitle("Cipher SSO 登录") as HTMLIFrameElement;

    window.dispatchEvent(
      new MessageEvent("message", {
        origin: window.location.origin,
        source: frame.contentWindow,
        data: { type: "cipher:casdoor-auth", status: "success", message: null },
      })
    );

    await waitFor(() => expect(onCasdoorAuthenticated).toHaveBeenCalledTimes(1));
    expect(screen.getByText("身份验证成功")).toBeInTheDocument();
  });

  it("shows an embedded OAuth error and passes it to the app", async () => {
    const onCasdoorError = vi.fn();
    renderLogin({ onCasdoorError });
    const frame = screen.getByTitle("Cipher SSO 登录") as HTMLIFrameElement;

    fireEvent(
      window,
      new MessageEvent("message", {
        origin: window.location.origin,
        source: frame.contentWindow,
        data: {
          type: "cipher:casdoor-auth",
          status: "error",
          message: "授权已取消",
        },
      })
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("授权已取消");
    expect(onCasdoorError).toHaveBeenCalledWith("授权已取消");
  });

  it("ignores authentication messages from another origin", async () => {
    const onCasdoorAuthenticated = vi.fn();
    renderLogin({ onCasdoorAuthenticated });
    const frame = screen.getByTitle("Cipher SSO 登录") as HTMLIFrameElement;

    window.dispatchEvent(
      new MessageEvent("message", {
        origin: "https://attacker.example",
        source: frame.contentWindow,
        data: { type: "cipher:casdoor-auth", status: "success" },
      })
    );

    await Promise.resolve();
    expect(onCasdoorAuthenticated).not.toHaveBeenCalled();
  });
});
