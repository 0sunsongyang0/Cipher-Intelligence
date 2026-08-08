import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ThemeProvider } from "../../theme";
import { SettingsDrawer } from "./SettingsDrawer";

describe("SettingsDrawer", () => {
  it("shows editable preferences while keeping the system prompt backend-managed", async () => {
    const user = userEvent.setup();
    const onSettingsChange = vi.fn();
    render(
      <SettingsDrawer
        open={true}
        onClose={vi.fn()}
        settings={{
          modelId: "deepseek-v4-flash",
          systemPrompt: "local override should not be shown"
        }}
        onSettingsChange={onSettingsChange}
      />
    );

    expect(screen.getByRole("dialog", { name: "设置" })).toBeInTheDocument();
    expect(document.querySelector(".settings-modal__scrim")).toBeInTheDocument();
    expect(screen.getByText("系统提示词")).toBeInTheDocument();
    expect(screen.getByText("由管理员后台统一配置")).toBeInTheDocument();
    expect(screen.queryByText("local override should not be shown")).toBeNull();
    expect(screen.getByRole("navigation", { name: "设置分类" })).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("回答语言"), "en");
    await user.selectOptions(screen.getByLabelText("详细程度"), "detailed");
    await user.click(screen.getByRole("button", { name: /对话偏好/ }));
    await user.click(screen.getByRole("checkbox", { name: /新对话默认联网/ }));

    expect(onSettingsChange).toHaveBeenCalledWith({ responseLanguage: "en" });
    expect(onSettingsChange).toHaveBeenCalledWith({ responseLength: "detailed" });
    expect(onSettingsChange).toHaveBeenCalledWith({ defaultWebSearch: true });
  });

  it("persists application-level motion and transparency preferences", async () => {
    const user = userEvent.setup();
    const onSettingsChange = vi.fn();
    render(
      <SettingsDrawer
        open={true}
        onClose={vi.fn()}
        settings={{ modelId: "deepseek-v4-flash", systemPrompt: "managed" }}
        onSettingsChange={onSettingsChange}
      />
    );

    await user.click(screen.getByRole("button", { name: /外观与辅助/ }));
    await user.selectOptions(screen.getByLabelText("动态效果"), "reduce");
    await user.selectOptions(screen.getByLabelText("透明材质"), "reduce");

    expect(onSettingsChange).toHaveBeenCalledWith({ motionPreference: "reduce" });
    expect(onSettingsChange).toHaveBeenCalledWith({ transparencyPreference: "reduce" });
  });

  it("offers light, dark, and system theme modes from appearance settings", async () => {
    const user = userEvent.setup();
    localStorage.clear();

    render(
      <ThemeProvider>
        <SettingsDrawer
          open={true}
          onClose={vi.fn()}
          settings={{ modelId: "deepseek-v4-flash", systemPrompt: "managed" }}
        />
      </ThemeProvider>
    );

    await user.click(screen.getByRole("button", { name: /外观与辅助/ }));
    const modeSelect = screen.getByLabelText("界面模式");

    expect(modeSelect).toHaveValue("light");
    expect(within(modeSelect).getByRole("option", { name: "日间" })).toBeInTheDocument();
    expect(within(modeSelect).getByRole("option", { name: "夜间" })).toBeInTheDocument();
    expect(within(modeSelect).getByRole("option", { name: "跟随系统" })).toBeInTheDocument();

    await user.selectOptions(modeSelect, "dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("cipher-theme")).toBe("dark");

    await user.selectOptions(modeSelect, "system");
    expect(document.documentElement.dataset.themePreference).toBe("system");
    expect(localStorage.getItem("cipher-theme")).toBe("system");
  });

  it("closes when the page scrim is clicked", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <SettingsDrawer
        open={true}
        onClose={onClose}
        settings={{ modelId: "deepseek-v4-flash", systemPrompt: "managed" }}
      />
    );

    await user.click(screen.getAllByRole("button", { name: "关闭设置" })[0]);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
