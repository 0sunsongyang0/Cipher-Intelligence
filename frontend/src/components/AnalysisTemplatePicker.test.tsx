import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AnalysisTemplate } from "../types";
import { AnalysisTemplatePicker } from "./AnalysisTemplatePicker";

const template: AnalysisTemplate = {
  id: 1,
  slug: "linux-elf",
  name: "Linux ELF 分析",
  scenario: "分析 Linux ELF 可执行文件",
  systemPrompt: "静态分析样本",
  checklist: ["确认文件类型"],
  requiredSkills: ["elf-parser"],
  outputFormat: "摘要",
  requiredEvidenceFields: ["sha256"],
  recommendedModel: "chatgpt-5.4-az",
  organizationId: null,
  status: "published",
  version: 1
};

describe("AnalysisTemplatePicker", () => {
  it("shows the public Cipher model name without exposing the internal model id", () => {
    render(<AnalysisTemplatePicker templates={[template]} title="选择安全分析模板" onSelect={vi.fn()} onClose={vi.fn()} />);

    expect(screen.getByText("v1 · Cipher Vector")).toBeInTheDocument();
    expect(screen.queryByText(/chatgpt-5\.4-az/)).not.toBeInTheDocument();
  });
});
