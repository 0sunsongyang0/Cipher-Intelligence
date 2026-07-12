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

const { uploadZip } = vi.hoisted(() => ({
  uploadZip: vi.fn()
}));

const { listConversations } = vi.hoisted(() => ({
  listConversations: vi.fn()
}));

const { getConversationMessages } = vi.hoisted(() => ({
  getConversationMessages: vi.fn()
}));

const { createConversation } = vi.hoisted(() => ({
  createConversation: vi.fn()
}));

const { importConversation } = vi.hoisted(() => ({
  importConversation: vi.fn()
}));

vi.mock("../lib/api", () => ({
  streamChat,
  uploadZip,
  listConversations,
  getConversationMessages,
  createConversation,
  importConversation
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
    vi.restoreAllMocks();
    streamChat.mockReset();
    uploadZip.mockReset();
    listConversations.mockReset();
    getConversationMessages.mockReset();
    createConversation.mockReset();
    importConversation.mockReset();
    listConversations.mockResolvedValue({ items: [] });
    getConversationMessages.mockResolvedValue({ items: [] });
    createConversation.mockImplementation(async ({ title }: { title: string }) => ({
      id: 1,
      title,
      created_at: "2026-07-09T00:00:00.000Z",
      updated_at: "2026-07-09T00:00:00.000Z"
    }));
    importConversation.mockImplementation(async ({ title, messages }: { title: string; messages: Array<{ role: string; content: string }> }) => ({
      id: 9,
      title,
      created_at: "2026-07-09T00:00:00.000Z",
      updated_at: "2026-07-09T00:01:00.000Z",
      importedMessages: messages.length
    }));
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

  it("preserves emoji from the streamed assistant response", async () => {
    streamChat.mockResolvedValue(createTextStream(["你好", "🙂"]));

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.sendMessage("Hi");
    });

    await waitFor(() => {
      expect(result.current.activeConversation?.messages).toHaveLength(2);
    });

    expect(result.current.activeConversation?.messages[1]).toMatchObject({
      role: "assistant",
      content: "你好🙂"
    });
    expect(loadChatState()?.conversations[0]?.messages[1]).toMatchObject({
      role: "assistant",
      content: "你好🙂"
    });
  });

  it("ignores keepalive markers from the streamed assistant response", async () => {
    streamChat.mockResolvedValue(
      createTextStream(["\u001e__CIPHER_KEEPALIVE__\u001e", "Hello", " world"])
    );

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.sendMessage("Hi");
    });

    await waitFor(() => {
      expect(result.current.activeConversation?.messages).toHaveLength(2);
    });

    expect(result.current.activeConversation?.messages[1]).toMatchObject({
      role: "assistant",
      content: "Hello world"
    });
    expect(loadChatState()?.conversations[0]?.messages[1]).toMatchObject({
      role: "assistant",
      content: "Hello world"
    });
  });

  it("surfaces streamed backend errors without showing protocol markers", async () => {
    streamChat.mockResolvedValue(
      createTextStream(["Hello", "\u001e__CIPHER_ERROR__:upstream failed\u001e"])
    );

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.sendMessage("Hi");
    });

    await waitFor(() => {
      expect(result.current.runtimeStatus).toBe("error");
    });

    expect(result.current.error).toBe("upstream failed");
    expect(result.current.activeConversation?.messages[1]).toMatchObject({
      role: "assistant",
      content: "Hello"
    });
  });

  it("loads cloud conversation history for the signed-in user on mount", async () => {
    listConversations.mockResolvedValue({
      items: [
        {
          id: 7,
          title: "Cloud conversation",
          created_at: "2026-07-09T00:00:00.000Z",
          updated_at: "2026-07-09T00:01:00.000Z"
        }
      ]
    });
    getConversationMessages.mockResolvedValue({
      items: [
        {
          id: 21,
          conversation_id: 7,
          role: "user",
          content: "Cloud hello",
          created_at: "2026-07-09T00:00:30.000Z"
        },
        {
          id: 22,
          conversation_id: 7,
          role: "assistant",
          content: "Cloud hi",
          created_at: "2026-07-09T00:00:40.000Z"
        }
      ]
    });

    const { result } = renderHook(() => useServerChat());

    await waitFor(() => {
      expect(result.current.conversations).toHaveLength(1);
    });

    expect(result.current.activeConversationId).toBe("7");
    expect(result.current.conversations).toMatchObject([
      {
        id: "7",
        title: "Cloud conversation",
        messages: [
          {
            id: "21",
            role: "user",
            content: "Cloud hello"
          },
          {
            id: "22",
            role: "assistant",
            content: "Cloud hi"
          }
        ]
      }
    ]);
  });

  it("restores referenced file chips from cloud conversation history on mount", async () => {
    listConversations.mockResolvedValue({
      items: [
        {
          id: 7,
          title: "Cloud conversation",
          created_at: "2026-07-09T00:00:00.000Z",
          updated_at: "2026-07-09T00:01:00.000Z"
        }
      ]
    });
    getConversationMessages.mockResolvedValue({
      items: [
        {
          id: 21,
          conversation_id: 7,
          role: "user",
          content: "Cloud hello",
          created_at: "2026-07-09T00:00:30.000Z",
          attachments: [
            {
              id: "attachment-1",
              name: "notes.txt",
              type: "TXT",
              size: 5,
              meta: "引用文件"
            }
          ]
        }
      ]
    });

    const { result } = renderHook(() => useServerChat());

    await waitFor(() => {
      expect(result.current.conversations).toHaveLength(1);
    });

    expect(result.current.conversations[0]?.messages[0]).toMatchObject({
      role: "user",
      content: "Cloud hello",
      attachments: [
        {
          id: "attachment-1",
          name: "notes.txt",
          type: "TXT",
          size: 5,
          meta: "引用文件"
        }
      ]
    });
  });

  it("keeps locally cached referenced file chips after refresh when cloud history lacks them", async () => {
    saveChatState({
      activeConversationId: "7",
      conversations: [
        {
          id: "7",
          title: "Cloud conversation",
          createdAt: "2026-07-09T00:00:00.000Z",
          updatedAt: "2026-07-09T00:01:00.000Z",
          messages: [
            {
              id: "local-user-1",
              role: "user",
              content: "Cloud hello",
              createdAt: "2026-07-09T00:00:30.000Z",
              attachments: [
                {
                  id: "attachment-1",
                  name: "notes.txt",
                  type: "TXT",
                  size: 5,
                  meta: "引用文件"
                }
              ]
            },
            {
              id: "local-assistant-1",
              role: "assistant",
              content: "Cloud hi",
              createdAt: "2026-07-09T00:00:40.000Z"
            }
          ],
          zipContext: undefined
        }
      ],
      settings: {
        systemPrompt: "You are a helpful assistant."
      }
    });

    listConversations.mockResolvedValue({
      items: [
        {
          id: 7,
          title: "Cloud conversation",
          created_at: "2026-07-09T00:00:00.000Z",
          updated_at: "2026-07-09T00:01:00.000Z"
        }
      ]
    });
    getConversationMessages.mockResolvedValue({
      items: [
        {
          id: 21,
          conversation_id: 7,
          role: "user",
          content: "Cloud hello",
          created_at: "2026-07-09T00:00:30.000Z"
        },
        {
          id: 22,
          conversation_id: 7,
          role: "assistant",
          content: "Cloud hi",
          created_at: "2026-07-09T00:00:40.000Z"
        }
      ]
    });

    const { result } = renderHook(() => useServerChat());

    await waitFor(() => {
      expect(result.current.conversations).toHaveLength(1);
    });

    expect(result.current.conversations[0]?.messages[0]).toMatchObject({
      role: "user",
      content: "Cloud hello",
      attachments: [
        {
          id: "attachment-1",
          name: "notes.txt",
          type: "TXT",
          size: 5,
          meta: "引用文件"
        }
      ]
    });
  });

  it("migrates legacy local conversations into cloud history when the server is empty", async () => {
    saveChatState({
      activeConversationId: "conversation-legacy",
      conversations: [
        {
          id: "conversation-legacy",
          title: "Legacy local thread",
          createdAt: "2026-07-08T00:00:00.000Z",
          updatedAt: "2026-07-08T00:01:00.000Z",
          messages: [
            {
              id: "message-1",
              role: "user",
              content: "Old local hello",
              createdAt: "2026-07-08T00:00:30.000Z"
            },
            {
              id: "message-2",
              role: "assistant",
              content: "Old local hi",
              createdAt: "2026-07-08T00:00:40.000Z"
            }
          ]
        }
      ],
      settings: {
        systemPrompt: "Be helpful"
      }
    });

    const { result } = renderHook(() => useServerChat());

    await waitFor(() => {
      expect(importConversation).toHaveBeenCalledWith({
        title: "Legacy local thread",
        messages: [
          { role: "user", content: "Old local hello" },
          { role: "assistant", content: "Old local hi" }
        ]
      });
    });

    expect(result.current.activeConversationId).toBe("9");
    expect(result.current.conversations).toMatchObject([
      {
        id: "9",
        title: "Legacy local thread",
        messages: [
          { role: "user", content: "Old local hello" },
          { role: "assistant", content: "Old local hi" }
        ]
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
        modelId: "deepseek-v4-pro",
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
      [],
      "deepseek-v4-pro",
      {
        conversationId: "1"
      }
    );
  });

  it("stores uploaded ZIP context on the active conversation and reuses it on later sends", async () => {
    uploadZip.mockResolvedValue({
      zipContextId: "zip-context-1",
      archiveName: "project.zip",
      entryCount: 2,
      extractedEntryCount: 1,
      inventoryOnlyCount: 1,
      skippedEntryCount: 0,
      supportedByCurrentModel: true,
      unsupportedReason: null
    });
    streamChat.mockResolvedValue(createTextStream(["done"]));

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.uploadZip(
        new File(["PK"], "project.zip", { type: "application/zip" }),
        "Use this ZIP"
      );
    });

    expect(result.current.activeConversation).toMatchObject({
      title: "Use this ZIP",
      zipContext: {
        zipContextId: "zip-context-1",
        archiveName: "project.zip",
        pendingAttachment: true
      }
    });

    const activeConversationId = result.current.activeConversationId;
    expect(activeConversationId).toBeTruthy();
    expect(uploadZip).toHaveBeenCalledWith(
      expect.any(File),
      {
        conversationId: activeConversationId,
        model: "deepseek-v4-flash"
      }
    );

    await act(async () => {
      await result.current.sendMessage("Question about zip");
    });

    expect(streamChat).toHaveBeenCalledWith(
      [
        {
          role: "user",
          content: "Question about zip",
          attachments: [
            expect.objectContaining({
              name: "project.zip",
              type: "ZIP",
              size: 0,
              meta: "ZIP · 已扫描 2 项 · 已提取 1 项 · 仅清单 1 项"
            })
          ]
        }
      ],
      [],
      "deepseek-v4-flash",
      {
        conversationId: "1",
        zipContextId: "zip-context-1"
      }
    );

    expect(result.current.activeConversation?.messages).toMatchObject([
      {
        role: "user",
        content: "Question about zip",
        attachments: [
          {
            name: "project.zip",
            meta: "ZIP · 已扫描 2 项 · 已提取 1 项 · 仅清单 1 项"
          }
        ]
      },
      {
        role: "assistant",
        content: "done"
      }
    ]);
    expect(result.current.activeConversation?.zipContext).toMatchObject({
      zipContextId: "zip-context-1",
      pendingAttachment: false
    });
    expect(result.current.stagedFiles).toMatchObject([
      {
        name: "project.zip",
        retainedForZipContext: true
      }
    ]);
  });

  it("re-uploads a retained ZIP automatically when the stored ZIP context has expired", async () => {
    uploadZip
      .mockResolvedValueOnce({
        zipContextId: "zip-context-1",
        archiveName: "project.zip",
        entryCount: 2,
        extractedEntryCount: 1,
        inventoryOnlyCount: 1,
        skippedEntryCount: 0,
        supportedByCurrentModel: true,
        unsupportedReason: null
      })
      .mockResolvedValueOnce({
        zipContextId: "zip-context-2",
        archiveName: "project.zip",
        entryCount: 2,
        extractedEntryCount: 1,
        inventoryOnlyCount: 1,
        skippedEntryCount: 0,
        supportedByCurrentModel: true,
        unsupportedReason: null
      });
    streamChat
      .mockRejectedValueOnce(new Error("ZIP 上下文不存在或已过期，请重新上传压缩包。"))
      .mockResolvedValueOnce(createTextStream(["done after retry"]));

    const { result } = renderHook(() => useServerChat());
    const file = new File(["PK"], "project.zip", { type: "application/zip" });

    await act(async () => {
      await result.current.uploadZip(file, "Use this ZIP");
    });

    await act(async () => {
      await result.current.sendMessage("Question about zip");
    });

    expect(uploadZip).toHaveBeenNthCalledWith(2, file, {
      conversationId: "1",
      model: "deepseek-v4-flash"
    });
    expect(streamChat).toHaveBeenLastCalledWith(
      [
        {
          role: "user",
          content: "Question about zip",
          attachments: [
            expect.objectContaining({
              name: "project.zip",
              type: "ZIP",
              size: 0,
              meta: "ZIP · 已扫描 2 项 · 已提取 1 项 · 仅清单 1 项"
            })
          ]
        }
      ],
      [],
      "deepseek-v4-flash",
      {
        conversationId: "1",
        zipContextId: "zip-context-2"
      }
    );
    expect(result.current.error).toBeNull();
    expect(result.current.activeConversation?.zipContext).toMatchObject({
      zipContextId: "zip-context-2",
      pendingAttachment: false
    });
    expect(result.current.stagedFiles).toMatchObject([
      {
        name: "project.zip",
        retainedForZipContext: true
      }
    ]);
  });

  it("shows a pending ZIP context immediately while upload is still in flight", async () => {
    let resolveUpload!: (value: {
      zipContextId: string;
      archiveName: string;
      entryCount: number;
      extractedEntryCount: number;
      inventoryOnlyCount: number;
      skippedEntryCount: number;
      supportedByCurrentModel: boolean;
      unsupportedReason: null;
    }) => void;

    const inFlightUpload = new Promise<{
      zipContextId: string;
      archiveName: string;
      entryCount: number;
      extractedEntryCount: number;
      inventoryOnlyCount: number;
      skippedEntryCount: number;
      supportedByCurrentModel: boolean;
      unsupportedReason: null;
    }>((resolve) => {
      resolveUpload = resolve;
    });

    uploadZip.mockReturnValue(inFlightUpload);

    const { result } = renderHook(() => useServerChat());
    const file = new File(["PK"], "project.zip", { type: "application/zip" });

    let uploadAttempt!: Promise<void>;

    await act(async () => {
      uploadAttempt = result.current.uploadZip(file, "Use this ZIP");
      await Promise.resolve();
    });

    expect(result.current.activeConversation).toMatchObject({
      title: "Use this ZIP",
      zipContext: {
        archiveName: "project.zip",
        pendingAttachment: true,
        uploading: true
      }
    });

    await act(async () => {
      resolveUpload({
        zipContextId: "zip-context-1",
        archiveName: "project.zip",
        entryCount: 36,
        extractedEntryCount: 14,
        inventoryOnlyCount: 2,
        skippedEntryCount: 20,
        supportedByCurrentModel: true,
        unsupportedReason: null
      });
      await uploadAttempt;
    });

    expect(result.current.activeConversation?.zipContext).toMatchObject({
      zipContextId: "zip-context-1",
      archiveName: "project.zip",
      entryCount: 36,
      extractedEntryCount: 14,
      inventoryOnlyCount: 2,
      skippedEntryCount: 20,
      pendingAttachment: true
    });
    expect(result.current.activeConversation?.zipContext).not.toHaveProperty("uploading");
  });

  it("keeps the final ZIP counts visible after upload completes", async () => {
    uploadZip.mockResolvedValue({
      zipContextId: "zip-context-1",
      archiveName: "project.zip",
      entryCount: 36,
      extractedEntryCount: 14,
      inventoryOnlyCount: 2,
      skippedEntryCount: 20,
      supportedByCurrentModel: true,
      unsupportedReason: null
    });
    streamChat.mockResolvedValue(createTextStream(["done"]));

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.uploadZip(new File(["PK"], "project.zip", { type: "application/zip" }), "Use this ZIP");
    });

    await act(async () => {
      await result.current.sendMessage("Question about zip");
    });

    expect(result.current.activeConversation?.messages[0]).toMatchObject({
      role: "user",
      content: "Question about zip",
      attachments: [
        {
          name: "project.zip",
          meta: "ZIP · 已扫描 36 项 · 已提取 14 项 · 仅清单 2 项 · 已跳过 20 项"
        }
      ]
    });
  });

  it("creates a remote conversation before uploading ZIP so the context stays usable", async () => {
    uploadZip.mockResolvedValue({
      zipContextId: "zip-context-1",
      archiveName: "project.zip",
      entryCount: 36,
      extractedEntryCount: 14,
      inventoryOnlyCount: 2,
      skippedEntryCount: 20,
      supportedByCurrentModel: true,
      unsupportedReason: null
    });

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.uploadZip(
        new File(["PK"], "project.zip", { type: "application/zip" }),
        "Use this ZIP"
      );
    });

    expect(createConversation).toHaveBeenCalledWith({ title: "Use this ZIP" });
    expect(uploadZip).toHaveBeenCalledWith(
      expect.any(File),
      expect.objectContaining({
        conversationId: "1"
      })
    );
    expect(result.current.activeConversationId).toBe("1");
  });

  it("replaces a pre-staged ZIP with the retained ZIP copy instead of duplicating it", async () => {
    uploadZip.mockResolvedValue({
      zipContextId: "zip-context-1",
      archiveName: "project.zip",
      entryCount: 2,
      extractedEntryCount: 1,
      inventoryOnlyCount: 1,
      skippedEntryCount: 0,
      supportedByCurrentModel: true,
      unsupportedReason: null
    });

    const { result } = renderHook(() => useServerChat());
    const file = new File(["PK"], "project.zip", { type: "application/zip" });

    act(() => {
      result.current.addFiles([file]);
    });

    expect(result.current.stagedFiles).toHaveLength(1);

    await act(async () => {
      await result.current.uploadZip(file, "Use this ZIP");
    });

    expect(result.current.stagedFiles).toHaveLength(1);
    expect(result.current.stagedFiles[0]).toMatchObject({
      name: "project.zip",
      retainedForZipContext: true
    });
  });

  it("keeps ZIP context for later sends without repeating the ZIP attachment chip", async () => {
    uploadZip.mockResolvedValue({
      zipContextId: "zip-context-1",
      archiveName: "project.zip",
      entryCount: 2,
      extractedEntryCount: 1,
      inventoryOnlyCount: 1,
      skippedEntryCount: 0,
      supportedByCurrentModel: true,
      unsupportedReason: null
    });
    streamChat
      .mockResolvedValueOnce(createTextStream(["first"]))
      .mockResolvedValueOnce(createTextStream(["second"]));

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.uploadZip(
        new File(["PK"], "project.zip", { type: "application/zip" }),
        "Use this ZIP"
      );
    });

    await act(async () => {
      await result.current.sendMessage("Question about zip");
    });

    await act(async () => {
      await result.current.sendMessage("Follow-up question");
    });

    expect(result.current.activeConversation?.messages).toMatchObject([
      {
        role: "user",
        content: "Question about zip",
        attachments: [
          {
            name: "project.zip",
            meta: expect.stringContaining("ZIP")
          }
        ]
      },
      {
        role: "assistant",
        content: "first"
      },
      {
        role: "user",
        content: "Follow-up question"
      },
      {
        role: "assistant",
        content: "second"
      }
    ]);
    expect(result.current.activeConversation?.messages[2]).not.toHaveProperty("attachments");
    expect(streamChat).toHaveBeenLastCalledWith(
      [
        {
          role: "user",
          content: "Question about zip",
          attachments: [
            expect.objectContaining({
              name: "project.zip",
              type: "ZIP",
              size: 0,
              meta: "ZIP · 已扫描 2 项 · 已提取 1 项 · 仅清单 1 项"
            })
          ]
        },
        { role: "assistant", content: "first" },
        { role: "user", content: "Follow-up question" }
      ],
      [],
      "deepseek-v4-flash",
      {
        conversationId: result.current.activeConversationId,
        zipContextId: "zip-context-1"
      }
    );
  });

  it("removes the active pending ZIP context when requested", async () => {
    uploadZip.mockResolvedValue({
      zipContextId: "zip-context-1",
      archiveName: "project.zip",
      entryCount: 2,
      extractedEntryCount: 1,
      inventoryOnlyCount: 1,
      skippedEntryCount: 0,
      supportedByCurrentModel: true,
      unsupportedReason: null
    });

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.uploadZip(
        new File(["PK"], "project.zip", { type: "application/zip" }),
        "Use this ZIP"
      );
    });

    expect(result.current.activeConversation?.zipContext).toMatchObject({
      zipContextId: "zip-context-1",
      pendingAttachment: true
    });

    act(() => {
      result.current.removePendingZipContext?.();
    });

    expect(result.current.activeConversation?.zipContext).toBeUndefined();
  });

  it("drops persisted ZIP context during hydration so stale ids are not reused", async () => {
    const savedState: PersistedChatState = {
      activeConversationId: "conversation-1",
      conversations: [
        {
          id: "conversation-1",
          title: "Saved conversation",
          createdAt: "2026-07-03T00:00:00.000Z",
          updatedAt: "2026-07-03T00:01:00.000Z",
          messages: [],
          zipContext: {
            zipContextId: "stale-zip-1",
            archiveName: "old.zip",
            entryCount: 1,
            extractedEntryCount: 1,
            inventoryOnlyCount: 0,
            skippedEntryCount: 0,
            supportedByCurrentModel: true,
            unsupportedReason: null
          }
        }
      ],
      settings: {
        modelId: "deepseek-v4-pro",
        systemPrompt: "Be concise"
      }
    };

    saveChatState(savedState);
    streamChat.mockResolvedValue(createTextStream(["done"]));

    const { result } = renderHook(() => useServerChat());

    expect(result.current.activeConversationId).toBe("conversation-1");
    expect(result.current.activeConversation?.zipContext).toBeUndefined();

    await act(async () => {
      await result.current.sendMessage("What now?");
    });

    expect(streamChat).toHaveBeenCalledWith(
      [
        {
          role: "user",
          content: "What now?"
        }
      ],
      [],
      "deepseek-v4-pro",
      {
        conversationId: "1"
      }
    );
  });

  it("includes the active conversation id on normal sends without ZIP context", async () => {
    streamChat.mockResolvedValue(createTextStream(["done"]));

    const { result } = renderHook(() => useServerChat());

    await act(async () => {
      await result.current.sendMessage("Hi");
    });

    const activeConversationId = result.current.activeConversationId;
    expect(activeConversationId).toBeTruthy();
    expect(streamChat).toHaveBeenCalledWith(
      [
        { role: "user", content: "Hi" }
      ],
      [],
      "deepseek-v4-flash",
      {
        conversationId: activeConversationId
      }
    );
  });

  it("forwards manual web search for the next send only", async () => {
    streamChat.mockResolvedValue(createTextStream(["done"]));

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.setWebSearchEnabled(true);
    });

    expect(result.current.webSearchEnabled).toBe(true);

    await act(async () => {
      await result.current.sendMessage("Hi");
    });

    expect(streamChat).toHaveBeenCalledWith(
      [{ role: "user", content: "Hi" }],
      [],
      "deepseek-v4-flash",
      {
        conversationId: result.current.activeConversationId,
        webSearch: true
      }
    );
    expect(result.current.webSearchEnabled).toBe(false);
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
        {
          role: "user",
          content: "read this",
          attachments: [
            expect.objectContaining({
              name: "notes.txt",
              type: "Text",
              size: file.size
            })
          ]
        }
      ],
      [file],
      "deepseek-v4-flash",
      {
        conversationId: result.current.activeConversationId
      }
    );
    expect(result.current.stagedFiles).toHaveLength(0);

    continueStream?.();

    await act(async () => {
      await sendPromise;
    });
  });

  it("stores sent attachment metadata on the first user message only", async () => {
    const file = new File(["hello"], "notes.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    });

    streamChat.mockResolvedValue(createTextStream(["done"]));

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.addFiles([file]);
    });

    await act(async () => {
      await result.current.sendMessage("Read this file");
    });

    expect(result.current.activeConversation?.messages).toMatchObject([
      {
        role: "user",
        content: "Read this file",
        attachments: [
          {
            name: "notes.docx",
            type: "DOCX",
            size: file.size
          }
        ]
      },
      {
        role: "assistant",
        content: "done"
      }
    ]);
  });

  it("assigns more specific staged attachment type labels for common file families", () => {
    const markdown = new File(["# notes"], "readme.md", { type: "text/markdown" });
    const csv = new File(["a,b"], "data.csv", { type: "text/csv" });
    const code = new File(["console.log(1)"], "app.js", { type: "text/javascript" });
    const video = new File(["fake"], "capture.mp4", { type: "video/mp4" });
    const archive = new File(["PK"], "bundle.7z", { type: "application/x-7z-compressed" });
    const database = new File(["sqlite"], "cache.sqlite", { type: "application/vnd.sqlite3" });
    const log = new File(["entry"], "runtime.log", { type: "text/plain" });

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.addFiles([markdown, csv, code, video, archive, database, log]);
    });

    expect(result.current.stagedFiles.map((file) => file.type)).toEqual([
      "Markdown",
      "CSV",
      "JavaScript",
      "Video",
      "Archive",
      "Database",
      "LOG"
    ]);
  });

  it("does not reuse earlier attachments on a later follow-up send", async () => {
    const firstFile = new File(["hello"], "notes.txt", { type: "text/plain" });

    streamChat
      .mockResolvedValueOnce(createTextStream(["first"]))
      .mockResolvedValueOnce(createTextStream(["second"]));

    const { result } = renderHook(() => useServerChat());

    act(() => {
      result.current.addFiles([firstFile]);
    });

    await act(async () => {
      await result.current.sendMessage("Use this file");
    });

    await act(async () => {
      await result.current.sendMessage("Now continue without it");
    });

    expect(result.current.activeConversation?.messages).toMatchObject([
      {
        role: "user",
        content: "Use this file",
        attachments: [{ name: "notes.txt" }]
      },
      {
        role: "assistant",
        content: "first"
      },
      {
        role: "user",
        content: "Now continue without it"
      },
      {
        role: "assistant",
        content: "second"
      }
    ]);

    expect(result.current.activeConversation?.messages[2]).not.toHaveProperty("attachments");
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



