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
export type ModelProvider = "deepseek" | "openai" | "claude";

type ModelOptionShape = {
  id: string;
  label: string;
  provider: ModelProvider;
  groupLabel: string;
};

function getModelIds<const T extends readonly ModelOptionShape[]>(options: T) {
  return options.map((option) => option.id) as { [K in keyof T]: T[K]["id"] };
}

function getModelLabels<const T extends readonly ModelOptionShape[]>(options: T) {
  return Object.fromEntries(options.map((option) => [option.id, option.label])) as Record<
    T[number]["id"],
    string
  >;
}

function getProviderLabels<const T extends readonly ModelOptionShape[]>(options: T) {
  return Object.fromEntries(options.map((option) => [option.provider, option.groupLabel])) as Record<
    T[number]["provider"],
    string
  >;
}

export const MODEL_PROVIDER_ORDER = ["deepseek", "openai", "claude"] as const;

export const DEEPSEEK_MODEL_OPTIONS = [
  { id: "deepseek-v4-flash", label: "deepseek-v4-flash", provider: "deepseek", groupLabel: "DeepSeek" },
  { id: "deepseek-v4-pro", label: "deepseek-v4-pro", provider: "deepseek", groupLabel: "DeepSeek" },
  { id: "chatgpt-5.5-official", label: "ChatGPT 5.5", provider: "openai", groupLabel: "OpenAI" },
  { id: "chatgpt-5.4-az", label: "ChatGPT 5.4", provider: "openai", groupLabel: "OpenAI" },
  { id: "claude-opus-4-7-official", label: "claude-opus-4-7", provider: "claude", groupLabel: "Claude" },
  { id: "claude-opus-4-6-aws", label: "claude-opus-4-6", provider: "claude", groupLabel: "Claude" },
  { id: "claude-sonnet-4-6-az", label: "claude-sonnet-4-6", provider: "claude", groupLabel: "Claude" }
] as const satisfies readonly ModelOptionShape[];

export const DEEPSEEK_MODEL_IDS = getModelIds(DEEPSEEK_MODEL_OPTIONS);

export type DeepSeekModelId = (typeof DEEPSEEK_MODEL_IDS)[number];
export type DeepSeekModelOption = (typeof DEEPSEEK_MODEL_OPTIONS)[number];

export const DEFAULT_DEEPSEEK_MODEL_ID: DeepSeekModelId = "deepseek-v4-flash";

export const DEEPSEEK_MODEL_LABELS = getModelLabels(DEEPSEEK_MODEL_OPTIONS);
export const MODEL_PROVIDER_LABELS = getProviderLabels(DEEPSEEK_MODEL_OPTIONS);

export function isDeepSeekModelId(value: string): value is DeepSeekModelId {
  return (DEEPSEEK_MODEL_IDS as readonly string[]).includes(value);
}

export function resolveDeepSeekModelId(value?: string): DeepSeekModelId {
  return typeof value === "string" && isDeepSeekModelId(value)
    ? value
    : DEFAULT_DEEPSEEK_MODEL_ID;
}

export function getDeepSeekModelLabel(modelId: DeepSeekModelId): string {
  return DEEPSEEK_MODEL_LABELS[modelId];
}

export function getDeepSeekModelProvider(modelId: DeepSeekModelId): ModelProvider {
  const option = DEEPSEEK_MODEL_OPTIONS.find((candidate) => candidate.id === modelId);

  if (!option) {
    throw new Error(`Missing provider metadata for model "${modelId}"`);
  }

  return option.provider;
}

export function getDeepSeekModelsByProvider(provider: ModelProvider): DeepSeekModelOption[] {
  return DEEPSEEK_MODEL_OPTIONS.filter((option) => option.provider === provider);
}

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

export type StagedAttachment = {
  id: string;
  file: File;
  name: string;
  type: string;
  size: number;
};

export type WebLlmInitProgress = {
  progress: number;
  text: string;
};

