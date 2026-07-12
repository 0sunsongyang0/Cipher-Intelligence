import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminPromptPanel } from "./AdminPromptPanel";

describe("AdminPromptPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders prompt metadata and enables save only when the draft is dirty", async () => {
    const user = userEvent.setup();
    const onDraftChange = vi.fn();
    const onSave = vi.fn();
    const onReload = vi.fn();
    const onReset = vi.fn();

    const { rerender } = render(
      <AdminPromptPanel
        prompt={{
          prompt: "Default system prompt",
          source: "default",
          updatedAt: null,
          status: "ready",
          message: "当前使用内置默认提示词。",
        }}
        draft="Default system prompt"
        loading={false}
        saving={false}
        resetting={false}
        reloading={false}
        onDraftChange={onDraftChange}
        onSave={onSave}
        onReload={onReload}
        onReset={onReset}
      />
    );

    expect(screen.getByRole("textbox", { name: "系统提示词编辑器" })).toHaveValue(
      "Default system prompt"
    );
    expect(screen.getByText("内置默认")).toBeInTheDocument();
    expect(screen.getByText("当前使用内置默认提示词")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "保存提示词" })).toBeDisabled();

    await user.clear(screen.getByRole("textbox", { name: "系统提示词编辑器" }));
    await user.type(screen.getByRole("textbox", { name: "系统提示词编辑器" }), "Custom prompt");

    expect(onDraftChange).toHaveBeenCalled();

    rerender(
      <AdminPromptPanel
        prompt={{
          prompt: "Default system prompt",
          source: "default",
          updatedAt: null,
          status: "ready",
          message: "当前使用内置默认提示词。",
        }}
        draft="Custom prompt"
        loading={false}
        saving={false}
        resetting={false}
        reloading={false}
        onDraftChange={onDraftChange}
        onSave={onSave}
        onReload={onReload}
        onReset={onReset}
      />
    );

    await user.click(screen.getByRole("button", { name: "保存提示词" }));

    expect(onSave).toHaveBeenCalledWith("Custom prompt");
  });

  it("confirms reset and exposes reload actions", async () => {
    const user = userEvent.setup();
    const onReset = vi.fn();
    const onReload = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(
      <AdminPromptPanel
        prompt={{
          prompt: "Custom prompt",
          source: "override",
          updatedAt: "2026-07-08T03:21:00Z",
          status: "fallback",
          message: "系统提示词配置文件无效，已回退到内置默认值。",
        }}
        draft="Custom prompt"
        loading={false}
        saving={false}
        resetting={false}
        reloading={false}
        onDraftChange={vi.fn()}
        onSave={vi.fn()}
        onReload={onReload}
        onReset={onReset}
      />
    );

    expect(screen.getByText("自定义覆盖")).toBeInTheDocument();
    expect(screen.getByText("已启用默认回退")).toBeInTheDocument();
    expect(screen.getByText(/2026/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重新加载提示词" }));
    await user.click(screen.getByRole("button", { name: "恢复默认提示词" }));

    expect(onReload).toHaveBeenCalledTimes(1);
    expect(window.confirm).toHaveBeenCalled();
    expect(onReset).toHaveBeenCalledTimes(1);
  });
});
