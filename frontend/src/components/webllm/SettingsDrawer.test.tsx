import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SettingsDrawer } from "./SettingsDrawer";

describe("SettingsDrawer", () => {
  it("shows the system prompt as backend-managed even when local settings contain text", () => {
    render(
      <SettingsDrawer
        open={true}
        onClose={vi.fn()}
        settings={{
          modelId: "deepseek-v4-flash",
          systemPrompt: "local override should not be shown"
        }}
      />
    );

    expect(screen.getByRole("dialog", { name: "设置" })).toBeInTheDocument();
    expect(screen.getByText("系统提示词")).toBeInTheDocument();
    expect(screen.getAllByText("由后端配置")).toHaveLength(2);
    expect(screen.queryByText("local override should not be shown")).toBeNull();
  });
});
