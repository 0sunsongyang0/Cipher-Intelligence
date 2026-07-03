import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ChatPage } from "./ChatPage";

describe("ChatPage", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = typeof input === "string" ? input : input.toString();

      if (url.endsWith("/api/conversations")) {
        return new Response(JSON.stringify([]), {
          status: 200,
          headers: {
            "Content-Type": "application/json"
          }
        });
      }

      throw new Error(`Unhandled request in test: ${url}`);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders the chat workspace entry points", async () => {
    render(<ChatPage />);

    expect(screen.getByText("\u65b0\u5efa\u5bf9\u8bdd")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "\u5154\u5154\u70b8\u5f39\u7684\u5927\u6a21\u578b\u52a9\u624b" })
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText("\u8f93\u5165\u4f60\u60f3\u95ee\u7684\u95ee\u9898\u2026")
    ).toBeInTheDocument();
  });
});