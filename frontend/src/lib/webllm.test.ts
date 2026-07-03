import { beforeEach, describe, expect, it, vi } from "vitest";

const createMLCEngine = vi.fn();

vi.mock(
  "@mlc-ai/web-llm",
  () => ({
    CreateMLCEngine: createMLCEngine
  })
);

describe("webllm runtime wrapper", () => {
  beforeEach(() => {
    createMLCEngine.mockReset();
  });

  it("creates an engine and forwards init progress", async () => {
    const engine = { chat: { completions: {} } };
    const progressHandler = vi.fn();
    const progressEvent = {
      progress: 0.5,
      text: "Loading model"
    };

    createMLCEngine.mockImplementation(async (_modelId, options) => {
      options.initProgressCallback(progressEvent);
      return engine;
    });

    const { createWebLlmEngine } = await import("./webllm");
    const result = await createWebLlmEngine("test-model", progressHandler);

    expect(createMLCEngine).toHaveBeenCalledWith("test-model", {
      initProgressCallback: expect.any(Function)
    });
    expect(progressHandler).toHaveBeenCalledWith(progressEvent);
    expect(result).toBe(engine);
  });
});
