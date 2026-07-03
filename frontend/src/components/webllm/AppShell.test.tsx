import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";
import * as useWebLLMChatModule from "../../hooks/useWebLLMChat";
import type { LocalConversation } from "../../types";

vi.mock("../../hooks/useWebLLMChat", () => ({
  useWebLLMChat: vi.fn()
}));

function buildConversation(): LocalConversation {
  return {
    id: "conversation-1",
    title: "Runtime setup",
    createdAt: "2026-07-03T10:00:00.000Z",
    updatedAt: "2026-07-03T10:00:00.000Z",
    messages: [
      {
        id: "message-1",
        role: "user",
        content: "How is the runtime doing?",
        createdAt: "2026-07-03T10:00:00.000Z"
      },
      {
        id: "message-2",
        role: "assistant",
        content: "The runtime is ready.",
        createdAt: "2026-07-03T10:00:01.000Z"
      }
    ]
  };
}

describe("AppShell", () => {
  const initializeEngine = vi.fn().mockResolvedValue(undefined);
  const sendMessage = vi.fn().mockResolvedValue(undefined);
  const setActiveConversationId = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useWebLLMChatModule.useWebLLMChat).mockReturnValue({
      activeConversation: buildConversation(),
      activeConversationId: "conversation-1",
      conversations: [buildConversation()],
      error: null,
      initializeEngine,
      initProgress: null,
      isGenerating: false,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });
  });

  it("renders the webllm shell sections and initializes the runtime on mount", async () => {
    render(<AppShell />);

    expect(screen.getByRole("complementary", { name: "Conversations" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Runtime" })).toBeInTheDocument();
    expect(screen.getByRole("log", { name: "Messages" })).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Prompt composer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();

    await waitFor(() => {
      expect(initializeEngine).toHaveBeenCalledTimes(1);
    });
  });

  it("switches conversations from the sidebar", async () => {
    const user = userEvent.setup();

    render(<AppShell />);

    await user.click(screen.getByRole("button", { name: /Runtime setup/i }));

    expect(setActiveConversationId).toHaveBeenCalledWith("conversation-1");
  });

  it("submits a prompt through the composer", async () => {
    const user = userEvent.setup();

    render(<AppShell />);

    await user.type(screen.getByLabelText("Message"), "Explain WebLLM");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith("Explain WebLLM");
    });
  });
});
