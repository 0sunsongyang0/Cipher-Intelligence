type SessionStatus = {
  authenticated: boolean;
};

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: string };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    return "Request failed. Please try again.";
  }

  return "Request failed. Please try again.";
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
