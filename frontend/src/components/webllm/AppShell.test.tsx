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
  const onLogout = vi.fn().mockResolvedValue(undefined);
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
    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByRole("heading", { name: "Local model chat" })).toBeInTheDocument();
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

    render(<AppShell onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: /Runtime setup/i }));

    expect(setActiveConversationId).toHaveBeenCalledWith("conversation-1");
  });

  it("submits a prompt through the composer", async () => {
    const user = userEvent.setup();

    render(<AppShell onLogout={onLogout} />);

    await user.type(screen.getByLabelText("Message"), "Explain WebLLM");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith("Explain WebLLM");
    });
  });

  it("exposes a logout action and labels settings as read-only", async () => {
    const user = userEvent.setup();

    render(<AppShell onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: "Logout" }));
    expect(onLogout).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByText("Read-only runtime details")).toBeInTheDocument();
  });

  it("shows a session error when logout fails", () => {
    render(<AppShell onLogout={onLogout} sessionError="Logout failed" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Logout failed");
  });

  it("shows clear loading state copy while the runtime is preparing", () => {
    vi.mocked(useWebLLMChatModule.useWebLLMChat).mockReturnValue({
      activeConversation: null,
      activeConversationId: null,
      conversations: [],
      error: null,
      initializeEngine,
      initProgress: {
        progress: 0.42,
        text: "Loading model weights"
      },
      isGenerating: false,
      runtimeStatus: "loading",
      sendMessage,
      setActiveConversationId,
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByText("Preparing local runtime")).toBeInTheDocument();
    expect(screen.getByText("Loading model weights (42%)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Runtime starting" })).toBeDisabled();
  });

  it("shows clear recovery actions when the runtime fails", () => {
    vi.mocked(useWebLLMChatModule.useWebLLMChat).mockReturnValue({
      activeConversation: null,
      activeConversationId: null,
      conversations: [],
      error: "GPU adapter unavailable",
      initializeEngine,
      initProgress: null,
      isGenerating: false,
      runtimeStatus: "error",
      sendMessage,
      setActiveConversationId,
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByText("Runtime needs attention")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("GPU adapter unavailable");
    expect(screen.getByRole("button", { name: "Retry runtime" })).toBeEnabled();
  });
});
