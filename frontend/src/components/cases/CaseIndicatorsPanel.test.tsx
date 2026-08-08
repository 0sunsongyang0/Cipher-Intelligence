import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CaseIndicatorsPanel } from "./CaseIndicatorsPanel";
import * as api from "../../lib/api";

vi.mock("../../lib/api", () => ({
  listCaseIndicators: vi.fn(), syncCaseIndicators: vi.fn(), enrichCaseIndicator: vi.fn(),
  updateCaseIndicator: vi.fn(), bulkUpdateCaseIndicators: vi.fn(), exportCaseIndicators: vi.fn(),
}));

const baseItem = { id: 7, type: "domain" as const, value: "evil.example", riskLevel: "unknown" as const, confidence: 0,
  status: "pending" as const, sourceType: "cape", capeCaseId: 1, sampleName: "sample.exe", firstSeenAt: "2026-08-08T00:00:00Z",
  lastSeenAt: "2026-08-08T00:00:00Z", expiresAt: null, enrichment: {} };
const list = { items: [baseItem], total: 1, counts: { type: { domain: 1, ip: 0, url: 0, md5: 0, sha1: 0, sha256: 0 }, status: { pending: 1, malicious: 0, suspicious: 0, false_positive: 0, blocked: 0 } } };

describe("CaseIndicatorsPanel intelligence", () => {
  beforeEach(() => { vi.clearAllMocks(); vi.mocked(api.listCaseIndicators).mockResolvedValue(list); });

  it("queries intelligence and renders source details without secrets", async () => {
    vi.mocked(api.enrichCaseIndicator).mockResolvedValue({ ...baseItem, confidence: 92, status: "suspicious", riskLevel: "critical", enrichment: {
      queriedAt: "2026-08-08T02:00:00Z", results: [{ provider: "virustotal", source: "VirusTotal", confidence: 92, malicious: true,
        tags: ["trojan", "c2"], externalUrl: "https://intel.example/result", updatedAt: "2026-08-08T01:00:00Z", fetchedAt: "2026-08-08T02:00:00Z", cached: false, stale: false }]
    }});
    render(<CaseIndicatorsPanel caseId={3} onCountChange={vi.fn()}/>);
    fireEvent.click(await screen.findByRole("button", { name: "查询情报" }));
    await waitFor(() => expect(api.enrichCaseIndicator).toHaveBeenCalledWith(3, 7));
    expect(await screen.findByText("VirusTotal")).toBeInTheDocument();
    expect(screen.getByText("92% · 恶意")).toBeInTheDocument();
    expect(screen.getByText("trojan")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "在 VirusTotal 查看" })).toHaveAttribute("rel", "noreferrer");
  });

  it("shows partial provider failures alongside successful cached data", async () => {
    vi.mocked(api.listCaseIndicators).mockResolvedValue({ ...list, items: [{ ...baseItem, enrichment: { results: [{ provider: "otx", source: "AlienVault OTX", confidence: 60, malicious: true, tags: [], externalUrl: null, updatedAt: null, fetchedAt: "2026-08-08T02:00:00Z", cached: true, stale: true }], errors: [{ provider: "greynoise", message: "timeout" }] } }] });
    render(<CaseIndicatorsPanel caseId={3} onCountChange={vi.fn()}/>);
    expect(await screen.findByText("过期缓存 / 降级")).toBeInTheDocument();
    expect(screen.getByText("部分来源失败：greynoise")).toBeInTheDocument();
  });
});
