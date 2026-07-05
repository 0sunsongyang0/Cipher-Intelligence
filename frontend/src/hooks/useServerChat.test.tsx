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

    expect(streamChat).toHaveBeenCalledWith(
      [
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
      ],
      []
    );
  });

  it("stages files, sends them with the prompt, and clears them when send starts", async () => {
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    let continueStream: (() => void) | undefined;
    const streamGate = new Promise<void>((resolve) => {
      continueStream = resolve;
    });
    const encoder = new TextEncoder();

    streamChat.mockResolvedValue(
      new ReadableStream<Uint8Array>({
        async start(controller) {
          await streamGate;
          controller.enqueue(encoder.encode("done"));
          controller.close();
        }
      })
    );

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.addFiles([file]);
    });

    expect(result.current.stagedFiles).toHaveLength(1);

    let sendPromise!: Promise<void>;

    await act(async () => {
      sendPromise = result.current.sendMessage("read this");
      await Promise.resolve();
    });

    expect(streamChat).toHaveBeenCalledWith(
      [
        { role: "system", content: "You are a helpful assistant." },
        { role: "user", content: "read this" }
      ],
      [file]
    );
    expect(result.current.stagedFiles).toHaveLength(0);

    continueStream?.();

    await act(async () => {
      await sendPromise;
    });
  });

  it("removes a staged file by id", () => {
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.addFiles([file]);
    });

    const stagedId = result.current.stagedFiles[0]?.id;

    expect(stagedId).toBeTruthy();

    act(() => {
      result.current.removeFile(stagedId!);
    });

    expect(result.current.stagedFiles).toHaveLength(0);
  });

  it("clears all staged files", () => {
    const firstFile = new File(["one"], "notes.txt", { type: "text/plain" });
    const secondFile = new File(["two"], "todo.pdf", { type: "application/pdf" });

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.addFiles([firstFile, secondFile]);
    });

    expect(result.current.stagedFiles).toHaveLength(2);

    act(() => {
      result.current.clearFiles();
    });

    expect(result.current.stagedFiles).toHaveLength(0);
  });

  it("keeps staged files available when an attachment send fails immediately", async () => {
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    streamChat.mockRejectedValue(new Error("request failed"));

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.addFiles([file]);
    });

    expect(result.current.stagedFiles).toHaveLength(1);

    await act(async () => {
      await result.current.sendMessage("read this");
    });

    expect(result.current.error).toBe("request failed");
    expect(result.current.stagedFiles).toHaveLength(1);
    expect(result.current.stagedFiles[0]?.file).toBe(file);
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

  it("deletes a non-active conversation without clearing the current one", () => {
    const savedState: PersistedChatState = {
      activeConversationId: "conversation-1",
      conversations: [
        {
          id: "conversation-1",
          title: "Active conversation",
          createdAt: "2026-07-03T00:00:00.000Z",
          updatedAt: "2026-07-03T00:01:00.000Z",
          messages: []
        },
        {
          id: "conversation-2",
          title: "Other conversation",
          createdAt: "2026-07-03T00:00:00.000Z",
          updatedAt: "2026-07-03T00:01:00.000Z",
          messages: []
        }
      ],
      settings: {
        systemPrompt: "Be helpful"
      }
    };

    saveChatState(savedState);

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.deleteConversation("conversation-2");
    });

    expect(result.current.activeConversationId).toBe("conversation-1");
    expect(result.current.conversations).toHaveLength(1);
    expect(result.current.conversations[0]?.id).toBe("conversation-1");
  });

  it("deletes the active conversation and clears the selection", () => {
    const savedState: PersistedChatState = {
      activeConversationId: "conversation-1",
      conversations: [
        {
          id: "conversation-1",
          title: "Active conversation",
          createdAt: "2026-07-03T00:00:00.000Z",
          updatedAt: "2026-07-03T00:01:00.000Z",
          messages: []
        }
      ],
      settings: {
        systemPrompt: "Be helpful"
      }
    };

    saveChatState(savedState);

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.deleteConversation("conversation-1");
    });

    expect(result.current.activeConversationId).toBeNull();
    expect(result.current.activeConversation).toBeNull();
    expect(result.current.conversations).toHaveLength(0);
  });
});
