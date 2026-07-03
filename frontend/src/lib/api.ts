import type { Conversation, Message } from "../types";

type SessionStatus = {
  authenticated: boolean;
};

type ConversationListResponse = {
  items: Conversation[];
};

type MessageListResponse = {
  items: Message[];
};

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    return "请求失败，请稍后重试。";
  }

  return "请求失败，请稍后重试。";
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

export async function fetchConversations(): Promise<Conversation[]> {
  const response = await fetch("/api/conversations", {
    credentials: "include"
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const payload = (await response.json()) as ConversationListResponse;
  return payload.items;
}

export async function createConversation(title: string): Promise<Conversation> {
  const response = await fetch("/api/conversations", {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ title })
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as Conversation;
}

export async function fetchMessages(conversationId: number): Promise<Message[]> {
  const response = await fetch(`/api/conversations/${conversationId}/messages`, {
    credentials: "include"
  });

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  const payload = (await response.json()) as MessageListResponse;
  return payload.items;
}
