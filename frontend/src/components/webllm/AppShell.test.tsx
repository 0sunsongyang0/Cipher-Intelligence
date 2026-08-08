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
    size: overrides.size ?? file.size,
    retainedForZipContext: overrides.retainedForZipContext
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
  const button = document.querySelector<HTMLButtonElement>(".bomb-shell__model-pill");
  expect(button).not.toBeNull();
  return button!;
}

function setMobileViewport(enabled: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockImplementation((query: string) => ({
      matches: enabled && query === "(max-width: 760px)",
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn()
    }))
  );
}

describe("AppShell", () => {
  const onLogout = vi.fn().mockResolvedValue(undefined);
  const sendMessage = vi.fn().mockResolvedValue(undefined);
  const submitCapeCase = vi.fn();
  const refreshCapeCase = vi.fn();
  const uploadZip = vi.fn().mockResolvedValue(undefined);
  const setActiveConversationId = vi.fn();
  const deleteConversation = vi.fn();
  const addFiles = vi.fn();
  const clearFiles = vi.fn();
  const removeFile = vi.fn();
  const setModelId = vi.fn();
  const setWebSearchEnabled = vi.fn();
  const stopGeneration = vi.fn();
  const renameConversation = vi.fn().mockResolvedValue(undefined);
  const setConversationPinned = vi.fn().mockResolvedValue(undefined);
  const setConversationArchived = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    setMobileViewport(false);
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: buildConversation(),
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      stopGeneration,
      renameConversation,
      setConversationPinned,
      setConversationArchived,
      removeFile,
      runtimeStatus: "ready",
      sendMessage,
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });
  });

  it("renders the shell layout with chat content", () => {
    render(
      <AppShell
        viewer={{
          id: 1,
          username: "alice",
          displayName: "Alice Chen",
          avatarUrl: "/api/account/avatars/user-1-0123456789abcdef.webp",
          isAdmin: false
        }}
        onLogout={onLogout}
      />
    );

    expect(screen.getByTestId("aurora-background")).toBeInTheDocument();
    expect(screen.getByTestId("chat-shell")).toBeInTheDocument();
    expect(screen.getByTestId("chat-input-dock")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "切换模型" })).toHaveAttribute(
      "title",
      "切换模型 · 当前为 Cipher Swift"
    );
    expect(screen.getByRole("img", { name: "Cipher Intelligence" })).toHaveAttribute(
      "src",
      "/assets/cipher-wordmark.svg"
    );
    expect(screen.getByRole("button", { name: "开启新对话" })).toHaveTextContent("新建对话");
    expect(screen.getByRole("searchbox", { name: "全文搜索会话" })).toHaveAttribute(
      "placeholder",
      "搜索标题、消息与 IOC"
    );
    expect(screen.getByText("最近对话", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("偏好设置")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Alice Chen 打开账号设置" })).toHaveTextContent("Alice Chen");
    expect(screen.getByRole("button", { name: "Alice Chen 打开账号设置" }).querySelector("img")).toHaveAttribute(
      "src",
      "/api/account/avatars/user-1-0123456789abcdef.webp"
    );
    expect(screen.getByTestId("message-row-message-1").querySelector(".bomb-shell__message-avatar-photo")).toHaveAttribute(
      "src",
      "/api/account/avatars/user-1-0123456789abcdef.webp"
    );
    expect(screen.getByRole("complementary", { name: "会话导航" })).toBeInTheDocument();
    expect(screen.getByRole("log")).toBeInTheDocument();
    expect(screen.getAllByText("Campus rollout plan")).toHaveLength(2);
    expect(screen.getByTestId("conversation-context")).toHaveTextContent("Campus rollout plan");
    expect(screen.getByTestId("conversation-context")).toHaveTextContent("推理服务在线");
    expect(screen.getByTestId("chat-input-dock")).toHaveAttribute("data-layout", "docked");
  });

  it("opens the standalone account page from the profile control", async () => {
    const user = userEvent.setup();
    const onOpenAccount = vi.fn();

    render(
      <AppShell
        viewer={{ id: 1, username: "alice", displayName: "Alice", avatarUrl: null, isAdmin: false }}
        onOpenAccount={onOpenAccount}
        onLogout={onLogout}
      />
    );

    await user.click(screen.getByRole("button", { name: "Alice 打开账号设置" }));

    expect(onOpenAccount).toHaveBeenCalledTimes(1);
  });

  it("full-text searches conversation messages from the permanent sidebar", async () => {
    const user = userEvent.setup();
    const incidentConversation: LocalConversation = {
      ...buildConversation(),
      id: "conversation-2",
      title: "SOC notes",
      messages: [
        {
          id: "message-incident",
          role: "assistant",
          content: "Incident response evidence includes beacon.example",
          createdAt: "2026-07-03T10:00:01.000Z"
        }
      ]
    };
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      ...vi.mocked(useServerChatModule.useServerChat)(),
      conversations: [buildConversation(), incidentConversation]
    });

    render(<AppShell onLogout={onLogout} />);

    const sidebar = screen.getByRole("complementary", { name: "会话导航" });
    const search = within(sidebar).getByRole("searchbox", { name: "全文搜索会话" });

    await user.type(search, "incident");

    expect(within(sidebar).queryByText("Campus rollout plan")).not.toBeInTheDocument();
    expect(within(sidebar).getByText("SOC notes")).toBeInTheDocument();

    await user.click(within(sidebar).getByRole("button", { name: "清空会话搜索" }));

    expect(within(sidebar).getByText("Campus rollout plan")).toBeInTheDocument();
    expect(within(sidebar).getByText("SOC notes")).toBeInTheDocument();
  });

  it("stops an in-flight generation from the composer", async () => {
    const user = userEvent.setup();
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      ...vi.mocked(useServerChatModule.useServerChat)(),
      isGenerating: true,
      stopGeneration
    });

    render(<AppShell onLogout={onLogout} />);
    const stopButton = screen.getByRole("button", { name: "停止生成" });
    expect(stopButton).toHaveClass("bomb-shell__send-button--active");
    await user.click(stopButton);

    expect(stopGeneration).toHaveBeenCalledTimes(1);
  });

  it("renames and pins a conversation from its management menu", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: "管理会话 Campus rollout plan" }));
    await user.click(screen.getByRole("button", { name: "重命名" }));
    const titleInput = screen.getByRole("textbox", { name: "会话名称" });
    await user.clear(titleInput);
    await user.type(titleInput, "Incident 42");
    await user.click(screen.getByRole("button", { name: "保存" }));

    expect(renameConversation).toHaveBeenCalledWith("conversation-1", "Incident 42");

    await user.click(screen.getByRole("button", { name: "管理会话 Campus rollout plan" }));
    await user.click(screen.getByRole("button", { name: "置顶会话" }));
    expect(setConversationPinned).toHaveBeenCalledWith("conversation-1", true);
  });

  it("restores the desktop sidebar after it has been collapsed", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    const sidebar = screen.getByRole("complementary", { name: "会话导航" });
    expect(sidebar).toHaveClass("bomb-shell__sidebar--open");

    await user.click(screen.getByRole("button", { name: "收起会话栏" }));

    expect(sidebar).not.toHaveClass("bomb-shell__sidebar--open");
    const expandButton = screen.getByRole("button", { name: "展开会话栏" });
    expect(expandButton).toHaveTextContent("展开");

    await user.click(expandButton);

    expect(sidebar).toHaveClass("bomb-shell__sidebar--open");
  });

  it("exposes composer focus state for material feedback", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    const dock = screen.getByTestId("chat-input-dock");
    expect(dock).toHaveAttribute("data-focused", "false");

    await user.click(screen.getByRole("textbox"));
    expect(dock).toHaveAttribute("data-focused", "true");

    await user.tab();
    expect(dock).toHaveAttribute("data-focused", "false");
  });

  it("centers the send button until the composer becomes multiline", async () => {
    render(<AppShell onLogout={onLogout} />);

    const dock = screen.getByRole("form", { name: "消息输入框" });
    const textarea = screen.getByRole("textbox");
    expect(dock).toHaveAttribute("data-multiline", "false");

    Object.defineProperty(textarea, "scrollHeight", {
      configurable: true,
      value: 88
    });
    fireEvent.change(textarea, { target: { value: "第一行\n第二行" } });

    await waitFor(() => {
      expect(dock).toHaveAttribute("data-multiline", "true");
    });
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

  it("toggles the manual web search button", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    const webSearchButton = screen.getByRole("button", { name: "启用联网搜索" });
    const webSearchIcon = webSearchButton.querySelector("svg");

    expect(webSearchIcon?.className.baseVal ?? webSearchIcon?.getAttribute("class")).toContain("tabler-icon-world");

    await user.click(webSearchButton);

    expect(setWebSearchEnabled).toHaveBeenCalledWith(true);
    expect(screen.getByRole("status")).toHaveTextContent("已启用联网搜索");
  });

  it("opens the CAPE panel from the dock tools", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: "打开 CAPE 面板" }));

    expect(screen.getByRole("heading", { name: "本地 CAPE 沙箱" })).toBeInTheDocument();
    expect(screen.getByText("样本将提交到本机 CAPE 环境进行分析，任务进度与结果摘要会显示在这里。")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "选择要分析的样本" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "提交到 CAPE" })).toBeDisabled();
  });

  it("renders the web search button in its active visual state", () => {
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: true,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    const webSearchButton = screen.getByRole("button", { name: "关闭联网搜索" });
    expect(webSearchButton.className).toContain("bomb-shell__dock-tool--active");
  });

  it("shows a success banner when web search is disabled", async () => {
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: true,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: "关闭联网搜索" }));

    expect(setWebSearchEnabled).toHaveBeenCalledWith(false);
    expect(screen.getByRole("status")).toHaveTextContent("已关闭联网搜索");
  });

  it("auto dismisses the red error banner and still shows later errors", () => {
    vi.useFakeTimers();

    try {
      let currentSessionError = "First error";
      const baseHookState = {
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
        submitCapeCase,
        refreshCapeCase,
        setWebSearchEnabled,
        uploadZip,
        setActiveConversationId,
        setModelId,
        stagedFiles: [],
        webSearchEnabled: false,
        settings: {
          modelId: "deepseek-v4-flash",
          systemPrompt: "You are a helpful assistant."
        }
      };

      vi.mocked(useServerChatModule.useServerChat).mockReturnValue(baseHookState);

      const { rerender } = render(<AppShell onLogout={onLogout} sessionError={currentSessionError} />);

      expect(screen.getByRole("alert")).toHaveTextContent("First error");

      act(() => {
        vi.advanceTimersByTime(3600);
      });

      expect(screen.queryByRole("alert")).toBeNull();

      currentSessionError = "Second error";
      rerender(<AppShell onLogout={onLogout} sessionError={currentSessionError} />);

      expect(screen.getByRole("alert")).toHaveTextContent("Second error");
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows provider groups before concrete models", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    await user.click(getModelMenuButton());

    const deepSeekProvider = screen.getByRole("menuitem", { name: "Cipher 轻量" });
    const openAiProvider = screen.getByRole("menuitem", { name: "Cipher 均衡" });
    const claudeProvider = screen.getByRole("menuitem", { name: "Cipher 深研" });

    expect(deepSeekProvider).toBeInTheDocument();
    expect(openAiProvider).toBeInTheDocument();
    expect(claudeProvider).toBeInTheDocument();
    expect(deepSeekProvider).toHaveAttribute("aria-haspopup", "menu");
    expect(deepSeekProvider).toHaveAttribute("aria-expanded", "true");
    expect(deepSeekProvider).toHaveAttribute("aria-controls");
    expect(openAiProvider).toHaveAttribute("aria-haspopup", "menu");
    expect(openAiProvider).toHaveAttribute("aria-expanded", "false");
    expect(openAiProvider).toHaveAttribute("aria-controls", deepSeekProvider.getAttribute("aria-controls"));
    expect(screen.queryByRole("menuitemradio", { name: "Cipher Prime" })).not.toBeInTheDocument();
  });

  it("uses a model switcher above the composer and anchors the menu beneath its trigger", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    const trigger = getModelMenuButton();
    vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
      bottom: 122,
      height: 42,
      left: 238,
      right: 280,
      top: 80,
      width: 42,
      x: 238,
      y: 80,
      toJSON: () => ({})
    });

    expect(trigger.querySelector(".bomb-shell__model-pill-switch")).not.toBeNull();
    expect(trigger).toHaveAttribute("title", "切换模型 · 当前为 Cipher Swift");
    expect(within(screen.getByTestId("chat-input-dock")).getByRole("button", { name: "切换模型" })).toBe(
      trigger
    );

    await user.click(trigger);

    const menu = screen.getByRole("menu", { name: "模型列表" });
    await waitFor(() => {
      expect(menu).toHaveAttribute("data-placement", "below");
      expect(menu).toHaveStyle({ left: "238px", top: "132px" });
    });
    expect(menu.parentElement).toBe(screen.getByTestId("chat-shell"));
  });

  it("keeps the phone model menu inside the viewport", async () => {
    vi.stubGlobal("innerWidth", 390);
    vi.stubGlobal("innerHeight", 844);

    try {
      const user = userEvent.setup();
      render(<AppShell onLogout={onLogout} />);

      const trigger = getModelMenuButton();
      vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue({
        bottom: 388,
        height: 38,
        left: 50,
        right: 230,
        top: 350,
        width: 180,
        x: 50,
        y: 350,
        toJSON: () => ({})
      });

      await user.click(trigger);

      const menu = screen.getByRole("menu", { name: "模型列表" });
      await waitFor(() => {
        expect(menu).toHaveAttribute("data-placement", "below");
        expect(menu).toHaveStyle({ left: "18px", top: "398px" });
      });
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("opens the Cipher 均衡 submenu and switches to Cipher Prime", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    await user.click(getModelMenuButton());
    const openAiProvider = screen.getByRole("menuitem", { name: "Cipher 均衡" });
    await user.hover(openAiProvider);
    await user.click(openAiProvider);
    await waitFor(() => {
      expect(openAiProvider).toHaveAttribute("aria-expanded", "true");
    });
    await user.click(await screen.findByRole("menuitemradio", { name: "Cipher Prime" }));

    expect(setModelId).toHaveBeenCalledWith("chatgpt-5.5-official");
    expect(getModelMenuButton()).toHaveAttribute("aria-expanded", "false");
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "claude-opus-4-7-official",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);
    await user.click(getModelMenuButton());

    expect(screen.getByRole("menuitem", { name: "Cipher 深研" }).className).toContain(
      "bomb-shell__model-provider-item--selected"
    );
  });

  it("moves focus into the active provider and supports keyboard navigation between menu levels", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    await user.click(getModelMenuButton());

    const deepSeekProvider = screen.getByRole("menuitem", { name: "Cipher 轻量" });
    await waitFor(() => {
      expect(deepSeekProvider).toHaveFocus();
    });

    fireEvent.keyDown(deepSeekProvider, { key: "ArrowDown" });
    const openAiProvider = screen.getByRole("menuitem", { name: "Cipher 均衡" });
    expect(openAiProvider).toHaveFocus();

    fireEvent.keyDown(openAiProvider, { key: "Enter" });
    fireEvent.keyDown(openAiProvider, { key: "ArrowRight" });

    const firstOpenAiModel = screen.getByRole("menuitemradio", { name: "Cipher Prime" });
    expect(firstOpenAiModel).toHaveFocus();

    fireEvent.keyDown(firstOpenAiModel, { key: "ArrowDown" });
    expect(screen.getByRole("menuitemradio", { name: "Cipher Vector" })).toHaveFocus();

    fireEvent.keyDown(screen.getByRole("menuitemradio", { name: "Cipher Vector" }), { key: "ArrowUp" });
    expect(firstOpenAiModel).toHaveFocus();

    fireEvent.keyDown(firstOpenAiModel, { key: "ArrowLeft" });
    expect(openAiProvider).toHaveFocus();
  });

  it("closes the menu on escape and returns focus to the trigger", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    const trigger = getModelMenuButton();
    await user.click(trigger);

    await waitFor(() => {
      expect(screen.getByRole("menuitem", { name: "Cipher 轻量" })).toHaveFocus();
    });

    await user.keyboard("{Escape}");

    expect(trigger).toHaveFocus();
    expect(trigger).toHaveAttribute("aria-expanded", "false");
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
      expect(
        Array.from((closingMenu as HTMLElement).querySelectorAll("button")).every((item) => item.hasAttribute("disabled"))
      ).toBe(true);

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

    await user.click(within(screen.getByTestId("chat-input-dock")).getByRole("button", { name: "添加附件" }));

    expect(clickSpy).toHaveBeenCalledTimes(1);

    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();

    const file = new File(["semester plan"], "semester-plan.pdf", { type: "application/pdf" });
    await user.upload(input!, file);

    expect(addFiles).toHaveBeenCalledWith([file]);
  });

  it("renders a pending ZIP context inside the shared attachment chip list", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        zipContext: {
          zipContextId: "zip-context-1",
          archiveName: "project-docs.zip",
          entryCount: 4,
          extractedEntryCount: 1,
          inventoryOnlyCount: 3,
          skippedEntryCount: 0,
          supportedByCurrentModel: true,
          unsupportedReason: null,
          pendingAttachment: true
        } as never
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    const attachmentList = document.querySelector(".bomb-shell__attachment-list");
    expect(attachmentList).not.toBeNull();
    expect(within(attachmentList as HTMLElement).getByText("project-docs.zip")).toBeInTheDocument();
    expect(within(attachmentList as HTMLElement).getByText(/ZIP/)).toBeInTheDocument();
    expect(document.querySelector(".bomb-shell__zip-context")).toBeNull();
  });

  it("shows the same remove action for a pending ZIP chip", async () => {
    const user = userEvent.setup();
    const removePendingZipContext = vi.fn();

    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        zipContext: {
          zipContextId: "zip-context-1",
          archiveName: "project-docs.zip",
          entryCount: 4,
          extractedEntryCount: 1,
          inventoryOnlyCount: 3,
          skippedEntryCount: 0,
          supportedByCurrentModel: true,
          unsupportedReason: null,
          pendingAttachment: true
        } as never
      },
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      removePendingZipContext,
      runtimeStatus: "ready",
      sendMessage,
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    await user.click(screen.getByRole("button", { name: "移除附件 project-docs.zip" }));

    expect(removePendingZipContext).toHaveBeenCalledTimes(1);
  });

  it("renders only one ZIP chip when the active ZIP is also retained in staged files", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        zipContext: {
          zipContextId: "zip-context-1",
          archiveName: "project-docs.zip",
          entryCount: 4,
          extractedEntryCount: 1,
          inventoryOnlyCount: 3,
          skippedEntryCount: 0,
          supportedByCurrentModel: true,
          unsupportedReason: null,
          pendingAttachment: true
        } as never
      },
      activeConversationId: "conversation-1",
      addFiles,
      clearFiles,
      conversations: [buildConversation()],
      deleteConversation,
      error: null,
      isGenerating: false,
      removeFile,
      removePendingZipContext: vi.fn(),
      runtimeStatus: "ready",
      sendMessage,
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [
        buildAttachment({
          id: "attachment-zip-1",
          file: new File(["PK"], "project-docs.zip", { type: "application/zip" }),
          name: "project-docs.zip",
          type: "ZIP",
          size: 73498624,
          retainedForZipContext: true
        })
      ],
      webSearchEnabled: false,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    const attachmentList = screen.getByRole("list", { name: "待发送附件" });
    expect(within(attachmentList).getAllByText("project-docs.zip")).toHaveLength(1);
  });

  it("does not block send for ChatGPT ZIP follow-up even when the stored support flag is stale", async () => {
    const user = userEvent.setup();

    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        zipContext: {
          zipContextId: "zip-context-1",
          archiveName: "project-docs.zip",
          entryCount: 4,
          extractedEntryCount: 4,
          inventoryOnlyCount: 0,
          skippedEntryCount: 0,
          supportedByCurrentModel: false,
          unsupportedReason: "当前模型不支持 ZIP 文件问答，请切换其他模型。"
        }
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "chatgpt-5.5-official",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    await user.type(screen.getByRole("textbox"), "Explain the ZIP.");
    await user.click(within(screen.getByTestId("chat-input-dock")).getAllByRole("button").at(-1)!);

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith("Explain the ZIP.");
    });
    expect(screen.queryByText("当前模型不支持 ZIP 文件问答，请切换其他模型。")).toBeNull();
  });

  it("does not show stale ZIP unsupported errors for Cipher follow-up sends", async () => {
    const user = userEvent.setup();

    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        zipContext: {
          zipContextId: "zip-context-1",
          archiveName: "project-docs.zip",
          entryCount: 4,
          extractedEntryCount: 4,
          inventoryOnlyCount: 0,
          skippedEntryCount: 0,
          supportedByCurrentModel: false,
          unsupportedReason: "当前模型不支持 ZIP 文件问答，请切换其他模型。"
        }
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    await user.type(screen.getByRole("textbox"), "Explain the ZIP.");
    await user.click(within(screen.getByTestId("chat-input-dock")).getAllByRole("button").at(-1)!);

    await waitFor(() => {
      expect(sendMessage).toHaveBeenCalledWith("Explain the ZIP.");
    });
    expect(
      screen.queryByText("当前模型不支持 ZIP 文件问答，请切换其他模型。")
    ).toBeNull();
  });

  it("routes a selected ZIP file through uploadZip instead of addFiles", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();

    const zipFile = new File(["PK"], "project-docs.zip", { type: "application/zip" });
    await user.upload(input!, zipFile);

    await waitFor(() => {
      expect(uploadZip).toHaveBeenCalledWith(zipFile, "");
    });
    expect(addFiles).not.toHaveBeenCalled();
  });

  it("shows a composer error when ZIP upload from file selection fails", async () => {
    const user = userEvent.setup();
    uploadZip.mockRejectedValueOnce(new Error("ZIP 上传失败"));
    render(<AppShell onLogout={onLogout} />);

    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();

    const zipFile = new File(["PK"], "broken.zip", { type: "application/zip" });
    await user.upload(input!, zipFile);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("ZIP 上传失败");
    });
    expect(addFiles).not.toHaveBeenCalled();
  });

  it("splits mixed file selection so ZIP uploads separately and normal files stay staged", async () => {
    const user = userEvent.setup();
    render(<AppShell onLogout={onLogout} />);

    const input = document.querySelector<HTMLInputElement>('input[type="file"]');
    expect(input).not.toBeNull();

    const zipFile = new File(["PK"], "project-docs.zip", { type: "application/zip" });
    const pdfFile = new File(["notes"], "semester-plan.pdf", { type: "application/pdf" });
    await user.upload(input!, [zipFile, pdfFile]);

    await waitFor(() => {
      expect(uploadZip).toHaveBeenCalledWith(zipFile, "");
    });
    expect(addFiles).toHaveBeenCalledWith([pdfFile]);
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [buildAttachment({ name: "campus-notes.pdf" })],
      webSearchEnabled: false,
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    const stagedList = document.querySelector(".bomb-shell__attachment-list");
    expect(stagedList).not.toBeNull();
    expect(within(stagedList as HTMLElement).getByText("campus-notes.pdf")).toBeInTheDocument();
    expect(
      (stagedList as HTMLElement)
        .querySelector<HTMLElement>(".bomb-shell__attachment-icon")
        ?.getAttribute("data-file-icon")
    ).toBe("pdf");

    await user.click(within(stagedList as HTMLElement).getByRole("button"));

    expect(removeFile).toHaveBeenCalledWith("attachment-1");
  });

  it("renders historical user attachments with the user message content", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "user",
            content: "Please review the attached draft.",
            createdAt: "2026-07-03T10:00:00.000Z",
            attachments: [
              {
                id: "attachment-1",
                name: "brief.docx",
                type: "DOCX",
                size: 2048
              }
            ]
          },
          {
            id: "message-2",
            role: "assistant",
            content: "I can help with that.",
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    const firstUserMessage = screen.getByTestId("message-row-message-1");
    const attachmentList = within(firstUserMessage).getByRole("list", { name: "消息附件" });
    const attachmentCard = within(attachmentList).getByRole("listitem");

    expect(within(firstUserMessage).getByText("Please review the attached draft.")).toBeInTheDocument();
    expect(attachmentCard).toHaveTextContent("brief.docx");
    expect(attachmentCard).toHaveTextContent("DOCX");
    expect(attachmentCard).toHaveTextContent("2 KB");
    expect(
      attachmentCard.querySelector<HTMLElement>(".bomb-shell__attachment-icon")?.getAttribute("data-file-icon")
    ).toBe("word");
  });

  it("renders ZIP attachments in the message history with the same card style", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "user",
            content: "Please answer based on the ZIP.",
            createdAt: "2026-07-03T10:00:00.000Z",
            attachments: [
              {
                id: "attachment-zip-1",
                name: "desktop.zip",
                type: "ZIP",
                size: 0,
                meta: "ZIP · 已扫描 2 项 · 已提取 1 项 · 仅清单 1 项"
              } as never
            ]
          },
          {
            id: "message-2",
            role: "assistant",
            content: "I can help with that.",
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    const firstUserMessage = screen.getByTestId("message-row-message-1");
    const attachmentList = within(firstUserMessage).getByRole("list", { name: "消息附件" });
    const attachmentCard = within(attachmentList).getByRole("listitem");

    expect(attachmentCard).toHaveTextContent("desktop.zip");
    expect(attachmentCard).toHaveTextContent("ZIP");
    expect(
      attachmentCard.querySelector<HTMLElement>(".bomb-shell__attachment-icon")?.getAttribute("data-file-icon")
    ).toBe("zip");
  });

  it("renders historical attachment cards only for the attachment-bearing first user turn", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "user",
            content: "Please review the attached draft.",
            createdAt: "2026-07-03T10:00:00.000Z",
            attachments: [
              {
                id: "attachment-1",
                name: "brief.docx",
                type: "DOCX",
                size: 2048
              }
            ]
          },
          {
            id: "message-2",
            role: "assistant",
            content: "I can help with that.",
            createdAt: "2026-07-03T10:00:01.000Z"
          },
          {
            id: "message-3",
            role: "user",
            content: "Also summarize the risks in plain text.",
            createdAt: "2026-07-03T10:00:02.000Z"
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "deepseek-v4-flash",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    const messageAttachments = screen.getAllByRole("list", { name: "消息附件" });
    const firstUserMessage = screen.getByTestId("message-row-message-1");
    const laterUserMessage = screen.getByTestId("message-row-message-3");

    expect(messageAttachments).toHaveLength(1);
    expect(within(firstUserMessage).getByRole("list", { name: "消息附件" })).toBeInTheDocument();
    expect(within(firstUserMessage).getByText("brief.docx")).toBeInTheDocument();
    expect(within(laterUserMessage).queryByRole("list", { name: "消息附件" })).toBeNull();
    expect(within(laterUserMessage).queryByText("brief.docx")).toBeNull();
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

  it("opens the conversation drawer with a left-edge swipe on mobile", () => {
    setMobileViewport(true);
    render(<AppShell onLogout={onLogout} />);

    const mainRegion = document.querySelector(".bomb-shell__main");
    expect(mainRegion).not.toBeNull();

    fireEvent.touchStart(mainRegion!, {
      touches: [{ clientX: 8, clientY: 220 }],
      changedTouches: [{ clientX: 8, clientY: 220 }]
    });
    fireEvent.touchMove(mainRegion!, {
      touches: [{ clientX: 104, clientY: 228 }],
      changedTouches: [{ clientX: 104, clientY: 228 }]
    });
    fireEvent.touchEnd(mainRegion!, {
      changedTouches: [{ clientX: 104, clientY: 228 }]
    });

    expect(document.querySelector(".conversation-drawer")).not.toBeNull();
  });

  it("closes the conversation drawer with a swipe on mobile", async () => {
    const user = userEvent.setup();
    setMobileViewport(true);
    render(<AppShell onLogout={onLogout} />);

    const headerButton = within(screen.getByRole("banner")).getAllByRole("button")[0];
    await user.click(headerButton);

    const drawerPanel = document.querySelector(".conversation-drawer__panel");
    expect(drawerPanel).not.toBeNull();

    fireEvent.touchStart(drawerPanel!, {
      touches: [{ clientX: 240, clientY: 260 }],
      changedTouches: [{ clientX: 240, clientY: 260 }]
    });
    fireEvent.touchMove(drawerPanel!, {
      touches: [{ clientX: 120, clientY: 266 }],
      changedTouches: [{ clientX: 120, clientY: 266 }]
    });
    fireEvent.touchEnd(drawerPanel!, {
      changedTouches: [{ clientX: 120, clientY: 266 }]
    });

    await waitFor(() => {
      expect(document.querySelector(".conversation-drawer")?.getAttribute("aria-hidden")).toBe("true");
    });
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

    fireEvent.dragEnter(screen.getByRole("complementary", { name: "会话导航" }), {
      dataTransfer
    });

    expect(document.querySelector(".bomb-shell__drop-overlay")).toBeNull();
    expect(addFiles).not.toHaveBeenCalled();

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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
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

    await user.click(screen.getAllByRole("button").find((button) => button.getAttribute("aria-label")?.includes("会话") || button.getAttribute("aria-label")?.includes("sidebar"))!);
    await user.click(screen.getByRole("button", { name: "开启新对话" }));

    expect(clearFiles).toHaveBeenCalled();
    expect(setActiveConversationId).toHaveBeenCalledWith(null);

    currentHookState = emptyHookState;
    rerender(<AppShell onLogout={onLogout} />);

    const log = screen.getByRole("log");
    expect(log.className).toContain("bomb-shell__message-stage--empty");
    expect(log.scrollTop).toBe(0);
    expect(document.querySelector(".bomb-shell__landing")).not.toBeNull();
    expect(document.querySelector(".bomb-shell__dock-wrap--centered")).not.toBeNull();
    expect(screen.getByRole("heading", { name: "从哪条线索开始？" })).toBeInTheDocument();
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
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

  it("renders parenthesized latex-style math often returned in chinese answers", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content:
              "对于该信号，基础角频率为 (\\omega_0 = 2\\pi/T = 14 , \\text{rad/s})。\n\n并且有 ( y(t) = x(t) )。",
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByText((content) => content.includes("对于该信号"))).toBeInTheDocument();
    expectReadableMath(2);
  });

  it("renders standard mathjax inline delimiters", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content: "基础周期为 \\( T = \\pi/7 \\)，频率为 \\( \\omega_0 = 14 \\)。",
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByText((content) => content.includes("基础周期") || content.includes("14"))).toBeInTheDocument();
    expectReadableMath(2);
  });

  it("renders bare multiline latex blocks and standalone equations from model answers", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content: `解答：
系统频率响应为
H(j\\omega)=\\begin{cases}
1, & |\\omega| \\geq 250 \\\\
0, & \\text{其他}
\\end{cases}

输入信号 x(t) 的基波周期 T = \\pi/7，因此基波角频率 \\omega_0 = \\frac{2\\pi}{T} = 14 \\text{ rad/s}.

周期信号 x(t) 可以表示为傅里叶级数 x(t)=\\sum_{k=-\\infty}^{\\infty} c_k e^{jk\\omega_0 t}

通过系统后输出 y(t)=\\sum_{k=-\\infty}^{\\infty} c_k H(jk\\omega_0)e^{jk\\omega_0 t}.`,
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByText((content) => content.includes("系统频率响应为"))).toBeInTheDocument();
    expectReadableMath(3);
  });

  it("renders latex lines that include chinese text blocks and malformed escaped dollar delimiters", () => {
    vi.mocked(useServerChatModule.useServerChat).mockReturnValue({
      activeConversation: {
        ...buildConversation(),
        messages: [
          {
            id: "message-1",
            role: "assistant",
            content: `第三步：利用积分条件确定 a 和 b

- 区间 [-0.5, 0.5]：仅有 t = 0 处的冲激，因此 \\int_{-0.5}^{0.5} x(t) \\, dt = 1.5(a+b) = 1 \\quad \\Rightarrow \\quad a+b = \\frac{2}{3}. \\tag{1}

- 区间 [0, 2]：包含 $t=0$ 和 $t=1.5$，因此 \\int_{0}^{2} x(t) \\, dt = 1.5(a+b) + 1.5(a-b) = 3a = 2 \\quad \\Rightarrow \\quad a = \\frac{2}{3}. \\tag{2}

代入 (1) 得 \\$b = 0$。
最终答案为：\\boxed{C_k = \\begin{cases} \\frac{2}{3}, & k \\text{为偶数} \\\\ 0, & k \\text{为奇数} \\end{cases}}`,
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
      submitCapeCase,
      refreshCapeCase,
      setWebSearchEnabled,
      uploadZip,
      setActiveConversationId,
      setModelId,
      stagedFiles: [],
      webSearchEnabled: false,
      settings: {
        modelId: "Llama-3.1-8B-Instruct-q4f32_1-MLC",
        systemPrompt: "You are a helpful assistant."
      }
    });

    render(<AppShell onLogout={onLogout} />);

    expect(screen.getByText((content) => content.includes("第三步"))).toBeInTheDocument();
    expectReadableMath(3);
  });
});
