import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  clearChatState,
  loadChatState,
  saveChatState,
  type PersistedChatState,
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

  it("accepts server-backed chat settings without requiring a model id", () => {
    const serverState: PersistedChatState = {
      activeConversationId: "conversation-1",
      conversations: savedState.conversations,
      settings: {
        systemPrompt: "Answer from the server"
      }
    };

    saveChatState(serverState);

    expect(loadChatState()).toEqual(serverState);
  });

  it("clears the persisted chat state", () => {
    saveChatState(savedState);

    clearChatState();

    expect(loadChatState()).toBeNull();
  });

  it("returns the fallback when persisted state is corrupted", () => {
    const fallback: StoredChatState = {
      activeConversationId: null,
      conversations: [],
      settings: {
        modelId: "fallback-model",
        systemPrompt: ""
      }
    };

    localStorage.setItem("webllm-chat-state", "{oops");

    expect(loadChatState(fallback)).toEqual(fallback);
  });

  it("returns the fallback when persisted state has the wrong shape", () => {
    const fallback: StoredChatState = {
      activeConversationId: null,
      conversations: [],
      settings: {
        modelId: "fallback-model",
        systemPrompt: ""
      }
    };

    localStorage.setItem(
      "webllm-chat-state",
      JSON.stringify({
        activeConversationId: 123,
        conversations: "not-an-array",
        settings: null
      })
    );

    expect(loadChatState(fallback)).toEqual(fallback);
  });

  it("returns the fallback when localStorage reads are unavailable", () => {
    const fallback: StoredChatState = {
      activeConversationId: null,
      conversations: [],
      settings: {
        modelId: "fallback-model",
        systemPrompt: ""
      }
    };

    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });

    expect(loadChatState(fallback)).toEqual(fallback);
  });

  it("ignores localStorage write and clear failures", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => {
      throw new Error("storage unavailable");
    });

    expect(() => saveChatState(savedState)).not.toThrow();
    expect(() => clearChatState()).not.toThrow();
  });
});
