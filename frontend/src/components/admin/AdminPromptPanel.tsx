import { IconDeviceFloppy, IconRefresh, IconRestore, IconSparkles } from "@tabler/icons-react";
import type { AdminPrompt } from "../../types";

function getSourceLabel(source: AdminPrompt["source"]): string {
  return source === "override" ? "自定义覆盖" : "内置默认";
}

function getUpdatedLabel(updatedAt: string | null): string {
  if (!updatedAt) {
    return "当前使用内置默认提示词";
  }

  const timestamp = Date.parse(updatedAt);

  if (Number.isNaN(timestamp)) {
    return updatedAt;
  }

  return new Date(timestamp).toLocaleString("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function getStatusLabel(status: AdminPrompt["status"]): string {
  if (status === "fallback") {
    return "已启用默认回退";
  }

  if (status === "error") {
    return "需要处理";
  }

  return "正常";
}

export function AdminPromptPanel({
  prompt,
  draft,
  loading,
  saving,
  resetting,
  reloading,
  onDraftChange,
  onSave,
  onReload,
  onReset,
}: {
  prompt: AdminPrompt;
  draft: string;
  loading: boolean;
  saving: boolean;
  resetting: boolean;
  reloading: boolean;
  onDraftChange: (value: string) => void;
  onSave: (value: string) => Promise<void> | void;
  onReload: () => Promise<void> | void;
  onReset: () => Promise<void> | void;
}) {
  const isBusy = loading || saving || resetting || reloading;
  const isDirty = draft !== prompt.prompt;
  const statusTone =
    prompt.status === "error" ? "danger" : prompt.status === "fallback" ? "warning" : "ready";

  function handleReset() {
    if (!window.confirm("确定将后端系统提示词重置为内置默认值吗？")) {
      return;
    }

    void onReset();
  }

  return (
    <section className="admin-panel-stack">
      <section className="admin-card admin-card--wide">
        <div className="admin-card__header">
          <div>
            <p className="eyebrow">系统提示词</p>
            <h2>后端系统提示词</h2>
          </div>
          <span className={`admin-status-chip admin-status-chip--${statusTone}`}>
            <IconSparkles size={14} stroke={1.8} aria-hidden="true" />
            {getStatusLabel(prompt.status)}
          </span>
        </div>

        <dl className="admin-meta-list admin-prompt-panel__meta">
          <div>
            <dt>来源</dt>
            <dd>{getSourceLabel(prompt.source)}</dd>
          </div>
          <div>
            <dt>更新时间</dt>
            <dd>{getUpdatedLabel(prompt.updatedAt)}</dd>
          </div>
          <div>
            <dt>编辑状态</dt>
            <dd>{isDirty ? "有未保存修改" : "已与后端同步"}</dd>
          </div>
        </dl>

        {prompt.message ? <p className="admin-prompt-panel__message">{prompt.message}</p> : null}
      </section>

      <section className="admin-card admin-card--wide">
        <div className="admin-card__header">
          <div>
            <p className="eyebrow">编辑器</p>
            <h2>提示词编辑</h2>
          </div>
        </div>

        <label className="prompt-composer__label" htmlFor="admin-prompt-editor">
          系统提示词编辑器
        </label>
        <textarea
          id="admin-prompt-editor"
          className="admin-prompt-panel__editor"
          aria-label="系统提示词编辑器"
          value={draft}
          onChange={(event) => onDraftChange(event.target.value)}
          rows={16}
          spellCheck={false}
          disabled={loading}
        />

        <p className="admin-card__meta">
          这个提示词会由后端注入到每一次对话请求中，公开聊天页面无法单独覆盖它。
        </p>

        <div className="admin-prompt-panel__actions">
          <button
            type="button"
            className="admin-action-button admin-action-button--primary"
            disabled={!isDirty || isBusy}
            onClick={() => void onSave(draft)}
            aria-label="保存提示词"
          >
            <IconDeviceFloppy size={16} stroke={1.8} aria-hidden="true" />
            {saving ? "保存中..." : "保存提示词"}
          </button>

          <button
            type="button"
            className="admin-action-button admin-action-button--ghost"
            disabled={isBusy}
            onClick={() => void onReload()}
            aria-label="重新加载提示词"
          >
            <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
            {reloading ? "加载中..." : "重新加载"}
          </button>

          <button
            type="button"
            className="admin-action-button admin-action-button--danger"
            disabled={isBusy}
            onClick={handleReset}
            aria-label="恢复默认提示词"
          >
            <IconRestore size={16} stroke={1.8} aria-hidden="true" />
            {resetting ? "重置中..." : "恢复默认"}
          </button>
        </div>
      </section>
    </section>
  );
}
