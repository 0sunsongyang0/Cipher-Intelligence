import { useEffect, useRef, type KeyboardEvent, type RefObject } from "react";

import type { PersistedChatState } from "../../types";

type SettingsDrawerProps = {
  onClose: () => void;
  openerRef?: RefObject<HTMLButtonElement | null>;
  open: boolean;
  settings: PersistedChatState["settings"];
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

export function SettingsDrawer({
  onClose,
  openerRef,
  open,
  settings: _settings
}: SettingsDrawerProps) {
  const hasOpenedRef = useRef(false);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);

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

  return (
    <aside
      className="settings-drawer"
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
      <div className="settings-drawer__header">
        <div>
          <p className="eyebrow">只读信息</p>
          <h2>设置</h2>
        </div>
        <button
          className="secondary-button"
          type="button"
          ref={closeButtonRef}
          onClick={onClose}
          aria-label="关闭设置"
        >
          关闭设置
        </button>
      </div>
      <p className="settings-drawer__lead">后端配置信息仅供查看</p>
      <dl className="settings-drawer__details">
        <dt>服务提供方</dt>
        <dd>DeepSeek 校园后端</dd>
        <dt>模型</dt>
        <dd>由后端配置</dd>
        <dt>系统提示词</dt>
        <dd>由后端配置</dd>
      </dl>
    </aside>
  );
}
