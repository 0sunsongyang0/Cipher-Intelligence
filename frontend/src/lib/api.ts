import {
  DEFAULT_DEEPSEEK_MODEL_ID,
  type AdminInviteCreateRequest,
  type AdminInviteItem,
  type AdminInviteListResponse,
  type AdminFileCacheClearResult,
  type AdminOverview,
  type AdminPrompt,
  type AdminPromptMutationResult,
  type ConversationApiItem,
  type ConversationApiListResponse,
  type ConversationImportResult,
  type DeepSeekModelId,
  type MessageApiListResponse,
  type OutboundChatMessage,
  type SessionStatus,
  type UploadZipResult
} from "../types";

type ErrorPayload = {
  detail?: string | Array<{ msg?: string }>;
};

function normalizeErrorText(text: string): string {
  return text.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function mapGatewayErrorMessage(response: Response, rawText: string): string | null {
  const normalizedText = rawText.toLowerCase();

  if (
    response.status === 524 ||
    ((response.status === 504 || response.status === 522) &&
      normalizedText.includes("cloudflare"))
  ) {
    return "服务器处理超时了，请稍等一下再试。";
  }

  if (response.status === 504) {
    return "服务器响应超时了，请稍后重试。";
  }

  if (response.status === 522) {
    return "服务器暂时连不上，请稍后重试。";
  }

  if (response.status === 523) {
    return "服务器地址暂时不可用，请稍后重试。";
  }

  if (
    normalizedText.includes("error code 524") ||
    normalizedText.includes("a timeout occurred") ||
    (normalizedText.includes("cloudflare") && normalizedText.includes("timed out"))
  ) {
    return "服务器处理超时了，请稍等一下再试。";
  }

  return null;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.clone().json()) as ErrorPayload;
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }

    if (Array.isArray(payload.detail)) {
      const firstMessage = payload.detail.find(
        (item) => typeof item?.msg === "string" && item.msg.trim()
      )?.msg;

      if (firstMessage) {
        return firstMessage;
      }
    }
  } catch {
    try {
      const rawText = await response.text();
      const mappedMessage = mapGatewayErrorMessage(response, rawText);

      if (mappedMessage) {
        return mappedMessage;
      }

      const text = normalizeErrorText(rawText);
      if (text) {
        return text.length > 240 ? `${text.slice(0, 237)}...` : text;
      }
    } catch {
      return "Request failed. Please try again.";
    }
  }

  return "Request failed. Please try again.";
}

function toRequestError(error: unknown): Error {
  if (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  ) {
    return new Error("Request was interrupted before the server responded.");
  }

  if (error instanceof Error) {
    if (error instanceof TypeError) {
      return new Error(
        "Unable to reach the server. Please check whether the backend is running and reachable."
      );
    }

    return error;
  }

  return new Error("Request failed. Please try again.");
}

export async function checkSession(): Promise<SessionStatus> {
  let response: Response;

  try {
    response = await fetch("/api/auth/session", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (response.status === 401) {
    return { authenticated: false, user: null };
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as SessionStatus;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export async function login(payload: {
  username: string;
  password: string;
}): Promise<SessionStatus> {
  let response: Response;

  try {
    response = await fetch("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as SessionStatus;
}

export async function register(payload: {
  username: string;
  password: string;
  inviteCode: string;
}): Promise<SessionStatus> {
  let response: Response;

  try {
    response = await fetch("/api/auth/register", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as SessionStatus;
}

export async function logout(): Promise<void> {
  let response: Response;

  try {
    response = await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function getAdminOverview(): Promise<AdminOverview> {
  let response: Response;

  try {
    response = await fetch("/api/admin/overview", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminOverview;
}

export async function controlAdminService(
  target: "backend" | "tunnel",
  action: "start" | "stop"
): Promise<void> {
  let response: Response;

  try {
    response = await fetch(`/api/admin/services/${target}/${action}`, {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function clearAdminFileCache(): Promise<AdminFileCacheClearResult> {
  let response: Response;

  try {
    response = await fetch("/api/admin/files/cache/clear", {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminFileCacheClearResult;
}

export async function getAdminPrompt(): Promise<AdminPrompt> {
  let response: Response;

  try {
    response = await fetch("/api/admin/prompt", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminPrompt;
}

export async function saveAdminPrompt(prompt: string): Promise<AdminPromptMutationResult> {
  let response: Response;

  try {
    response = await fetch("/api/admin/prompt", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ prompt })
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminPromptMutationResult;
}

export async function resetAdminPrompt(): Promise<AdminPromptMutationResult> {
  let response: Response;

  try {
    response = await fetch("/api/admin/prompt/reset", {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminPromptMutationResult;
}

export async function getAdminInvites(): Promise<AdminInviteListResponse> {
  let response: Response;

  try {
    response = await fetch("/api/admin/invites", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminInviteListResponse;
}

export async function createAdminInvite(payload: AdminInviteCreateRequest): Promise<AdminInviteItem> {
  let response: Response;

  try {
    response = await fetch("/api/admin/invites", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminInviteItem;
}

export async function toggleAdminInvite(inviteId: number): Promise<AdminInviteItem> {
  let response: Response;

  try {
    response = await fetch(`/api/admin/invites/${inviteId}/toggle`, {
      method: "POST",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as AdminInviteItem;
}

export async function deleteAdminInvite(inviteId: number): Promise<void> {
  let response: Response;

  try {
    response = await fetch(`/api/admin/invites/${inviteId}`, {
      method: "DELETE",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function listConversations(): Promise<ConversationApiListResponse> {
  let response: Response;

  try {
    response = await fetch("/api/conversations", {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as ConversationApiListResponse;
}

export async function createConversation(payload: { title: string }): Promise<ConversationApiItem> {
  let response: Response;

  try {
    response = await fetch("/api/conversations", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as ConversationApiItem;
}

export async function getConversationMessages(
  conversationId: string
): Promise<MessageApiListResponse> {
  let response: Response;

  try {
    response = await fetch(`/api/conversations/${conversationId}/messages`, {
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as MessageApiListResponse;
}

export async function deleteConversation(conversationId: string): Promise<void> {
  let response: Response;

  try {
    response = await fetch(`/api/conversations/${conversationId}`, {
      method: "DELETE",
      credentials: "include"
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function importConversation(payload: {
  title: string;
  messages: OutboundChatMessage[];
}): Promise<ConversationImportResult> {
  let response: Response;

  try {
    response = await fetch("/api/conversations/import", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(payload)
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as ConversationImportResult;
}

export async function streamChat(
  messages: OutboundChatMessage[],
  files: File[] = [],
  model: DeepSeekModelId = DEFAULT_DEEPSEEK_MODEL_ID,
  scope?: {
    conversationId?: string;
    zipContextId?: string;
    webSearch?: boolean;
  }
): Promise<ReadableStream<Uint8Array>> {
  let response: Response;

  try {
    response = await fetch("/api/chat", {
      method: "POST",
      credentials: "include",
      ...(files.length > 0
        ? {
            body: (() => {
              const formData = new FormData();

              formData.append(
                "messages",
                JSON.stringify({
                  messages,
                  model,
                  ...(scope?.conversationId ? { conversationId: scope.conversationId } : {}),
                  ...(scope?.zipContextId ? { zipContextId: scope.zipContextId } : {}),
                  ...(scope?.webSearch ? { webSearch: true } : {})
                })
              );

              for (const file of files) {
                formData.append("files", file);
              }

              return formData;
            })()
          }
        : {
            headers: {
              "Content-Type": "application/json"
            },
            body: JSON.stringify({
              messages,
              model,
              ...(scope?.conversationId ? { conversationId: scope.conversationId } : {}),
              ...(scope?.zipContextId ? { zipContextId: scope.zipContextId } : {}),
              ...(scope?.webSearch ? { webSearch: true } : {})
            })
          })
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  if (response.body === null) {
    throw new Error("Chat response did not include a readable stream.");
  }

  return response.body;
}

export async function uploadZip(
  file: File,
  payload: { conversationId: string; model: DeepSeekModelId }
): Promise<UploadZipResult> {
  let response: Response;

  try {
    const formData = new FormData();
    formData.append("conversationId", payload.conversationId);
    formData.append("model", payload.model);
    formData.append("file", file);

    response = await fetch("/api/upload_zip", {
      method: "POST",
      credentials: "include",
      body: formData
    });
  } catch (error) {
    throw toRequestError(error);
  }

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const result = (await response.json()) as UploadZipResult;
  if (!result.uploading) {
    return result;
  }

  const deadline = Date.now() + 120_000;
  while (Date.now() < deadline) {
    await delay(500);

    let statusResponse: Response;
    try {
      statusResponse = await fetch(
        `/api/upload_zip/${encodeURIComponent(result.zipContextId)}?conversationId=${encodeURIComponent(payload.conversationId)}&model=${encodeURIComponent(payload.model)}`,
        {
          credentials: "include"
        }
      );
    } catch (error) {
      throw toRequestError(error);
    }

    if (!statusResponse.ok) {
      throw new Error(await readErrorMessage(statusResponse));
    }

    const statusResult = (await statusResponse.json()) as UploadZipResult;
    if (statusResult.uploading) {
      continue;
    }

    if (statusResult.errorMessage) {
      throw new Error(statusResult.errorMessage);
    }

    return statusResult;
  }

  throw new Error("ZIP 解析耗时过长，请稍后重试。");
}
