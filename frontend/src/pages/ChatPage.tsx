import { useEffect, useRef, useState } from "react";
import { ChatComposer } from "../components/ChatComposer";
import { MessageList } from "../components/MessageList";
import { Sidebar } from "../components/Sidebar";
import { streamChat } from "../lib/stream";
import type { Conversation, Message } from "../types";

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return "暂时无法完成当前操作，请稍后重试。";
}

function buildConversationTitle(content: string): string {
  const normalized = content.trim().replace(/\s+/g, " ");
  return normalized.slice(0, 24) || "新建对话";
}

function upsertConversation(
  conversations: Conversation[],
  nextConversation: Conversation
): Conversation[] {
  return [
    nextConversation,
    ...conversations.filter(({ id }) => id !== nextConversation.id)
  ];
}

async function fetchConversationsSafe(): Promise<Conversation[]> {
  const api = await import("../lib/api");

  if (typeof api.fetchConversations !== "function") {
    return [];
  }

  return api.fetchConversations();
}

async function createConversationSafe(title: string): Promise<Conversation> {
  const api = await import("../lib/api");

  if (typeof api.createConversation !== "function") {
    const now = new Date().toISOString();
    return {
      id: Date.now(),
      title,
      created_at: now,
      updated_at: now
    };
  }

  return api.createConversation(title);
}

async function fetchMessagesSafe(conversationId: number): Promise<Message[]> {
  const api = await import("../lib/api");

  if (typeof api.fetchMessages !== "function") {
    return [];
  }

  return api.fetchMessages(conversationId);
}

export function ChatPage() {
  const nextTempId = useRef(-1);
  const pendingLocalConversationId = useRef<number | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoadingConversations, setIsLoadingConversations] = useState(true);
  const [isLoadingMessages, setIsLoadingMessages] = useState(false);
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadConversationList() {
      try {
        const items = await fetchConversationsSafe();
        if (!active) {
          return;
        }

        setConversations(items);
        setActiveConversationId((currentConversationId) => {
          if (currentConversationId !== null) {
            const stillExists = items.some(({ id }) => id === currentConversationId);
            if (stillExists) {
              return currentConversationId;
            }
          }

          return items[0]?.id ?? null;
        });
      } catch (nextError) {
        if (active) {
          setError(getErrorMessage(nextError));
        }
      } finally {
        if (active) {
          setIsLoadingConversations(false);
        }
      }
    }

    void loadConversationList();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    if (activeConversationId === null) {
      setMessages([]);
      setIsLoadingMessages(false);
      return () => {
        active = false;
      };
    }

    const conversationId = activeConversationId;

    async function loadConversationMessages() {
      setIsLoadingMessages(true);

      try {
        const items = await fetchMessagesSafe(conversationId);
        if (!active) {
          return;
        }

        if (pendingLocalConversationId.current === conversationId) {
          return;
        }

        setMessages(items);
      } catch (nextError) {
        if (active) {
          setError(getErrorMessage(nextError));
        }
      } finally {
        if (active) {
          setIsLoadingMessages(false);
        }
      }
    }

    void loadConversationMessages();

    return () => {
      active = false;
    };
  }, [activeConversationId]);

  async function refreshConversationState(conversationId: number) {
    const [nextConversations, nextMessages] = await Promise.all([
      fetchConversationsSafe(),
      fetchMessagesSafe(conversationId)
    ]);

    setConversations(nextConversations);
    setActiveConversationId(conversationId);
    setMessages(nextMessages);
  }

  async function handleCreateConversation() {
    setError(null);
    setIsCreatingConversation(true);

    try {
      const conversation = await createConversationSafe("新建对话");
      setConversations((current) => upsertConversation(current, conversation));
      setActiveConversationId(conversation.id);
      setMessages([]);
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setIsCreatingConversation(false);
    }
  }

  async function ensureConversation(content: string): Promise<Conversation> {
    if (activeConversationId !== null) {
      const existingConversation = conversations.find(
        ({ id }) => id === activeConversationId
      );

      if (existingConversation) {
        return existingConversation;
      }
    }

    const conversation = await createConversationSafe(buildConversationTitle(content));
    setConversations((current) => upsertConversation(current, conversation));
    setActiveConversationId(conversation.id);
    setMessages([]);
    return conversation;
  }

  async function handleSendMessage(content: string) {
    setError(null);
    setIsStreaming(true);

    let conversationId: number | null = null;

    try {
      const conversation = await ensureConversation(content);
      conversationId = conversation.id;
      pendingLocalConversationId.current = conversationId;

      const createdAt = new Date().toISOString();
      const optimisticUserMessage: Message = {
        id: nextTempId.current--,
        conversation_id: conversationId,
        role: "user",
        content,
        created_at: createdAt
      };
      const optimisticAssistantMessageId = nextTempId.current--;
      const optimisticAssistantMessage: Message = {
        id: optimisticAssistantMessageId,
        conversation_id: conversationId,
        role: "assistant",
        content: "",
        created_at: createdAt
      };

      setMessages((current) => [
        ...current,
        optimisticUserMessage,
        optimisticAssistantMessage
      ]);

      await streamChat(conversationId, content, (chunk) => {
        setMessages((current) =>
          current.map((message) =>
            message.id === optimisticAssistantMessageId
              ? {
                  ...message,
                  content: `${message.content}${chunk}`
                }
              : message
          )
        );
      });
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setIsStreaming(false);

      if (conversationId !== null) {
        try {
          await refreshConversationState(conversationId);
        } catch (refreshError) {
          setError(getErrorMessage(refreshError));
        }
      }

      pendingLocalConversationId.current = null;
    }
  }

  return (
    <main className="shell shell--chat">
      <div className="chat-layout">
        <Sidebar
          conversations={conversations}
          activeConversationId={activeConversationId}
          disabled={isStreaming}
          isCreatingConversation={isCreatingConversation}
          isLoading={isLoadingConversations}
          onCreateConversation={handleCreateConversation}
          onSelectConversation={setActiveConversationId}
        />

        <section className="chat-workspace">
          <header className="chat-header">
            <div>
              <p className="eyebrow">Private Campus Copilot</p>
              <h1>兔兔炸弹的大模型助手</h1>
              <h2 className="sr-only">对话界面正在准备中</h2>
            </div>
            <p className="muted">
              {activeConversationId === null
                ? "新建一个对话，或者直接发出你的第一条问题。"
                : "当前对话支持纯文本流式回复，助手会边生成边显示。"}
            </p>
          </header>

          {error ? (
            <p className="error-message chat-error" role="alert">
              {error}
            </p>
          ) : null}

          <MessageList
            isLoading={isLoadingMessages}
            isStreaming={isStreaming}
            messages={messages}
          />

          <ChatComposer
            disabled={
              isLoadingConversations ||
              isLoadingMessages ||
              isCreatingConversation ||
              isStreaming
            }
            isStreaming={isStreaming}
            onSubmit={handleSendMessage}
          />
        </section>
      </div>
    </main>
  );
}
