import { beforeEach, describe, expect, it } from "vitest";
import {
  clearChatState,
  loadChatState,
  saveChatState,
  type StoredChatState
} from "./storage";

describe("storage helpers", () => {
  const savedState: StoredChatState = {
    activeConversationId: "conversation-2",
    conversations: [
      {
        id: "conversation-1",
        title: "First chat",
        createdAt: "2026-07-03T00:00:00.000Z",
        updatedAt: "2026-07-03T00:00:00.000Z",
        messages: []
      },
      {
        id: "conversation-2",
        title: "Second chat",
        createdAt: "2026-07-03T01:00:00.000Z",
        updatedAt: "2026-07-03T01:00:00.000Z",
        messages: [
          {
            id: "message-1",
            role: "user",
            content: "Hello",
            createdAt: "2026-07-03T01:05:00.000Z"
          }
        ]
      }
    ],
    settings: {
      modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
      systemPrompt: "Be helpful"
    }
  };

  beforeEach(() => {
    localStorage.clear();
  });

  it("returns the provided fallback when nothing is stored", () => {
    const fallback: StoredChatState = {
      activeConversationId: null,
      conversations: [],
      settings: {
        modelId: "fallback-model",
        systemPrompt: ""
      }
    };

    expect(loadChatState(fallback)).toEqual(fallback);
  });

  it("round-trips chat state through local storage", () => {
    saveChatState(savedState);

    expect(loadChatState()).toEqual(savedState);
  });

  it("clears the persisted chat state", () => {
    saveChatState(savedState);

    clearChatState();

    expect(loadChatState()).toBeNull();
  });
});
