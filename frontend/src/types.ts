export type Conversation = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: number;
  conversation_id: number;
  role: "user" | "assistant";
  content: string;
  created_at: string;
};

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

export type WebLlmSettings = {
  modelId: string;
  systemPrompt: string;
};

export type StoredChatState = {
  activeConversationId: string | null;
  conversations: LocalConversation[];
  settings: WebLlmSettings;
};

export type WebLlmInitProgress = {
  progress: number;
  text: string;
};
