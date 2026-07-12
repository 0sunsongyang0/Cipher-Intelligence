export type ChatRole = "system" | "user" | "assistant";

export type AuthUser = {
  id: number;
  username: string;
  isAdmin: boolean;
};

export type SessionStatus = {
  authenticated: boolean;
  user: AuthUser | null;
};

export type AdminInviteItem = {
  id: number;
  code: string;
  label: string;
  isActive: boolean;
  maxUses: number | null;
  usedCount: number;
  expiresAt: string | null;
  createdAt: string;
};

export type AdminInviteListResponse = {
  items: AdminInviteItem[];
};

export type ConversationApiItem = {
  id: number;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ConversationApiListResponse = {
  items: ConversationApiItem[];
};

export type ConversationImportResult = ConversationApiItem & {
  importedMessages: number;
};

export type MessageApiItem = {
  id: number;
  conversation_id: number;
  role: ChatRole;
  content: string;
  created_at: string;
  attachments?: MessageAttachment[];
};

export type MessageApiListResponse = {
  items: MessageApiItem[];
};

export type AdminInviteCreateRequest = {
  code: string;
  label: string;
  maxUses: number | null;
  expiresAt: string | null;
  isActive: boolean;
};

export type LocalChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  createdAt: string;
  attachments?: MessageAttachment[];
};

export type MessageAttachment = {
  id: string;
  name: string;
  type: string;
  size: number;
  meta?: string;
};

export type LocalConversation = {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: LocalChatMessage[];
  zipContext?: ZipConversationContext;
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
  { id: "claude-sonnet-4-6-az", label: "claude-sonnet-4-6", provider: "claude", groupLabel: "Claude" },
  { id: "claude-opus-4-7-backup", label: "claude-opus-4-7 备用", provider: "claude", groupLabel: "Claude" },
  { id: "claude-opus-4-6-backup", label: "claude-opus-4-6 备用", provider: "claude", groupLabel: "Claude" },
  { id: "claude-sonnet-4-6-backup", label: "claude-sonnet-4-6 备用", provider: "claude", groupLabel: "Claude" }
] as const satisfies readonly ModelOptionShape[];

export const DEEPSEEK_MODEL_IDS = getModelIds(DEEPSEEK_MODEL_OPTIONS);

export type DeepSeekModelId = (typeof DEEPSEEK_MODEL_IDS)[number];
export type DeepSeekModelOption = (typeof DEEPSEEK_MODEL_OPTIONS)[number];

export const DEFAULT_DEEPSEEK_MODEL_ID: DeepSeekModelId = "deepseek-v4-flash";
export const ZIP_UNSUPPORTED_MODEL_REASON = "当前模型不支持 ZIP 文件问答，请切换其他模型。";

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

export function isZipContextSupportedModel(modelId: DeepSeekModelId): boolean {
  return DEEPSEEK_MODEL_OPTIONS.some((option) => option.id === modelId);
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

export type ZipConversationContext = {
  zipContextId: string;
  archiveName: string;
  entryCount: number;
  extractedEntryCount: number;
  inventoryOnlyCount: number;
  skippedEntryCount: number;
  supportedByCurrentModel: boolean;
  unsupportedReason: string | null;
  pendingAttachment?: boolean;
  uploading?: boolean;
  errorMessage?: string | null;
};

export type UploadZipResult = ZipConversationContext;

export type AdminOverview = {
  services: {
    backend: { running: boolean; pid?: number | null; label?: string; detail?: string };
    tunnel: { running: boolean; pid?: number | null; label?: string; detail?: string };
    autostartEnabled: boolean;
  };
  access: {
    localUrl: string;
    publicUrl: string;
  };
  models: {
    providers: Array<{ provider: string; healthy: number; total: number }>;
  };
  files: {
    uploadLimit: number;
    zipEnabled: boolean;
    zipContextCount: number;
  };
};

export type AdminFileCacheClearResult = {
  ok: boolean;
  cleared: number;
};

export type AdminPromptSource = "default" | "override";
export type AdminPromptStatus = "ready" | "fallback" | "error";

export type AdminPrompt = {
  prompt: string;
  source: AdminPromptSource;
  updatedAt: string | null;
  status: AdminPromptStatus;
  message: string | null;
};

export type AdminPromptMutationResult = AdminPrompt & {
  ok: boolean;
};

export function buildZipAttachmentMeta(
  context: Pick<
    ZipConversationContext,
    "entryCount" | "extractedEntryCount" | "inventoryOnlyCount" | "skippedEntryCount" | "uploading"
  >
): string {
  if (context.uploading) {
    return "ZIP · 上传中...";
  }

  return [
    `ZIP · 已扫描 ${context.entryCount} 项`,
    `已提取 ${context.extractedEntryCount} 项`,
    context.inventoryOnlyCount > 0 ? `仅清单 ${context.inventoryOnlyCount} 项` : null,
    context.skippedEntryCount > 0 ? `已跳过 ${context.skippedEntryCount} 项` : null
  ]
    .filter((part): part is string => part !== null)
    .join(" · ");
}

export type OutboundChatMessage = {
  role: ChatRole;
  content: string;
  attachments?: MessageAttachment[];
};

export type StagedAttachment = {
  id: string;
  file: File;
  name: string;
  type: string;
  size: number;
  retainedForZipContext?: boolean;
};

export type WebLlmInitProgress = {
  progress: number;
  text: string;
};
