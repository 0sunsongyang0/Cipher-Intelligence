import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("submits the typed password", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(<LoginPage onSubmit={onSubmit} isSubmitting={false} error={null} />);

    expect(screen.getByRole("heading", { name: "Enter the campus chat" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("Access passphrase"), "campus-secret");
    await user.click(screen.getByRole("button", { name: "Open chat" }));

    expect(onSubmit).toHaveBeenCalledWith("campus-secret");
  });

  it("prevents blank password submission", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(<LoginPage onSubmit={onSubmit} isSubmitting={false} error={null} />);

    const button = screen.getByRole("button", { name: "Open chat" });

    expect(button).toBeDisabled();

    await user.type(screen.getByLabelText("Access passphrase"), "   ");

    expect(button).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("submits surrounding whitespace exactly as entered", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(<LoginPage onSubmit={onSubmit} isSubmitting={false} error={null} />);

    await user.type(screen.getByLabelText("Access passphrase"), "  campus-secret  ");
    await user.click(screen.getByRole("button", { name: "Open chat" }));

    expect(onSubmit).toHaveBeenCalledWith("  campus-secret  ");
  });
});
