import { CreateMLCEngine } from "@mlc-ai/web-llm";

import type { WebLlmInitProgress } from "../types";

export async function createWebLlmEngine(
  modelId: string,
  onInitProgress?: (progress: WebLlmInitProgress) => void
) {
  return CreateMLCEngine(modelId, {
    initProgressCallback(progress) {
      onInitProgress?.(progress as WebLlmInitProgress);
    }
  });
}
