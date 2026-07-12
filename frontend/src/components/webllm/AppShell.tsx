import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type DragEvent,
  type KeyboardEvent,
  type TouchEvent
} from "react";
import {
  IconArrowUp,
  IconCheck,
  IconChevronDown,
  IconExternalLink,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconMessage,
  IconPaperclip,
  IconPlayerStopFilled,
  IconSettings,
  IconUserCircle,
  IconWorld,
  IconX
} from "@tabler/icons-react";

import {
  buildZipAttachmentMeta as formatZipAttachmentMeta,
  MODEL_PROVIDER_LABELS,
  MODEL_PROVIDER_ORDER,
  getDeepSeekModelLabel,
  getDeepSeekModelProvider,
  getDeepSeekModelsByProvider,
  isZipContextSupportedModel,
  resolveDeepSeekModelId,
  ZIP_UNSUPPORTED_MODEL_REASON,
  type DeepSeekModelId,
  type ModelProvider,
  type RuntimeStatus
} from "../../types";
import cipherLogo from "../../assets/cipher-logo-tight.png";
import { useServerChat } from "../../hooks/useServerChat";
import { AuroraBackground } from "../AuroraBackground";
import { AttachmentTypeIcon } from "./AttachmentTypeIcon";
import { MessageContent } from "./MessageContent";
import { SettingsDrawer } from "./SettingsDrawer";

type AppShellProps = {
  onLogout: () => Promise<void> | void;
  sessionError?: string | null;
};

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])'
].join(", ");

const MODEL_MENU_CLOSE_MS = 220;
const ERROR_BANNER_CLOSE_MS = 3600;
const MODEL_SUBMENU_ID = "webllm-model-submenu";
const MOBILE_EDGE_SWIPE_START_PX = 28;
const MOBILE_SWIPE_TRIGGER_PX = 64;
const MOBILE_SWIPE_VERTICAL_TOLERANCE_PX = 72;

type ModelButtonRefMap = Partial<Record<DeepSeekModelId, HTMLButtonElement | null>>;
type ProviderButtonRefMap = Partial<Record<ModelProvider, HTMLButtonElement | null>>;
type TouchSwipeState = {
  mode: "idle" | "open-drawer" | "close-drawer";
  startX: number;
  startY: number;
  deltaX: number;
  deltaY: number;
};

function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) {
    return [];
  }

  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

function trapFocus(event: KeyboardEvent<HTMLElement>, container: HTMLElement | null) {
  const focusableElements = getFocusableElements(container);

  if (focusableElements.length === 0) {
    event.preventDefault();
    return;
  }

  const firstElement = focusableElements[0];
  const lastElement = focusableElements[focusableElements.length - 1];
  const activeElement = document.activeElement as HTMLElement | null;

  if (event.shiftKey) {
    if (!activeElement || activeElement === firstElement || !container?.contains(activeElement)) {
      event.preventDefault();
      lastElement.focus();
    }
    return;
  }

  if (activeElement === lastElement) {
    event.preventDefault();
    firstElement.focus();
  }
}

function isMobileViewport(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  if (typeof window.matchMedia === "function") {
    return window.matchMedia("(max-width: 760px)").matches;
  }

  return window.innerWidth <= 760;
}

function isTabletLandscapeViewport(): boolean {
  if (typeof window === "undefined") {
    return false;
  }

  if (typeof window.matchMedia === "function") {
    return window.matchMedia("(min-width: 761px) and (max-width: 1180px) and (orientation: landscape)").matches;
  }

  return window.innerWidth >= 761 && window.innerWidth <= 1180 && window.innerWidth > window.innerHeight;
}

function getTouchPoint(event: TouchEvent<HTMLElement>) {
  return event.touches[0] ?? event.changedTouches[0] ?? null;
}

function isTouchInteractiveTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }

  return Boolean(target.closest("button, a, input, textarea, select, label, summary, [role='button']"));
}

function buildIdleTouchSwipeState(): TouchSwipeState {
  return {
    mode: "idle",
    startX: 0,
    startY: 0,
    deltaX: 0,
    deltaY: 0
  };
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

function formatAttachmentSize(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }

  if (size < 1024 * 1024) {
    return `${Math.round(size / 102.4) / 10} KB`;
  }

  return `${Math.round(size / 104857.6) / 10} MB`;
}

function formatAttachmentMeta(type: string, size: number): string {
  return `${type} · ${formatAttachmentSize(size)}`;
}

function isNearBottom(element: HTMLElement, threshold = 120): boolean {
  const distanceToBottom = element.scrollHeight - element.scrollTop - element.clientHeight;
  return distanceToBottom <= threshold;
}

function scrollMessageStageToLatestMessage(
  container: HTMLElement,
  messageElement: HTMLElement,
  behavior: ScrollBehavior
) {
  const reservedBottomSpace = 206;
  const maxScrollTop = container.scrollHeight - container.clientHeight;
  const nextScrollTop = Math.max(
    0,
    Math.min(
      messageElement.offsetTop + messageElement.offsetHeight - (container.clientHeight - reservedBottomSpace),
      maxScrollTop
    )
  );

  if (typeof container.scrollTo === "function") {
    container.scrollTo({
      top: nextScrollTop,
      behavior
    });
    return;
  }

  container.scrollTop = nextScrollTop;
}

function buildShellStatus(runtimeStatus: RuntimeStatus, isGenerating: boolean) {
  if (runtimeStatus === "error") {
    return {
      label: "异常",
      footer: "连接异常",
      header: "运行时不可用",
      tone: "error"
    } as const;
  }

  if (runtimeStatus === "loading" || isGenerating) {
    return {
      label: "生成中",
      footer: "正在生成回复",
      header: "正在输出内容",
      tone: "loading"
    } as const;
  }

  if (runtimeStatus === "ready") {
    return {
      label: "就绪",
      footer: "共享推理服务已连接",
      header: "推理服务在线",
      tone: "ready"
    } as const;
  }

  return {
    label: "等待中",
    footer: "等待推理服务启动",
    header: "运行时准备中",
    tone: "idle"
  } as const;
}

export function AppShell({ onLogout, sessionError = null }: AppShellProps) {
  const [isSidebarOpen, setSidebarOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMounted, setDrawerMounted] = useState(false);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [modelMenuMounted, setModelMenuMounted] = useState(false);
  const [modelMenuVisible, setModelMenuVisible] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [isComposerFocused, setComposerFocused] = useState(false);
  const [mobileKeyboardOffset, setMobileKeyboardOffset] = useState(0);
  const [isTabletLandscape, setTabletLandscape] = useState(() => isTabletLandscapeViewport());
  const [composerError, setComposerError] = useState<string | null>(null);
  const [dismissedErrorMessage, setDismissedErrorMessage] = useState<string | null>(null);
  const [searchBannerMessage, setSearchBannerMessage] = useState<string | null>(null);
  const [contextMenuState, setContextMenuState] = useState<{
    conversationId: string;
    x: number;
    y: number;
  } | null>(null);
  const [isDragActive, setDragActive] = useState(false);
  const conversationsButtonRef = useRef<HTMLButtonElement | null>(null);
  const drawerPanelRef = useRef<HTMLDivElement | null>(null);
  const settingsButtonRef = useRef<HTMLButtonElement | null>(null);
  const modelMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const modelMenuRef = useRef<HTMLDivElement | null>(null);
  const modelProviderItemRefs = useRef<ProviderButtonRefMap>({});
  const modelSubmenuItemRefs = useRef<ModelButtonRefMap>({});
  const contextMenuRef = useRef<HTMLDivElement | null>(null);
  const messageStageRef = useRef<HTMLElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const lastMessageRef = useRef<HTMLDivElement | null>(null);
  const messagesEndRef = useRef<HTMLDivElement | null>(null);
  const hasOpenedDrawerRef = useRef(false);
  const shouldAutoScrollRef = useRef(true);
  const dragDepthRef = useRef(0);
  const drawerOpenFrameRef = useRef<number | null>(null);
  const modelMenuOpenFrameRef = useRef<number | null>(null);
  const previousMessageCountRef = useRef(0);
  const touchSwipeRef = useRef<TouchSwipeState>(buildIdleTouchSwipeState());

  const {
    activeConversation,
    activeConversationId,
    addFiles,
    clearFiles,
    conversations,
    deleteConversation,
    error,
    isGenerating,
    removePendingZipContext,
    removeFile,
    runtimeStatus,
    sendMessage,
    setWebSearchEnabled,
    uploadZip,
    setActiveConversationId,
    setModelId,
    stagedFiles,
    webSearchEnabled,
    settings
  } = useServerChat();
  const [activeModelProvider, setActiveModelProvider] = useState<ModelProvider>(() =>
    getDeepSeekModelProvider(resolveDeepSeekModelId(settings.modelId))
  );

  const shellStatus = useMemo(
    () => buildShellStatus(runtimeStatus, isGenerating),
    [runtimeStatus, isGenerating]
  );
  const modelId = resolveDeepSeekModelId(settings.modelId);
  const modelLabel = getDeepSeekModelLabel(modelId);
  const selectedProvider = getDeepSeekModelProvider(modelId);
  const activeProvider = activeModelProvider ?? selectedProvider;
  const activeProviderModels = getDeepSeekModelsByProvider(activeProvider);

  const messages = activeConversation?.messages ?? [];
  const activeZipContext = activeConversation?.zipContext;
  const pendingZipAttachmentMeta = activeZipContext ? formatZipAttachmentMeta(activeZipContext) : null;
  const retainedPendingZipAttachment =
    activeZipContext?.pendingAttachment && activeZipContext.archiveName
      ? stagedFiles.find(
          (attachment) =>
            attachment.retainedForZipContext &&
            attachment.type === "ZIP" &&
            attachment.name === activeZipContext.archiveName
        )
      : undefined;
  const visibleStagedFiles = retainedPendingZipAttachment
    ? stagedFiles.filter((attachment) => attachment.id !== retainedPendingZipAttachment.id)
    : stagedFiles;
  const activeZipSupportedBySelectedModel = !activeZipContext || isZipContextSupportedModel(modelId);
  const activeZipUnsupportedReason =
    activeZipContext && !activeZipSupportedBySelectedModel
      ? activeZipContext.unsupportedReason ?? ZIP_UNSUPPORTED_MODEL_REASON
      : null;
  const activeError = sessionError ?? composerError ?? error;
  const visibleError = activeError && activeError !== dismissedErrorMessage ? activeError : null;

  useEffect(() => {
    if (searchBannerMessage === null) {
      return;
    }

    const timer = window.setTimeout(() => {
      setSearchBannerMessage(null);
    }, 1800);

    return () => {
      window.clearTimeout(timer);
    };
  }, [searchBannerMessage]);

  useEffect(() => {
    if (activeError === null) {
      setDismissedErrorMessage(null);
      return;
    }

    if (activeError === dismissedErrorMessage) {
      return;
    }

    const timer = window.setTimeout(() => {
      setDismissedErrorMessage(activeError);
    }, ERROR_BANNER_CLOSE_MS);

    return () => {
      window.clearTimeout(timer);
    };
  }, [activeError, dismissedErrorMessage]);

  useEffect(() => {
    if (activeZipUnsupportedReason === null) {
      setComposerError(null);
    }
  }, [activeZipUnsupportedReason]);

  useEffect(() => {
    if (messages.length === 0) {
      shouldAutoScrollRef.current = true;
      previousMessageCountRef.current = 0;
      if (messageStageRef.current) {
        if (typeof messageStageRef.current.scrollTo === "function") {
          messageStageRef.current.scrollTo({
            top: 0,
            behavior: "auto"
          });
        } else {
          messageStageRef.current.scrollTop = 0;
        }
      }
      return;
    }

    if (!shouldAutoScrollRef.current) {
      previousMessageCountRef.current = messages.length;
      return;
    }

    if (messageStageRef.current && lastMessageRef.current) {
      const behavior = previousMessageCountRef.current < messages.length && !isGenerating ? "smooth" : "auto";
      scrollMessageStageToLatestMessage(messageStageRef.current, lastMessageRef.current, behavior);
    }

    previousMessageCountRef.current = messages.length;
  }, [messages, isGenerating]);

  useEffect(() => {
    if (!textareaRef.current) {
      return;
    }

    textareaRef.current.style.height = "auto";
    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 150)}px`;
  }, [draft]);

  useEffect(() => {
    if (drawerOpen) {
      hasOpenedDrawerRef.current = true;
      const firstFocusableElement = getFocusableElements(drawerPanelRef.current)[0];
      firstFocusableElement?.focus();
      return;
    }

    setDrawerVisible(false);

    const closeTimer = window.setTimeout(() => {
      setDrawerMounted(false);
    }, 320);

    if (hasOpenedDrawerRef.current) {
      hasOpenedDrawerRef.current = false;
      conversationsButtonRef.current?.focus();
    }

    return () => {
      window.clearTimeout(closeTimer);
    };
  }, [drawerOpen]);

  useEffect(() => {
    return () => {
      if (drawerOpenFrameRef.current !== null) {
        window.cancelAnimationFrame(drawerOpenFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    function handleViewportChange() {
      const mobile = isMobileViewport();
      const tabletLandscape = isTabletLandscapeViewport();

      setTabletLandscape(tabletLandscape);

      if (!mobile) {
        setDrawerOpen(false);
      }

      if (tabletLandscape) {
        setSidebarOpen(true);
        return;
      }

      if (mobile) {
        setSidebarOpen(false);
      }
    }

    handleViewportChange();
    window.addEventListener("resize", handleViewportChange);

    return () => {
      window.removeEventListener("resize", handleViewportChange);
    };
  }, []);

  useEffect(() => {
    if (!isComposerFocused || !isMobileViewport() || typeof window === "undefined") {
      setMobileKeyboardOffset(0);
      return;
    }

    const visualViewport = window.visualViewport;
    if (!visualViewport) {
      return;
    }

    const updateKeyboardOffset = () => {
      const nextOffset = Math.max(0, window.innerHeight - visualViewport.height - visualViewport.offsetTop);
      setMobileKeyboardOffset(nextOffset > 12 ? nextOffset : 0);
    };

    updateKeyboardOffset();
    visualViewport.addEventListener("resize", updateKeyboardOffset);
    visualViewport.addEventListener("scroll", updateKeyboardOffset);

    return () => {
      visualViewport.removeEventListener("resize", updateKeyboardOffset);
      visualViewport.removeEventListener("scroll", updateKeyboardOffset);
    };
  }, [isComposerFocused]);

  useEffect(() => {
    if (contextMenuState === null) {
      return;
    }

    function handlePointerDown(event: MouseEvent) {
      if (contextMenuRef.current?.contains(event.target as Node)) {
        return;
      }

      setContextMenuState(null);
    }

    function handleEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setContextMenuState(null);
      }
    }

    function handleScroll() {
      setContextMenuState(null);
    }

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    window.addEventListener("scroll", handleScroll, true);

    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
      window.removeEventListener("scroll", handleScroll, true);
    };
  }, [contextMenuState]);

  useEffect(() => {
    if (modelMenuOpen) {
      setModelMenuMounted(true);
      modelMenuOpenFrameRef.current = window.requestAnimationFrame(() => {
        modelMenuOpenFrameRef.current = window.requestAnimationFrame(() => {
          setModelMenuVisible(true);
          modelMenuOpenFrameRef.current = null;
        });
      });

      return () => {
        if (modelMenuOpenFrameRef.current !== null) {
          window.cancelAnimationFrame(modelMenuOpenFrameRef.current);
          modelMenuOpenFrameRef.current = null;
        }
      };
    }

    setModelMenuVisible(false);

    const closeTimer = window.setTimeout(() => {
      setModelMenuMounted(false);
    }, MODEL_MENU_CLOSE_MS);

    return () => {
      window.clearTimeout(closeTimer);
    };
  }, [modelMenuOpen]);

  useEffect(() => {
    return () => {
      if (modelMenuOpenFrameRef.current !== null) {
        window.cancelAnimationFrame(modelMenuOpenFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!modelMenuOpen) {
      return;
    }

    function handlePointerDown(event: MouseEvent) {
      if (
        modelMenuRef.current?.contains(event.target as Node) ||
        modelMenuButtonRef.current?.contains(event.target as Node)
      ) {
        return;
      }

      setModelMenuOpen(false);
    }

    function handleEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") {
        setModelMenuOpen(false);
        modelMenuButtonRef.current?.focus();
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);

    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [modelMenuOpen]);

  useEffect(() => {
    if (modelMenuOpen) {
      setActiveModelProvider(selectedProvider);
      const focusFrame = window.requestAnimationFrame(() => {
        focusProviderItem(selectedProvider);
      });

      return () => {
        window.cancelAnimationFrame(focusFrame);
      };
    }
  }, [modelMenuOpen, selectedProvider]);

  async function handleSend() {
    if (!draft.trim() || isGenerating) {
      return;
    }

    if (activeZipUnsupportedReason) {
      setComposerError(activeZipUnsupportedReason);
      return;
    }

    const nextDraft = draft;
    setComposerError(null);
    setDraft("");
    await sendMessage(nextDraft);
  }

  function handleNewConversation() {
    setDrawerOpen(false);
    clearFiles();
    setActiveConversationId(null);
  }

  function handleSelectConversation(conversationId: string) {
    setDrawerOpen(false);
    setContextMenuState(null);
    setComposerError(null);
    clearFiles();
    setActiveConversationId(conversationId);
  }

  async function routeIncomingFiles(files: File[]) {
    if (files.length === 0) {
      return;
    }

    const zipFiles: File[] = [];
    const standardFiles: File[] = [];

    for (const file of files) {
      if (file.name.toLowerCase().endsWith(".zip")) {
        zipFiles.push(file);
      } else {
        standardFiles.push(file);
      }
    }

    if (standardFiles.length > 0) {
      addFiles(standardFiles);
    }

    if (zipFiles.length === 0) {
      return;
    }

    setComposerError(null);

    try {
      for (const zipFile of zipFiles) {
        await uploadZip(zipFile, draft.trim());
      }
    } catch (nextError) {
      setComposerError(nextError instanceof Error ? nextError.message : "ZIP 上传失败，请稍后重试。");
    }
  }

  function handleFileSelection(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files ? Array.from(event.target.files) : [];
    void routeIncomingFiles(files);
    event.target.value = "";
  }

  function handleConversationDrawerOpen() {
    if (isTabletLandscapeViewport()) {
      setDrawerOpen(false);
      setSidebarOpen((previousState) => !previousState);
      return;
    }

    if (drawerOpen) {
      return;
    }

    if (drawerOpenFrameRef.current !== null) {
      window.cancelAnimationFrame(drawerOpenFrameRef.current);
      drawerOpenFrameRef.current = null;
    }

    function openDrawerWithAnimation() {
      setDrawerMounted(true);
      setDrawerOpen(true);
      drawerOpenFrameRef.current = window.requestAnimationFrame(() => {
        drawerOpenFrameRef.current = window.requestAnimationFrame(() => {
          setDrawerVisible(true);
          drawerOpenFrameRef.current = null;
        });
      });
    }

    if (isMobileViewport() || isSidebarOpen) {
      if (typeof window === "undefined") {
        setDrawerMounted(true);
        setDrawerOpen(true);
        setDrawerVisible(true);
        return;
      }

      openDrawerWithAnimation();
      return;
    }

    setSidebarOpen(true);
  }

  function resetTouchSwipe() {
    touchSwipeRef.current = buildIdleTouchSwipeState();
  }

  function handleMainTouchStart(event: TouchEvent<HTMLElement>) {
    if (!isMobileViewport() || drawerOpen || settingsOpen || modelMenuOpen) {
      resetTouchSwipe();
      return;
    }

    if (isTouchInteractiveTarget(event.target)) {
      resetTouchSwipe();
      return;
    }

    const point = getTouchPoint(event);
    if (!point || point.clientX > MOBILE_EDGE_SWIPE_START_PX) {
      resetTouchSwipe();
      return;
    }

    touchSwipeRef.current = {
      mode: "open-drawer",
      startX: point.clientX,
      startY: point.clientY,
      deltaX: 0,
      deltaY: 0
    };
  }

  function handleMainTouchMove(event: TouchEvent<HTMLElement>) {
    if (touchSwipeRef.current.mode !== "open-drawer") {
      return;
    }

    const point = getTouchPoint(event);
    if (!point) {
      return;
    }

    touchSwipeRef.current = {
      ...touchSwipeRef.current,
      deltaX: point.clientX - touchSwipeRef.current.startX,
      deltaY: point.clientY - touchSwipeRef.current.startY
    };
  }

  function handleMainTouchEnd() {
    const swipe = touchSwipeRef.current;
    if (
      swipe.mode === "open-drawer" &&
      swipe.deltaX >= MOBILE_SWIPE_TRIGGER_PX &&
      Math.abs(swipe.deltaY) <= MOBILE_SWIPE_VERTICAL_TOLERANCE_PX
    ) {
      handleConversationDrawerOpen();
    }

    resetTouchSwipe();
  }

  function handleDrawerTouchStart(event: TouchEvent<HTMLElement>) {
    if (!drawerOpen || !isMobileViewport()) {
      resetTouchSwipe();
      return;
    }

    const point = getTouchPoint(event);
    if (!point || isTouchInteractiveTarget(event.target)) {
      resetTouchSwipe();
      return;
    }

    touchSwipeRef.current = {
      mode: "close-drawer",
      startX: point.clientX,
      startY: point.clientY,
      deltaX: 0,
      deltaY: 0
    };
  }

  function handleDrawerTouchMove(event: TouchEvent<HTMLElement>) {
    if (touchSwipeRef.current.mode !== "close-drawer") {
      return;
    }

    const point = getTouchPoint(event);
    if (!point) {
      return;
    }

    touchSwipeRef.current = {
      ...touchSwipeRef.current,
      deltaX: point.clientX - touchSwipeRef.current.startX,
      deltaY: point.clientY - touchSwipeRef.current.startY
    };
  }

  function handleDrawerTouchEnd() {
    const swipe = touchSwipeRef.current;
    if (
      swipe.mode === "close-drawer" &&
      swipe.deltaX <= -MOBILE_SWIPE_TRIGGER_PX &&
      Math.abs(swipe.deltaY) <= MOBILE_SWIPE_VERTICAL_TOLERANCE_PX
    ) {
      setDrawerOpen(false);
    }

    resetTouchSwipe();
  }

  function isFileDrag(event: DragEvent<HTMLElement>): boolean {
    return event.dataTransfer?.types.includes("Files") ?? false;
  }

  function handleMainDragEnter(event: DragEvent<HTMLElement>) {
    if (!isFileDrag(event)) {
      return;
    }

    event.preventDefault();
    dragDepthRef.current += 1;
    setDragActive(true);
  }

  function handleMainDragOver(event: DragEvent<HTMLElement>) {
    if (!isFileDrag(event)) {
      return;
    }

    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }

  function handleMainDragLeave(event: DragEvent<HTMLElement>) {
    if (!isFileDrag(event)) {
      return;
    }

    event.preventDefault();
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1);

    if (dragDepthRef.current === 0) {
      setDragActive(false);
    }
  }

  function handleMainDrop(event: DragEvent<HTMLElement>) {
    if (!isFileDrag(event)) {
      return;
    }

    event.preventDefault();
    dragDepthRef.current = 0;
    setDragActive(false);

    const files = Array.from(event.dataTransfer.files ?? []);

    if (files.length > 0) {
      void routeIncomingFiles(files);
    }
  }

  function handleMessageStageScroll() {
    if (!messageStageRef.current || messages.length === 0) {
      return;
    }

    shouldAutoScrollRef.current = isNearBottom(messageStageRef.current);
  }

  function focusProviderItem(provider: ModelProvider) {
    modelProviderItemRefs.current[provider]?.focus();
  }

  function focusFirstModelForProvider(provider: ModelProvider) {
    const firstModel = getDeepSeekModelsByProvider(provider)[0];

    if (!firstModel) {
      return;
    }

    modelSubmenuItemRefs.current[firstModel.id]?.focus();
  }

  function handleProviderKeyDown(event: KeyboardEvent<HTMLButtonElement>, provider: ModelProvider) {
    const providerIndex = MODEL_PROVIDER_ORDER.indexOf(provider);

    if (event.key === "ArrowDown") {
      event.preventDefault();
      const nextProvider = MODEL_PROVIDER_ORDER[(providerIndex + 1) % MODEL_PROVIDER_ORDER.length];
      setActiveModelProvider(nextProvider);
      focusProviderItem(nextProvider);
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      const nextProvider = MODEL_PROVIDER_ORDER[
        (providerIndex - 1 + MODEL_PROVIDER_ORDER.length) % MODEL_PROVIDER_ORDER.length
      ];
      setActiveModelProvider(nextProvider);
      focusProviderItem(nextProvider);
      return;
    }

    if (event.key === "ArrowRight") {
      event.preventDefault();
      setActiveModelProvider(provider);
      focusFirstModelForProvider(provider);
      return;
    }

    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      setActiveModelProvider(provider);
    }
  }

  function handleModelMenuItemKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const activeModelIndex = activeProviderModels.findIndex(
      (option) => modelSubmenuItemRefs.current[option.id] === event.currentTarget
    );

    if (event.key === "ArrowDown") {
      event.preventDefault();
      const nextOption = activeProviderModels[(activeModelIndex + 1) % activeProviderModels.length];
      modelSubmenuItemRefs.current[nextOption?.id]?.focus();
      return;
    }

    if (event.key === "ArrowUp") {
      event.preventDefault();
      const nextOption =
        activeProviderModels[(activeModelIndex - 1 + activeProviderModels.length) % activeProviderModels.length];
      modelSubmenuItemRefs.current[nextOption?.id]?.focus();
      return;
    }

    if (event.key === "ArrowLeft") {
      event.preventDefault();
      focusProviderItem(activeProvider);
    }
  }

  function handleModelSelect(nextModelId: DeepSeekModelId) {
    setModelId(nextModelId);
    setModelMenuOpen(false);
  }

  function handleWebSearchToggle() {
    const nextEnabled = !webSearchEnabled;
    setWebSearchEnabled(nextEnabled);
    setSearchBannerMessage(nextEnabled ? "已启用联网搜索" : "已关闭联网搜索");
  }

  function renderSidebarContent() {
    return (
      <div className="bomb-shell__sidebar-content">
        <div className="bomb-shell__sidebar-top">
          <div className="bomb-shell__logo-row">
            <span className="bomb-shell__logo">
              <img className="bomb-shell__logo-mark" src={cipherLogo} alt="" aria-hidden="true" />
              <span>Cipher AI</span>
            </span>
            <button
              type="button"
              className="bomb-shell__icon-button"
              aria-label="收起会话栏"
              onClick={() => {
                setSidebarOpen(false);
                setDrawerOpen(false);
              }}
            >
              <IconLayoutSidebarLeftCollapse size={18} stroke={1.8} aria-hidden="true" />
            </button>
          </div>

          <button
            className="bomb-shell__new-chat"
            type="button"
            onClick={handleNewConversation}
            disabled={isGenerating}
          >
            <span>开启新对话</span>
          </button>
        </div>

        <div className="bomb-shell__sidebar-list-wrap">
          <p className="bomb-shell__sidebar-label">最近对话记录</p>

          {conversations.length === 0 ? (
            <div className="bomb-shell__sidebar-empty">
              <p className="eyebrow">暂无会话</p>
              <h2>开始新的对话</h2>
              <p>你发起的新对话会显示在这里。</p>
            </div>
          ) : (
            <div className="bomb-shell__sidebar-list">
              {conversations.map((conversation) => {
                const isActive = conversation.id === activeConversationId;

                return (
                  <button
                    key={conversation.id}
                    className={`bomb-shell__sidebar-item${isActive ? " bomb-shell__sidebar-item--active" : ""}`}
                    type="button"
                    onClick={() => handleSelectConversation(conversation.id)}
                    onContextMenu={(event) => {
                      event.preventDefault();
                      setContextMenuState({
                        conversationId: conversation.id,
                        x: event.clientX,
                        y: event.clientY
                      });
                    }}
                    disabled={isGenerating}
                    aria-pressed={isActive}
                  >
                    <span className="bomb-shell__sidebar-item-title">
                      <IconMessage size={16} stroke={1.8} aria-hidden="true" />
                      <span>{conversation.title}</span>
                    </span>
                    <small>{formatTimestamp(conversation.updatedAt)}</small>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="bomb-shell__profile">
          <button
            className="bomb-shell__profile-card"
            type="button"
            ref={settingsButtonRef}
            onClick={() => setSettingsOpen(true)}
          >
            <div className="bomb-shell__profile-avatar">
              <IconUserCircle size={18} stroke={1.8} />
            </div>
            <div className="bomb-shell__profile-copy">
              <span>Designer.Dev</span>
              <small>打开设置</small>
            </div>
            <IconSettings className="bomb-shell__profile-gear" size={16} stroke={1.8} aria-hidden="true" />
          </button>
        </div>
      </div>
    );
  }

  function renderComposer(layout: "centered" | "docked") {
    return (
      <div
        className={`bomb-shell__dock-wrap${layout === "centered" ? " bomb-shell__dock-wrap--centered" : ""}`}
        data-testid="chat-input-dock"
      >
        {activeZipContext?.pendingAttachment || visibleStagedFiles.length > 0 ? (
          <div className="bomb-shell__attachments" aria-live="polite">
            <ul className="bomb-shell__attachment-list" aria-label="待发送附件">
              {activeZipContext?.pendingAttachment ? (
                <li className="bomb-shell__attachment-chip">
                  <AttachmentTypeIcon
                    className="bomb-shell__attachment-icon"
                    name={activeZipContext.archiveName}
                    type="ZIP"
                  />
                  <span className="bomb-shell__attachment-copy">
                    <span className="bomb-shell__attachment-name">{activeZipContext.archiveName}</span>
                    <span className="bomb-shell__attachment-meta">{pendingZipAttachmentMeta}</span>
                  </span>
                  <button
                    type="button"
                    className="bomb-shell__attachment-remove"
                    aria-label={`移除附件 ${activeZipContext.archiveName}`}
                    onClick={() => {
                      removePendingZipContext?.();
                      if (retainedPendingZipAttachment) {
                        removeFile(retainedPendingZipAttachment.id);
                      }
                    }}
                  >
                    <IconX size={14} stroke={2} aria-hidden="true" />
                  </button>
                </li>
              ) : null}
              {visibleStagedFiles.map((attachment) => (
                <li key={attachment.id} className="bomb-shell__attachment-chip">
                  <AttachmentTypeIcon
                    className="bomb-shell__attachment-icon"
                    name={attachment.name}
                    type={attachment.type}
                  />
                  <span className="bomb-shell__attachment-copy">
                    <span className="bomb-shell__attachment-name">{attachment.name}</span>
                    <span className="bomb-shell__attachment-meta">
                      {attachment.type} · {formatAttachmentSize(attachment.size)}
                    </span>
                  </span>
                  <button
                    type="button"
                    className="bomb-shell__attachment-remove"
                    aria-label={`移除附件 ${attachment.name}`}
                    onClick={() => removeFile(attachment.id)}
                  >
                    <IconX size={14} stroke={2} aria-hidden="true" />
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <form
          className={`bomb-shell__dock${layout === "centered" ? " bomb-shell__dock--centered" : ""}`}
          aria-label="消息输入框"
          onSubmit={(event) => {
            event.preventDefault();
            void handleSend();
          }}
        >
          <label className="sr-only" htmlFor="prompt-composer-message">
            消息内容
          </label>
          <input
            ref={fileInputRef}
            className="sr-only"
            type="file"
            multiple
            tabIndex={-1}
            onChange={handleFileSelection}
          />
          <button
            className="bomb-shell__dock-tool"
            type="button"
            aria-label="添加附件"
            onClick={() => fileInputRef.current?.click()}
            disabled={isGenerating}
          >
            <IconPaperclip size={18} stroke={1.8} />
          </button>

          <button
            className={`bomb-shell__dock-tool${webSearchEnabled ? " bomb-shell__dock-tool--search bomb-shell__dock-tool--active" : ""}`}
            type="button"
            aria-label={webSearchEnabled ? "关闭联网搜索" : "启用联网搜索"}
            aria-pressed={webSearchEnabled}
            onClick={handleWebSearchToggle}
            disabled={isGenerating}
          >
            <IconWorld size={18} stroke={1.8} />
          </button>

          <textarea
            ref={textareaRef}
            id="prompt-composer-message"
            name="message"
            className="bomb-shell__dock-input"
            value={draft}
            onChange={(event) => {
              if (composerError) {
                setComposerError(null);
              }
              setDraft(event.target.value);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                void handleSend();
              }
            }}
            placeholder="向 Cipher AI 输入你的问题..."
            rows={1}
            disabled={isGenerating}
          />

          <button
            className={`bomb-shell__send-button${draft.trim() ? " bomb-shell__send-button--active" : ""}`}
            type="submit"
            aria-label={isGenerating ? "生成中" : "发送消息"}
            disabled={!draft.trim() || isGenerating}
          >
            {isGenerating ? <IconPlayerStopFilled size={18} /> : <IconArrowUp size={18} stroke={2} />}
          </button>
        </form>

        <div className="bomb-shell__dock-footer">
          <span className={`bomb-shell__runtime-pill bomb-shell__runtime-pill--${shellStatus.tone}`}>
            {shellStatus.label}
          </span>
          <span>Cipher AI 是一款 AI 工具，其回答未必正确无误。</span>
        </div>
      </div>
    );
  }

  return (
    <main className="webllm-shell bomb-shell" data-testid="chat-shell">
      <AuroraBackground testId="aurora-background" />

      <div className="bomb-shell__root" aria-hidden={drawerOpen || settingsOpen ? "true" : undefined}>
        <div
          className={`bomb-shell__sidebar-spacer${isSidebarOpen ? " bomb-shell__sidebar-spacer--open" : ""}`}
          aria-hidden="true"
        />

        <aside
          className={`bomb-shell__sidebar${isSidebarOpen ? " bomb-shell__sidebar--open" : ""}`}
          aria-label="Conversations"
        >
          {renderSidebarContent()}
        </aside>

        <div
          className={`bomb-shell__main${isSidebarOpen ? " bomb-shell__main--sidebar-open" : ""}${
            isDragActive ? " bomb-shell__main--drag-active" : ""
          }`}
          onDragEnter={handleMainDragEnter}
          onDragOver={handleMainDragOver}
          onDragLeave={handleMainDragLeave}
          onDrop={handleMainDrop}
          onTouchStart={handleMainTouchStart}
          onTouchMove={handleMainTouchMove}
          onTouchEnd={handleMainTouchEnd}
          onTouchCancel={handleMainTouchEnd}
        >
          <header className="bomb-shell__header" role="banner">
            <button
              type="button"
              className={`bomb-shell__icon-button bomb-shell__icon-button--header${
                isSidebarOpen ? " bomb-shell__icon-button--mobile" : ""
              }`}
              aria-label={isSidebarOpen ? "打开会话抽屉" : "展开会话栏"}
              ref={conversationsButtonRef}
              onClick={handleConversationDrawerOpen}
            >
              <IconLayoutSidebarLeftExpand size={18} stroke={1.8} aria-hidden="true" />
            </button>

            <button
              ref={modelMenuButtonRef}
              type="button"
              className={`bomb-shell__model-pill${modelMenuOpen ? " bomb-shell__model-pill--open" : ""}`}
              aria-label="切换模型"
              aria-haspopup="menu"
              aria-expanded={modelMenuOpen}
              onClick={() => setModelMenuOpen((previousState) => !previousState)}
            >
              <span>{modelLabel}</span>
              <IconChevronDown
                className={`bomb-shell__model-pill-chevron${modelMenuOpen ? " bomb-shell__model-pill-chevron--open" : ""}`}
                size={14}
                stroke={1.8}
                aria-hidden="true"
              />
            </button>

            {modelMenuMounted ? (
              <div
                ref={modelMenuRef}
                className={`bomb-shell__model-menu${
                  modelMenuVisible ? " bomb-shell__model-menu--open" : " bomb-shell__model-menu--closing"
                }`}
                role="menu"
                aria-label="模型列表"
                aria-hidden={modelMenuOpen ? undefined : "true"}
              >
                <div className="bomb-shell__model-provider-list">
                  {MODEL_PROVIDER_ORDER.map((provider) => {
                    const isSelected = provider === selectedProvider;
                    const isActive = provider === activeProvider;

                    return (
                      <button
                        key={provider}
                        type="button"
                        role="menuitem"
                        aria-haspopup="menu"
                        aria-expanded={isActive}
                        aria-controls={MODEL_SUBMENU_ID}
                        disabled={!modelMenuOpen}
                        className={`bomb-shell__model-provider-item${
                          isSelected ? " bomb-shell__model-provider-item--selected" : ""
                        }${isActive ? " bomb-shell__model-provider-item--active" : ""}`}
                        ref={(element) => {
                          modelProviderItemRefs.current[provider] = element;
                        }}
                        onMouseEnter={() => setActiveModelProvider(provider)}
                        onFocus={() => setActiveModelProvider(provider)}
                        onClick={() => setActiveModelProvider(provider)}
                        onKeyDown={(event) => handleProviderKeyDown(event, provider)}
                      >
                        {MODEL_PROVIDER_LABELS[provider]}
                      </button>
                    );
                  })}
                </div>

                <div id={MODEL_SUBMENU_ID} className="bomb-shell__model-submenu">
                  {activeProviderModels.map((option) => {
                    const isSelected = option.id === modelId;

                    return (
                      <button
                        key={option.id}
                        type="button"
                        role="menuitemradio"
                        disabled={!modelMenuOpen}
                        className={`bomb-shell__model-menu-item${
                          isSelected ? " bomb-shell__model-menu-item--selected" : ""
                        }`}
                        aria-checked={isSelected}
                        ref={(element) => {
                          modelSubmenuItemRefs.current[option.id] = element;
                        }}
                        onClick={() => handleModelSelect(option.id)}
                        onKeyDown={handleModelMenuItemKeyDown}
                      >
                        <span>{option.label}</span>
                        <span className="bomb-shell__model-menu-check" aria-hidden="true">
                          {isSelected ? <IconCheck size={14} stroke={2.2} /> : null}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ) : null}

            <div className="bomb-shell__header-actions">
              <button
                type="button"
                className="bomb-shell__icon-button bomb-shell__icon-button--header"
                aria-label="退出登录"
                onClick={() => void onLogout()}
              >
                <IconExternalLink size={18} stroke={1.8} aria-hidden="true" />
              </button>
            </div>
          </header>

          {visibleError ? (
            <p className="status-banner status-banner--error bomb-shell__top-alert" role="alert">
              {visibleError}
            </p>
          ) : null}

          {!visibleError && searchBannerMessage ? (
            <p className="status-banner status-banner--success bomb-shell__top-alert bomb-shell__top-toast" role="status">
              {searchBannerMessage}
            </p>
          ) : null}

          <section
            className={`bomb-shell__message-stage${messages.length === 0 ? " bomb-shell__message-stage--empty" : ""}`}
            aria-label="消息列表"
            role="log"
            aria-live="polite"
            ref={messageStageRef}
            onScroll={handleMessageStageScroll}
          >
            <div className="bomb-shell__message-stack">
              {messages.length === 0 ? (
                <div className="bomb-shell__landing">
                  <div className="bomb-shell__landing-copy">
                    <p className="bomb-shell__landing-title">需要我为你做些什么？</p>
                  </div>
                  {renderComposer("centered")}
                </div>
              ) : (
                messages.map((message, index) => {
                  const isUser = message.role === "user";
                  const isStreamingAssistant = !isUser && isGenerating && index === messages.length - 1;

                  return (
                    <div
                      key={message.id}
                      className={`bomb-shell__message-row${isUser ? " bomb-shell__message-row--user" : ""}`}
                      data-testid={`message-row-${message.id}`}
                      ref={index === messages.length - 1 ? lastMessageRef : null}
                    >
                      {!isUser ? (
                        <div className="bomb-shell__avatar bomb-shell__avatar--assistant">
                          <img className="bomb-shell__avatar-mark" src={cipherLogo} alt="" aria-hidden="true" />
                        </div>
                      ) : null}

                      <div
                        className={`bomb-shell__bubble${
                          isUser ? " bomb-shell__bubble--user" : " bomb-shell__bubble--assistant"
                        }`}
                      >
                        <div className="bomb-shell__bubble-copy">
                          {isUser && message.attachments && message.attachments.length > 0 ? (
                            <div className="bomb-shell__history-attachments">
                              <ul className="bomb-shell__history-attachment-list" aria-label="消息附件">
                                {message.attachments.map((attachment) => (
                                  <li key={attachment.id} className="bomb-shell__history-attachment-card">
                                    <AttachmentTypeIcon
                                      className="bomb-shell__attachment-icon bomb-shell__attachment-icon--history"
                                      name={attachment.name}
                                      type={attachment.type}
                                    />
                                    <span className="bomb-shell__history-attachment-copy">
                                      <span className="bomb-shell__history-attachment-name">{attachment.name}</span>
                                      <span className="bomb-shell__history-attachment-meta">
                                        {attachment.meta ?? formatAttachmentMeta(attachment.type, attachment.size)}
                                      </span>
                                    </span>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          ) : null}
                          <MessageContent content={message.content} />
                          {isStreamingAssistant ? <span className="bomb-shell__caret" aria-hidden="true" /> : null}
                        </div>
                      </div>

                      {isUser ? (
                        <div className="bomb-shell__avatar bomb-shell__avatar--user">
                          <IconUserCircle size={18} stroke={1.8} />
                        </div>
                      ) : null}
                    </div>
                  );
                })
              )}

              {messages.length > 0 ? <div ref={messagesEndRef} className="bomb-shell__message-anchor" /> : null}
            </div>
          </section>

          {messages.length > 0 ? renderComposer("docked") : null}

          {isDragActive ? (
            <div className="bomb-shell__drop-overlay" aria-hidden="true">
              <div className="bomb-shell__drop-overlay-card">
                <span className="bomb-shell__drop-overlay-title">拖入文件即可添加附件</span>
                <span className="bomb-shell__drop-overlay-copy">文件会暂存在输入框上方，发送这条消息时一起提交。</span>
              </div>
            </div>
          ) : null}
        </div>
      </div>

      {contextMenuState ? (
        <div
          ref={contextMenuRef}
          className="bomb-shell__context-menu"
          style={{
            left: `${contextMenuState.x}px`,
            top: `${contextMenuState.y}px`
          }}
          role="menu"
          aria-label="对话记录菜单"
        >
          <button
            type="button"
            className="bomb-shell__context-menu-item bomb-shell__context-menu-item--danger"
            onClick={() => {
              deleteConversation(contextMenuState.conversationId);
              setContextMenuState(null);
            }}
          >
            删除对话记录
          </button>
        </div>
      ) : null}

      {drawerOpen || drawerMounted ? (
        <div
          className={`conversation-drawer${drawerVisible ? " conversation-drawer--open" : ""}`}
          role="dialog"
          aria-label="会话抽屉"
          aria-modal="true"
          aria-hidden={drawerOpen ? undefined : "true"}
          id="conversation-drawer"
          onKeyDown={(event) => {
            if (!drawerOpen) {
              return;
            }

            if (event.key === "Escape") {
              setDrawerOpen(false);
              return;
            }

            if (event.key === "Tab") {
              trapFocus(event, drawerPanelRef.current);
            }
          }}
        >
          <button
            className="conversation-drawer__scrim"
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            onClick={() => setDrawerOpen(false)}
          />
          <div
            className="conversation-drawer__panel bomb-shell__drawer-panel"
            ref={drawerPanelRef}
            tabIndex={-1}
            onTouchStart={handleDrawerTouchStart}
            onTouchMove={handleDrawerTouchMove}
            onTouchEnd={handleDrawerTouchEnd}
            onTouchCancel={handleDrawerTouchEnd}
          >
            <aside className="bomb-shell__drawer-sidebar" aria-label="会话列表">
              {renderSidebarContent()}
            </aside>
          </div>
        </div>
      ) : null}

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        openerRef={settingsButtonRef}
        settings={settings}
      />
    </main>
  );
}
