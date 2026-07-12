import { useEffect, useMemo, useRef, useState } from "react";

import {
  createConversation as createConversationApi,
  deleteConversation as deleteConversationApi,
  getConversationMessages,
  importConversation as importConversationApi,
  listConversations,
  streamChat,
  uploadZip as uploadZipApi
} from "../lib/api";
import { loadChatState, saveChatState } from "../lib/storage";
import type {
  DeepSeekModelId,
  LocalChatMessage,
  LocalConversation,
  MessageAttachment,
  OutboundChatMessage,
  PersistedChatState,
  RuntimeStatus,
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
  clearFiles: () => void;
  deleteConversation: (conversationId: string) => void;
  error: string | null;
  isGenerating: boolean;
  addFiles: (files: File[]) => void;
  removeFile: (attachmentId: string) => void;
  removePendingZipContext?: () => void;
  runtimeStatus: RuntimeStatus;
  sendMessage: (content: string) => Promise<void>;
  setWebSearchEnabled: (enabled: boolean) => void;
  uploadZip: (file: File, prompt: string) => Promise<void>;
  setActiveConversationId: (conversationId: string | null) => void;
  setModelId: (modelId: DeepSeekModelId) => void;
  stagedFiles: StagedAttachment[];
  settings: PersistedChatState["settings"];
  webSearchEnabled: boolean;
};

const DEFAULT_CHAT_STATE: PersistedChatState = {
  activeConversationId: null,
  conversations: [],
  settings: {
    systemPrompt: "You are a helpful assistant."
  }
};

const MISSING_ZIP_CONTEXT_ERROR = "ZIP 上下文不存在或已过期，请重新上传压缩包。";
const STREAM_KEEPALIVE_MARKER = "\u001e__CIPHER_KEEPALIVE__\u001e";
const STREAM_ERROR_PREFIX = "\u001e__CIPHER_ERROR__:";
const STREAM_MARKER_SUFFIX = "\u001e";

function parseStreamPayload(text: string): { content: string; error: string | null } {
  let content = text.split(STREAM_KEEPALIVE_MARKER).join("");
  let error: string | null = null;

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

  return { content, error };
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
  const [webSearchEnabled, setWebSearchEnabled] = useState(false);

  const chatStateRef = useRef(chatState);
  const generationInFlightRef = useRef(false);
  const hydratedFromCloudRef = useRef(false);

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
                : {})
            }));

            return {
              id: String(conversation.id),
              title: conversation.title,
              createdAt: conversation.created_at,
              updatedAt: conversation.updated_at,
              messages: mergeRemoteMessagesWithLocalAttachments(
                remoteMessages,
                localConversation?.messages ?? []
              )
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
    const filesForRequest = regularStagedFilesForRequest.map((attachment) => attachment.file);
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
          ...(currentZipContextId ? { zipContextId: currentZipContextId } : {})
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
                    content: assistantContent
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
                    content: assistantContent
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
      generationInFlightRef.current = false;
      setIsGenerating(false);
    }
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
      setStagedFiles((previousFiles) => [
        ...previousFiles,
        ...files.map((file) => ({
          id: createId("attachment"),
          file,
          name: file.name,
          type: inferAttachmentType(file),
          size: file.size
        }))
      ]);
    },
    clearFiles() {
      setStagedFiles([]);
    },
    conversations: chatState.conversations,
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
    error,
    isGenerating,
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
    stagedFiles,
    settings: chatState.settings
    ,
    webSearchEnabled
  };
}

function isRemoteConversationId(value: string): boolean {
  return /^\d+$/.test(value);
}

