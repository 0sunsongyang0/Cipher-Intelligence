import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import type { OutboundChatMessage } from "../types";

describe("api auth helpers", () => {
  it("loads the public Casdoor provider configuration", async () => {
    const config = {
      enabled: true,
      provider: "casdoor" as const,
      displayName: "Cipher SSO"
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(config), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(api.getCasdoorAuthConfig()).resolves.toEqual(config);
    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/casdoor/config", {
      credentials: "include"
    });
  });

  it("returns an anonymous session payload when the session endpoint returns 401", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 401 })
    );

    await expect(api.checkSession()).resolves.toEqual({ authenticated: false, user: null });
    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/session", {
      credentials: "include"
    });
  });

  it("throws backend detail when the session endpoint returns a server error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "session backend unavailable" }), {
        status: 500,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(api.checkSession()).rejects.toThrow("session backend unavailable");
  });

  it("posts username and password for login", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          authenticated: true,
          user: { id: 1, username: "alice", isAdmin: false }
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(api.login({ username: "alice", password: "StrongPass123!" })).resolves.toEqual({
      authenticated: true,
      user: { id: 1, username: "alice", isAdmin: false }
    });

    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/login", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ username: "alice", password: "StrongPass123!" })
    });
  });

  it("posts registration payload with invite code", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          authenticated: true,
          user: { id: 2, username: "new-user", isAdmin: false }
        }),
        {
          status: 201,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(
      api.register({
        username: "new-user",
        password: "StrongPass123!",
        inviteCode: "SMBU@2014520uu-"
      })
    ).resolves.toEqual({
      authenticated: true,
      user: { id: 2, username: "new-user", isAdmin: false }
    });

    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/register", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        username: "new-user",
        password: "StrongPass123!",
        inviteCode: "SMBU@2014520uu-"
      })
    });
  });

  it("throws the backend detail when login fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "bad password" }), {
        status: 401,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(api.login({ username: "alice", password: "wrong" })).rejects.toThrow("bad password");
  });

  it("patches account profile changes without sending a mutable username", async () => {
    const updatedUser = {
      id: 1,
      username: "alice",
      displayName: "Threat Hunter",
      avatarUrl: null,
      isAdmin: false
    };
    const overview = {
      user: updatedUser,
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor" as const,
        providerName: "Cipher SSO",
        email: "hunter@example.test",
        emailVerified: false,
        connectedAccounts: [],
        mfaEnabled: false,
        passwordEnabled: true,
        lastSignInAt: null,
        lastSyncedAt: "2026-08-06T08:00:00Z",
        syncStatus: "current" as const,
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(
      api.updateAccountProfile({
        displayName: "Threat Hunter",
        email: "hunter@example.test",
        removeAvatar: true
      })
    ).resolves.toEqual(overview);

    expect(fetchSpy).toHaveBeenCalledWith("/api/account/profile", {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        displayName: "Threat Hunter",
        email: "hunter@example.test",
        removeAvatar: true
      })
    });
  });

  it("reloads the account overview when an older profile endpoint returns a flat user", async () => {
    const legacyUser = {
      id: 1,
      username: "alice",
      displayName: "Threat Hunter",
      avatarUrl: null,
      isAdmin: false
    };
    const overview = {
      user: legacyUser,
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor" as const,
        providerName: "Cipher SSO",
        email: "hunter@example.test",
        emailVerified: false,
        connectedAccounts: [],
        mfaEnabled: false,
        passwordEnabled: true,
        lastSignInAt: null,
        lastSyncedAt: "2026-08-06T08:00:00Z",
        syncStatus: "current" as const,
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify(legacyUser), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify(overview), {
          status: 200,
          headers: { "Content-Type": "application/json" }
        })
      );

    await expect(
      api.updateAccountProfile({ displayName: "Threat Hunter" })
    ).resolves.toEqual(overview);

    expect(fetchSpy).toHaveBeenNthCalledWith(1, "/api/account/profile", {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ displayName: "Threat Hunter" })
    });
    expect(fetchSpy).toHaveBeenNthCalledWith(2, "/api/account", {
      credentials: "include"
    });
  });

  it("loads the synchronized account overview", async () => {
    const overview = {
      user: { id: 1, username: "alice", displayName: "Alice", avatarUrl: null, isAdmin: false },
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: true,
        connectedAccounts: [{ provider: "github", label: "GitHub" }],
        mfaEnabled: true,
        passwordEnabled: true,
        lastSignInAt: null,
        lastSyncedAt: "2026-08-06T08:00:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(api.getAccountOverview()).resolves.toEqual(overview);
    expect(fetchSpy).toHaveBeenCalledWith("/api/account", { credentials: "include" });
  });

  it("requests a fresh Casdoor account sync", async () => {
    const overview = {
      user: { id: 1, username: "alice", displayName: "Alice", avatarUrl: null, isAdmin: false },
      workspaceAvatarUrl: null,
      identityAvatarUrl: null,
      identity: {
        source: "casdoor",
        providerName: "Cipher SSO",
        email: "alice@example.test",
        emailVerified: true,
        connectedAccounts: [],
        mfaEnabled: false,
        passwordEnabled: true,
        lastSignInAt: null,
        lastSyncedAt: "2026-08-06T08:00:00Z",
        syncStatus: "current",
        syncAvailable: true,
        managementUrl: "https://login.example.test/account"
      }
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(overview), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(api.syncAccount()).resolves.toEqual(overview);
    expect(fetchSpy).toHaveBeenCalledWith("/api/account/sync", {
      method: "POST",
      credentials: "include"
    });
  });

  it("requests an account email verification message", async () => {
    const result = {
      email: "alice@example.test",
      sent: true,
      message: "验证邮件已发送，请查看邮箱。"
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(result), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(api.sendAccountEmailVerification()).resolves.toEqual(result);
    expect(fetchSpy).toHaveBeenCalledWith("/api/account/email-verification", {
      method: "POST",
      credentials: "include"
    });
  });

  it("posts to the logout endpoint with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 })
    );

    await expect(api.logout()).resolves.toBeUndefined();
    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/logout", {
      method: "POST",
      credentials: "include"
    });
  });

  it.each([
    ["checkSession", () => api.checkSession()],
    ["login", () => api.login({ username: "alice", password: "StrongPass123!" })],
    [
      "register",
      () =>
        api.register({
          username: "new-user",
          password: "StrongPass123!",
          inviteCode: "invite-code"
        })
    ],
    ["logout", () => api.logout()]
  ])("normalizes network failures for %s", async (_name, request) => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(request()).rejects.toThrow(
      "Unable to reach the server. Please check whether the backend is running and reachable."
    );
  });

  it.each([
    ["checkSession", () => api.checkSession()],
    ["login", () => api.login({ username: "alice", password: "StrongPass123!" })],
    [
      "register",
      () =>
        api.register({
          username: "new-user",
          password: "StrongPass123!",
          inviteCode: "invite-code"
        })
    ],
    ["logout", () => api.logout()]
  ])("normalizes aborted requests for %s", async (_name, request) => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new DOMException("Aborted", "AbortError"));

    await expect(request()).rejects.toThrow(
      "Request was interrupted before the server responded."
    );
  });

  it("parses the admin overview payload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            services: {
              backend: { running: true },
              tunnel: { running: false },
              autostartEnabled: true
            },
            access: {
              localUrl: "http://127.0.0.1:8000/chat",
              publicUrl: "https://chat.example.invalid/chat"
            },
            models: { providers: [] },
            files: { uploadLimit: 10, zipEnabled: true, zipContextCount: 0 }
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json"
            }
          }
        )
      )
    );

    const payload = await api.getAdminOverview();

    expect(payload.files.uploadLimit).toBe(10);
    expect(payload.services.backend.running).toBe(true);
  });

  it("posts admin service controls with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 })
    );

    await expect(api.controlAdminService("backend", "start")).resolves.toBeUndefined();
    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/services/backend/start", {
      method: "POST",
      credentials: "include"
    });
  });

  it("surfaces a clear error when the admin overview endpoint is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(api.getAdminOverview()).rejects.toThrow(
      "Unable to reach the server. Please check whether the backend is running and reachable."
    );
  });

  it("surfaces backend detail when admin service control fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "service control failed" }), {
        status: 502,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(api.controlAdminService("tunnel", "stop")).rejects.toThrow("service control failed");
  });

  it("maps an empty 503 response to a chat-service diagnostic", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 503 }));

    await expect(api.getAdminOverview()).rejects.toThrow(
      "聊天服务暂时不可用，请检查后端是否启动，以及 `backend/.env` 里的模型密钥是否已配置。"
    );
  });

  it("loads admin observability metrics with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({
        days: 7,
        requestSuccessRate: 99,
        averageResponseTimeMs: 120,
        modelFailureRate: 1,
        tokenUsage: { input: 10, output: 20, total: 30 },
        capeTaskAverageDurationMs: 2500,
        activeUsers: 3,
        events: 12
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    const payload = await api.getAdminObservability(7);

    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/observability?days=7", { credentials: "include" });
    expect(payload.tokenUsage.total).toBe(30);
  });

  it("posts zip cache clear requests with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ ok: true, cleared: 3 }), {
        status: 200,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(api.clearAdminFileCache()).resolves.toEqual({ ok: true, cleared: 3 });
    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/files/cache/clear", {
      method: "POST",
      credentials: "include"
    });
  });

  it("loads the admin prompt with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          prompt: "Default prompt",
          source: "default",
          updatedAt: null,
          status: "ready",
          message: "Prompt loaded"
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(api.getAdminPrompt()).resolves.toEqual({
      prompt: "Default prompt",
      source: "default",
      updatedAt: null,
      status: "ready",
      message: "Prompt loaded"
    });
    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/prompt", {
      credentials: "include"
    });
  });

  it("posts prompt saves with credentials and json body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          prompt: "Saved prompt",
          source: "override",
          updatedAt: "2026-07-09T10:00:00Z",
          status: "ready",
          message: "Prompt saved"
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(api.saveAdminPrompt("Saved prompt")).resolves.toEqual({
      ok: true,
      prompt: "Saved prompt",
      source: "override",
      updatedAt: "2026-07-09T10:00:00Z",
      status: "ready",
      message: "Prompt saved"
    });
    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/prompt", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ prompt: "Saved prompt" })
    });
  });

  it("posts prompt reset requests with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          ok: true,
          prompt: "Default prompt",
          source: "default",
          updatedAt: null,
          status: "ready",
          message: "Prompt reset"
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(api.resetAdminPrompt()).resolves.toEqual({
      ok: true,
      prompt: "Default prompt",
      source: "default",
      updatedAt: null,
      status: "ready",
      message: "Prompt reset"
    });
    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/prompt/reset", {
      method: "POST",
      credentials: "include"
    });
  });

  it("surfaces backend detail when loading the admin prompt fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "prompt unavailable" }), {
        status: 503,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(api.getAdminPrompt()).rejects.toThrow("prompt unavailable");
  });

  it("loads admin invites with credentials", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          items: [
            {
              id: 1,
              code: "SMBU@2014520uu-",
              label: "July batch",
              isActive: true,
              maxUses: 5,
              usedCount: 0,
              expiresAt: null,
              createdAt: "2026-07-09T10:00:00Z"
            }
          ]
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(api.getAdminInvites()).resolves.toEqual({
      items: [
        {
          id: 1,
          code: "SMBU@2014520uu-",
          label: "July batch",
          isActive: true,
          maxUses: 5,
          usedCount: 0,
          expiresAt: null,
          createdAt: "2026-07-09T10:00:00Z"
        }
      ]
    });
    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/invites", {
      credentials: "include"
    });
  });

  it("creates an admin invite with a json body", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 1,
          code: "SMBU@2014520uu-",
          label: "July batch",
          isActive: true,
          maxUses: 5,
          usedCount: 0,
          expiresAt: null,
          createdAt: "2026-07-09T10:00:00Z"
        }),
        {
          status: 201,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(
      api.createAdminInvite({
        code: "SMBU@2014520uu-",
        label: "July batch",
        maxUses: 5,
        expiresAt: null,
        isActive: true
      })
    ).resolves.toMatchObject({
      id: 1,
      code: "SMBU@2014520uu-"
    });
    expect(fetchSpy).toHaveBeenCalledWith("/api/admin/invites", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        code: "SMBU@2014520uu-",
        label: "July batch",
        maxUses: 5,
        expiresAt: null,
        isActive: true
      })
    });
  });

  it("toggles and deletes admin invites with credentials", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            id: 1,
            code: "SMBU@2014520uu-",
            label: "July batch",
            isActive: false,
            maxUses: 5,
            usedCount: 0,
            expiresAt: null,
            createdAt: "2026-07-09T10:00:00Z"
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json"
            }
          }
        )
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(api.toggleAdminInvite(1)).resolves.toMatchObject({ id: 1, isActive: false });
    await expect(api.deleteAdminInvite(1)).resolves.toBeUndefined();

    expect(fetchSpy).toHaveBeenNthCalledWith(1, "/api/admin/invites/1/toggle", {
      method: "POST",
      credentials: "include"
    });
    expect(fetchSpy).toHaveBeenNthCalledWith(2, "/api/admin/invites/1", {
      method: "DELETE",
      credentials: "include"
    });
  });
});

describe("streamChat", () => {
  it("posts full message history as JSON when no files are attached", async () => {
    const body = new ReadableStream<Uint8Array>();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200
      })
    );
    const messages: OutboundChatMessage[] = [
      {
        role: "system",
        content: "Be brief"
      },
      {
        role: "user",
        content: "Hello"
      },
      {
        role: "assistant",
        content: "Hi"
      },
      {
        role: "user",
        content: "How are you?"
      }
    ];

    await expect(api.streamChat(messages, [], "deepseek-v4-pro")).resolves.toBe(body);
    expect(fetchSpy).toHaveBeenCalledTimes(1);

    const [url, options] = fetchSpy.mock.calls[0] ?? [];

    expect(url).toBe("/api/chat");
    expect(options).toEqual({
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ messages, model: "deepseek-v4-pro" })
    });
  });

  it("includes conversation scope fields in JSON chat requests when provided", async () => {
    const body = new ReadableStream<Uint8Array>();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200
      })
    );
    const messages: OutboundChatMessage[] = [{ role: "user", content: "Hello" }];

    await expect(
      api.streamChat(messages, [], "deepseek-v4-pro", {
        conversationId: "conversation-1",
        zipContextId: "zip-context-1"
      })
    ).resolves.toBe(body);

    const [, options] = fetchSpy.mock.calls[0] ?? [];

    expect(options).toEqual({
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        messages,
        model: "deepseek-v4-pro",
        conversationId: "conversation-1",
        zipContextId: "zip-context-1"
      })
    });
  });

  it("includes the manual webSearch flag in JSON chat requests when provided", async () => {
    const body = new ReadableStream<Uint8Array>();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200
      })
    );
    const messages: OutboundChatMessage[] = [{ role: "user", content: "latest ai news" }];

    await expect(
      api.streamChat(messages, [], "deepseek-v4-pro", {
        webSearch: true
      })
    ).resolves.toBe(body);

    const [, options] = fetchSpy.mock.calls[0] ?? [];

    expect(options).toEqual({
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        messages,
        model: "deepseek-v4-pro",
        webSearch: true
      })
    });
  });

  it("posts multipart form data when files are attached", async () => {
    const body = new ReadableStream<Uint8Array>();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200
      })
    );
    const messages: OutboundChatMessage[] = [{ role: "user", content: "Summarize this file" }];
    const file = new File(["report body"], "report.txt", { type: "text/plain" });

    await expect(api.streamChat(messages, [file], "deepseek-v4-pro")).resolves.toBe(body);

    const [url, options] = fetchSpy.mock.calls[0] ?? [];

    expect(url).toBe("/api/chat");
    expect(options).toMatchObject({
      method: "POST",
      credentials: "include"
    });
    expect(options?.body).toBeInstanceOf(FormData);

    const formData = options?.body as FormData;
    expect(formData.get("messages")).toBe(JSON.stringify({ messages, model: "deepseek-v4-pro" }));
    expect(formData.get("files")).toBe(file);
  });

  it("includes conversation scope fields in multipart chat requests when provided", async () => {
    const body = new ReadableStream<Uint8Array>();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(body, {
        status: 200
      })
    );
    const messages: OutboundChatMessage[] = [{ role: "user", content: "Summarize this file" }];
    const file = new File(["report body"], "report.txt", { type: "text/plain" });

    await expect(
      api.streamChat(messages, [file], "deepseek-v4-pro", {
        conversationId: "conversation-1",
        zipContextId: "zip-context-1"
      })
    ).resolves.toBe(body);

    const [, options] = fetchSpy.mock.calls[0] ?? [];
    const formData = options?.body as FormData;

    expect(formData.get("messages")).toBe(
      JSON.stringify({
        messages,
        model: "deepseek-v4-pro",
        conversationId: "conversation-1",
        zipContextId: "zip-context-1"
      })
    );
    expect(formData.get("files")).toBe(file);
  });

  it("throws backend detail when streaming request fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "session expired" }), {
        status: 401,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(api.streamChat([{ role: "user", content: "Hello" }])).rejects.toThrow(
      "session expired"
    );
  });

  it("maps Cloudflare HTML timeout pages to a friendly chat error", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        "<html><head><title>524 A timeout occurred</title></head><body>cloudflare</body></html>",
        {
          status: 524,
          headers: {
            "Content-Type": "text/html"
          }
        }
      )
    );

    await expect(api.streamChat([{ role: "user", content: "Hello" }])).rejects.toThrow(
      "服务器处理超时了，请稍等一下再试。"
    );
  });

  it("surfaces validation messages from structured backend errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [{ msg: "Input should be a valid dictionary or object to extract fields from" }]
        }),
        {
          status: 422,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(api.streamChat([{ role: "user", content: "Hello" }], [new File(["x"], "a.txt")])).rejects.toThrow(
      "Input should be a valid dictionary or object to extract fields from"
    );
  });

  it("throws a readable error when the response has no stream body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 200 }));

    await expect(api.streamChat([{ role: "user", content: "Hello" }])).rejects.toThrow(
      "Chat response did not include a readable stream."
    );
  });

  it("surfaces a clear error when the backend is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(api.streamChat([{ role: "user", content: "Hello" }])).rejects.toThrow(
      "Unable to reach the server. Please check whether the backend is running and reachable."
    );
  });
});

describe("uploadZip", () => {
  it("posts zip upload form data to the dedicated upload route", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          zipContextId: "zip-context-1",
          archiveName: "project-docs.zip",
          entryCount: 2,
          extractedEntryCount: 1,
          inventoryOnlyCount: 1,
          skippedEntryCount: 0,
          supportedByCurrentModel: true,
          unsupportedReason: null
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );
    const zipFile = new File(["PK"], "project-docs.zip", { type: "application/zip" });

    await expect(
      api.uploadZip(zipFile, {
        conversationId: "conversation-1",
        model: "deepseek-v4-flash"
      })
    ).resolves.toMatchObject({
      zipContextId: "zip-context-1",
      archiveName: "project-docs.zip",
      extractedEntryCount: 1,
      inventoryOnlyCount: 1
    });

    const [url, options] = fetchSpy.mock.calls[0] ?? [];
    expect(url).toBe("/api/upload_zip");
    expect(options).toMatchObject({
      method: "POST",
      credentials: "include"
    });
    expect(options?.body).toBeInstanceOf(FormData);

    const formData = options?.body as FormData;
    expect(formData.get("conversationId")).toBe("conversation-1");
    expect(formData.get("model")).toBe("deepseek-v4-flash");
    expect(formData.get("file")).toBe(zipFile);
  });

  it("polls ZIP status until parsing finishes", async () => {
    vi.spyOn(globalThis, "setTimeout").mockImplementation((((callback: TimerHandler) => {
      if (typeof callback === "function") {
        callback();
      }
      return 0 as unknown as ReturnType<typeof setTimeout>;
    }) as unknown) as typeof setTimeout);
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            zipContextId: "zip-context-1",
            archiveName: "project-docs.zip",
            entryCount: 0,
            extractedEntryCount: 0,
            inventoryOnlyCount: 0,
            skippedEntryCount: 0,
            supportedByCurrentModel: true,
            unsupportedReason: null,
            uploading: true,
            errorMessage: null
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json"
            }
          }
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            zipContextId: "zip-context-1",
            archiveName: "project-docs.zip",
            entryCount: 2,
            extractedEntryCount: 1,
            inventoryOnlyCount: 1,
            skippedEntryCount: 0,
            supportedByCurrentModel: true,
            unsupportedReason: null,
            uploading: false,
            errorMessage: null
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json"
            }
          }
        )
      );

    const promise = api.uploadZip(new File(["PK"], "project-docs.zip", { type: "application/zip" }), {
      conversationId: "conversation-1",
      model: "deepseek-v4-flash"
    });

    await expect(promise).resolves.toMatchObject({
      zipContextId: "zip-context-1",
      extractedEntryCount: 1,
      uploading: false
    });

    expect(fetchSpy.mock.calls[1]?.[0]).toBe(
      "/api/upload_zip/zip-context-1?conversationId=conversation-1&model=deepseek-v4-flash"
    );
  });

  it("surfaces ZIP parse errors reported by the status endpoint", async () => {
    vi.spyOn(globalThis, "setTimeout").mockImplementation((((callback: TimerHandler) => {
      if (typeof callback === "function") {
        callback();
      }
      return 0 as unknown as ReturnType<typeof setTimeout>;
    }) as unknown) as typeof setTimeout);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            zipContextId: "zip-context-1",
            archiveName: "project-docs.zip",
            entryCount: 0,
            extractedEntryCount: 0,
            inventoryOnlyCount: 0,
            skippedEntryCount: 0,
            supportedByCurrentModel: true,
            unsupportedReason: null,
            uploading: true,
            errorMessage: null
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json"
            }
          }
        )
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            zipContextId: "zip-context-1",
            archiveName: "project-docs.zip",
            entryCount: 0,
            extractedEntryCount: 0,
            inventoryOnlyCount: 0,
            skippedEntryCount: 0,
            supportedByCurrentModel: true,
            unsupportedReason: null,
            uploading: false,
            errorMessage: "Invalid ZIP archive: project-docs.zip"
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json"
            }
          }
        )
      );

    const promise = api
      .uploadZip(new File(["PK"], "project-docs.zip", { type: "application/zip" }), {
        conversationId: "conversation-1",
        model: "deepseek-v4-flash"
      })
      .catch((error: unknown) => {
        throw error;
      });

    await expect(promise).rejects.toThrow("Invalid ZIP archive: project-docs.zip");
  });

  it("surfaces backend detail when zip upload fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "zip upload failed" }), {
        status: 400,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(
      api.uploadZip(new File(["PK"], "project-docs.zip", { type: "application/zip" }), {
        conversationId: "conversation-1",
        model: "deepseek-v4-flash"
      })
    ).rejects.toThrow("zip upload failed");
  });

  it("surfaces non-json upload error text instead of the generic fallback", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("413 Request Entity Too Large", {
        status: 413,
        headers: {
          "Content-Type": "text/plain"
        }
      })
    );

    await expect(
      api.uploadZip(new File(["PK"], "project-docs.zip", { type: "application/zip" }), {
        conversationId: "conversation-1",
        model: "deepseek-v4-flash"
      })
    ).rejects.toThrow("413 Request Entity Too Large");
  });

  it("surfaces a clear error when zip upload cannot reach the backend", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(
      api.uploadZip(new File(["PK"], "project-docs.zip", { type: "application/zip" }), {
        conversationId: "conversation-1",
        model: "deepseek-v4-flash"
      })
    ).rejects.toThrow(
      "Unable to reach the server. Please check whether the backend is running and reachable."
    );
  });
});

describe("CAPE API", () => {
  it("submits a sample file to the CAPE route", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ taskId: 99, status: "submitted", reusedExistingTask: true }), {
        status: 200,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(
      api.submitCapeSample(new File(["MZ"], "payload.exe", { type: "application/octet-stream" }), {
        machine: "win10",
        tags: "trojan,cape"
      })
    ).resolves.toEqual({ taskId: 99, status: "submitted", reusedExistingTask: true });

    expect(fetchSpy.mock.calls[0]?.[0]).toBe("/api/cape/submit?machine=win10&tags=trojan%2Ccape");
  });

  it("loads CAPE task status", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          taskId: 99,
          status: "reported",
          completed: true,
          score: 8.2,
          targetFilename: "payload.exe",
          machine: "win10"
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(api.getCapeTaskStatus(99)).resolves.toMatchObject({
      taskId: 99,
      completed: true
    });
  });

  it("loads CAPE task summary", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          taskId: 99,
          status: "reported",
          score: 8.2,
          submittedFilename: "payload.exe",
          sha256: "abc",
          iocs: { domains: ["evil.example"], ips: ["8.8.8.8"], urls: [] },
          tactics: [],
          droppedFiles: [],
          signatures: []
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(api.getCapeTaskSummary(99)).resolves.toMatchObject({
      taskId: 99,
      iocs: { domains: ["evil.example"] }
    });
  });

  it("throws a typed CAPE report wait error while the report is still being generated", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Task is still being analyzed" }), {
        status: 409,
        headers: {
          "Content-Type": "application/json"
        }
      })
    );

    await expect(api.getCapeTaskSummary(99)).rejects.toThrow(api.CapeReportNotReadyError);
  });

  it("creates a chat-native CAPE case for a conversation", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: 7,
          conversationId: 1,
          taskId: 99,
          sampleName: "payload.exe",
          status: "submitted",
          completed: false,
          score: null,
          targetFilename: null,
          machine: null,
          sha256: null,
          reusedExistingTask: false,
          summary: null,
          createdAt: "2026-07-20T00:00:00.000Z",
          updatedAt: "2026-07-20T00:00:00.000Z"
        }),
        {
          status: 201,
          headers: {
            "Content-Type": "application/json"
          }
        }
      )
    );

    await expect(
      api.createCapeCase(new File(["MZ"], "payload.exe", { type: "application/octet-stream" }), {
        conversationId: "1"
      })
    ).resolves.toMatchObject({
      id: 7,
      conversationId: 1,
      taskId: 99,
      sampleName: "payload.exe"
    });

    expect(fetchSpy.mock.calls[0]?.[0]).toBe("/api/cape/cases?conversationId=1");
  });
});
