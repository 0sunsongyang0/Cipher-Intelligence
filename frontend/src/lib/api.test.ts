import { describe, expect, it, vi } from "vitest";
import * as api from "./api";
import type { OutboundChatMessage } from "../types";

describe("api auth helpers", () => {
  it("exports rebuilt auth helpers and server chat helper", () => {
    const exports = api as Record<string, unknown>;

    expect(Object.keys(exports).sort()).toEqual([
      "checkSession",
      "login",
      "logout",
      "streamChat"
    ]);
  });

  it("returns false when the session endpoint is not ok", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 401 })
    );

    await expect(api.checkSession()).resolves.toBe(false);
    expect(fetchSpy).toHaveBeenCalledWith("/api/auth/session", {
      credentials: "include"
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

    await expect(api.login("wrong")).rejects.toThrow("bad password");
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
});

describe("streamChat", () => {
  it("posts full message history to the backend chat endpoint", async () => {
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

    await expect(api.streamChat(messages)).resolves.toBe(body);
    expect(fetchSpy).toHaveBeenCalledWith("/api/chat", {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ messages })
    });
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

  it("throws a readable error when the response has no stream body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 200 }));

    await expect(api.streamChat([{ role: "user", content: "Hello" }])).rejects.toThrow(
      "Chat response did not include a readable stream."
    );
  });
});
