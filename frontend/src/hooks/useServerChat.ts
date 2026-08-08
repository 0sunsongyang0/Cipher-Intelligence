import { useEffect, useMemo, useRef, useState } from "react";

import {
  createConversation as createConversationApi,
  createCapeCase as createCapeCaseApi,
  deleteConversation as deleteConversationApi,
  getCapeCase,
  getConversationMessages,
  importConversation as importConversationApi,
  listCapeCases,
  listConversations,
  streamChat,
  updateConversation as updateConversationApi,
  uploadZip as uploadZipApi,
  runSkill as runSkillApi
} from "../lib/api";
import { loadChatState, saveChatState } from "../lib/storage";
import { uploadFileResumably } from "../lib/resumableUpload";
import type {
  CapeCase,
  CaseMetadataUpdate,
  AnalysisTemplate,
  DeepSeekModelId,
  LocalChatMessage,
  LocalConversation,
  MessageAttachment,
  MessageEvidence,
  OutboundChatMessage,
  PersistedChatState,
  RuntimeStatus,
  SkillPackage,
  StagedAttachment
} from "../types";
import {
  buildZipAttachmentMeta as formatZipAttachmentMeta,
  resolveDeepSeekModelId
} from "../types";

type UseServerChatResult = {
  activeConversation: LocalConversation | null;
  activeConversationId: string | null;
  conversations: LocalConversation[];
  createConversationFromTemplate?: (template: AnalysisTemplate | null) => Promise<LocalConversation | void>;
  clearFiles: () => void;
  deleteConversation: (conversationId: string) => void;
  renameConversation?: (conversationId: string, title: string) => Promise<void>;
  setConversationPinned?: (conversationId: string, pinned: boolean) => Promise<void>;
  setConversationArchived?: (conversationId: string, archived: boolean) => Promise<void>;
  updateCaseMetadata?: (conversationId: string, metadata: CaseMetadataUpdate) => Promise<void>;
  error: string | null;
  isGenerating: boolean;
  notificationMessage?: string | null;
  clearNotification?: () => void;
  addFiles: (files: File[]) => void;
  removeFile: (attachmentId: string) => void;
  retryFile?: (attachmentId: string) => void;
  removePendingZipContext?: () => void;
  runtimeStatus: RuntimeStatus;
  sendMessage: (content: string) => Promise<void>;
  runConversationSkill?: (skill: SkillPackage, prompt: string, input: Record<string, unknown>) => Promise<void>;
  stopGeneration?: () => void;
  submitCapeCase: (file: File) => Promise<CapeCase>;
  refreshCapeCase: (caseId: number) => Promise<CapeCase>;
  setWebSearchEnabled: (enabled: boolean) => void;
  uploadZip: (file: File, prompt: string) => Promise<void>;
  setActiveConversationId: (conversationId: string | null) => void;
  setModelId: (modelId: DeepSeekModelId) => void;
  updateSettings?: (settings: Partial<PersistedChatState["settings"]>) => void;
  stagedFiles: StagedAttachment[];
  settings: PersistedChatState["settings"];
  webSearchEnabled: boolean;
};

const DEFAULT_CHAT_STATE: PersistedChatState = {
  activeConversationId: null,
  conversations: [],
  settings: {
    systemPrompt: "You are a helpful assistant.",
    responseLanguage: "zh-CN",
    responseLength: "balanced",
    defaultWebSearch: false,
    capeNotificationsEnabled: true,
    motionPreference: "system",
    transparencyPreference: "system"
  }
};

const MISSING_ZIP_CONTEXT_ERROR = "ZIP 上下文不存在或已过期，请重新上传压缩包。";
const STREAM_KEEPALIVE_MARKER = "\u001e__CIPHER_KEEPALIVE__\u001e";
const STREAM_ERROR_PREFIX = "\u001e__CIPHER_ERROR__:";
const STREAM_EVIDENCE_PREFIX = "\u001e__CIPHER_EVIDENCE__:";
const STREAM_MARKER_SUFFIX = "\u001e";
const ALLOWED_ATTACHMENT_EXTENSIONS = new Set(["txt","log","md","markdown","csv","json","xml","yaml","yml","sql","pdf","doc","docx","xls","xlsx","ppt","pptx","zip","rar","7z","tar","gz","tgz","bz2","xz","png","jpg","jpeg","webp","gif","svg","bmp","tif","tiff","heic","py","js","jsx","mjs","cjs","ts","tsx","mts","cts","java","c","cc","cpp","cxx","h","hpp","hh","hxx","html","htm","css","scss","sass","less","mp4","mov","mkv","avi","webm","flv","mpg","mpeg","m4v","mp3","wav","aac","m4a","flac","ogg","oga","sqlite","sqlite3","db","mdb","accdb","pcap","cap","evtx"]);

function parseStreamPayload(text: string): {
  content: string;
  error: string | null;
  evidence: MessageEvidence[];
} {
  let content = text.split(STREAM_KEEPALIVE_MARKER).join("");
  let error: string | null = null;
  const evidence: MessageEvidence[] = [];

  while (true) {
    const start = content.indexOf(STREAM_ERROR_PREFIX);
    if (start === -1) {
      break;
    }

    const end = content.indexOf(STREAM_MARKER_SUFFIX, start + STREAM_ERROR_PREFIX.length);
    if (end === -1) {
      break;
    }

    if (error === null) {
      error = content.slice(start + STREAM_ERROR_PREFIX.length, end);
    }

    content = `${content.slice(0, start)}${content.slice(end + STREAM_MARKER_SUFFIX.length)}`;
  }

  while (true) {
    const start = content.indexOf(STREAM_EVIDENCE_PREFIX);
    if (start === -1) {
      break;
    }
    const end = content.indexOf(STREAM_MARKER_SUFFIX, start + STREAM_EVIDENCE_PREFIX.length);
    if (end === -1) {
      content = content.slice(0, start);
      break;
    }
    const rawPayload = content.slice(start + STREAM_EVIDENCE_PREFIX.length, end);
    try {
      const parsed = JSON.parse(rawPayload) as unknown;
      if (Array.isArray(parsed)) {
        for (const item of parsed) {
          if (
            typeof item === "object" &&
            item !== null &&
            typeof (item as MessageEvidence).citation === "string" &&
            typeof (item as MessageEvidence).title === "string" &&
            typeof (item as MessageEvidence).sourceType === "string"
          ) {
            evidence.push(item as MessageEvidence);
          }
        }
      }
    } catch {
      // Ignore malformed evidence metadata while preserving the answer stream.
    }
    content = `${content.slice(0, start)}${content.slice(end + STREAM_MARKER_SUFFIX.length)}`;
  }

  const dedupedEvidence = evidence.filter(
    (item, index, items) =>
      items.findIndex(
        (candidate) =>
          candidate.citation === item.citation &&
          candidate.title === item.title &&
          candidate.url === item.url
      ) === index
  );
  return { content, error, evidence: dedupedEvidence };
}

function createId(prefix: string): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }

  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function createLocalConversation(firstMessage: string): LocalConversation {
  const timestamp = new Date().toISOString();
  const normalized = firstMessage.trim().replace(/\s+/g, " ");

  return {
    id: createId("conversation"),
    title: normalized.slice(0, 48) || "New conversation",
    caseStatus: "open",
    severity: "unknown",
    tags: [],
    createdAt: timestamp,
    updatedAt: timestamp,
    messages: []
  };
}

function createMessage(role: LocalChatMessage["role"], content: string): LocalChatMessage {
  return {
    id: createId("message"),
    role,
    content,
    createdAt: new Date().toISOString()
  };
}

function serializeSentAttachments(stagedFiles: StagedAttachment[]) {
  return stagedFiles.map(({ id, name, type, size }) => ({
    id,
    name,
    type,
    size
  }));
}

function findRetainedZipAttachment(
  stagedFiles: StagedAttachment[],
  conversation: LocalConversation
): StagedAttachment | undefined {
  return stagedFiles.find(
    (attachment) =>
      attachment.retainedForZipContext &&
      attachment.type === "ZIP" &&
      (conversation.zipContext?.archiveName === undefined ||
        attachment.name === conversation.zipContext.archiveName)
  );
}

function inferAttachmentType(file: File): string {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  const normalizedMimeType = file.type.trim().toLowerCase();

  const typeByExtension: Record<string, string> = {
    pdf: "PDF",
    doc: "DOC",
    docx: "DOCX",
    xls: "XLS",
    xlsx: "XLSX",
    ppt: "PPT",
    pptx: "PPTX",
    md: "Markdown",
    markdown: "Markdown",
    csv: "CSV",
    json: "JSON",
    xml: "XML",
    yaml: "YAML",
    yml: "YAML",
    sql: "SQL",
    log: "LOG",
    js: "JavaScript",
    jsx: "JavaScript",
    mjs: "JavaScript",
    cjs: "JavaScript",
    ts: "TypeScript",
    tsx: "TypeScript",
    mts: "TypeScript",
    cts: "TypeScript",
    py: "Python",
    java: "Java",
    c: "C",
    h: "C",
    cc: "C++",
    cpp: "C++",
    cxx: "C++",
    hpp: "C++",
    hh: "C++",
    hxx: "C++",
    html: "HTML",
    htm: "HTML",
    css: "CSS",
    scss: "CSS",
    sass: "CSS",
    less: "CSS",
    png: "Image",
    jpg: "Image",
    jpeg: "Image",
    webp: "Image",
    bmp: "Image",
    gif: "Image",
    svg: "Image",
    tif: "Image",
    tiff: "Image",
    heic: "Image",
    mp4: "Video",
    mov: "Video",
    mkv: "Video",
    avi: "Video",
    webm: "Video",
    flv: "Video",
    mpg: "Video",
    mpeg: "Video",
    m4v: "Video",
    mp3: "Audio",
    wav: "Audio",
    aac: "Audio",
    m4a: "Audio",
    flac: "Audio",
    ogg: "Audio",
    oga: "Audio",
    zip: "ZIP",
    rar: "Archive",
    "7z": "Archive",
    tar: "Archive",
    gz: "Archive",
    tgz: "Archive",
    bz2: "Archive",
    xz: "Archive",
    sqlite: "Database",
    sqlite3: "Database",
    db: "Database",
    mdb: "Database",
    accdb: "Database",
    pcap: "PCAP",
    cap: "PCAP",
    evtx: "EVTX",
    txt: "Text"
  };

  const typeByMimeType: Record<string, string> = {
    "application/pdf": "PDF",
    "application/msword": "DOC",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "DOCX",
    "application/vnd.ms-excel": "XLS",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "XLSX",
    "application/vnd.ms-powerpoint": "PPT",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PPTX",
    "text/markdown": "Markdown",
    "text/csv": "CSV",
    "application/json": "JSON",
    "text/xml": "XML",
    "application/xml": "XML",
    "application/yaml": "YAML",
    "text/yaml": "YAML",
    "application/x-yaml": "YAML",
    "text/javascript": "JavaScript",
    "application/javascript": "JavaScript",
    "application/x-javascript": "JavaScript",
    "text/typescript": "TypeScript",
    "application/typescript": "TypeScript",
    "text/x-python": "Python",
    "application/x-python-code": "Python",
    "application/zip": "ZIP",
    "application/x-zip-compressed": "ZIP",
    "application/x-7z-compressed": "Archive",
    "application/vnd.rar": "Archive",
    "application/x-rar-compressed": "Archive",
    "application/vnd.sqlite3": "Database",
    "text/plain": "Text"
  };

  if (extension && typeByExtension[extension]) {
    return typeByExtension[extension];
  }

  if (normalizedMimeType && typeByMimeType[normalizedMimeType]) {
    return typeByMimeType[normalizedMimeType];
  }

  if (normalizedMimeType.startsWith("image/")) {
    return "Image";
  }

  if (normalizedMimeType.startsWith("video/")) {
    return "Video";
  }

  if (normalizedMimeType.startsWith("audio/")) {
    return "Audio";
  }

  return "Text";
}

function buildZipContextAttachment(conversation: LocalConversation): MessageAttachment | null {
  if (!conversation.zipContext?.pendingAttachment) {
    return null;
  }

  return {
    id: `zip-attachment-${conversation.zipContext.zipContextId}`,
    name: conversation.zipContext.archiveName,
    type: "ZIP",
    size: 0,
    meta: formatZipAttachmentMeta(conversation.zipContext)
  };
}

function appendMessages(
  conversations: LocalConversation[],
  conversationId: string,
  messages: LocalChatMessage[]
): LocalConversation[] {
  return conversations.map((conversation) =>
    conversation.id === conversationId
      ? {
          ...conversation,
          messages,
          updatedAt: new Date().toISOString()
        }
      : conversation
  );
}

function upsertCapeCase(
  conversations: LocalConversation[],
  conversationId: string,
  capeCase: CapeCase
): LocalConversation[] {
  return conversations.map((conversation) => {
    if (conversation.id !== conversationId) {
      return conversation;
    }

    const existingCases = conversation.capeCases ?? [];
    const hasExistingCase = existingCases.some((candidate) => candidate.id === capeCase.id);
    const nextCases = hasExistingCase
      ? existingCases.map((candidate) => (candidate.id === capeCase.id ? capeCase : candidate))
      : [...existingCases, capeCase];

    return {
      ...conversation,
      capeCases: nextCases,
      updatedAt: new Date().toISOString()
    };
  });
}

function mergeRemoteMessagesWithLocalAttachments(
  remoteMessages: LocalChatMessage[],
  localMessages: LocalChatMessage[]
): LocalChatMessage[] {
  return remoteMessages.map((remoteMessage, index) => {
    if (remoteMessage.attachments && remoteMessage.attachments.length > 0) {
      return remoteMessage;
    }

    const localMessage = localMessages[index];
    if (!localMessage || localMessage.role !== remoteMessage.role) {
      return remoteMessage;
    }

    if (localMessage.content !== remoteMessage.content) {
      return remoteMessage;
    }

    if (!localMessage.attachments || localMessage.attachments.length === 0) {
      return remoteMessage;
    }

    return {
      ...remoteMessage,
      attachments: localMessage.attachments
    };
  });
}

function buildOutboundMessages(
  messages: LocalChatMessage[]
): OutboundChatMessage[] {
  return messages.map((message) => ({
    role: message.role,
    content: message.content,
    ...(message.attachments && message.attachments.length > 0
      ? { attachments: message.attachments }
      : {})
  }));
}

function stripRuntimeZipContext(conversation: LocalConversation): LocalConversation {
  if (!conversation.zipContext) {
    return conversation;
  }

  const { zipContext: _zipContext, ...conversationWithoutZipContext } = conversation;
  return conversationWithoutZipContext;
}

function stripRuntimeZipContexts(chatState: PersistedChatState): PersistedChatState {
  return {
    ...chatState,
    conversations: chatState.conversations.map(stripRuntimeZipContext)
  };
}

export function useServerChat(): UseServerChatResult {
  const [chatState, setChatState] = useState<PersistedChatState>(() =>
    stripRuntimeZipContexts(loadChatState(DEFAULT_CHAT_STATE) ?? DEFAULT_CHAT_STATE)
  );
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>("ready");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stagedFiles, setStagedFiles] = useState<StagedAttachment[]>([]);
  const [webSearchEnabled, setWebSearchEnabled] = useState(
    () => chatState.settings.defaultWebSearch ?? false
  );
  const [notificationMessage, setNotificationMessage] = useState<string | null>(null);

  const chatStateRef = useRef(chatState);
  const generationInFlightRef = useRef(false);
  const hydratedFromCloudRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const notifiedCapeCasesRef = useRef(new Set<number>());

  useEffect(() => {
    chatStateRef.current = chatState;
    saveChatState(stripRuntimeZipContexts(chatState));
  }, [chatState]);

  useEffect(() => {
    if (hydratedFromCloudRef.current) {
      return;
    }

    hydratedFromCloudRef.current = true;

    void (async () => {
      try {
        const remoteConversations = await listConversations();
        if (remoteConversations.items.length === 0) {
          const localState = chatStateRef.current;
          if (localState.conversations.length === 0) {
            return;
          }

          const migratedConversations = await Promise.all(
            localState.conversations.map(async (conversation) => {
              const importedConversation = await importConversationApi({
                title: conversation.title,
                messages: conversation.messages.map((message) => ({
                  role: message.role,
                  content: message.content
                }))
              });

              return {
                ...conversation,
                id: String(importedConversation.id),
                isPinned: importedConversation.is_pinned ?? false,
                isArchived: importedConversation.is_archived ?? false,
                caseStatus: importedConversation.case_status ?? "open",
                severity: importedConversation.severity ?? "unknown",
                assignee: importedConversation.assignee ?? null,
                tags: importedConversation.tags ?? [],
                caseSummary: importedConversation.case_summary ?? null,
                createdAt: importedConversation.created_at,
                updatedAt: importedConversation.updated_at
              };
            })
          );

          setChatState((previousState) => ({
            ...previousState,
            activeConversationId:
              previousState.activeConversationId !== null
                ? migratedConversations.find(
                    (conversation) => conversation.title ===
                      previousState.conversations.find(
                        (candidate) => candidate.id === previousState.activeConversationId
                      )?.title
                  )?.id ?? migratedConversations[0]?.id ?? null
                : migratedConversations[0]?.id ?? null,
            conversations: migratedConversations
          }));
          return;
        }

        const hydratedConversations = await Promise.all(
          remoteConversations.items.map(async (conversation) => {
            const messages = await getConversationMessages(String(conversation.id));
            const capeCases = await listCapeCases(String(conversation.id));
            const localConversation = chatStateRef.current.conversations.find(
              (candidate) => candidate.id === String(conversation.id)
            );
            const remoteMessages = messages.items.map((message) => ({
              id: String(message.id),
              role: message.role,
              content: message.content,
              createdAt: message.created_at,
              ...(message.attachments && message.attachments.length > 0
                ? { attachments: message.attachments }
                : {}),
              ...(message.evidence && message.evidence.length > 0
                ? { evidence: message.evidence }
                : {})
            }));

            return {
              id: String(conversation.id),
              title: conversation.title,
              isPinned: conversation.is_pinned ?? false,
              isArchived: conversation.is_archived ?? false,
              caseStatus: conversation.case_status ?? "open",
              severity: conversation.severity ?? "unknown",
              assignee: conversation.assignee ?? null,
              tags: conversation.tags ?? [],
              caseSummary: conversation.case_summary ?? null,
              analysisTemplate: conversation.analysis_config ?? null,
              createdAt: conversation.created_at,
              updatedAt: conversation.updated_at,
              messages: mergeRemoteMessagesWithLocalAttachments(
                remoteMessages,
                localConversation?.messages ?? []
              ),
              capeCases: capeCases.items
            } satisfies LocalConversation;
          })
        );

        setChatState((previousState) => ({
          ...previousState,
          activeConversationId:
            previousState.activeConversationId !== null &&
            hydratedConversations.some(
              (conversation) => conversation.id === previousState.activeConversationId
            )
              ? previousState.activeConversationId
              : hydratedConversations[0]?.id ?? null,
          conversations: hydratedConversations
        }));
      } catch (nextError) {
        setError(nextError instanceof Error ? nextError.message : "Failed to load cloud history.");
      }
    })();
  }, []);

  const activeConversation = useMemo(
    () =>
      chatState.activeConversationId === null
        ? null
        : chatState.conversations.find(
            (conversation) => conversation.id === chatState.activeConversationId
          ) ?? null,
    [chatState.activeConversationId, chatState.conversations]
  );
  const activeModelId = resolveDeepSeekModelId(chatState.settings.modelId);

  useEffect(() => {
    const pendingCases = chatState.conversations.flatMap((conversation) =>
      (conversation.capeCases ?? [])
        .filter((capeCase) => !capeCase.completed)
        .map((capeCase) => ({ capeCase, conversationId: conversation.id }))
    );
    if (pendingCases.length === 0) {
      return;
    }

    let active = true;
    let checking = false;

    async function checkPendingCases() {
      if (checking) {
        return;
      }
      checking = true;

      try {
        await Promise.all(
          pendingCases.map(async ({ capeCase, conversationId }) => {
            try {
              const refreshedCase = await getCapeCase(capeCase.id);
              if (!active) {
                return;
              }

              setChatState((previousState) => ({
                ...previousState,
                conversations: upsertCapeCase(
                  previousState.conversations,
                  conversationId,
                  refreshedCase
                )
              }));

              if (
                refreshedCase.completed &&
                !notifiedCapeCasesRef.current.has(refreshedCase.id) &&
                (chatState.settings.capeNotificationsEnabled ?? true)
              ) {
                notifiedCapeCasesRef.current.add(refreshedCase.id);
                const message = `CAPE Case #${refreshedCase.id}（${refreshedCase.sampleName}）分析完成`;
                setNotificationMessage(message);

                if (
                  typeof window !== "undefined" &&
                  "Notification" in window &&
                  Notification.permission === "granted"
                ) {
                  new Notification("Cipher 分析完成", { body: message });
                }
              }
            } catch {
              // Keep polling other cases; transient CAPE errors remain recoverable in the case card.
            }
          })
        );
      } finally {
        checking = false;
      }
    }

    const intervalId = window.setInterval(() => {
      void checkPendingCases();
    }, 5000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, [chatState.conversations, chatState.settings.capeNotificationsEnabled]);

  async function ensureRemoteConversation(
    conversation: LocalConversation | null,
    fallbackTitle: string
  ): Promise<LocalConversation> {
    if (conversation && isRemoteConversationId(conversation.id)) {
      return conversation;
    }

    const createdConversation = await createConversationApi({
      title: conversation?.title || fallbackTitle
    });

    return {
      ...(conversation ?? createLocalConversation(fallbackTitle)),
      id: String(createdConversation.id),
      title: createdConversation.title,
      isPinned: createdConversation.is_pinned ?? false,
      isArchived: createdConversation.is_archived ?? false,
      caseStatus: createdConversation.case_status ?? "open",
      severity: createdConversation.severity ?? "unknown",
      assignee: createdConversation.assignee ?? null,
      tags: createdConversation.tags ?? [],
      caseSummary: createdConversation.case_summary ?? null,
      createdAt: createdConversation.created_at,
      updatedAt: createdConversation.updated_at
    };
  }

  async function sendMessage(content: string) {
    const normalizedContent = content.trim();

    if (!normalizedContent) {
      return;
    }

    if (generationInFlightRef.current) {
      throw new Error("Chat generation is already in progress.");
    }

    generationInFlightRef.current = true;
    const abortController = new AbortController();
    abortControllerRef.current = abortController;
    setError(null);
    setIsGenerating(true);
    setRuntimeStatus("loading");

    const currentState = chatStateRef.current;
    const existingConversation =
      currentState.activeConversationId === null
        ? null
        : currentState.conversations.find(
            (conversation) => conversation.id === currentState.activeConversationId
          ) ?? null;

    const stagedFilesForRequest = stagedFiles;
    const regularStagedFilesForRequest = stagedFilesForRequest.filter(
      (attachment) => !attachment.retainedForZipContext
    );
    const useWebSearchForRequest = webSearchEnabled;
    const sentAttachments = serializeSentAttachments(regularStagedFilesForRequest);
    const filesForRequest = regularStagedFilesForRequest.filter((attachment) => !attachment.uploadId).map((attachment) => attachment.file);
    const uploadedFileIds = regularStagedFilesForRequest.flatMap((attachment) => attachment.uploadId ? [attachment.uploadId] : []);
    const targetConversation = await ensureRemoteConversation(
      existingConversation,
      normalizedContent.slice(0, 48) || "New conversation"
    );
    const retainedZipAttachment = findRetainedZipAttachment(stagedFilesForRequest, targetConversation);
    const zipAttachment = buildZipContextAttachment(targetConversation);
    const attachmentsForMessage = zipAttachment
      ? [zipAttachment, ...sentAttachments]
      : sentAttachments;
    const userMessage: LocalChatMessage = {
      ...createMessage("user", normalizedContent),
      ...(attachmentsForMessage.length > 0 ? { attachments: attachmentsForMessage } : {})
    };
    const assistantMessage = createMessage("assistant", "");
    const conversationMessages = [...targetConversation.messages, userMessage];
    const nextMessages = [...conversationMessages, assistantMessage];

    setStagedFiles((previousFiles) =>
      previousFiles.filter((attachment) => attachment.retainedForZipContext)
    );
    setWebSearchEnabled(false);

    setChatState((previousState) => {
      const hasConversation = previousState.conversations.some(
        (conversation) => conversation.id === targetConversation.id
      );
      const baseConversations = hasConversation
        ? previousState.conversations
        : [targetConversation, ...previousState.conversations];

      return {
        ...previousState,
        activeConversationId: targetConversation.id,
        conversations: baseConversations.map((conversation) =>
          conversation.id === targetConversation.id
            ? {
                ...conversation,
                zipContext: conversation.zipContext
                  ? {
                      ...conversation.zipContext,
                      pendingAttachment: false
                    }
                  : conversation.zipContext,
                messages: nextMessages,
                updatedAt: new Date().toISOString()
              }
            : conversation
        )
      };
    });

    let assistantContent = "";
    let streamedAssistantPayload = "";
    let currentZipContextId = targetConversation.zipContext?.zipContextId;

    async function streamAssistantResponse() {
      const stream = await streamChat(
        buildOutboundMessages(conversationMessages),
        filesForRequest,
        activeModelId,
        {
          conversationId: targetConversation.id,
          ...(useWebSearchForRequest ? { webSearch: true } : {}),
          ...(currentZipContextId ? { zipContextId: currentZipContextId } : {}),
          responseLanguage: currentState.settings.responseLanguage ?? "zh-CN",
          responseLength: currentState.settings.responseLength ?? "balanced",
          signal: abortController.signal
          ,...(uploadedFileIds.length ? { uploadedFileIds } : {})
        }
      );
      const reader = stream.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          break;
        }

        streamedAssistantPayload += decoder.decode(value, { stream: true });
        const parsedPayload = parseStreamPayload(streamedAssistantPayload);
        assistantContent = parsedPayload.content;

        setChatState((previousState) => ({
          ...previousState,
          conversations: appendMessages(
            previousState.conversations,
            targetConversation.id,
            nextMessages.map((message) =>
              message.id === assistantMessage.id
                ? {
                    ...message,
                    content: assistantContent,
                    ...(parsedPayload.evidence.length > 0
                      ? { evidence: parsedPayload.evidence }
                      : {})
                  }
                : message
            )
          )
        }));

        if (parsedPayload.error) {
          throw new Error(parsedPayload.error);
        }
      }

      const remainingContent = decoder.decode();

      if (remainingContent) {
        streamedAssistantPayload += remainingContent;
        const parsedPayload = parseStreamPayload(streamedAssistantPayload);
        assistantContent = parsedPayload.content;

        setChatState((previousState) => ({
          ...previousState,
          conversations: appendMessages(
            previousState.conversations,
            targetConversation.id,
            nextMessages.map((message) =>
              message.id === assistantMessage.id
                ? {
                    ...message,
                    content: assistantContent,
                    ...(parsedPayload.evidence.length > 0
                      ? { evidence: parsedPayload.evidence }
                      : {})
                  }
                : message
            )
          )
        }));

        if (parsedPayload.error) {
          throw new Error(parsedPayload.error);
        }
      }
    }

    try {
      await streamAssistantResponse();
      setRuntimeStatus("ready");
    } catch (nextError) {
      if (
        typeof nextError === "object" &&
        nextError !== null &&
        "name" in nextError &&
        nextError.name === "AbortError"
      ) {
        setRuntimeStatus("ready");
        return;
      }

      const nextErrorMessage =
        nextError instanceof Error ? nextError.message : "Failed to generate response.";

      if (
        !assistantContent &&
        nextErrorMessage === MISSING_ZIP_CONTEXT_ERROR &&
        retainedZipAttachment
      ) {
        try {
          const refreshedZipContext = await uploadZipApi(retainedZipAttachment.file, {
            conversationId: targetConversation.id,
            model: activeModelId
          });
          currentZipContextId = refreshedZipContext.zipContextId;

          setChatState((previousState) => ({
            ...previousState,
            conversations: previousState.conversations.map((conversation) =>
              conversation.id === targetConversation.id
                ? {
                    ...conversation,
                    zipContext: {
                      ...refreshedZipContext,
                      pendingAttachment: false
                    },
                    updatedAt: new Date().toISOString()
                  }
                : conversation
            )
          }));

          await streamAssistantResponse();
          setRuntimeStatus("ready");
          return;
        } catch (retryError) {
          nextError = retryError;
        }
      }

      if (!assistantContent) {
        setChatState((previousState) => ({
          ...previousState,
          conversations: previousState.conversations.map((conversation) =>
            conversation.id === targetConversation.id
              ? {
                  ...conversation,
                  zipContext: zipAttachment && conversation.zipContext
                    ? {
                        ...conversation.zipContext,
                        pendingAttachment: true
                      }
                    : conversation.zipContext,
                  messages: conversationMessages,
                  updatedAt: new Date().toISOString()
                }
              : conversation
          )
        }));
      }

      setStagedFiles((previousFiles) => [...regularStagedFilesForRequest, ...previousFiles]);
      setRuntimeStatus("error");
      setError(nextError instanceof Error ? nextError.message : "Failed to generate response.");
    } finally {
      if (abortControllerRef.current === abortController) {
        abortControllerRef.current = null;
      }
      generationInFlightRef.current = false;
      setIsGenerating(false);
    }
  }

  async function runConversationSkill(skill: SkillPackage, prompt: string, input: Record<string, unknown>) {
    if (generationInFlightRef.current) throw new Error("Chat generation is already in progress.");
    if (!skill.installed) throw new Error("请先在 Skills 市场安装该技能");
    setError(null); setIsGenerating(true); setRuntimeStatus("loading");
    try {
      const currentState = chatStateRef.current;
      const existingConversation = currentState.activeConversationId === null ? null :
        currentState.conversations.find(item => item.id === currentState.activeConversationId) ?? null;
      const targetConversation = await ensureRemoteConversation(existingConversation, prompt.slice(0, 48) || skill.name);
      const result = await runSkillApi(skill.id, input, { conversationId: Number(targetConversation.id), prompt });
      const messages = (result.conversationMessages ?? []).map(message => ({
        id: String(message.id), role: message.role, content: message.content, createdAt: message.createdAt
      } satisfies LocalChatMessage));
      setChatState(previous => {
        const exists = previous.conversations.some(item => item.id === targetConversation.id);
        const base = exists ? previous.conversations : [targetConversation, ...previous.conversations];
        return { ...previous, activeConversationId: targetConversation.id,
          conversations: base.map(item => item.id === targetConversation.id
            ? { ...item, messages: [...item.messages, ...messages], updatedAt: new Date().toISOString() }
            : item) };
      });
      setRuntimeStatus("ready");
    } catch (nextError) {
      setRuntimeStatus("error"); setError(nextError instanceof Error ? nextError.message : "Skill 运行失败"); throw nextError;
    } finally { setIsGenerating(false); }
  }

  function stopGeneration() {
    abortControllerRef.current?.abort();
  }

  async function updateConversationMetadata(
    conversationId: string,
    payload: {
      title?: string;
      isPinned?: boolean;
      isArchived?: boolean;
      caseStatus?: CaseMetadataUpdate["caseStatus"];
      severity?: CaseMetadataUpdate["severity"];
      assignee?: string;
      tags?: string[];
      caseSummary?: string;
    }
  ) {
    const previousConversation = chatStateRef.current.conversations.find(
      (conversation) => conversation.id === conversationId
    );
    if (!previousConversation) {
      return;
    }

    const applyUpdate = (conversation: LocalConversation): LocalConversation => ({
      ...conversation,
      ...(payload.title !== undefined ? { title: payload.title } : {}),
      ...(payload.isPinned !== undefined ? { isPinned: payload.isPinned } : {}),
      ...(payload.isArchived !== undefined
        ? {
            isArchived: payload.isArchived,
            ...(payload.isArchived ? { isPinned: false } : {})
          }
        : {}),
      ...(payload.caseStatus !== undefined ? { caseStatus: payload.caseStatus } : {}),
      ...(payload.severity !== undefined ? { severity: payload.severity } : {}),
      ...(payload.assignee !== undefined ? { assignee: payload.assignee || null } : {}),
      ...(payload.tags !== undefined ? { tags: payload.tags } : {}),
      ...(payload.caseSummary !== undefined ? { caseSummary: payload.caseSummary || null } : {}),
      updatedAt: new Date().toISOString()
    });

    setChatState((previousState) => ({
      ...previousState,
      activeConversationId:
        payload.isArchived && previousState.activeConversationId === conversationId
          ? null
          : previousState.activeConversationId,
      conversations: previousState.conversations.map((conversation) =>
        conversation.id === conversationId ? applyUpdate(conversation) : conversation
      )
    }));

    if (!isRemoteConversationId(conversationId)) {
      return;
    }

    try {
      const updated = await updateConversationApi(conversationId, payload);
      setChatState((previousState) => ({
        ...previousState,
        conversations: previousState.conversations.map((conversation) =>
          conversation.id === conversationId
            ? {
                ...conversation,
                title: updated.title,
                isPinned: updated.is_pinned ?? false,
                isArchived: updated.is_archived ?? false,
                caseStatus: updated.case_status ?? "open",
                severity: updated.severity ?? "unknown",
                assignee: updated.assignee ?? null,
                tags: updated.tags ?? [],
                caseSummary: updated.case_summary ?? null,
                updatedAt: updated.updated_at
              }
            : conversation
        )
      }));
    } catch (nextError) {
      setChatState((previousState) => ({
        ...previousState,
        conversations: previousState.conversations.map((conversation) =>
          conversation.id === conversationId ? previousConversation : conversation
        )
      }));
      setError(nextError instanceof Error ? nextError.message : "更新会话失败。");
      throw nextError;
    }
  }

  async function submitCapeCase(file: File): Promise<CapeCase> {
    const currentState = chatStateRef.current;
    const existingConversation =
      currentState.activeConversationId === null
        ? null
        : currentState.conversations.find(
            (conversation) => conversation.id === currentState.activeConversationId
          ) ?? null;
    const targetConversation = await ensureRemoteConversation(
      existingConversation,
      `CAPE 分析：${file.name}`.slice(0, 48)
    );

    setChatState((previousState) => {
      const hasConversation = previousState.conversations.some(
        (conversation) => conversation.id === targetConversation.id
      );

      return {
        ...previousState,
        activeConversationId: targetConversation.id,
        conversations: hasConversation
          ? previousState.conversations
          : [targetConversation, ...previousState.conversations]
      };
    });

    const capeCase = await createCapeCaseApi(file, {
      conversationId: targetConversation.id
    });

    setChatState((previousState) => ({
      ...previousState,
      activeConversationId: targetConversation.id,
      conversations: upsertCapeCase(previousState.conversations, targetConversation.id, capeCase)
    }));

    return capeCase;
  }

  async function refreshCapeCase(caseId: number): Promise<CapeCase> {
    const capeCase = await getCapeCase(caseId);
    setChatState((previousState) => ({
      ...previousState,
      conversations: upsertCapeCase(
        previousState.conversations,
        String(capeCase.conversationId),
        capeCase
      )
    }));
    return capeCase;
  }

  async function uploadZip(file: File, prompt: string) {
    const normalizedPrompt = prompt.trim();
    const currentState = chatStateRef.current;
    const existingConversation =
      currentState.activeConversationId === null
        ? null
        : currentState.conversations.find(
            (conversation) => conversation.id === currentState.activeConversationId
          ) ?? null;
    const targetConversation = await ensureRemoteConversation(
      existingConversation,
      normalizedPrompt || file.name
    );
    const model = resolveDeepSeekModelId(currentState.settings.modelId);
    const pendingZipContext = {
      zipContextId: createId("zip-upload"),
      archiveName: file.name,
      entryCount: 0,
      extractedEntryCount: 0,
      inventoryOnlyCount: 0,
      skippedEntryCount: 0,
      supportedByCurrentModel: true,
      unsupportedReason: null,
      pendingAttachment: true,
      uploading: true
    } as const;

    setStagedFiles((previousFiles) => {
      const nonRetainedFiles = previousFiles.filter(
        (attachment) =>
          !attachment.retainedForZipContext &&
          !(
            attachment.name === file.name &&
            attachment.size === file.size &&
            attachment.type === "ZIP"
          )
      );

      return [
        ...nonRetainedFiles,
        {
          id: createId("attachment"),
          file,
          name: file.name,
          type: "ZIP",
          size: file.size,
          retainedForZipContext: true
        }
      ];
    });

    setChatState((previousState) => {
      const hasConversation = previousState.conversations.some(
        (conversation) => conversation.id === targetConversation.id
      );
      const baseConversations = hasConversation
        ? previousState.conversations
        : [targetConversation, ...previousState.conversations];

      return {
        ...previousState,
        activeConversationId: targetConversation.id,
        conversations: baseConversations.map((conversation) =>
          conversation.id === targetConversation.id
            ? {
                ...conversation,
                zipContext: pendingZipContext,
                updatedAt: new Date().toISOString()
              }
            : conversation
        )
      };
    });

    let zipContext;
    try {
      zipContext = await uploadZipApi(file, {
        conversationId: targetConversation.id,
        model
      });
    } catch (nextError) {
      setChatState((previousState) => {
        if (existingConversation) {
          return {
            ...previousState,
            conversations: previousState.conversations.map((conversation) =>
              conversation.id === targetConversation.id
                ? {
                    ...conversation,
                    zipContext: existingConversation.zipContext,
                    updatedAt: new Date().toISOString()
                  }
                : conversation
            )
          };
        }

        return {
          ...previousState,
          activeConversationId:
            previousState.activeConversationId === targetConversation.id
              ? null
              : previousState.activeConversationId,
          conversations: previousState.conversations.filter(
            (conversation) => conversation.id !== targetConversation.id
          )
        };
      });

      throw nextError;
    }

    setChatState((previousState) => {
      const hasConversation = previousState.conversations.some(
        (conversation) => conversation.id === targetConversation.id
      );
      const baseConversations = hasConversation
        ? previousState.conversations
        : [targetConversation, ...previousState.conversations];

      return {
        ...previousState,
        activeConversationId: targetConversation.id,
        conversations: baseConversations.map((conversation) =>
          conversation.id === targetConversation.id
            ? {
                ...conversation,
                zipContext: {
                  ...zipContext,
                  pendingAttachment: true
                },
                updatedAt: new Date().toISOString()
              }
            : conversation
        )
      };
    });
  }

  return {
    activeConversation,
    activeConversationId: chatState.activeConversationId,
    addFiles(files) {
      const acceptedFiles = files.slice(0, Math.max(0, 10 - stagedFiles.length)).filter((file) => {
        const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
        return file.size > 0 && file.size <= 100 * 1024 * 1024 && ALLOWED_ATTACHMENT_EXTENSIONS.has(extension);
      });
      const attachments = acceptedFiles.map((file) => ({
          id: createId("attachment"),
          file,
          name: file.name,
          type: inferAttachmentType(file),
          size: file.size,
          uploadStatus: "hashing" as const,
          uploadProgress: 2
        }));
      setStagedFiles((previousFiles) => [...previousFiles, ...attachments]);
      if (acceptedFiles.length !== files.length) setError("每次最多 10 个附件，单个文件不能超过 100 MB，空文件无法上传。");
      for (const attachment of attachments) {
        void uploadFileResumably(attachment.file, (progress) => {
          setStagedFiles((current) => current.map((item) => item.id === attachment.id ? {
            ...item, uploadStatus: progress.status, uploadProgress: progress.progress,
            uploadId: progress.uploadId, uploadError: progress.error, deduplicated: progress.deduplicated
          } : item));
        });
      }
    },
    clearFiles() {
      setStagedFiles([]);
    },
    retryFile(attachmentId) {
      const attachment = stagedFiles.find((item) => item.id === attachmentId);
      if (!attachment) return;
      void uploadFileResumably(attachment.file, (progress) => {
        setStagedFiles((current) => current.map((item) => item.id === attachmentId ? {
          ...item, uploadStatus: progress.status, uploadProgress: progress.progress,
          uploadId: progress.uploadId, uploadError: progress.error, deduplicated: progress.deduplicated
        } : item));
      });
    },
    clearNotification() {
      setNotificationMessage(null);
    },
    conversations: chatState.conversations,
    async createConversationFromTemplate(template: AnalysisTemplate | null) {
      const created = await createConversationApi({
        title: template?.name ?? "新安全分析",
        ...(template ? { templateId: template.id } : {})
      });
      const local: LocalConversation = {
        ...createLocalConversation(created.title), id: String(created.id), title: created.title,
        isPinned: created.is_pinned ?? false, isArchived: created.is_archived ?? false,
        caseStatus: created.case_status ?? "open", severity: created.severity ?? "unknown",
        assignee: created.assignee ?? null, tags: created.tags ?? [], caseSummary: created.case_summary ?? null,
        analysisTemplate: created.analysis_config ?? template,
        createdAt: created.created_at, updatedAt: created.updated_at, messages: []
      };
      setChatState(previous => ({ ...previous, conversations: [local, ...previous.conversations], activeConversationId: local.id }));
      return local;
    },
    deleteConversation(conversationId) {
      if (isRemoteConversationId(conversationId)) {
        void deleteConversationApi(conversationId).catch((nextError) => {
          setError(nextError instanceof Error ? nextError.message : "Failed to delete conversation.");
        });
      }

      setChatState((previousState) => {
        const nextConversations = previousState.conversations.filter(
          (conversation) => conversation.id !== conversationId
        );

        return {
          ...previousState,
          activeConversationId:
            previousState.activeConversationId === conversationId
              ? null
              : previousState.activeConversationId,
          conversations: nextConversations
        };
      });
    },
    renameConversation(conversationId, title) {
      return updateConversationMetadata(conversationId, { title: title.trim() });
    },
    setConversationPinned(conversationId, pinned) {
      return updateConversationMetadata(conversationId, { isPinned: pinned });
    },
    setConversationArchived(conversationId, archived) {
      return updateConversationMetadata(conversationId, { isArchived: archived });
    },
    updateCaseMetadata(conversationId, metadata) {
      return updateConversationMetadata(conversationId, metadata);
    },
    error,
    isGenerating,
    notificationMessage,
    removeFile(attachmentId) {
      setStagedFiles((previousFiles) =>
        previousFiles.filter((attachment) => attachment.id !== attachmentId)
      );
    },
    removePendingZipContext() {
      setChatState((previousState) => {
        if (!previousState.activeConversationId) {
          return previousState;
        }

        return {
          ...previousState,
          conversations: previousState.conversations.map((conversation) =>
            conversation.id === previousState.activeConversationId
              ? {
                  ...conversation,
                  zipContext: undefined,
                  updatedAt: new Date().toISOString()
                }
              : conversation
          )
        };
      });
    },
    runtimeStatus,
    sendMessage,
    runConversationSkill,
    stopGeneration,
    submitCapeCase,
    refreshCapeCase,
    setWebSearchEnabled,
    uploadZip,
    setActiveConversationId(conversationId) {
      setChatState((previousState) => ({
        ...previousState,
        activeConversationId: conversationId
      }));
    },
    setModelId(modelId) {
      setChatState((previousState) => ({
        ...previousState,
        settings: {
          ...previousState.settings,
          modelId
        }
      }));
    },
    updateSettings(nextSettings) {
      setChatState((previousState) => ({
        ...previousState,
        settings: {
          ...previousState.settings,
          ...nextSettings
        }
      }));
    },
    stagedFiles,
    settings: chatState.settings,
    webSearchEnabled
  };
}

function isRemoteConversationId(value: string): boolean {
  return /^\d+$/.test(value);
}
