import { useEffect, useMemo, useRef, useState } from "react";

import { streamChat } from "../lib/api";
import { loadChatState, saveChatState } from "../lib/storage";
import type {
  LocalChatMessage,
  LocalConversation,
  OutboundChatMessage,
  PersistedChatState,
  RuntimeStatus,
  StagedAttachment
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
  runtimeStatus: RuntimeStatus;
  sendMessage: (content: string) => Promise<void>;
  setActiveConversationId: (conversationId: string | null) => void;
  stagedFiles: StagedAttachment[];
  settings: PersistedChatState["settings"];
};

const DEFAULT_CHAT_STATE: PersistedChatState = {
  activeConversationId: null,
  conversations: [],
  settings: {
    systemPrompt: "You are a helpful assistant."
  }
};

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

function inferAttachmentType(file: File): string {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";

  if (extension === "pdf") {
    return "PDF";
  }

  if (extension === "docx") {
    return "DOCX";
  }

  if (["png", "jpg", "jpeg", "webp", "bmp", "gif"].includes(extension)) {
    return "Image";
  }

  return "Text";
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

function buildOutboundMessages(
  settings: PersistedChatState["settings"],
  messages: LocalChatMessage[]
): OutboundChatMessage[] {
  const outboundMessages: OutboundChatMessage[] = [];

  if (settings.systemPrompt.trim()) {
    outboundMessages.push({
      role: "system",
      content: settings.systemPrompt
    });
  }

  for (const message of messages) {
    outboundMessages.push({
      role: message.role,
      content: message.content
    });
  }

  return outboundMessages;
}

export function useServerChat(): UseServerChatResult {
  const [chatState, setChatState] = useState<PersistedChatState>(() =>
    loadChatState(DEFAULT_CHAT_STATE) ?? DEFAULT_CHAT_STATE
  );
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>("ready");
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stagedFiles, setStagedFiles] = useState<StagedAttachment[]>([]);

  const chatStateRef = useRef(chatState);
  const generationInFlightRef = useRef(false);

  useEffect(() => {
    chatStateRef.current = chatState;
    saveChatState(chatState);
  }, [chatState]);

  const activeConversation = useMemo(
    () =>
      chatState.activeConversationId === null
        ? null
        : chatState.conversations.find(
            (conversation) => conversation.id === chatState.activeConversationId
          ) ?? null,
    [chatState.activeConversationId, chatState.conversations]
  );

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

    const targetConversation = existingConversation ?? createLocalConversation(normalizedContent);
    const userMessage = createMessage("user", normalizedContent);
    const assistantMessage = createMessage("assistant", "");
    const conversationMessages = [...targetConversation.messages, userMessage];
    const nextMessages = [...conversationMessages, assistantMessage];
    const stagedFilesForRequest = stagedFiles;
    const filesForRequest = stagedFilesForRequest.map((attachment) => attachment.file);

    setStagedFiles([]);

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
        conversations: appendMessages(
          baseConversations,
          targetConversation.id,
          nextMessages
        )
      };
    });

    let assistantContent = "";

    try {
      const stream = await streamChat(
        buildOutboundMessages(currentState.settings, conversationMessages),
        filesForRequest
      );
      const reader = stream.getReader();
      const decoder = new TextDecoder();

      while (true) {
        const { done, value } = await reader.read();

        if (done) {
          break;
        }

        assistantContent += decoder.decode(value, { stream: true });

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
      }

      const remainingContent = decoder.decode();

      if (remainingContent) {
        assistantContent += remainingContent;

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
      }

      setRuntimeStatus("ready");
    } catch (nextError) {
      setStagedFiles((previousFiles) => [...stagedFilesForRequest, ...previousFiles]);
      setRuntimeStatus("error");
      setError(nextError instanceof Error ? nextError.message : "Failed to generate response.");
    } finally {
      generationInFlightRef.current = false;
      setIsGenerating(false);
    }
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
    runtimeStatus,
    sendMessage,
    setActiveConversationId(conversationId) {
      setChatState((previousState) => ({
        ...previousState,
        activeConversationId: conversationId
      }));
    },
    stagedFiles,
    settings: chatState.settings
  };
}
