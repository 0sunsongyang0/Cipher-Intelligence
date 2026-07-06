import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "./AppShell";
import * as useServerChatModule from "../../hooks/useServerChat";
import type { LocalConversation, StagedAttachment } from "../../types";

type MockServerChatState = ReturnType<typeof useServerChatModule.useServerChat>;

vi.mock("../../hooks/useServerChat", () => ({
  useServerChat: vi.fn()
}));

function buildConversation(): LocalConversation {
  return {
    id: "conversation-1",
    title: "Campus rollout plan",
    createdAt: "2026-07-03T10:00:00.000Z",
    updatedAt: "2026-07-03T10:00:00.000Z",
    messages: [
      {
        id: "message-1",
        role: "user",
        content: "What is the current status?",
        createdAt: "2026-07-03T10:00:00.000Z"
      },
      {
        id: "message-2",
        role: "assistant",
        content: "The backend is connected and ready.",
        createdAt: "2026-07-03T10:00:01.000Z"
      }
    ]
  };
}

function buildAttachment(overrides: Partial<StagedAttachment> = {}): StagedAttachment {
  const file = overrides.file ?? new File(["attachment body"], "campus-notes.pdf", {
    type: "application/pdf"
  });

  return {
    id: overrides.id ?? "attachment-1",
    file,
    name: overrides.name ?? file.name,
    type: overrides.type ?? "PDF",
    size: overrides.size ?? file.size
  };
}

function expectReadableMath(minCount = 1) {
  expect(document.querySelectorAll("mjx-container").length).toBeGreaterThanOrEqual(minCount);
  expect(document.querySelectorAll('[data-mml-node="merror"]')).toHaveLength(0);
  expect(document.body.textContent).not.toContain("\\(");
  expect(document.body.textContent).not.toContain("\\[");
  expect(document.body.textContent).not.toContain("\\sum");
  expect(document.body.textContent).not.toContain("\\frac");
}

function getModelMenuButton() {
  const button = document.querySelector(".bomb-shell__model-pill");
  expect(button).not.toBeNull();
  return button as HTMLButtonElement;
}

describe("AppShell", () => {
  const onLogout = vi.fn().mockResolvedValue(undefined);
  const sendMessage = vi.fn().mockResolvedValue(undefined);
  const setActiveConversationId = vi.fn();
  const deleteConversation = vi.fn();
  const addFiles = vi.fn();
  const clearFiles = vi.fn();
  const removeFile = vi.fn();
  const setModelId = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: buildConversation(),
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });
  });

  it("renders the shell layout with chat content", () => {
    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByTestId("aurora-background")).toBeInTheDocument();
    expect(screen.getByTestId("chat-shell")).toBeInTheDocument();
    expect(screen.getByTestId("chat-input-dock")).toBeInTheDocument();
    expect(screen.getByText("deepseek-v4-flash")).toBeInTheDocument();
    expect(screen.getByText("Bomb AI")).toBeInTheDocument();
    expect(screen.getByText("Designer.Dev")).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "Conversations" })).toBeInTheDocument();
    expect(screen.getByRole("log")).toBeInTheDocument();
    expect(screen.getByText("Campus rollout plan")).toBeInTheDocument();
  });

  it("submits a prompt through the composer", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    await user.type(screen.getByRole("textbox"), "Explain the rollout plan.");
    await user.click(within(screen.getByTestId("chat-input-dock")).getAllByRole("button").at(-1)!);

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith("Explain the rollout plan.");
    });
  });

  it("shows provider groups before concrete models", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    await user.click(getModelMenuButton());

    expect(screen.getByRole("button", { name: "DeepSeek" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OpenAI" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Claude" })).toBeInTheDocument();
    expect(screen.queryByRole("menuitemradio", { name: "ChatGPT 5.5" })).not.toBeInTheDocument();
  });

  it("opens the OpenAI submenu and switches to ChatGPT 5.5", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    await user.click(getModelMenuButton());
    await user.hover(screen.getByRole("button", { name: "OpenAI" }));
    await user.click(screen.getByRole("menuitemradio", { name: "ChatGPT 5.5" }));

    expect(setModelId).toHaveBeenCalledWith("chatgpt-5.5-official");
  });

  it("highlights the provider for the currently selected model", async () => {
    const user = userEvent.setup();
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: buildConversation(),
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      settings: {
        modelId: "claude-opus-4-7-official",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);
    await user.click(getModelMenuButton());

    expect(screen.getByRole("button", { name: "Claude" }).className).toContain(
      "bomb-shell__model-provider-item--selected"
    );
  });

  it("keeps the model menu mounted briefly while it animates closed", () => {
    vi.useFakeTimers();

    try {
      render(<AppShell onLogout={onLogout} />);

      fireEvent.click(getModelMenuButton());
      expect(document.querySelector(".bomb-shell__model-menu")).not.toBeNull();

      fireEvent.click(getModelMenuButton());

      const closingMenu = document.querySelector(".bomb-shell__model-menu");
      expect(closingMenu).not.toBeNull();
      expect(closingMenu?.className).toContain("bomb-shell__model-menu--closing");

      act(() => {
        vi.advanceTimersByTime(240);
      });

      expect(document.querySelector(".bomb-shell__model-menu")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens the hidden file picker from the paperclip control and stages uploaded files", async () => {
    const user = userEvent.setup();
    const clickSpy = vi.spyOn(HTMLInputElement.prototype, "click");
    render(<AppShell onLogout={onLogout} />);

    await user.click(within(screen.getByTestId("chat-input-dock")).getAllByRole("button")[0]);

    expect(clickSpy).toHaveBeenCalledTimes(1);

    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();

    const file = new File(["semester plan"], "semester-plan.pdf", { type: "application/pdf" });
    await user.upload(input!, file);

    expect(addFiles).toHaveBeenCalledWith([file]);
  });

  it("renders staged attachments above the composer and removes them from the chip action", async () => {
    const user = userEvent.setup();

    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: buildConversation(),
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [buildAttachment({ name: "campus-notes.pdf" })],
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    const stagedList = document.querySelector(".bomb-shell__attachment-list");
    expect(stagedList).not.toBeNull();
    expect(within(stagedList as HTMLElement).getByText("campus-notes.pdf")).toBeInTheDocument();

    await user.click(within(stagedList as HTMLElement).getByRole("button"));

    expect(removeFile).toHaveBeenCalledWith("attachment-1");
  });

  it("shows a drag overlay over the main chat region and stages dropped files there", () => {
    render(<AppShell onLogout={onLogout} />);

    const messageStage = screen.getByRole("log");
    const file = new File(["drop"], "dropped.txt", { type: "text/plain" });
    const dataTransfer = {
      files: [file],
      items: [],
      types: ["Files"]
    };

    fireEvent.dragEnter(messageStage, { dataTransfer });

    expect(document.querySelector(".bomb-shell__drop-overlay")).not.toBeNull();

    fireEvent.drop(messageStage, { dataTransfer });

    expect(addFiles).toHaveBeenCalledWith([file]);
    expect(document.querySelector(".bomb-shell__drop-overlay")).toBeNull();
  });

  it("does not treat the sidebar or drawer sidebar as drop targets", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    const file = new File(["drop"], "ignored.txt", { type: "text/plain" });
    const dataTransfer = {
      files: [file],
      items: [],
      types: ["Files"]
    };

    fireEvent.dragEnter(screen.getByRole("complementary", { name: "Conversations" }), {
      dataTransfer
    });

    expect(document.querySelector(".bomb-shell__drop-overlay")).toBeNull();
    expect(addFiles).not.toHaveBeenCalled();

    await user.click(within(screen.getByRole("banner")).getAllByRole("button")[0]);
    await user.click(within(screen.getByRole("banner")).getAllByRole("button")[0]);

    const drawerSidebar = screen.getAllByRole("complementary").find((element) =>
      element.className.includes("bomb-shell__drawer-sidebar")
    );

    expect(drawerSidebar).toBeTruthy();

    fireEvent.dragEnter(drawerSidebar!, { dataTransfer });
    fireEvent.drop(drawerSidebar!, { dataTransfer });

    expect(document.querySelector(".bomb-shell__drop-overlay")).toBeNull();
    expect(addFiles).not.toHaveBeenCalled();
  });

  it("returns to the centered empty-state landing when starting a new conversation from an existing thread", async () => {
    const user = userEvent.setup();
    const populatedHookState: MockServerChatState = {
      activeConversation: buildConversation(),
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready" as const,
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    };
    const emptyHookState: MockServerChatState = {
      ...populatedHookState,
      activeConversation: null,
      activeConversationId: null
    };
    let currentHookState = populatedHookState;
    vi.mocked(useServerChatModule.useServerChat).mockImplementation(() => currentHookState);

    const { rerender } = render(<AppShell onLogout={onLogout} />);
    const logBeforeReset = screen.getByRole("log");
    Object.defineProperty(logBeforeReset, "scrollHeight", { configurable: true, value: 2400 });
    Object.defineProperty(logBeforeReset, "clientHeight", { configurable: true, value: 900 });
    logBeforeReset.scrollTop = 1480;

    await user.click(within(screen.getByRole("complementary", { name: "Conversations" })).getAllByRole("button")[1]);

    expect(clearFiles).toHaveBeenCalled();
    expect(setActiveConversationId).toHaveBeenCalledWith(null);

    currentHookState = emptyHookState;
    rerender(<AppShell onLogout={onLogout} />);

    const log = screen.getByRole("log");
    expect(log.className).toContain("bomb-shell__message-stage--empty");
    expect(log.scrollTop).toBe(0);
    expect(document.querySelector(".bomb-shell__landing")).not.toBeNull();
    expect(document.querySelector(".bomb-shell__dock-wrap--centered")).not.toBeNull();
    expect(document.querySelector(".bomb-shell__dock-wrap:not(.bomb-shell__dock-wrap--centered)")).toBeNull();
  });

  it("renders assistant latex content through a rich renderer", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content: "Inline formula $E=mc^2$\\n\\n$$\\\\int_0^1 x^2 \\\\, dx$$",
            createdAt: "2026-07-03T10:00:01.000Z"
          }
        ]
      },
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByText((content) => content.includes("Inline formula"))).toBeInTheDocument();
    expect(screen.queryByText("Inline formula $E=mc^2$")).not.toBeInTheDocument();
    expectReadableMath(2);
  });

  it("renders parenthesized latex-style math often returned in answers", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content:
              "Signal period ( T = \\pi/7 ) gives base frequency (\\omega_0 = 2\\pi/T = 14 , \\text{rad/s}). The output is ( y(t) = x(t) ).",
            createdAt: "2026-07-03T10:00:01.000Z"
          }
        ]
      },
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expectReadableMath(1);
  });

  it("renders standard mathjax inline delimiters", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content: "The period is \\( T = \\pi/7 \\) and the base frequency is \\( \\omega_0 = 14 \\).",
            createdAt: "2026-07-03T10:00:01.000Z"
          }
        ]
      },
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expectReadableMath(1);
  });

  it("renders bare multiline latex blocks and standalone equations from model answers", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content: `Frequency response:
The ideal high-pass response is
H(j\\omega)=\\begin{cases}
1, & |\\omega| \\geq 250 \\\\
0, & \\text{otherwise}
\\end{cases}

For x(t) with T = \\pi/7, the base frequency is \\omega_0 = \\frac{2\\pi}{T} = 14 \\text{ rad/s}.

x(t)=\\sum_{k=-\\infty}^{\\infty} c_k e^{jk\\omega_0 t}

y(t)=\\sum_{k=-\\infty}^{\\infty} c_k H(jk\\omega_0)e^{jk\\omega_0 t}.`,
            createdAt: "2026-07-03T10:00:01.000Z"
          }
        ]
      },
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expectReadableMath(3);
  });

  it("renders latex lines that include text blocks and malformed escaped dollar delimiters", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content: `Solve for a and b.

- On [-0.5, 0.5], integrate around t = 0:
\\int_{-0.5}^{0.5} x(t) \\, dt = 1.5(a+b) = 1 \\quad \\Rightarrow \\quad a+b = \\frac{2}{3}. \\tag{1}

- On [0, 2], split at t = 0 and t = 1.5:
\\int_{0}^{2} x(t) \\, dt = 1.5(a+b) + 1.5(a-b) = 3a = 2 \\quad \\Rightarrow \\quad a = \\frac{2}{3}. \\tag{2}

From (1), \\$b = 0$.
Therefore \\boxed{C_k = \\begin{cases} \\frac{2}{3}, & k \\text{ even} \\\\ 0, & k \\text{ odd} \\end{cases}}`,
            createdAt: "2026-07-03T10:00:01.000Z"
          }
        ]
      },
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expectReadableMath(3);
  });
});

