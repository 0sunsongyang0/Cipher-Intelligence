import { describe, expect, it, vi } from "vitest";
import * as api from "./api";

describe("api auth helpers", () => {
  it("exports auth helpers plus undefined legacy chat shims", () => {
    const exports = api as Record<string, unknown>;

    expect(Object.keys(exports).sort()).toEqual([
      "checkSession",
      "createConversation",
      "fetchConversations",
      "fetchMessages",
      "login",
      "logout"
    ]);
    expect(exports.fetchConversations).toBeUndefined();
    expect(exports.createConversation).toBeUndefined();
    expect(exports.fetchMessages).toBeUndefined();
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
