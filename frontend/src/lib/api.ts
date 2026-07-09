import {
  DEFAULT_DEEPSEEK_MODEL_ID,
  type AdminFileCacheClearResult,
  type AdminOverview,
  type AdminPrompt,
  type AdminPromptMutationResult,
  type DeepSeekModelId,
  type OutboundChatMessage,
  type SessionStatus,
  type UploadZipResult
} from "../types";

type ErrorPayload = {
  detail?: string | Array<{ msg?: string }>;
};

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
      const text = (await response.text()).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
      if (text) {
        return text;
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

  return (await response.json()) as UploadZipResult;
}
