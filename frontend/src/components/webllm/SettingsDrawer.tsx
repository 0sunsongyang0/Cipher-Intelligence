import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";

import {
  DEEPSEEK_MODEL_OPTIONS,
  DEFAULT_DEEPSEEK_MODEL_ID,
  type ChatSettings
} from "../../types";
import { useTheme } from "../../theme";

type SettingsDrawerProps = {
  onClose: () => void;
  openerRef?: RefObject<HTMLButtonElement | null>;
  open: boolean;
  settings: ChatSettings;
  onSettingsChange?: (settings: Partial<ChatSettings>) => void;
};

const FOCUSABLE_SELECTOR = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  '[tabindex]:not([tabindex="-1"])'
].join(", ");

function getFocusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) {
    return [];
  }

  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

function handleDialogTabKey(event: KeyboardEvent<HTMLElement>, container: HTMLElement | null) {
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

const SETTINGS_SECTIONS = [
  { id: "ai", label: "AI 与回答", description: "模型、语言和回答风格" },
  { id: "conversation", label: "对话偏好", description: "联网与新会话行为" },
  { id: "notifications", label: "通知", description: "任务完成提醒" },
  { id: "appearance", label: "外观与辅助", description: "动态和透明材质" }
] as const;

type SettingsSectionId = (typeof SETTINGS_SECTIONS)[number]["id"];

export function SettingsDrawer({
  onClose,
  openerRef,
  open,
  settings,
  onSettingsChange = () => undefined
}: SettingsDrawerProps) {
  const { preference: themePreference, setPreference: setThemePreference } = useTheme();
  const hasOpenedRef = useRef(false);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);
  const [notificationPermission, setNotificationPermission] = useState<NotificationPermission | "unsupported">(
    () => typeof Notification === "undefined" ? "unsupported" : Notification.permission
  );
  const [activeSection, setActiveSection] = useState<SettingsSectionId>("ai");

  useEffect(() => {
    if (open) {
      hasOpenedRef.current = true;
      closeButtonRef.current?.focus();
      return;
    }

    if (hasOpenedRef.current) {
      hasOpenedRef.current = false;
      openerRef?.current?.focus();
    }
  }, [open, openerRef]);

  if (!open) {
    return null;
  }

  async function handleNotificationChange(enabled: boolean) {
    onSettingsChange({ capeNotificationsEnabled: enabled });
    if (!enabled || typeof Notification === "undefined") {
      return;
    }

    if (Notification.permission === "default") {
      const permission = await Notification.requestPermission();
      setNotificationPermission(permission);
      return;
    }

    setNotificationPermission(Notification.permission);
  }

  return (
    <div className="settings-modal">
      <button
        type="button"
        className="settings-modal__scrim"
        aria-label="关闭设置"
        tabIndex={-1}
        onClick={onClose}
      />
      <section
        className="settings-drawer settings-modal__panel"
        role="dialog"
        aria-label="设置"
        aria-modal="true"
        ref={dialogRef}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            onClose();
            return;
          }

          if (event.key === "Tab") {
            handleDialogTabKey(event, dialogRef.current);
          }
        }}
      >
        <div className="settings-drawer__header settings-modal__header">
          <div>
            <p className="eyebrow">工作区偏好</p>
            <h2>设置</h2>
          </div>
          <button
            className="settings-modal__close"
            type="button"
            ref={closeButtonRef}
            onClick={onClose}
            aria-label="关闭设置"
          >
            <span aria-hidden="true">×</span>
          </button>
        </div>

        <div className="settings-modal__layout">
          <nav className="settings-modal__sidebar" aria-label="设置分类">
            <p className="settings-modal__sidebar-label">偏好设置</p>
            {SETTINGS_SECTIONS.map((section) => (
              <button
                key={section.id}
                type="button"
                className={`settings-modal__nav-item${activeSection === section.id ? " settings-modal__nav-item--active" : ""}`}
                aria-current={activeSection === section.id ? "page" : undefined}
                onClick={() => setActiveSection(section.id)}
              >
                <strong>{section.label}</strong>
                <small>{section.description}</small>
              </button>
            ))}
          </nav>

          <div className="settings-modal__content">
            {activeSection === "ai" ? (
              <section className="settings-modal__section" aria-labelledby="settings-ai-title">
                <div className="settings-modal__section-heading">
                  <h3 id="settings-ai-title">AI 与回答</h3>
                  <p>这组设置会一起应用到之后发送的请求。</p>
                </div>
                <div className="settings-drawer__form settings-drawer__form--compact">
                  <label className="settings-drawer__field">
                    <span>默认模型</span>
                    <select
                      value={settings.modelId ?? DEFAULT_DEEPSEEK_MODEL_ID}
                      onChange={(event) => onSettingsChange({ modelId: event.target.value })}
                    >
                      {DEEPSEEK_MODEL_OPTIONS.map((model) => (
                        <option key={model.id} value={model.id}>{model.groupLabel} · {model.label}</option>
                      ))}
                    </select>
                  </label>
                  <div className="settings-modal__field-grid">
                    <label className="settings-drawer__field">
                      <span>回答语言</span>
                      <select
                        value={settings.responseLanguage ?? "zh-CN"}
                        onChange={(event) => onSettingsChange({
                          responseLanguage: event.target.value === "en" ? "en" : "zh-CN"
                        })}
                      >
                        <option value="zh-CN">简体中文</option>
                        <option value="en">English</option>
                      </select>
                    </label>
                    <label className="settings-drawer__field">
                      <span>详细程度</span>
                      <select
                        value={settings.responseLength ?? "balanced"}
                        onChange={(event) => {
                          const value = event.target.value;
                          onSettingsChange({
                            responseLength: value === "concise" || value === "detailed" ? value : "balanced"
                          });
                        }}
                      >
                        <option value="concise">简洁</option>
                        <option value="balanced">均衡</option>
                        <option value="detailed">详细</option>
                      </select>
                    </label>
                  </div>
                </div>
                <dl className="settings-drawer__details settings-drawer__details--compact">
                  <dt>系统提示词</dt>
                  <dd>由管理员后台统一配置</dd>
                </dl>
              </section>
            ) : null}

            {activeSection === "conversation" ? (
              <section className="settings-modal__section" aria-labelledby="settings-conversation-title">
                <div className="settings-modal__section-heading">
                  <h3 id="settings-conversation-title">对话偏好</h3>
                  <p>管理新对话默认启用的能力。</p>
                </div>
                <label className="settings-drawer__toggle">
                  <span>
                    <strong>新对话默认联网</strong>
                    <small>每次新建会话时自动开启联网搜索。</small>
                  </span>
                  <input
                    type="checkbox"
                    checked={settings.defaultWebSearch ?? false}
                    onChange={(event) => onSettingsChange({ defaultWebSearch: event.target.checked })}
                  />
                </label>
              </section>
            ) : null}

            {activeSection === "notifications" ? (
              <section className="settings-modal__section" aria-labelledby="settings-notifications-title">
                <div className="settings-modal__section-heading">
                  <h3 id="settings-notifications-title">通知</h3>
                  <p>即使切换到其他对话，也能及时获知分析进度。</p>
                </div>
                <label className="settings-drawer__toggle">
                  <span>
                    <strong>CAPE 完成通知</strong>
                    <small>
                      {notificationPermission === "granted"
                        ? "桌面与应用内通知已启用。"
                        : notificationPermission === "denied"
                          ? "浏览器已阻止桌面通知，仍会显示应用内通知。"
                          : notificationPermission === "unsupported"
                            ? "当前浏览器仅显示应用内通知。"
                            : "启用时将请求浏览器通知权限。"}
                    </small>
                  </span>
                  <input
                    type="checkbox"
                    checked={settings.capeNotificationsEnabled ?? true}
                    onChange={(event) => void handleNotificationChange(event.target.checked)}
                  />
                </label>
              </section>
            ) : null}

            {activeSection === "appearance" ? (
              <section className="settings-modal__section" aria-labelledby="settings-appearance-title">
                <div className="settings-modal__section-heading">
                  <h3 id="settings-appearance-title">外观与辅助</h3>
                  <p>可跟随系统，也可以为 Cipher 单独选择更安静的视觉效果。</p>
                </div>
                <div className="settings-drawer__form settings-drawer__form--compact">
                  <label className="settings-drawer__field">
                    <span>界面模式</span>
                    <select
                      value={themePreference}
                      onChange={(event) => {
                        const value = event.target.value;
                        setThemePreference(value === "dark" || value === "system" ? value : "light");
                      }}
                    >
                      <option value="light">日间</option>
                      <option value="dark">夜间</option>
                      <option value="system">跟随系统</option>
                    </select>
                  </label>
                  <label className="settings-drawer__field">
                    <span>动态效果</span>
                    <select
                      value={settings.motionPreference ?? "system"}
                      onChange={(event) => {
                        const value = event.target.value;
                        onSettingsChange({
                          motionPreference: value === "reduce" || value === "standard" ? value : "system"
                        });
                      }}
                    >
                      <option value="system">跟随系统</option>
                      <option value="reduce">减少动态</option>
                      <option value="standard">标准动态（系统允许时）</option>
                    </select>
                  </label>
                  <label className="settings-drawer__field">
                    <span>透明材质</span>
                    <select
                      value={settings.transparencyPreference ?? "system"}
                      onChange={(event) => {
                        const value = event.target.value;
                        onSettingsChange({
                          transparencyPreference: value === "reduce" || value === "standard" ? value : "system"
                        });
                      }}
                    >
                      <option value="system">跟随系统</option>
                      <option value="reduce">降低透明度</option>
                      <option value="standard">标准材质（系统允许时）</option>
                    </select>
                  </label>
                </div>
              </section>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
