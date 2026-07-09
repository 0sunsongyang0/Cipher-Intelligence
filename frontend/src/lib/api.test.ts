import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import type { OutboundChatMessage } from "../types";

describe("api auth helpers", () => {
  it("returns an anonymous session payload when the session endpoint is not ok", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 401 })
    );

    await expect(api.checkSession()).resolves.toEqual({ authenticated: false, user: null });
    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/session", {
      credentials: "include"
    });
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
              publicUrl: "https://[private-host]/chat"
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

