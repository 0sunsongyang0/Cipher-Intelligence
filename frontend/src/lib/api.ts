import type { OutboundChatMessage } from "../types";

type SessionStatus = {
  authenticated: boolean;
};

type ErrorPayload = {
  detail?: string | Array<{ msg?: string }>;
};

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as ErrorPayload;
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
    return "Request failed. Please try again.";
  }

  return "Request failed. Please try again.";
}

function toRequestError(error: unknown): Error {
  if (error instanceof Error) {
    if (error.name === "AbortError") {
      return new Error("Request was interrupted before the server responded.");
    }

    if (error instanceof TypeError) {
      return new Error(
        "Unable to reach the server. Please check whether the backend is running and reachable."
      );
    }

    return error;
  }

  return new Error("Request failed. Please try again.");
}

export async function checkSession(): Promise<boolean> {
  const response = await fetch("/api/auth/session", {
    credentials: "include"
  });

  if (!response.ok) {
    return false;
  }

  const payload = (await response.json()) as SessionStatus;
  return payload.authenticated;
}

export async function login(password: string): Promise<void> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ password })
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function logout(): Promise<void> {
  const response = await fetch("/api/auth/logout", {
    method: "POST",
    credentials: "include"
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
}

export async function streamChat(
  messages: OutboundChatMessage[],
  files: File[] = []
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

              formData.append("messages", JSON.stringify({ messages }));

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
            body: JSON.stringify({ messages })
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
