import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type CSSProperties,
  type DragEvent,
  type KeyboardEvent,
  type TouchEvent
} from "react";
import {
  IconArrowsExchange,
  IconBiohazard,
  IconBriefcase,
  IconCheck,
  IconChevronDown,
  IconChevronRight,
  IconCopy,
  IconDownload,
  IconDots,
  IconEdit,
  IconExternalLink,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconMessage,
  IconPaperclip,
  IconPlayerPlay,
  IconPlayerStopFilled,
  IconPlus,
  IconRefresh,
  IconSearch,
  IconShieldSearch,
  IconSend2,
  IconSettings,
  IconSparkles,
  IconFileDescription,
  IconCode,
  IconThumbDown,
  IconThumbUp,
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
  type AuthUser,
  type CapeCase,
  type CapeExportFormat,
  type MessageEvidence,
  type ModelProvider,
  type RuntimeStatus,
  type SkillPackage,
  type AnalysisTemplate
} from "../../types";
import cipherLogo from "../../assets/cipher-mark.svg";
import { useServerChat } from "../../hooks/useServerChat";
import { downloadCapeCaseExport, getSkills, listAnalysisTemplates, submitMessageFeedback } from "../../lib/api";
import { AuroraBackground } from "../AuroraBackground";
import { ThemeToggle } from "../ThemeToggle";
import { AttachmentTypeIcon } from "./AttachmentTypeIcon";
import { CapeDrawer } from "./CapeDrawer";
import { CaseWorkspaceDrawer } from "./CaseWorkspaceDrawer";
import { MessageContent } from "./MessageContent";
import { SettingsDrawer } from "./SettingsDrawer";
import { NotificationCenter } from "./NotificationCenter";
import { createSkillInitialInput, SkillInputForm } from "../skills/SkillInputForm";
import { AnalysisTemplatePicker } from "../AnalysisTemplatePicker";

type AppShellProps = {
  onLogout: () => Promise<void> | void;
  onOpenAccount?: () => void;
  onOpenCases?: () => void;
  onOpenSkills?: () => void;
  onOpenJobs?: () => void;
  sessionError?: string | null;
  viewer?: AuthUser | null;
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
const MODEL_MENU_GAP_PX = 10;
const MODEL_MENU_VIEWPORT_PADDING_PX = 12;
const MODEL_MENU_DESKTOP_WIDTH_PX = 394;
const MODEL_MENU_DESKTOP_HEIGHT_PX = 190;
const MODEL_MENU_COMPACT_WIDTH_PX = 320;
const MODEL_MENU_COMPACT_HEIGHT_PX = 352;
const MODEL_MENU_PHONE_WIDTH_PX = 360;
const MODEL_MENU_PHONE_HEIGHT_PX = 190;
const ERROR_BANNER_CLOSE_MS = 3600;
const MODEL_SUBMENU_ID = "webllm-model-submenu";
const MOBILE_EDGE_SWIPE_START_PX = 28;
const MOBILE_SWIPE_TRIGGER_PX = 64;
const MOBILE_SWIPE_VERTICAL_TOLERANCE_PX = 72;
const MESSAGE_PAGE_SIZE = 60;
const LONG_MESSAGE_CHARACTERS = 1800;

function getCapeStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "排队中",
    running: "分析中",
    processing: "处理中",
    reported: "报告完成",
    failed_analysis: "分析失败",
    failed_processing: "处理失败",
    failed_reporting: "报告失败",
    recovered: "已恢复"
  };

  return labels[status] ?? status;
}

function formatCapeCount(value: number): string {
  return value.toLocaleString("zh-CN");
}

function MessageEvidenceList({ evidence }: { evidence: MessageEvidence[] }) {
  if (evidence.length === 0) {
    return null;
  }

  return (
    <details className="bomb-shell__message-evidence">
      <summary>
        <span>证据来源</span>
        <span>{evidence.length}</span>
      </summary>
      <ol>
        {evidence.map((item, index) => (
          <li key={`${item.citation}-${item.url ?? item.title}-${index}`}>
            <span className="bomb-shell__message-evidence-icon" aria-hidden="true">
              {item.sourceType === "web" ? (
                <IconWorld size={15} stroke={1.8} />
              ) : item.sourceType === "cape" ? (
                <IconBiohazard size={15} stroke={1.8} />
              ) : (
                <IconPaperclip size={15} stroke={1.8} />
              )}
            </span>
            <span className="bomb-shell__message-evidence-copy">
              <strong>[{item.citation}] {item.title}</strong>
              <span>{item.locator ?? item.snippet ?? "当前回答引用"}</span>
            </span>
            {item.url ? (
              <a href={item.url} target="_blank" rel="noreferrer" aria-label={`打开来源 ${item.title}`}>
                <IconExternalLink size={14} stroke={1.8} aria-hidden="true" />
              </a>
            ) : null}
          </li>
        ))}
      </ol>
    </details>
  );
}

function SandboxIntelligenceCard({
  capeCase,
  onAction,
  onExport
}: {
  capeCase: CapeCase;
  onAction: (prompt: string) => void;
  onExport: (caseId: number, format: CapeExportFormat) => Promise<void>;
}) {
  const summary = capeCase.summary;
  const iocCount = summary
    ? summary.iocs.domains.length + summary.iocs.ips.length + summary.iocs.urls.length
    : 0;
  const riskTone = capeCase.score !== null && capeCase.score >= 7 ? "high" : capeCase.score !== null && capeCase.score >= 4 ? "medium" : "unknown";

  return (
    <article className="bomb-shell__cape-card" data-testid={`cape-case-${capeCase.id}`}>
      <div className="bomb-shell__cape-card-header">
        <div>
          <p className="eyebrow">Sandbox Intelligence</p>
          <h3>CAPE Case #{capeCase.id}</h3>
        </div>
        <span className={`bomb-shell__cape-risk bomb-shell__cape-risk--${riskTone}`}>
          {capeCase.score !== null ? `Score ${capeCase.score}` : "等待评分"}
        </span>
      </div>

      <div className="bomb-shell__cape-card-meta">
        <span>Task #{capeCase.taskId}</span>
        <span>{getCapeStatusLabel(capeCase.status)}</span>
        <span>{capeCase.sampleName}</span>
        {capeCase.reusedExistingTask ? <span>复用已有任务</span> : null}
      </div>

      <div className="bomb-shell__cape-card-grid">
        <div>
          <strong>IOC</strong>
          <span>{summary ? formatCapeCount(iocCount) : "分析中"}</span>
        </div>
        <div>
          <strong>ATT&CK</strong>
          <span>{summary ? formatCapeCount(summary.tactics.length) : "分析中"}</span>
        </div>
        <div>
          <strong>Dropped</strong>
          <span>{summary ? formatCapeCount(summary.droppedFiles.length) : "分析中"}</span>
        </div>
      </div>

      {summary ? (
        <div className="bomb-shell__cape-evidence">
          <p>
            <strong>SHA256</strong>
            <span>{summary.sha256 ?? capeCase.sha256 ?? "未返回"}</span>
          </p>
          <p>
            <strong>关键 IOC</strong>
            <span>
              {[...summary.iocs.domains, ...summary.iocs.ips, ...summary.iocs.urls].slice(0, 3).join("、") || "暂无"}
            </span>
          </p>
          <p>
            <strong>行为线索</strong>
            <span>{summary.tactics.slice(0, 3).map((item) => item.technique).join("、") || "暂无 TTP 映射"}</span>
          </p>
        </div>
      ) : (
        <p className="bomb-shell__cape-card-copy">CAPE 正在生成证据，完成后这张卡片会自动沉淀为当前对话的 Case Memory。</p>
      )}

      <div className="bomb-shell__cape-card-actions">
        <button type="button" className="secondary-button" disabled={!summary} onClick={() => void onExport(capeCase.id, "bundle")}>
          导出证据包
        </button>
        <button type="button" className="secondary-button" disabled={!summary} onClick={() => onAction(`基于 CAPE Case #${capeCase.id} 生成一份 SOC 分析报告。`)}>
          SOC 报告
        </button>
        <button type="button" className="secondary-button secondary-button--soft" disabled={!summary} onClick={() => onAction(`提取 CAPE Case #${capeCase.id} 的 IOC，并按封禁优先级整理。`)}>
          提取 IOC
        </button>
        <button type="button" className="secondary-button secondary-button--soft" disabled={!summary} onClick={() => onAction(`解释 CAPE Case #${capeCase.id} 中最可疑的行为链，并说明证据来源。`)}>
          解释行为链
        </button>
        <button type="button" className="secondary-button secondary-button--soft" disabled={!summary} onClick={() => onAction(`基于 CAPE Case #${capeCase.id} 生成 Sigma 和 YARA 初稿。`)}>
          Sigma / YARA
        </button>
      </div>
    </article>
  );
}

type ModelButtonRefMap = Partial<Record<DeepSeekModelId, HTMLButtonElement | null>>;
type ProviderButtonRefMap = Partial<Record<ModelProvider, HTMLButtonElement | null>>;
type ModelMenuPlacement = "above" | "below";
type ModelMenuPosition = {
  left: number;
  placement: ModelMenuPlacement;
  top: number;
};
type TouchSwipeState = {
  mode: "idle" | "open-drawer" | "close-drawer";
  startX: number;
  startY: number;
  deltaX: number;
  deltaY: number;
  lastX: number;
  lastTime: number;
  velocityX: number;
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
    deltaY: 0,
    lastX: 0,
    lastTime: 0,
    velocityX: 0
  };
}

const CHAT_SKILL_ALIASES: Record<string, string> = {
  ioc: "ioc-enrichment", lolbas: "lolbas-command-analyzer", gtfo: "gtfobins-command-analyzer",
  attack: "attack-technique-mapper", capa: "capa-capability-review", block: "firewall-blocklist-builder"
};

function parseChatSkillCommand(skills: SkillPackage[], draft: string): { skill: SkillPackage; input: Record<string, unknown> } | null {
  const match = /^\/(\w+)\s+([\s\S]+)$/u.exec(draft.trim());
  if (!match) return null;
  const key = CHAT_SKILL_ALIASES[match[1].toLocaleLowerCase()];
  const skill = skills.find(item => item.key === key && item.entitlement.allowed);
  if (!skill) return null;
  const raw = match[2].trim();
  const values = raw.split(/[\n,]+/u).map(item => item.trim()).filter(Boolean);
  const field = key === "ioc-enrichment" ? "iocs" : key === "attack-technique-mapper" ? "behaviors" :
    key === "capa-capability-review" ? "capabilities" : key === "firewall-blocklist-builder" ? "indicators" : "commands";
  return { skill, input: createSkillInitialInput(skill, { [field]: field === "commands" ? [raw] : values }) };
}

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
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

function getProfileInitials(value: string): string {
  return value
    .trim()
    .split(/\s+/u)
    .slice(0, 2)
    .map((part) => Array.from(part)[0] ?? "")
    .join("")
    .toLocaleUpperCase() || "C";
}

export function AppShell({
  onLogout,
  onOpenAccount = () => undefined,
  onOpenCases = () => undefined,
  onOpenSkills = () => undefined,
  onOpenJobs = () => undefined,
  sessionError = null,
  viewer = null
}: AppShellProps) {
  const [isSidebarOpen, setSidebarOpen] = useState(() => !isMobileViewport());
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerMounted, setDrawerMounted] = useState(false);
  const [drawerVisible, setDrawerVisible] = useState(false);
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  const [modelMenuMounted, setModelMenuMounted] = useState(false);
  const [modelMenuVisible, setModelMenuVisible] = useState(false);
  const [modelMenuPosition, setModelMenuPosition] = useState<ModelMenuPosition>({
    left: 314,
    placement: "below",
    top: 88
  });
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [templatePickerOpen, setTemplatePickerOpen] = useState(false);
  const [analysisTemplates, setAnalysisTemplates] = useState<AnalysisTemplate[]>([]);
  const [caseWorkspaceOpen, setCaseWorkspaceOpen] = useState(false);
  const [capePanelOpen, setCapePanelOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [isComposerMultiline, setComposerMultiline] = useState(false);
  const [conversationSearch, setConversationSearch] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [renameDialogState, setRenameDialogState] = useState<{
    conversationId: string;
    title: string;
  } | null>(null);
  const [isComposerFocused, setComposerFocused] = useState(false);
  const [mobileKeyboardOffset, setMobileKeyboardOffset] = useState(0);
  const [isTabletLandscape, setTabletLandscape] = useState(() => isTabletLandscapeViewport());
  const [composerError, setComposerError] = useState<string | null>(null);
  const [conversationSkills, setConversationSkills] = useState<SkillPackage[]>([]);
  const [skillPickerOpen, setSkillPickerOpen] = useState(false);
  const [selectedConversationSkill, setSelectedConversationSkill] = useState<SkillPackage | null>(null);
  const [conversationSkillInput, setConversationSkillInput] = useState<Record<string, unknown>>({});
  const [dismissedErrorMessage, setDismissedErrorMessage] = useState<string | null>(null);
  const [searchBannerMessage, setSearchBannerMessage] = useState<string | null>(null);
  const [messageSearch, setMessageSearch] = useState("");
  const [messageSearchIndex, setMessageSearchIndex] = useState(0);
  const [visibleMessageCount, setVisibleMessageCount] = useState(MESSAGE_PAGE_SIZE);
  const [expandedMessages, setExpandedMessages] = useState<Set<string>>(() => new Set());
  const [messageFeedback, setMessageFeedback] = useState<Record<string, "up" | "down" | undefined>>({});
  const [feedbackReasonMessageId, setFeedbackReasonMessageId] = useState<string | null>(null);
  const [contextMenuState, setContextMenuState] = useState<{
    conversationId: string;
    x: number;
    y: number;
  } | null>(null);
  const [isDragActive, setDragActive] = useState(false);
  const [drawerDragOffset, setDrawerDragOffset] = useState(0);
  const conversationsButtonRef = useRef<HTMLButtonElement | null>(null);
  const drawerPanelRef = useRef<HTMLDivElement | null>(null);
  const settingsButtonRef = useRef<HTMLButtonElement | null>(null);
  const caseWorkspaceButtonRef = useRef<HTMLButtonElement | null>(null);
  const capeButtonRef = useRef<HTMLButtonElement | null>(null);
  const modelMenuButtonRef = useRef<HTMLButtonElement | null>(null);
  const modelMenuRef = useRef<HTMLDivElement | null>(null);
  const modelProviderItemRefs = useRef<ProviderButtonRefMap>({});
  const modelSubmenuItemRefs = useRef<ModelButtonRefMap>({});
  const contextMenuRef = useRef<HTMLDivElement | null>(null);
  const messageStageRef = useRef<HTMLElement | null>(null);
  const conversationSearchRef = useRef<HTMLInputElement | null>(null);
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
    createConversationFromTemplate = async (_template: AnalysisTemplate | null) => undefined,
    deleteConversation,
    renameConversation = async () => undefined,
    setConversationArchived = async () => undefined,
    setConversationPinned = async () => undefined,
    updateCaseMetadata = async () => undefined,
    error,
    isGenerating,
    notificationMessage = null,
    clearNotification = () => undefined,
    removePendingZipContext,
    removeFile,
    retryFile,
    runtimeStatus,
    sendMessage,
    runConversationSkill = async () => undefined,
    stopGeneration = () => undefined,
    submitCapeCase,
    setWebSearchEnabled,
    uploadZip,
    setActiveConversationId,
    setModelId,
    updateSettings = () => undefined,
    stagedFiles,
    webSearchEnabled,
    settings
  } = useServerChat();

  useEffect(() => {
    let active = true;
    getSkills().then(result => {
      if (active) setConversationSkills(result.items.filter(item =>
        item.installed && item.enabled && item.reviewStatus === "verified"
      ));
    }).catch(() => undefined);
    return () => { active = false; };
  }, []);
  useEffect(() => { listAnalysisTemplates().then(result => setAnalysisTemplates(result.items)).catch(() => undefined); }, []);
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

  async function handleFeedback(
    messageId: string,
    rating: "up" | "down" | null,
    reason?: "factual_error" | "citation_error" | "formatting" | "not_helpful" | "other"
  ) {
    setMessageFeedback((previous) => ({
      ...previous,
      [messageId]: rating ?? undefined
    }));
    if (rating !== "down" || reason) {
      setFeedbackReasonMessageId(null);
    }
    try {
      await submitMessageFeedback(messageId, { rating, ...(reason ? { reason } : {}) });
    } catch (nextError) {
      setComposerError(nextError instanceof Error ? nextError.message : "保存回答反馈失败。 ");
    }
  }
  const activeProviderModels = getDeepSeekModelsByProvider(activeProvider);
  const profileName = viewer?.displayName ?? viewer?.username ?? "账号";
  const profileAvatarUrl = viewer?.avatarUrl ?? null;

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.motionPreference = settings.motionPreference ?? "system";
    root.dataset.transparencyPreference = settings.transparencyPreference ?? "system";

    return () => {
      delete root.dataset.motionPreference;
      delete root.dataset.transparencyPreference;
    };
  }, [settings.motionPreference, settings.transparencyPreference]);

  const updateModelMenuPosition = useCallback(() => {
    const trigger = modelMenuButtonRef.current;
    if (!trigger || typeof window === "undefined") {
      return;
    }

    const triggerRect = trigger.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const compactMenu = viewportWidth <= 820;
    const phoneMenu = viewportWidth <= 760;
    const measuredMenuWidth = modelMenuRef.current?.offsetWidth ?? 0;
    const measuredMenuHeight = modelMenuRef.current?.offsetHeight ?? 0;
    const menuWidth =
      measuredMenuWidth ||
      (phoneMenu
        ? Math.min(MODEL_MENU_PHONE_WIDTH_PX, viewportWidth - MODEL_MENU_VIEWPORT_PADDING_PX * 2)
        : compactMenu
          ? Math.min(MODEL_MENU_COMPACT_WIDTH_PX, viewportWidth - MODEL_MENU_VIEWPORT_PADDING_PX * 2)
          : MODEL_MENU_DESKTOP_WIDTH_PX);
    const menuHeight =
      measuredMenuHeight ||
      (phoneMenu
        ? MODEL_MENU_PHONE_HEIGHT_PX
        : compactMenu
          ? MODEL_MENU_COMPACT_HEIGHT_PX
          : MODEL_MENU_DESKTOP_HEIGHT_PX);
    const belowTop = triggerRect.bottom + MODEL_MENU_GAP_PX;
    const aboveTop = triggerRect.top - MODEL_MENU_GAP_PX - menuHeight;
    const hasRoomBelow = belowTop + menuHeight <= viewportHeight - MODEL_MENU_VIEWPORT_PADDING_PX;
    const placement: ModelMenuPlacement = hasRoomBelow ? "below" : "above";
    let left = triggerRect.left;
    let top = placement === "below" ? belowTop : aboveTop;

    left = Math.max(
      MODEL_MENU_VIEWPORT_PADDING_PX,
      Math.min(left, viewportWidth - menuWidth - MODEL_MENU_VIEWPORT_PADDING_PX)
    );
    top = Math.max(
      MODEL_MENU_VIEWPORT_PADDING_PX,
      Math.min(top, viewportHeight - menuHeight - MODEL_MENU_VIEWPORT_PADDING_PX)
    );

    setModelMenuPosition((currentPosition) => {
      if (
        currentPosition.left === left &&
        currentPosition.top === top &&
        currentPosition.placement === placement
      ) {
        return currentPosition;
      }

      return { left, placement, top };
    });
  }, []);

  const messages = activeConversation?.messages ?? [];
  const visibleMessageStart = Math.max(0, messages.length - visibleMessageCount);
  const visibleMessages = messages.slice(visibleMessageStart);
  const messageSearchMatches = useMemo(() => {
    const query = messageSearch.trim().toLocaleLowerCase();
    if (!query) return [];
    return messages.filter((message) => message.content.toLocaleLowerCase().includes(query));
  }, [messageSearch, messages]);
  useEffect(() => {
    setVisibleMessageCount(MESSAGE_PAGE_SIZE);
    setMessageSearch("");
    setMessageSearchIndex(0);
  }, [activeConversation?.id]);
  const capeCases = activeConversation?.capeCases ?? [];
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
  const visibleConversations = useMemo(() => {
    const query = conversationSearch.trim().toLocaleLowerCase();
    const terms = query.split(/\s+/u).filter(Boolean);

    return conversations
      .filter((conversation) => showArchived || query || !conversation.isArchived)
      .filter((conversation) => {
        if (terms.length === 0) {
          return true;
        }

        const searchableText = [
          conversation.title,
          ...conversation.messages.flatMap((message) => [
            message.content,
            ...(message.attachments ?? []).map((attachment) => attachment.name)
          ]),
          ...(conversation.capeCases ?? []).flatMap((capeCase) => [
            capeCase.sampleName,
            capeCase.sha256 ?? "",
            capeCase.summary ? JSON.stringify(capeCase.summary) : ""
          ])
        ]
          .join("\n")
          .toLocaleLowerCase();

        return terms.every((term) => searchableText.includes(term));
      })
      .sort((left, right) => {
        if (Boolean(left.isPinned) !== Boolean(right.isPinned)) {
          return left.isPinned ? -1 : 1;
        }
        return Date.parse(right.updatedAt) - Date.parse(left.updatedAt);
      });
  }, [conversationSearch, conversations, showArchived]);
  const activeZipSupportedBySelectedModel = !activeZipContext || isZipContextSupportedModel(modelId);
  const activeZipUnsupportedReason =
    activeZipContext && !activeZipSupportedBySelectedModel
      ? activeZipContext.unsupportedReason ?? ZIP_UNSUPPORTED_MODEL_REASON
      : null;
  const activeError = sessionError ?? composerError ?? error;
  const visibleError = activeError && activeError !== dismissedErrorMessage ? activeError : null;
  const contextMenuConversation = contextMenuState
    ? conversations.find((conversation) => conversation.id === contextMenuState.conversationId) ?? null
    : null;

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
    if (notificationMessage === null) {
      return;
    }

    const timer = window.setTimeout(() => {
      clearNotification();
    }, 6000);

    return () => {
      window.clearTimeout(timer);
    };
  }, [clearNotification, notificationMessage]);

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

  useLayoutEffect(() => {
    if (!textareaRef.current) {
      return;
    }

    textareaRef.current.style.height = "auto";
    const contentHeight = textareaRef.current.scrollHeight;
    textareaRef.current.style.height = `${Math.min(contentHeight, 150)}px`;
    setComposerMultiline(contentHeight > 44);
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

  useLayoutEffect(() => {
    if (!modelMenuMounted) {
      return;
    }

    updateModelMenuPosition();
    const positionFrame = window.requestAnimationFrame(updateModelMenuPosition);

    window.addEventListener("resize", updateModelMenuPosition);
    window.addEventListener("scroll", updateModelMenuPosition, true);

    return () => {
      window.cancelAnimationFrame(positionFrame);
      window.removeEventListener("resize", updateModelMenuPosition);
      window.removeEventListener("scroll", updateModelMenuPosition, true);
    };
  }, [activeProvider, modelMenuMounted, updateModelMenuPosition]);

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
    const skillCommand = parseChatSkillCommand(conversationSkills, nextDraft);
    if (skillCommand) {
      await runConversationSkill(skillCommand.skill, nextDraft, skillCommand.input);
      return;
    }
    await sendMessage(nextDraft);
  }

  async function handleConversationSkillRun() {
    if (!selectedConversationSkill) return;
    const prompt = `/${selectedConversationSkill.key}`;
    setComposerError(null);
    try {
      await runConversationSkill(selectedConversationSkill, prompt, conversationSkillInput);
      setSkillPickerOpen(false);
    } catch (nextError) {
      setComposerError(nextError instanceof Error ? nextError.message : "Skill 运行失败");
    }
  }

  function handleNewConversation() {
    setDrawerOpen(false);
    clearFiles();
    setActiveConversationId(null);
    setTemplatePickerOpen(true);
  }

  async function initializeNewConversation(templateId: number | null) {
    const template = templateId === null
      ? null
      : analysisTemplates.find((item) => item.id === templateId) ?? null;
    setTemplatePickerOpen(false);
    setDrawerOpen(false);
    clearFiles();
    if (template) {
      setModelId(resolveDeepSeekModelId(template.recommendedModel));
    }
    await createConversationFromTemplate(template);
    setWebSearchEnabled(settings.defaultWebSearch ?? false);
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
      deltaY: 0,
      lastX: point.clientX,
      lastTime: performance.now(),
      velocityX: 0
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
      deltaY: 0,
      lastX: point.clientX,
      lastTime: performance.now(),
      velocityX: 0
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

    const now = performance.now();
    const elapsed = Math.max(now - touchSwipeRef.current.lastTime, 1);
    const deltaX = point.clientX - touchSwipeRef.current.startX;
    const nextVelocity = ((point.clientX - touchSwipeRef.current.lastX) / elapsed) * 1000;

    touchSwipeRef.current = {
      ...touchSwipeRef.current,
      deltaX,
      deltaY: point.clientY - touchSwipeRef.current.startY,
      lastX: point.clientX,
      lastTime: now,
      velocityX: nextVelocity
    };
    setDrawerDragOffset(Math.min(0, deltaX));
  }

  function handleDrawerTouchEnd() {
    const swipe = touchSwipeRef.current;
    if (
      swipe.mode === "close-drawer" &&
      (swipe.deltaX <= -MOBILE_SWIPE_TRIGGER_PX || swipe.velocityX <= -420) &&
      Math.abs(swipe.deltaY) <= MOBILE_SWIPE_VERTICAL_TOLERANCE_PX
    ) {
      setDrawerOpen(false);
    }

    setDrawerDragOffset(0);
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

  function locateMessage(direction: 1 | -1) {
    if (messageSearchMatches.length === 0) return;
    const nextIndex = (messageSearchIndex + direction + messageSearchMatches.length) % messageSearchMatches.length;
    setMessageSearchIndex(nextIndex);
    const target = messageSearchMatches[nextIndex];
    const targetIndex = messages.findIndex((message) => message.id === target.id);
    if (targetIndex < visibleMessageStart) setVisibleMessageCount(messages.length - targetIndex);
    window.requestAnimationFrame(() => {
      document.querySelector(`[data-testid="message-row-${target.id}"]`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    });
  }

  function exportConversation() {
    if (!activeConversation) return;
    const markdown = [`# ${activeConversation.title}`, "", ...messages.flatMap((message) => [
      `## ${message.role === "user" ? "用户" : message.role === "assistant" ? "Cipher" : "系统"}`,
      "",
      message.content,
      ""
    ])].join("\n");
    const blobUrl = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = blobUrl;
    anchor.download = `${activeConversation.title.replace(/[\\/:*?"<>|]/g, "-") || "cipher-chat"}.md`;
    anchor.click();
    URL.revokeObjectURL(blobUrl);
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
              <img
                className="bomb-shell__brand-wordmark bomb-shell__brand-wordmark--light"
                src="/assets/cipher-wordmark.svg"
                alt="Cipher Intelligence"
              />
              <img
                className="bomb-shell__brand-wordmark bomb-shell__brand-wordmark--dark"
                src="/assets/cipher-wordmark-dark.svg"
                alt=""
                aria-hidden="true"
              />
            </span>
            <button
              type="button"
              className="bomb-shell__icon-button bomb-shell__sidebar-collapse"
              aria-label="收起会话栏"
              onClick={() => {
                setSidebarOpen(false);
                setDrawerOpen(false);
              }}
            >
              <IconLayoutSidebarLeftCollapse size={18} stroke={1.8} aria-hidden="true" />
              <span className="bomb-shell__collapse-label">收起</span>
            </button>
          </div>

          <div className="bomb-shell__sidebar-primary-actions">
            <button
              className="bomb-shell__new-chat"
              type="button"
              aria-label="开启新对话"
              onClick={handleNewConversation}
              disabled={isGenerating}
            >
              <IconPlus size={16} stroke={1.9} aria-hidden="true" />
              <span>新建对话</span>
            </button>
          </div>

          <label className="bomb-shell__sidebar-search">
            <IconSearch size={15} stroke={1.8} aria-hidden="true" />
            <input
              ref={conversationSearchRef}
              type="search"
              value={conversationSearch}
              onChange={(event) => setConversationSearch(event.target.value)}
              placeholder="搜索标题、消息与 IOC"
              aria-label="全文搜索会话"
              autoComplete="off"
            />
          </label>
        </div>

        <div className="bomb-shell__sidebar-list-wrap">
          <div className="bomb-shell__sidebar-heading-row">
            <p className="bomb-shell__sidebar-label">
              最近对话
              <span className="bomb-shell__sidebar-count">{visibleConversations.length}</span>
            </p>
            <span className="bomb-shell__sidebar-heading-actions">
              <button
                type="button"
                className={`bomb-shell__sidebar-clear${showArchived ? " bomb-shell__sidebar-clear--active" : ""}`}
                onClick={() => setShowArchived((current) => !current)}
                aria-pressed={showArchived}
              >
                {showArchived ? "隐藏归档" : "查看归档"}
              </button>
              <button
                type="button"
                className="bomb-shell__sidebar-clear"
                onClick={() => {
                  setConversationSearch("");
                  conversationSearchRef.current?.focus();
                }}
                disabled={!conversationSearch}
                aria-label="清空会话搜索"
              >
                清除
              </button>
            </span>
          </div>

          {visibleConversations.length === 0 ? (
            <div className="bomb-shell__sidebar-empty">
              <p className="eyebrow">{conversations.length === 0 ? "暂无会话" : "未找到会话"}</p>
              <h2>{conversations.length === 0 ? "开始新的对话" : "试试其他关键词"}</h2>
              <p>
                {conversations.length === 0
                  ? "你发起的新对话会显示在这里。"
                  : "标题、消息、附件与 IOC 中没有匹配内容。"}
              </p>
            </div>
          ) : (
            <div className="bomb-shell__sidebar-list">
              {visibleConversations.map((conversation) => {
                const isActive = conversation.id === activeConversationId;

                function openConversationMenu(x: number, y: number) {
                  setContextMenuState({
                    conversationId: conversation.id,
                    x,
                    y
                  });
                }

                return (
                  <div className="bomb-shell__sidebar-item-wrap" key={conversation.id}>
                    <button
                      className={`bomb-shell__sidebar-item${isActive ? " bomb-shell__sidebar-item--active" : ""}`}
                      type="button"
                      onClick={() => handleSelectConversation(conversation.id)}
                      onContextMenu={(event) => {
                        event.preventDefault();
                        openConversationMenu(event.clientX, event.clientY);
                      }}
                      disabled={isGenerating}
                      aria-pressed={isActive}
                    >
                      <span className="bomb-shell__sidebar-item-title">
                        <IconMessage size={16} stroke={1.8} aria-hidden="true" />
                        <span>{conversation.title}</span>
                        {conversation.isPinned ? <em>置顶</em> : null}
                        {conversation.isArchived ? <em>归档</em> : null}
                      </span>
                      <small>{formatTimestamp(conversation.updatedAt)}</small>
                    </button>
                    <button
                      type="button"
                      className="bomb-shell__sidebar-item-more"
                      aria-label={`管理会话 ${conversation.title}`}
                      onClick={(event) => {
                        const rect = event.currentTarget.getBoundingClientRect();
                        openConversationMenu(Math.max(12, rect.right - 190), rect.bottom + 4);
                      }}
                    >
                      <IconDots size={18} stroke={2} aria-hidden="true" />
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        <div className="bomb-shell__profile">
          <button className="bomb-shell__profile-card bomb-shell__profile-card--settings" type="button" onClick={onOpenSkills}>
            <span className="bomb-shell__profile-avatar bomb-shell__profile-avatar--settings" aria-hidden="true"><IconSparkles size={14} stroke={1.8} /></span>
            <div className="bomb-shell__profile-copy"><span>Skill Store</span><small>安全分析能力与工具</small></div>
            <IconChevronRight className="bomb-shell__profile-chevron" size={16} stroke={1.8} aria-hidden="true" />
          </button>
          <button className="bomb-shell__profile-card bomb-shell__profile-card--settings" type="button" onClick={onOpenCases}>
            <span className="bomb-shell__profile-avatar bomb-shell__profile-avatar--settings" aria-hidden="true"><IconBriefcase size={14} stroke={1.8} /></span>
            <div className="bomb-shell__profile-copy"><span>Case 中心</span><small>研判、处置与事件关联</small></div>
            <IconChevronRight className="bomb-shell__profile-chevron" size={16} stroke={1.8} aria-hidden="true" />
          </button>
          <button className="bomb-shell__profile-card bomb-shell__profile-card--settings" type="button" onClick={onOpenJobs}>
            <span className="bomb-shell__profile-avatar bomb-shell__profile-avatar--settings"><IconPlayerPlay size={14} /></span><div className="bomb-shell__profile-copy"><span>任务中心</span><small>进度、失败与重试</small></div><IconChevronRight className="bomb-shell__profile-chevron" size={16} />
          </button>
          <button
            className="bomb-shell__profile-card bomb-shell__profile-card--settings"
            type="button"
            onClick={() => setSettingsOpen(true)}
            ref={settingsButtonRef}
          >
            <span className="bomb-shell__profile-avatar bomb-shell__profile-avatar--settings" aria-hidden="true">
              <IconSettings size={14} stroke={1.8} />
            </span>
            <div className="bomb-shell__profile-copy">
              <span>偏好设置</span>
              <small>模型、显示与对话偏好</small>
            </div>
            <IconChevronRight className="bomb-shell__profile-chevron" size={16} stroke={1.8} aria-hidden="true" />
          </button>

          <button
            className="bomb-shell__profile-card"
            type="button"
            aria-label={`${profileName} 打开账号设置`}
            onClick={onOpenAccount}
          >
            <span className="bomb-shell__profile-avatar bomb-shell__profile-avatar--account" aria-hidden="true">
              {profileAvatarUrl ? (
                <img className="bomb-shell__profile-photo" src={profileAvatarUrl} alt="" />
              ) : (
                <span className="bomb-shell__profile-initials">{getProfileInitials(profileName)}</span>
              )}
            </span>
            <div className="bomb-shell__profile-copy">
              <span>{profileName}</span>
              <small>账号与个人资料</small>
            </div>
            <IconChevronRight className="bomb-shell__profile-chevron" size={16} stroke={1.8} aria-hidden="true" />
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
        data-layout={layout}
        data-focused={isComposerFocused ? "true" : "false"}
      >
        <div className="bomb-shell__composer-model-bar">
          <button
            ref={modelMenuButtonRef}
            type="button"
            className={`bomb-shell__model-pill bomb-shell__composer-model-pill${
              modelMenuOpen ? " bomb-shell__model-pill--open" : ""
            }`}
            aria-label="切换模型"
            aria-haspopup="menu"
            aria-expanded={modelMenuOpen}
            title={`切换模型 · 当前为 ${modelLabel}`}
            onClick={() => {
              if (!modelMenuOpen) {
                updateModelMenuPosition();
              }
              setModelMenuOpen((previousState) => !previousState);
            }}
          >
            <span className="bomb-shell__composer-model-icon" aria-hidden="true">
              <IconArrowsExchange className="bomb-shell__model-pill-switch" size={16} stroke={1.9} />
            </span>
            <span className="bomb-shell__composer-model-copy">
              <strong>{modelLabel}</strong>
              <small>{MODEL_PROVIDER_LABELS[selectedProvider]}</small>
            </span>
            <IconChevronDown
              className={`bomb-shell__model-pill-chevron${
                modelMenuOpen ? " bomb-shell__model-pill-chevron--open" : ""
              }`}
              size={15}
              stroke={2}
              aria-hidden="true"
            />
          </button>
        </div>

        <div className="bomb-shell__composer-row">
          <button
            ref={caseWorkspaceButtonRef}
            className={`bomb-shell__case-workspace-launcher${
              caseWorkspaceOpen ? " bomb-shell__case-workspace-launcher--active" : ""
            }`}
            type="button"
            aria-label="打开 Case 工作区"
            aria-pressed={caseWorkspaceOpen}
            onClick={() => setCaseWorkspaceOpen(true)}
          >
            <IconBriefcase size={18} stroke={1.8} aria-hidden="true" />
          </button>

          <form
            className={`bomb-shell__dock${layout === "centered" ? " bomb-shell__dock--centered" : ""}`}
            data-multiline={isComposerMultiline ? "true" : "false"}
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
                        {attachment.uploadStatus === "hashing" ? "正在校验文件" : attachment.uploadStatus === "uploading" ? `上传 ${attachment.uploadProgress ?? 0}%` : attachment.uploadStatus === "failed" ? `上传失败 · ${attachment.uploadError ?? "可在发送时重试"}` : attachment.deduplicated ? "已秒传 · 内容重复" : `${attachment.type} · ${formatAttachmentSize(attachment.size)}`}
                      </span>
                      {attachment.uploadStatus === "hashing" || attachment.uploadStatus === "uploading" ? <span className="bomb-shell__attachment-progress" style={{ "--upload-progress": `${attachment.uploadProgress ?? 0}%` } as CSSProperties} /> : null}
                      {attachment.uploadStatus === "failed" ? <button type="button" className="bomb-shell__attachment-retry" onClick={() => retryFile?.(attachment.id)}>重试</button> : null}
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

          {webSearchEnabled || capePanelOpen ? (
            <div className="bomb-shell__composer-chips" aria-label="已启用功能">
              {webSearchEnabled ? (
                <button type="button" className="bomb-shell__composer-chip" onClick={handleWebSearchToggle}>
                  <IconWorld size={13} stroke={1.9} aria-hidden="true" />
                  <span>联网搜索</span>
                  <IconX size={12} stroke={2} aria-hidden="true" />
                </button>
              ) : null}
              {capePanelOpen ? (
                <button
                  type="button"
                  className="bomb-shell__composer-chip"
                  onClick={() => setCapePanelOpen(false)}
                >
                  <IconBiohazard size={13} stroke={1.9} aria-hidden="true" />
                  <span>CAPE 分析</span>
                  <IconX size={12} stroke={2} aria-hidden="true" />
                </button>
              ) : null}
            </div>
          ) : null}

          <div className="bomb-shell__dock-main-row">
            <div className="bomb-shell__dock-actions" aria-label="输入工具">
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

              <button
                ref={capeButtonRef}
                className={`bomb-shell__dock-tool${capePanelOpen ? " bomb-shell__dock-tool--active" : ""}`}
                type="button"
                aria-label={capePanelOpen ? "关闭 CAPE 面板" : "打开 CAPE 面板"}
                aria-pressed={capePanelOpen}
                onClick={() => setCapePanelOpen((previousState) => !previousState)}
                disabled={isGenerating}
              >
                <IconBiohazard size={18} stroke={1.8} />
              </button>

              {conversationSkills.length > 0 ? <button
                className={`bomb-shell__dock-tool${skillPickerOpen ? " bomb-shell__dock-tool--active" : ""}`}
                type="button"
                aria-label={skillPickerOpen ? "关闭对话技能" : "选择对话技能"}
                aria-expanded={skillPickerOpen}
                onClick={() => setSkillPickerOpen(value => !value)}
                disabled={isGenerating}
              >
                <IconSparkles size={18} stroke={1.8} />
              </button> : null}
            </div>

            {skillPickerOpen && conversationSkills.length > 0 ? (
              <div className="conversation-skill-picker" role="dialog" aria-label="对话技能">
                <div className="conversation-skill-picker__head">
                  <div><strong>对话技能</strong><span>结果会保存到当前对话</span></div>
                  <button type="button" onClick={() => setSkillPickerOpen(false)} aria-label="关闭对话技能"><IconX size={16}/></button>
                </div>
                <div className="conversation-skill-picker__list">
                  {conversationSkills.map(skill => <button type="button" key={skill.id}
                    className={selectedConversationSkill?.id === skill.id ? "is-active" : ""}
                    disabled={!skill.entitlement.allowed}
                    onClick={() => { setSelectedConversationSkill(skill); setConversationSkillInput(createSkillInitialInput(skill)); }}>
                    <span>{skill.name}</span><small>{skill.entitlement.allowed
                      ? `/${Object.entries(CHAT_SKILL_ALIASES).find(([, key]) => key === skill.key)?.[0] ?? skill.key}`
                      : "套餐未包含"}</small>
                  </button>)}
                </div>
                {selectedConversationSkill ? <div className="conversation-skill-picker__form">
                  <div><strong>{selectedConversationSkill.name}</strong><small>{selectedConversationSkill.author} · v{selectedConversationSkill.version}</small></div>
                  <SkillInputForm skill={selectedConversationSkill} value={conversationSkillInput} onChange={setConversationSkillInput}/>
                  <button type="button" className="cases-primary" disabled={isGenerating} onClick={() => void handleConversationSkillRun()}><IconPlayerPlay size={16}/>在对话中运行</button>
                </div> : <p className="conversation-skill-picker__empty">选择技能，或直接输入 /ioc、/lolbas、/gtfo、/attack、/capa、/block。</p>}
              </div>
            ) : null}

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
              placeholder="向 Cipher AI 提问..."
              rows={1}
              disabled={isGenerating}
              onFocus={() => setComposerFocused(true)}
              onBlur={() => setComposerFocused(false)}
            />

            <button
              className={`bomb-shell__send-button${
                draft.trim() || isGenerating ? " bomb-shell__send-button--active" : ""
              }`}
              type={isGenerating ? "button" : "submit"}
              aria-label={isGenerating ? "停止生成" : "发送消息"}
              disabled={!isGenerating && !draft.trim()}
              onClick={isGenerating ? stopGeneration : undefined}
            >
              {isGenerating ? <IconPlayerStopFilled size={18} /> : <IconSend2 size={18} stroke={1.9} />}
            </button>
          </div>
          </form>
        </div>

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

      <div className="bomb-shell__root" aria-hidden={drawerOpen || settingsOpen || caseWorkspaceOpen ? "true" : undefined}>
        <div
          className={`bomb-shell__sidebar-spacer${isSidebarOpen ? " bomb-shell__sidebar-spacer--open" : ""}`}
          aria-hidden="true"
        />

        <aside
          className={`bomb-shell__sidebar${isSidebarOpen ? " bomb-shell__sidebar--open" : ""}`}
          aria-label="会话导航"
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
            <div className="bomb-shell__header-leading">
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
                <span className="bomb-shell__sidebar-expand-label">展开</span>
              </button>

              <div className="bomb-shell__conversation-context" data-testid="conversation-context">
                <span>{activeConversation?.title ?? "新对话"}</span>
                <small>{activeConversation?.analysisTemplate
                  ? `${activeConversation.analysisTemplate.name} · v${activeConversation.analysisTemplate.version} · ${shellStatus.header}`
                  : shellStatus.header}</small>
              </div>
            </div>

            <div className="bomb-shell__header-actions">
              <NotificationCenter />
              <ThemeToggle className="theme-toggle--header" />
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

          {!visibleError && !searchBannerMessage && notificationMessage ? (
            <div className="status-banner status-banner--success bomb-shell__top-alert bomb-shell__top-toast bomb-shell__notification" role="status">
              <span>{notificationMessage}</span>
              <button type="button" onClick={clearNotification} aria-label="关闭通知">×</button>
            </div>
          ) : null}

          <section
            className={`bomb-shell__message-stage${messages.length === 0 && capeCases.length === 0 ? " bomb-shell__message-stage--empty" : ""}`}
            aria-label="消息列表"
            role="log"
            aria-live="polite"
            ref={messageStageRef}
            onScroll={handleMessageStageScroll}
          >
            {messages.length > 0 ? (
              <div className="bomb-shell__message-toolbar" role="search" aria-label="搜索当前会话消息">
                <label>
                  <IconSearch size={15} stroke={1.8} aria-hidden="true" />
                  <input
                    type="search"
                    value={messageSearch}
                    placeholder="搜索当前会话"
                    onChange={(event) => { setMessageSearch(event.target.value); setMessageSearchIndex(0); }}
                    onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); locateMessage(event.shiftKey ? -1 : 1); } }}
                  />
                </label>
                {messageSearch.trim() ? <span>{messageSearchMatches.length ? `${messageSearchIndex + 1}/${messageSearchMatches.length}` : "无结果"}</span> : null}
                <button type="button" disabled={messageSearchMatches.length === 0} onClick={() => locateMessage(-1)} aria-label="上一个搜索结果">↑</button>
                <button type="button" disabled={messageSearchMatches.length === 0} onClick={() => locateMessage(1)} aria-label="下一个搜索结果">↓</button>
                <button type="button" onClick={exportConversation} aria-label="导出当前会话"><IconDownload size={15} stroke={1.8} /></button>
              </div>
            ) : null}
            <div className="bomb-shell__message-stack">
              {messages.length === 0 && capeCases.length === 0 ? (
                <div className="bomb-shell__landing">
                  <div className="bomb-shell__landing-copy">
                    <span className="bomb-shell__landing-status">
                      <span aria-hidden="true" />
                      {activeConversation?.analysisTemplate
                        ? `已加载分析模板 · v${activeConversation.analysisTemplate.version}`
                        : "安全分析工作台"}
                    </span>
                    <h1 className="bomb-shell__landing-title">
                      {activeConversation?.analysisTemplate?.name ?? "从哪条线索开始？"}
                    </h1>
                    {activeConversation?.analysisTemplate ? (
                      <p className="bomb-shell__template-scenario">
                        {activeConversation.analysisTemplate.scenario} · {activeConversation.analysisTemplate.checklist.length} 项检查 · {activeConversation.analysisTemplate.requiredSkills.length} 个 Skill
                      </p>
                    ) : null}
                  </div>
                  {renderComposer("centered")}
                  <div className="bomb-shell__quick-prompts" aria-label="快捷任务">
                    <button type="button" onClick={() => setDraft("分析这份样本的风险、关键 IOC 与攻击链。")}>
                      <IconShieldSearch size={20} stroke={1.7} aria-hidden="true" />
                      <span><strong>样本研判</strong><small>提取 IOC 与攻击链</small></span>
                    </button>
                    <button type="button" onClick={() => setDraft("审查这段代码中的安全风险，并按严重程度给出修复建议。")}>
                      <IconCode size={20} stroke={1.7} aria-hidden="true" />
                      <span><strong>代码审查</strong><small>定位风险与修复点</small></span>
                    </button>
                    <button type="button" onClick={() => setDraft("基于现有线索生成一份简洁的 SOC 事件报告。")}>
                      <IconFileDescription size={20} stroke={1.7} aria-hidden="true" />
                      <span><strong>SOC 报告</strong><small>整理证据与处置建议</small></span>
                    </button>
                  </div>
                </div>
              ) : (
                <>
                {visibleMessageStart > 0 ? (
                  <button className="bomb-shell__load-history" type="button" onClick={() => setVisibleMessageCount((count) => count + MESSAGE_PAGE_SIZE)}>
                    加载更早消息（剩余 {visibleMessageStart} 条）
                  </button>
                ) : null}
                {visibleMessages.map((message, visibleIndex) => {
                  const index = visibleMessageStart + visibleIndex;
                  const isUser = message.role === "user";
                  const isStreamingAssistant = !isUser && isGenerating && index === messages.length - 1;
                  const precedingUserMessage = !isUser
                    ? messages.slice(0, index).reverse().find((candidate) => candidate.role === "user")
                    : undefined;

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
                          {!isUser ? <p className="bomb-shell__bubble-role">CIPHER A.I +</p> : null}
                          <div className={`${!isUser ? "bomb-shell__response-content" : ""}${!expandedMessages.has(message.id) && message.content.length > LONG_MESSAGE_CHARACTERS ? " bomb-shell__response-content--collapsed" : ""}`.trim() || undefined}>
                            <MessageContent content={message.content} />
                            {isStreamingAssistant ? <span className="bomb-shell__caret" aria-hidden="true" /> : null}
                            {!isUser && message.evidence && message.evidence.length > 0 ? (
                              <MessageEvidenceList evidence={message.evidence} />
                            ) : null}
                          </div>
                          {message.content.length > LONG_MESSAGE_CHARACTERS && !isStreamingAssistant ? (
                            <button className="bomb-shell__message-expand" type="button" onClick={() => setExpandedMessages((current) => { const next = new Set(current); next.has(message.id) ? next.delete(message.id) : next.add(message.id); return next; })}>
                              {expandedMessages.has(message.id) ? "收起长内容" : "展开完整内容"}
                            </button>
                          ) : null}
                        </div>

                        {!isUser && !isStreamingAssistant ? (
                          <div className="bomb-shell__message-actions" aria-label="回答操作">
                            <div className="bomb-shell__message-feedback">
                              <button
                                type="button"
                                aria-label="回答有帮助"
                                aria-pressed={messageFeedback[message.id] === "up"}
                                onClick={() => void handleFeedback(
                                  message.id,
                                  messageFeedback[message.id] === "up" ? null : "up"
                                )}
                              >
                                <IconThumbUp size={15} stroke={1.8} aria-hidden="true" />
                              </button>
                              <span aria-hidden="true" />
                              <button
                                type="button"
                                aria-label="回答无帮助"
                                aria-pressed={messageFeedback[message.id] === "down"}
                                onClick={() => {
                                  if (messageFeedback[message.id] === "down") {
                                    void handleFeedback(message.id, null);
                                    return;
                                  }
                                  setMessageFeedback((previous) => ({ ...previous, [message.id]: "down" }));
                                  setFeedbackReasonMessageId(message.id);
                                }}
                              >
                                <IconThumbDown size={15} stroke={1.8} aria-hidden="true" />
                              </button>
                              <span aria-hidden="true" />
                              <button
                                type="button"
                                aria-label="复制回答"
                                onClick={() => void navigator.clipboard?.writeText(message.content)}
                              >
                                <IconCopy size={15} stroke={1.8} aria-hidden="true" />
                              </button>
                            </div>

                            {feedbackReasonMessageId === message.id ? (
                              <div className="bomb-shell__feedback-reasons" role="group" aria-label="点踩原因">
                                <span>指出原因</span>
                                {[
                                  ["factual_error", "事实错误"],
                                  ["citation_error", "引用错误"],
                                  ["formatting", "格式问题"],
                                  ["not_helpful", "没有帮助"],
                                  ["other", "其他"]
                                ].map(([reason, label]) => (
                                  <button
                                    key={reason}
                                    type="button"
                                    onClick={() => void handleFeedback(
                                      message.id,
                                      "down",
                                      reason as "factual_error" | "citation_error" | "formatting" | "not_helpful" | "other"
                                    )}
                                  >
                                    {label}
                                  </button>
                                ))}
                              </div>
                            ) : null}

                            <button
                              type="button"
                              className="bomb-shell__regenerate"
                              disabled={!precedingUserMessage || isGenerating}
                              onClick={() => {
                                if (precedingUserMessage) {
                                  void sendMessage(precedingUserMessage.content);
                                }
                              }}
                            >
                              <IconRefresh size={14} stroke={1.8} aria-hidden="true" />
                              <span>Regenerate</span>
                            </button>
                          </div>
                        ) : null}
                      </div>

                      {isUser ? (
                        <div className="bomb-shell__avatar bomb-shell__avatar--user">
                          {profileAvatarUrl ? (
                            <img
                              className="bomb-shell__message-avatar-photo"
                              src={profileAvatarUrl}
                              alt=""
                              aria-hidden="true"
                            />
                          ) : (
                            <IconUserCircle size={18} stroke={1.8} aria-hidden="true" />
                          )}
                        </div>
                      ) : null}

                      {isUser ? (
                        <div className="bomb-shell__user-message-actions"><button type="button" className="bomb-shell__message-edit" aria-label="复制此消息" onClick={() => void navigator.clipboard?.writeText(message.content)}><IconCopy size={15} stroke={1.8} /></button><button
                          type="button"
                          className="bomb-shell__message-edit"
                          aria-label="再次编辑此消息"
                          onClick={() => {
                            setDraft(message.content);
                            textareaRef.current?.focus();
                          }}
                        >
                          <IconEdit size={15} stroke={1.8} aria-hidden="true" />
                        </button></div>
                      ) : null}
                    </div>
                  );
                })}
                {capeCases.map((capeCase, caseIndex) => (
                  <div
                    key={`cape-case-${capeCase.id}`}
                    className="bomb-shell__message-row bomb-shell__message-row--cape"
                    data-testid={`cape-case-row-${capeCase.id}`}
                    ref={messages.length === 0 && caseIndex === capeCases.length - 1 ? lastMessageRef : null}
                  >
                    <div className="bomb-shell__avatar bomb-shell__avatar--assistant">
                      <img className="bomb-shell__avatar-mark" src={cipherLogo} alt="" aria-hidden="true" />
                    </div>
                    <SandboxIntelligenceCard
                      capeCase={capeCase}
                      onAction={(prompt) => {
                        void sendMessage(prompt);
                      }}
                      onExport={downloadCapeCaseExport}
                    />
                  </div>
                ))}
                </>
              )}

              {messages.length > 0 || capeCases.length > 0 ? <div ref={messagesEndRef} className="bomb-shell__message-anchor" /> : null}
            </div>
          </section>

          {messages.length > 0 || capeCases.length > 0 ? renderComposer("docked") : null}

          {isDragActive ? (
            <div className="bomb-shell__drop-overlay" aria-hidden="true">
              <div className="bomb-shell__drop-overlay-card">
                <span className="bomb-shell__drop-overlay-title">拖入文件即可添加附件</span>
                <span className="bomb-shell__drop-overlay-copy">文件会暂存在输入框上方，发送这条消息时一起提交。</span>
              </div>
            </div>
          ) : null}
        </div>

        <aside className="bomb-shell__upgrade-rail" aria-label="升级入口">
          <button
            type="button"
            className="bomb-shell__upgrade-tab"
            onClick={() => setSettingsOpen(true)}
          >
            <IconSparkles size={15} stroke={1.9} aria-hidden="true" />
            <span>升级 Pro</span>
          </button>
        </aside>
      </div>

      {modelMenuMounted ? (
        <div
          ref={modelMenuRef}
          className={`bomb-shell__model-menu${
            modelMenuVisible ? " bomb-shell__model-menu--open" : " bomb-shell__model-menu--closing"
          }`}
          data-placement={modelMenuPosition.placement}
          style={{
            left: `${modelMenuPosition.left}px`,
            top: `${modelMenuPosition.top}px`
          }}
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
            className="bomb-shell__context-menu-item"
            onClick={() => {
              if (contextMenuConversation) {
                setRenameDialogState({
                  conversationId: contextMenuConversation.id,
                  title: contextMenuConversation.title
                });
              }
              setContextMenuState(null);
            }}
          >
            重命名
          </button>
          <button
            type="button"
            className="bomb-shell__context-menu-item"
            onClick={() => {
              if (contextMenuConversation) {
                void setConversationPinned(
                  contextMenuConversation.id,
                  !contextMenuConversation.isPinned
                ).catch(() => undefined);
              }
              setContextMenuState(null);
            }}
          >
            {contextMenuConversation?.isPinned ? "取消置顶" : "置顶会话"}
          </button>
          <button
            type="button"
            className="bomb-shell__context-menu-item"
            onClick={() => {
              if (contextMenuConversation) {
                void setConversationArchived(
                  contextMenuConversation.id,
                  !contextMenuConversation.isArchived
                ).catch(() => undefined);
              }
              setContextMenuState(null);
            }}
          >
            {contextMenuConversation?.isArchived ? "移出归档" : "归档会话"}
          </button>
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

      {renameDialogState ? (
        <div className="bomb-shell__dialog-scrim" role="presentation">
          <form
            className="bomb-shell__rename-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="rename-conversation-title"
            onSubmit={(event) => {
              event.preventDefault();
              const field = event.currentTarget.elements.namedItem("conversation-title");
              const title = field instanceof HTMLInputElement ? field.value.trim() : "";
              if (!title) {
                return;
              }
              void renameConversation(renameDialogState.conversationId, title).then(() => {
                setRenameDialogState(null);
              }).catch(() => undefined);
            }}
          >
            <p className="eyebrow">会话管理</p>
            <h2 id="rename-conversation-title">重命名对话</h2>
            <input
              name="conversation-title"
              defaultValue={renameDialogState.title}
              maxLength={255}
              autoFocus
              aria-label="会话名称"
            />
            <div className="bomb-shell__rename-dialog-actions">
              <button type="button" className="secondary-button" onClick={() => setRenameDialogState(null)}>
                取消
              </button>
              <button type="submit" className="primary-button">保存</button>
            </div>
          </form>
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
            data-dragging={drawerDragOffset < 0 ? "true" : undefined}
            style={drawerDragOffset < 0 ? { transform: `translate3d(${drawerDragOffset}px, 0, 0) scale(0.985)` } : undefined}
            onTouchStart={handleDrawerTouchStart}
            onTouchMove={handleDrawerTouchMove}
            onTouchEnd={handleDrawerTouchEnd}
            onTouchCancel={handleDrawerTouchEnd}
          >
            <aside className="bomb-shell__drawer-sidebar" aria-label="会话导航">
              {renderSidebarContent()}
            </aside>
          </div>
        </div>
      ) : null}

      {templatePickerOpen ? <AnalysisTemplatePicker templates={analysisTemplates} title="选择安全分析模板" onSelect={templateId => void initializeNewConversation(templateId)} onClose={() => setTemplatePickerOpen(false)} /> : null}
      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        openerRef={settingsButtonRef}
        settings={settings}
        onSettingsChange={(nextSettings) => {
          updateSettings(nextSettings);
          if (nextSettings.modelId) {
            setModelId(resolveDeepSeekModelId(nextSettings.modelId));
          }
        }}
      />
      <CaseWorkspaceDrawer
        open={caseWorkspaceOpen}
        conversation={activeConversation}
        onClose={() => setCaseWorkspaceOpen(false)}
        openerRef={caseWorkspaceButtonRef}
        onUpdate={updateCaseMetadata}
        onExport={downloadCapeCaseExport}
      />
      <CapeDrawer
        open={capePanelOpen}
        onClose={() => setCapePanelOpen(false)}
        onSubmitCase={submitCapeCase}
        openerRef={capeButtonRef}
      />
    </main>
  );
}
