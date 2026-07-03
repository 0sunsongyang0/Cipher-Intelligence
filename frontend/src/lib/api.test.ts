import { describe, expect, it, vi } from "vitest";
import * as api from "./api";

describe("api auth helpers", () => {
  it("exports only auth/session helpers", () => {
    expect(Object.keys(api).sort()).toEqual(["checkSession", "login"]);
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
});
