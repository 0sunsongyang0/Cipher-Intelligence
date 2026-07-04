import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  loadChatState,
  saveChatState,
  type PersistedChatState
} from "../lib/storage";
import { useServerChat } from "./useServerChat";

const { streamChat } = vi.hoisted(() => ({
  streamChat: vi.fn()
}));

vi.mock("../lib/api", () => ({
  streamChat
}));

function createTextStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();

  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(encoder.encode(chunk));
      }

      controller.close();
    }
  });
}

describe("useServerChat", () => {
  beforeEach(() => {
    localStorage.clear();
    streamChat.mockReset();
  });

  it("restores saved local state on mount", () => {
    const savedState: PersistedChatState = {
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
        systemPrompt: "Be helpful"
      }
    };

    saveChatState(savedState);

    const { result } = renderHook(() => useServerChat());

    expect(result.current.activeConversationId).toBe("conversation-1");
    expect(result.current.conversations).toEqual(savedState.conversations);
    expect(result.current.settings).toEqual(savedState.settings);
    expect(result.current.activeConversation?.messages).toEqual(
      savedState.conversations[0].messages
    );
  });

  it("streams assistant content into the active conversation", async () => {
    streamChat.mockResolvedValue(createTextStream(["Hello", " world"]));

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.sendMessage("Hi");
    });

    await waitFor(() => {
      expect(result.current.activeConversation?.messages).toHaveLength(2);
    });

    expect(result.current.activeConversation?.messages).toMatchObject([
      {
        role: "user",
        content: "Hi"
      },
      {
        role: "assistant",
        content: "Hello world"
      }
    ]);
    expect(result.current.runtimeStatus).toBe("ready");
    expect(result.current.isGenerating).toBe(false);
    expect(loadChatState()?.conversations[0]?.messages).toMatchObject([
      {
        role: "user",
        content: "Hi"
      },
      {
        role: "assistant",
        content: "Hello world"
      }
    ]);
  });

  it("posts the full history to the backend", async () => {
    const savedState: PersistedChatState = {
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
              content: "Hello",
              createdAt: "2026-07-03T00:00:30.000Z"
            },
            {
              id: "message-2",
              role: "assistant",
              content: "Hi",
              createdAt: "2026-07-03T00:00:40.000Z"
            }
          ]
        }
      ],
      settings: {
        systemPrompt: "Be concise"
      }
    };

    saveChatState(savedState);
    streamChat.mockResolvedValue(createTextStream(["Done"]));

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.sendMessage("What now?");
    });

    expect(streamChat).toHaveBeenCalledWith([
      {
        role: "system",
        content: "Be concise"
      },
      {
        role: "user",
        content: "Hello"
      },
      {
        role: "assistant",
        content: "Hi"
      },
      {
        role: "user",
        content: "What now?"
      }
    ]);
  });

  it("preserves user message plus partial assistant content when streaming fails", async () => {
    const encoder = new TextEncoder();
    let readCount = 0;

    streamChat.mockResolvedValue(
      new ReadableStream<Uint8Array>({
        pull(controller) {
          readCount += 1;

          if (readCount > 1) {
            controller.error(new Error("stream interrupted"));
            return;
          }

          controller.enqueue(encoder.encode("Partial"));
        }
      })
    );

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await expect(result.current.sendMessage("Hi")).resolves.toBeUndefined();
    });

    expect(result.current.error).toBe("stream interrupted");
    expect(result.current.isGenerating).toBe(false);
    expect(result.current.activeConversation?.messages).toMatchObject([
      {
        role: "user",
        content: "Hi"
      },
      {
        role: "assistant",
        content: "Partial"
      }
    ]);
  });

  it("rejects concurrent generation runs", async () => {
    let continueStream: (() => void) | undefined;
    const streamGate = new Promise<void>((resolve) => {
      continueStream = resolve;
    });
    const encoder = new TextEncoder();

    streamChat.mockResolvedValue(
      new ReadableStream<Uint8Array>({
        async start(controller) {
          controller.enqueue(encoder.encode("Hello"));
          await streamGate;
          controller.enqueue(encoder.encode(" again"));
          controller.close();
        }
      })
    );

    const { result } = renderHook(() => useServerChat());

    let firstSendPromise!: Promise<void>;

    await act(async () => {
      firstSendPromise = result.current.sendMessage("Hi");
      await Promise.resolve();
    });

    const secondSendPromise = result.current
      .sendMessage("Another message")
      .catch((error) => error);

    await waitFor(() => {
      expect(streamChat).toHaveBeenCalledTimes(1);
    });

    continueStream?.();

    await act(async () => {
      await firstSendPromise;
    });

    await expect(secondSendPromise).resolves.toMatchObject({
      message: "Chat generation is already in progress."
    });
    expect(result.current.activeConversation?.messages).toHaveLength(2);
  });
});
