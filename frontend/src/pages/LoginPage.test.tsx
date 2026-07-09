import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("renders the aurora auth shell with login as the default mode", () => {
    render(
      <LoginPage
        mode="login"
        onModeChange={vi.fn()}
        onLogin={vi.fn()}
        onRegister={vi.fn()}
        isSubmitting={false}
        error={null}
      />
    );

    expect(screen.getByTestId("aurora-background")).toBeInTheDocument();
    expect(screen.getByTestId("login-shell-card")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "进入聊天界面" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录", pressed: true })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("用户名")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
  });

  it("submits username and password for login", async () => {
    const user = userEvent.setup();
    const onLogin = vi.fn();

    render(
      <LoginPage
        mode="login"
        onModeChange={vi.fn()}
        onLogin={onLogin}
        onRegister={vi.fn()}
        isSubmitting={false}
        error={null}
      />
    );

    await user.type(screen.getByLabelText("用户名"), "alice");
    await user.type(screen.getByLabelText("密码"), "StrongPass123!");
    await user.click(screen.getAllByRole("button", { name: "登录" })[1]!);

    expect(onLogin).toHaveBeenCalledWith({
      username: "alice",
      password: "StrongPass123!",
    });
  });

  it("switches to register mode and submits invite-code registration", async () => {
    const user = userEvent.setup();
    const onModeChange = vi.fn();
    const onRegister = vi.fn();

    const { rerender } = render(
      <LoginPage
        mode="login"
        onModeChange={onModeChange}
        onLogin={vi.fn()}
        onRegister={onRegister}
        isSubmitting={false}
        error={null}
      />
    );

    await user.click(screen.getByRole("button", { name: "注册" }));
    expect(onModeChange).toHaveBeenCalledWith("register");

    rerender(
      <LoginPage
        mode="register"
        onModeChange={onModeChange}
        onLogin={vi.fn()}
        onRegister={onRegister}
        isSubmitting={false}
        error={null}
      />
    );

    await user.type(screen.getByLabelText("用户名"), "new-user");
    await user.type(screen.getByLabelText("密码"), "StrongPass123!");
    await user.type(screen.getByLabelText("确认密码"), "StrongPass123!");
    await user.type(screen.getByLabelText("邀请码"), "SMBU@2014520uu-");
    await user.click(screen.getByRole("button", { name: "创建账号" }));

    expect(onRegister).toHaveBeenCalledWith({
      username: "new-user",
      password: "StrongPass123!",
      confirmPassword: "StrongPass123!",
      inviteCode: "SMBU@2014520uu-",
    });
  });

  it("disables register submit when confirm password is blank", async () => {
    const user = userEvent.setup();

    render(
      <LoginPage
        mode="register"
        onModeChange={vi.fn()}
        onLogin={vi.fn()}
        onRegister={vi.fn()}
        isSubmitting={false}
        error={null}
      />
    );

    const button = screen.getByRole("button", { name: "创建账号" });
    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText("用户名"), "new-user");
    await user.type(screen.getByLabelText("密码"), "StrongPass123!");
    await user.type(screen.getByLabelText("邀请码"), "SMBU@2014520uu-");

    expect(button).toBeDisabled();
  });

  it("shows the submitting state for the active mode", () => {
    render(
      <LoginPage
        mode="register"
        onModeChange={vi.fn()}
        onLogin={vi.fn()}
        onRegister={vi.fn()}
        isSubmitting={true}
        error={null}
      />
    );

    expect(screen.getByLabelText("用户名")).toBeDisabled();
    expect(screen.getByLabelText("密码")).toBeDisabled();
    expect(screen.getByRole("button", { name: "创建中..." })).toBeDisabled();
  });
});
