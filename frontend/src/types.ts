export type ChatRole = "system" | "user" | "assistant";

export type LocalChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
};

export type LocalConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: LocalChatMessage[];
};

export type RuntimeStatus = "idle" | "loading" | "ready" | "error";

export type ChatSettings = {
  systemPrompt: string;
  modelId?: string;
};

export type WebLlmSettings = {
  modelId: string;
  systemPrompt: string;
};

export type StoredChatState = {
  activeConversationId: string | null;
  conversations: LocalConversation[];
  settings: WebLlmSettings;
};

export type ServerChatState = {
  activeConversationId: string | null;
  conversations: LocalConversation[];
  settings: ChatSettings;
};

export type PersistedChatState = StoredChatState | ServerChatState;

export type OutboundChatMessage = {
  role: ChatRole;
  content: string;
};

export type WebLlmInitProgress = {
  progress: number;
  text: string;
};
