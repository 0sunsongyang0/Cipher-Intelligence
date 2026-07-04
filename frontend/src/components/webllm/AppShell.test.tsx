import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "./AppShell";
import * as useServerChatModule from "../../hooks/useServerChat";
import type { LocalConversation } from "../../types";

vi.mock("../../hooks/useServerChat", () => ({
  useServerChat: vi.fn()
}));

function buildConversation(): LocalConversation {
  return {
    id: "conversation-1",
    title: "Campus deployment",
    createdAt: "2026-07-03T10:00:00.000Z",
    updatedAt: "2026-07-03T10:00:00.000Z",
    messages: [
      {
        id: "message-1",
        role: "user",
        content: "How is the campus assistant doing?",
        createdAt: "2026-07-03T10:00:00.000Z"
      },
      {
        id: "message-2",
        role: "assistant",
        content: "The DeepSeek campus assistant is ready.",
        createdAt: "2026-07-03T10:00:01.000Z"
      }
    ]
  };
}

describe("AppShell", () => {
  const onLogout = vi.fn().mockResolvedValue(undefined);
  const sendMessage = vi.fn().mockResolvedValue(undefined);
  const setActiveConversationId = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: buildConversation(),
      activeConversationId: "conversation-1",
      conversations: [buildConversation()],
      error: null,
      isGenerating: false,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      settings: {
        systemPrompt: "You are a helpful assistant."
      }
    });
  });

  it("renders the campus backend shell sections without starting a client runtime", () => {
    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByRole("heading", { name: "DeepSeek campus chat" })).toBeInTheDocument();
    expect(screen.getByText(/shared campus backend/i)).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Conversations" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Runtime" })).toBeInTheDocument();
    expect(screen.getByRole("log", { name: "Messages" })).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Prompt composer" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
  });

  it("switches conversations from the sidebar", async () => {
    const user = userEvent.setup();

    render(<AppShell onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: /Campus deployment/i }));

    expect(setActiveConversationId).toHaveBeenCalledWith("conversation-1");
  });

  it("submits a prompt through the composer", async () => {
    const user = userEvent.setup();

    render(<AppShell onLogout={onLogout} />);

    await user.type(screen.getByLabelText("Message"), "Explain the campus deployment");
    await user.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith("Explain the campus deployment");
    });
  });

  it("exposes a logout action and labels settings as read-only", async () => {
    const user = userEvent.setup();

    render(<AppShell onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: "Logout" }));
    expect(onLogout).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(screen.getByText("Read-only backend details")).toBeInTheDocument();
    expect(screen.getByText("DeepSeek campus backend")).toBeInTheDocument();
  });

  it("shows a session error when logout fails", () => {
    render(<AppShell onLogout={onLogout} sessionError="Logout failed" />);

    expect(screen.getByRole("alert")).toHaveTextContent("Logout failed");
  });

  it("shows clear streaming state copy while the backend is responding", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: null,
      activeConversationId: null,
      conversations: [],
      error: null,
      isGenerating: true,
      runtimeStatus: "loading",
      sendMessage,
      setActiveConversationId,
      settings: {
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByRole("heading", { name: "Backend responding" })).toBeInTheDocument();
    expect(screen.getByText(/DeepSeek is streaming a response/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Backend responding" })).toBeDisabled();
  });

  it("shows clear recovery copy when the backend fails", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: null,
      activeConversationId: null,
      conversations: [],
      error: "Campus backend unavailable",
      isGenerating: false,
      runtimeStatus: "error",
      sendMessage,
      setActiveConversationId,
      settings: {
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByText("Backend needs attention")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Campus backend unavailable");
    expect(screen.getByRole("button", { name: "Backend unavailable" })).toBeDisabled();
  });
});
