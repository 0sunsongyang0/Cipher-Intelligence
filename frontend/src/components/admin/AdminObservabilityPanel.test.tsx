import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../../lib/api";
import { AdminObservabilityPanel } from "./AdminObservabilityPanel";

vi.mock("../../lib/api", () => ({ getAdminObservability: vi.fn() }));

describe("AdminObservabilityPanel", () => {
  beforeEach(() => {
    vi.mocked(api.getAdminObservability).mockResolvedValue({
      days: 30,
      requestSuccessRate: 98.5,
      averageResponseTimeMs: 1234,
      modelFailureRate: 2.5,
      tokenUsage: { input: 1200, output: 800, total: 2000 },
      capeTaskAverageDurationMs: 65000,
      activeUsers: 42,
      events: 99
    });
  });

  it("renders aggregate observability metrics", async () => {
    render(<AdminObservabilityPanel />);

    expect(await screen.findByText("98.5%")).toBeInTheDocument();
    expect(screen.getByText("1.2 s")).toBeInTheDocument();
    expect(screen.getByText("2.5%")).toBeInTheDocument();
    expect(screen.getByText("2,000")).toBeInTheDocument();
    expect(screen.getByText("65.0 s")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText(/事件总数 99/)).toBeInTheDocument();
    expect(api.getAdminObservability).toHaveBeenCalledWith(30);
  });
});
