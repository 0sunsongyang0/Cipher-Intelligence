import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  ChatCompletionChunk,
  ChatCompletionMessageParam,
  MLCEngineInterface
} from "@mlc-ai/web-llm";

import { createWebLlmEngine } from "../lib/webllm";
import { loadChatState, saveChatState } from "../lib/storage";
import type {
  LocalChatMessage,
  LocalConversation,
  StoredChatState,
  WebLlmInitProgress,
  WebLlmSettings
} from "../types";

type RuntimeStatus = "idle" | "loading" | "ready" | "error";

type UseWebLLMChatResult = {
  activeConversation: LocalConversation | null;
  activeConversationId: string | null;
  conversations: LocalConversation[];
  error: string | null;
  initializeEngine: () => Promise<void>;
  initProgress: WebLlmInitProgress | null;
  isGenerating: boolean;
  runtimeStatus: RuntimeStatus;
  sendMessage: (content: string) => Promise<void>;
  setActiveConversationId: (conversationId: string | null) => void;
  settings: WebLlmSettings;
};

const DEFAULT_SETTINGS: WebLlmSettings = {
  modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
  systemPrompt: "You are a helpful assistant."
};

const DEFAULT_CHAT_STATE: StoredChatState = {
  activeConversationId: null,
  conversations: [],
  settings: DEFAULT_SETTINGS
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

function buildPromptMessages(
  settings: WebLlmSettings,
  messages: LocalChatMessage[]
): ChatCompletionMessageParam[] {
  const promptMessages: ChatCompletionMessageParam[] = [];

  if (settings.systemPrompt.trim()) {
    promptMessages.push({
      role: "system",
      content: settings.systemPrompt
    });
  }

  for (const message of messages) {
    if (message.role === "system") {
      promptMessages.push({
        role: "system",
        content: message.content
      });
      continue;
    }

    if (message.role === "user") {
      promptMessages.push({
        role: "user",
        content: message.content
      });
      continue;
    }

    promptMessages.push({
      role: "assistant",
      content: message.content
    });
  }

  return promptMessages;
}

function readChunkContent(chunk: ChatCompletionChunk): string {
  return chunk.choices
    .map((choice) => choice.delta.content ?? "")
    .join("");
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

export function useWebLLMChat(): UseWebLLMChatResult {
  const [chatState, setChatState] = useState<StoredChatState>(() =>
    loadChatState(DEFAULT_CHAT_STATE) ?? DEFAULT_CHAT_STATE
  );
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus>("idle");
  const [initProgress, setInitProgress] = useState<WebLlmInitProgress | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const engineRef = useRef<MLCEngineInterface | null>(null);
  const initInFlightRef = useRef<Promise<void> | null>(null);
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

  const initializeEngine = useCallback(async () => {
    if (engineRef.current !== null) {
      return;
    }

    if (initInFlightRef.current !== null) {
      return initInFlightRef.current;
    }

    setError(null);
    setRuntimeStatus("loading");

    const initPromise = (async () => {
      try {
        const engine = await createWebLlmEngine(
          chatStateRef.current.settings.modelId,
          (progress) => {
            setInitProgress(progress);
          }
        );

        engineRef.current = engine as MLCEngineInterface;
        setRuntimeStatus("ready");
      } catch (nextError) {
        setRuntimeStatus("error");
        setError(nextError instanceof Error ? nextError.message : "Failed to initialize WebLLM.");
        throw nextError;
      } finally {
        initInFlightRef.current = null;
      }
    })();

    initInFlightRef.current = initPromise;
    return initPromise;
  }, []);

  async function sendMessage(content: string) {
    const normalizedContent = content.trim();

    if (!normalizedContent) {
      return;
    }

    const engine = engineRef.current;
    if (engine === null) {
      throw new Error("WebLLM engine is not initialized.");
    }

    if (generationInFlightRef.current) {
      throw new Error("Chat generation is already in progress.");
    }

    generationInFlightRef.current = true;
    setError(null);
    setIsGenerating(true);

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

    try {
      const stream = await engine.chat.completions.create({
        stream: true,
        messages: buildPromptMessages(currentState.settings, conversationMessages)
      });

      let assistantContent = "";

      for await (const chunk of stream as AsyncIterable<ChatCompletionChunk>) {
        const delta = readChunkContent(chunk);
        if (!delta) {
          continue;
        }

        assistantContent += delta;

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
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "Failed to generate response.");
      throw nextError;
    } finally {
      generationInFlightRef.current = false;
      setIsGenerating(false);
    }
  }

  return {
    activeConversation,
    activeConversationId: chatState.activeConversationId,
    conversations: chatState.conversations,
    error,
    initializeEngine,
    initProgress,
    isGenerating,
    runtimeStatus,
    sendMessage,
    setActiveConversationId(conversationId) {
      setChatState((previousState) => ({
        ...previousState,
        activeConversationId: conversationId
      }));
    },
    settings: chatState.settings
  };
}
