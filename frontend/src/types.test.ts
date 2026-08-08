import { describe, expect, it } from "vitest";

import {
  buildZipAttachmentMeta,
  DEEPSEEK_MODEL_IDS,
  DEEPSEEK_MODEL_LABELS,
  DEEPSEEK_MODEL_OPTIONS,
  MODEL_PROVIDER_LABELS,
  MODEL_PROVIDER_ORDER,
  ZIP_UNSUPPORTED_MODEL_REASON,
  getDeepSeekModelProvider,
  getDeepSeekModelsByProvider,
  isZipContextSupportedModel
} from "./types";

describe("grouped model metadata", () => {
  it("keeps providers in the approved menu order", () => {
    expect(MODEL_PROVIDER_ORDER).toEqual(["deepseek", "openai", "claude"]);
  });

  it("returns only the economy models for the first provider", () => {
    expect(getDeepSeekModelsByProvider("deepseek").map((model) => model.id)).toEqual([
      "deepseek-v4-flash",
      "deepseek-v4-pro"
    ]);
  });

  it("keeps the middle submenu focused on usable primary models only", () => {
    expect(getDeepSeekModelsByProvider("openai").map((model) => model.id)).toEqual([
      "chatgpt-5.5-official",
      "chatgpt-5.4-az"
    ]);
  });

  it("maps chatgpt-5.5-official back to its provider", () => {
    expect(getDeepSeekModelProvider("chatgpt-5.5-official")).toBe("openai");
  });

  it("derives model ids and labels from the provider-aware catalog", () => {
    expect(DEEPSEEK_MODEL_IDS).toEqual(DEEPSEEK_MODEL_OPTIONS.map((model) => model.id));
    expect(DEEPSEEK_MODEL_LABELS).toEqual(
      Object.fromEntries(DEEPSEEK_MODEL_OPTIONS.map((model) => [model.id, model.label]))
    );
  });

  it("fails loudly when provider metadata is missing for a model id", () => {
    expect(() => getDeepSeekModelProvider("missing-model-id" as never)).toThrow(
      'Missing provider metadata for model "missing-model-id"'
    );
  });

  it("round-trips the provider grouping from the canonical catalog", () => {
    for (const provider of MODEL_PROVIDER_ORDER) {
      const providerModels = DEEPSEEK_MODEL_OPTIONS.filter((model) => model.provider === provider);
      const providerLabels = new Set(providerModels.map((model) => model.groupLabel));

      expect(providerLabels.size).toBe(1);
      expect([...providerLabels][0]).toBe(MODEL_PROVIDER_LABELS[provider]);
    }

    expect(DEEPSEEK_MODEL_OPTIONS.map((model) => getDeepSeekModelProvider(model.id))).toEqual(
      DEEPSEEK_MODEL_OPTIONS.map((model) => model.provider)
    );

    expect(MODEL_PROVIDER_ORDER.flatMap((provider) => getDeepSeekModelsByProvider(provider))).toEqual(
      DEEPSEEK_MODEL_OPTIONS
    );
  });

  it("keeps the flattened option order stable for downstream consumers", () => {
    expect(DEEPSEEK_MODEL_OPTIONS.map((model) => model.id)).toEqual([
      "deepseek-v4-flash",
      "deepseek-v4-pro",
      "chatgpt-5.5-official",
      "chatgpt-5.4-az",
      "claude-opus-4-7-official",
      "claude-opus-4-6-aws",
      "claude-sonnet-4-6-az",
    ]);
  });

  it("marks every configured server-backed model as ZIP-supported for runtime gating", () => {
    for (const model of DEEPSEEK_MODEL_OPTIONS) {
      expect(isZipContextSupportedModel(model.id)).toBe(true);
    }

    expect(ZIP_UNSUPPORTED_MODEL_REASON).toBe("当前模型不支持 ZIP 文件问答，请切换其他模型。");
  });

  it("formats uploading ZIP copy for immediate attachment feedback", () => {
    expect(
      buildZipAttachmentMeta({
        entryCount: 0,
        extractedEntryCount: 0,
        inventoryOnlyCount: 0,
        skippedEntryCount: 0,
        uploading: true
      })
    ).toBe("ZIP · 上传中...");
  });

  it("formats parsed ZIP copy with extracted, inventory-only, and skipped counts", () => {
    expect(
      buildZipAttachmentMeta({
        entryCount: 36,
        extractedEntryCount: 14,
        inventoryOnlyCount: 2,
        skippedEntryCount: 20,
        uploading: false
      })
    ).toBe("ZIP · 已扫描 36 项 · 已提取 14 项 · 仅清单 2 项 · 已跳过 20 项");
  });
});
