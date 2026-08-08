import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { AdminQualityPanel } from "./AdminQualityPanel";

vi.mock("../../lib/api", () => ({ getAdminQuality: vi.fn() }));

describe("AdminQualityPanel", () => {
  beforeEach(() => {
    vi.mocked(api.getAdminQuality).mockResolvedValue({
      days: 30,
      totalRequests: 12,
      successfulRequests: 10,
      errorRequests: 1,
      cancelledRequests: 1,
      successRate: 83.3,
      avgFirstTokenMs: 245,
      avgDurationMs: 1850,
      feedback: { up: 7, down: 2 },
      models: [{
        model: "deepseek-v4-pro", provider: "deepseek", requests: 12,
        successful: 10, errors: 1, cancelled: 1, successRate: 83.3,
        avgFirstTokenMs: 245, avgDurationMs: 1850, thumbsUp: 7, thumbsDown: 2
      }]
    });
  });

  it("renders aggregate and per-model quality metrics", async () => {
    render(<AdminQualityPanel />);

    expect(await screen.findByText("deepseek-v4-pro")).toBeInTheDocument();
    expect(screen.getAllByText("83.3%")).toHaveLength(2);
    expect(screen.getAllByText("245 ms")).toHaveLength(2);
    expect(screen.getAllByText("1.9 s")).toHaveLength(2);
    expect(screen.getAllByText("7 / 2")).toHaveLength(2);
    expect(api.getAdminQuality).toHaveBeenCalledWith(30);
  });
});
