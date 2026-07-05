import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("renders the aurora-glass login shell", () => {
    render(<LoginPage onSubmit={vi.fn()} isSubmitting={false} error={null} />);

    expect(screen.getByTestId("aurora-background")).toBeInTheDocument();
    expect(screen.getByTestId("login-shell-card")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "进入聊天界面" })).toBeInTheDocument();
    expect(screen.getByText("私有工作区访问")).toBeInTheDocument();
    expect(screen.getByText("共享 DeepSeek 后端")).toBeInTheDocument();
    expect(screen.getByText("访问验证")).toBeInTheDocument();
  });

  it("submits the typed password", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(<LoginPage onSubmit={onSubmit} isSubmitting={false} error={null} />);

    await user.type(screen.getByLabelText("访问密码"), "campus-secret");
    await user.click(screen.getByRole("button", { name: "进入聊天" }));

    expect(onSubmit).toHaveBeenCalledWith("campus-secret");
  });

  it("prevents blank password submission", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(<LoginPage onSubmit={onSubmit} isSubmitting={false} error={null} />);

    const button = screen.getByRole("button", { name: "进入聊天" });

    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText("访问密码"), "   ");

    expect(button).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits surrounding whitespace exactly as entered", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(<LoginPage onSubmit={onSubmit} isSubmitting={false} error={null} />);

    await user.type(screen.getByLabelText("访问密码"), "  campus-secret  ");
    await user.click(screen.getByRole("button", { name: "进入聊天" }));

    expect(onSubmit).toHaveBeenCalledWith("  campus-secret  ");
  });

  it("shows the submitting state", () => {
    render(<LoginPage onSubmit={vi.fn()} isSubmitting={true} error={null} />);

    expect(screen.getByLabelText("访问密码")).toBeDisabled();
    expect(screen.getByRole("button", { name: "正在进入..." })).toBeDisabled();
  });
});
