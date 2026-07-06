import { describe, expect, it } from "vitest";

import {
  DEEPSEEK_MODEL_OPTIONS,
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
