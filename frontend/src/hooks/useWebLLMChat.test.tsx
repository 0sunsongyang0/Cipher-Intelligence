import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { saveChatState, type StoredChatState } from "../lib/storage";
import { useWebLLMChat } from "./useWebLLMChat";

const { createWebLlmEngine } = vi.hoisted(() => ({
  createWebLlmEngine: vi.fn()
}));

vi.mock("../lib/webllm", () => ({
  createWebLlmEngine
}));

describe("useWebLLMChat", () => {
  beforeEach(() => {
    localStorage.clear();
    createWebLlmEngine.mockReset();
  });

  it("restores saved local state on mount", async () => {
    const savedState: StoredChatState = {
      activeConversationId: "conversation-1",
      conversations: [
        {
          id: "conversation-1",
          title: "Saved conversation",
          createdAt: "2026-07-03T00:00:00.000Z",
          updatedAt: "2026-07-03T00:01:00.000Z",
          messages: [
            {
              id: "message-1",
              role: "user",
              content: "Hello again",
              createdAt: "2026-07-03T00:00:30.000Z"
            }
          ]
        }
      ],
      settings: {
        modelId: "test-model",
        systemPrompt: "Be helpful"
      }
    };

    saveChatState(savedState);

    const { result } = renderHook(() => useWebLLMChat());

    expect(result.current.activeConversationId).toBe("conversation-1");
    expect(result.current.conversations).toEqual(savedState.conversations);
    expect(result.current.settings).toEqual(savedState.settings);
    expect(result.current.activeConversation?.messages).toEqual(
      savedState.conversations[0].messages
    );
  });

  it("streams assistant content into the active conversation", async () => {
    createWebLlmEngine.mockResolvedValue({
      chat: {
        completions: {
          create: vi.fn(async (_request: unknown) => {
            async function* chunks() {
              yield {
                choices: [
                  {
                    delta: {
                      content: "Hello"
                    }
                  }
                ]
              };
              yield {
                choices: [
                  {
                    delta: {
                      content: " world"
                    }
                  }
                ]
              };
            }

            return chunks();
          })
        }
      }
    });

    const { result } = renderHook(() => useWebLLMChat());

    await act(async () => {
      await result.current.initializeEngine();
      await result.current.sendMessage("Hi");
    });

    await waitFor(() => {
      expect(result.current.activeConversation?.messages).toHaveLength(2);
    });

    const messages = result.current.activeConversation?.messages ?? [];

    expect(messages[0]).toMatchObject({
      role: "user",
      content: "Hi"
    });
    expect(messages[1]).toMatchObject({
      role: "assistant",
      content: "Hello world"
    });
    expect(result.current.isGenerating).toBe(false);
  });
});
