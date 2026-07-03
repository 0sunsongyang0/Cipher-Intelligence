import type { StoredChatState } from "../types";

const CHAT_STATE_STORAGE_KEY = "webllm-chat-state";

export type { StoredChatState } from "../types";

export function loadChatState(fallback?: StoredChatState): StoredChatState | null {
  const rawValue = localStorage.getItem(CHAT_STATE_STORAGE_KEY);

  if (rawValue === null) {
    return fallback ?? null;
  }

  try {
    return JSON.parse(rawValue) as StoredChatState;
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
