import { describe, expect, it } from "vitest";

import {
  DEEPSEEK_MODEL_IDS,
  DEEPSEEK_MODEL_LABELS,
  DEEPSEEK_MODEL_OPTIONS,
  MODEL_PROVIDER_LABELS,
  MODEL_PROVIDER_ORDER,
  getDeepSeekModelProvider,
  getDeepSeekModelsByProvider
} from "./types";

describe("grouped model metadata", () => {
  it("keeps providers in the approved menu order", () => {
    expect(MODEL_PROVIDER_ORDER).toEqual(["deepseek", "openai", "claude"]);
  });

  it("returns only DeepSeek models for the DeepSeek provider", () => {
    expect(getDeepSeekModelsByProvider("deepseek").map((model) => model.id)).toEqual([
      "deepseek-v4-flash",
      "deepseek-v4-pro"
    ]);
  });

  it("maps chatgpt-5.5-official back to the OpenAI provider", () => {
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
      "claude-sonnet-4-6-az"
    ]);
  });
});
