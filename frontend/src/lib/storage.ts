import type { StoredChatState } from "../types";

const CHAT_STATE_STORAGE_KEY = "webllm-chat-state";

export type { StoredChatState } from "../types";

function isValidChatState(value: unknown): value is StoredChatState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<StoredChatState>;

  if (
    candidate.activeConversationId !== null &&
    typeof candidate.activeConversationId !== "string"
  ) {
    return false;
  }

  if (!Array.isArray(candidate.conversations)) {
    return false;
  }

  if (
    typeof candidate.settings !== "object" ||
    candidate.settings === null ||
    typeof candidate.settings.modelId !== "string" ||
    typeof candidate.settings.systemPrompt !== "string"
  ) {
    return false;
  }

  return candidate.conversations.every((conversation) => {
    if (typeof conversation !== "object" || conversation === null) {
      return false;
    }

    return (
      typeof conversation.id === "string" &&
      typeof conversation.title === "string" &&
      typeof conversation.createdAt === "string" &&
      typeof conversation.updatedAt === "string" &&
      Array.isArray(conversation.messages) &&
      conversation.messages.every((message) => {
        if (typeof message !== "object" || message === null) {
          return false;
        }

        return (
          typeof message.id === "string" &&
          (message.role === "system" ||
            message.role === "user" ||
            message.role === "assistant") &&
          typeof message.content === "string" &&
          typeof message.createdAt === "string"
        );
      })
    );
  });
}

export function loadChatState(fallback?: StoredChatState): StoredChatState | null {
  const rawValue = localStorage.getItem(CHAT_STATE_STORAGE_KEY);

  if (rawValue === null) {
    return fallback ?? null;
  }

  try {
    const parsedValue = JSON.parse(rawValue) as unknown;

    if (!isValidChatState(parsedValue)) {
      localStorage.removeItem(CHAT_STATE_STORAGE_KEY);
      return fallback ?? null;
    }

    return parsedValue;
  } catch {
    localStorage.removeItem(CHAT_STATE_STORAGE_KEY);
    return fallback ?? null;
  }
}

export function saveChatState(state: StoredChatState): void {
  localStorage.setItem(CHAT_STATE_STORAGE_KEY, JSON.stringify(state));
}

export function clearChatState(): void {
  localStorage.removeItem(CHAT_STATE_STORAGE_KEY);
}
