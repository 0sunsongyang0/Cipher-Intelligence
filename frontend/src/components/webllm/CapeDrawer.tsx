import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from "react";

import { CapeReportNotReadyError, getCapeTaskStatus, getCapeTaskSummary, submitCapeSample } from "../../lib/api";
import type { CapeAnalysisSummary, CapeCase, CapeTaskStatus } from "../../types";

type CapeDrawerProps = {
  onClose: () => void;
  onSubmitCase?: (file: File) => Promise<CapeCase>;
  openerRef?: RefObject<HTMLButtonElement | null>;
  open: boolean;
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

function formatCount(value: number) {
  return value.toLocaleString("zh-CN");
}

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

export function CapeDrawer({ onClose, onSubmitCase, openerRef, open }: CapeDrawerProps) {
  const hasOpenedRef = useRef(false);
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [taskStatus, setTaskStatus] = useState<CapeTaskStatus | null>(null);
  const [summary, setSummary] = useState<CapeAnalysisSummary | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

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

  useEffect(() => {
    if (!open || !taskStatus || (taskStatus.completed && summary)) {
      return;
    }

    const intervalId = window.setInterval(() => {
      void (async () => {
        try {
          const nextStatus = await getCapeTaskStatus(taskStatus.taskId);
          setTaskStatus(nextStatus);

          if (nextStatus.completed) {
            await fetchSummaryIfReady(nextStatus.taskId);
          }
        } catch (nextError) {
          setError(nextError instanceof Error ? nextError.message : "刷新 CAPE 任务状态失败。");
        }
      })();
    }, 3000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [open, summary, taskStatus]);

  if (!open) {
    return null;
  }

  async function handleSubmit() {
    if (!selectedFile) {
      setError("请先选择一个样本文件。");
      return;
    }

    setSubmitting(true);
    setError(null);
    setNotice(null);
    setSummary(null);

    try {
      const submission = onSubmitCase
        ? await onSubmitCase(selectedFile)
        : await submitCapeSample(selectedFile);
      const taskId = submission.taskId;
      if (submission.reusedExistingTask) {
        setNotice(`已复用正在分析的 CAPE 任务 #${taskId}，不用重复排队。`);
      } else if (onSubmitCase) {
        setNotice(`已创建 CAPE Case，任务 #${taskId} 会在当前对话中持续更新。`);
      }
      const nextStatus = await getCapeTaskStatus(taskId);
      setTaskStatus(nextStatus);

      if (nextStatus.completed) {
        await fetchSummaryIfReady(nextStatus.taskId);
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "提交 CAPE 样本失败。");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleRefresh() {
    if (!taskStatus) {
      return;
    }

    setRefreshing(true);
    setError(null);
    setNotice(null);

    try {
      const nextStatus = await getCapeTaskStatus(taskStatus.taskId);
      setTaskStatus(nextStatus);

      if (nextStatus.completed) {
        await fetchSummaryIfReady(nextStatus.taskId);
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "刷新 CAPE 任务状态失败。");
    } finally {
      setRefreshing(false);
    }
  }

  async function fetchSummaryIfReady(taskId: number) {
    try {
      const nextSummary = await getCapeTaskSummary(taskId);
      setSummary(nextSummary);
      setNotice(null);
    } catch (nextError) {
      if (nextError instanceof CapeReportNotReadyError) {
        setNotice("CAPE 已完成分析，报告 JSON 还在生成中；稍等几秒会自动刷新。");
        return;
      }

      throw nextError;
    }
  }

  return (
    <aside
      className="settings-drawer bomb-shell__cape-drawer"
      role="dialog"
      aria-label="CAPE 沙箱"
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
        <div className="bomb-shell__cape-heading">
          <p className="eyebrow">本机分析环境</p>
          <h2>本地 CAPE 沙箱</h2>
        </div>
        <button
          className="bomb-shell__cape-close"
          type="button"
          ref={closeButtonRef}
          onClick={onClose}
          aria-label="关闭 CAPE 面板"
          title="关闭面板"
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>

      <p className="settings-drawer__lead">
        样本将提交到本机 CAPE 环境进行分析，任务进度与结果摘要会显示在这里。
      </p>

      {error ? (
        <p className="status-banner status-banner--error" role="alert">
          {error}
        </p>
      ) : null}

      {notice ? <p className="status-banner">{notice}</p> : null}

      <input
        ref={fileInputRef}
        className="sr-only"
        type="file"
        onChange={(event) => {
          setSelectedFile(event.target.files?.[0] ?? null);
          setError(null);
        }}
      />

      <button
        type="button"
        className={`bomb-shell__cape-file${selectedFile ? " bomb-shell__cape-file--selected" : ""}`}
        aria-label={selectedFile ? `更换样本文件，当前文件 ${selectedFile.name}` : "选择要分析的样本"}
        onClick={() => fileInputRef.current?.click()}
      >
        <span className="bomb-shell__cape-file-icon" aria-hidden="true">↑</span>
        <span className="bomb-shell__cape-file-copy">
          <strong>{selectedFile ? selectedFile.name : "选择要分析的样本"}</strong>
          <span>{selectedFile ? "点击可更换文件" : "从本机选择文件，不会上传到第三方服务"}</span>
        </span>
        <span className="bomb-shell__cape-file-action">{selectedFile ? "更换" : "浏览"}</span>
      </button>

      <div className="bomb-shell__cape-actions">
        <button
          type="button"
          className="primary-button bomb-shell__cape-submit"
          disabled={!selectedFile || submitting}
          onClick={() => void handleSubmit()}
        >
          {submitting ? "正在提交..." : "提交到 CAPE"}
        </button>
        <button
          type="button"
          className="secondary-button secondary-button--soft"
          disabled={!taskStatus || refreshing}
          onClick={() => void handleRefresh()}
        >
          {refreshing ? "刷新中..." : "刷新状态"}
        </button>
      </div>

      {taskStatus ? (
        <dl className="settings-drawer__details bomb-shell__cape-details">
          <dt>任务 ID</dt>
          <dd>{taskStatus.taskId}</dd>
          <dt>状态</dt>
          <dd>{getCapeStatusLabel(taskStatus.status)}</dd>
          <dt>样本名</dt>
          <dd>{taskStatus.targetFilename ?? "等待返回"}</dd>
          <dt>分析机</dt>
          <dd>{taskStatus.machine ?? "未返回"}</dd>
          <dt>评分</dt>
          <dd>{taskStatus.score ?? "未返回"}</dd>
        </dl>
      ) : null}

      {summary ? (
        <div className="bomb-shell__cape-summary">
          <div className="bomb-shell__cape-stat-grid">
            <div className="bomb-shell__cape-stat-card">
              <strong>IOC</strong>
              <span>
                域名 {formatCount(summary.iocs.domains.length)} / IP {formatCount(summary.iocs.ips.length)} / URL{" "}
                {formatCount(summary.iocs.urls.length)}
              </span>
            </div>
            <div className="bomb-shell__cape-stat-card">
              <strong>ATT&CK</strong>
              <span>{formatCount(summary.tactics.length)} 条映射</span>
            </div>
            <div className="bomb-shell__cape-stat-card">
              <strong>Dropped</strong>
              <span>{formatCount(summary.droppedFiles.length)} 个文件</span>
            </div>
          </div>

          <div className="bomb-shell__cape-columns">
            <div>
              <h3>IOC 预览</h3>
              <ul>
                {summary.iocs.domains.slice(0, 5).map((item) => (
                  <li key={`domain-${item}`}>{item}</li>
                ))}
                {summary.iocs.urls.slice(0, 5).map((item) => (
                  <li key={`url-${item}`}>{item}</li>
                ))}
                {summary.iocs.domains.length === 0 && summary.iocs.urls.length === 0 ? <li>暂无网络 IOC。</li> : null}
              </ul>
            </div>
            <div>
              <h3>ATT&CK / 行为</h3>
              <ul>
                {summary.tactics.slice(0, 5).map((item) => (
                  <li key={`${item.technique}-${item.signature}`}>
                    {item.technique} · {item.signature}
                  </li>
                ))}
                {summary.tactics.length === 0 ? <li>暂无 TTP 映射。</li> : null}
              </ul>
            </div>
            <div>
              <h3>落地文件</h3>
              <ul>
                {summary.droppedFiles.slice(0, 5).map((item) => (
                  <li key={`${item.path}-${item.sha256}`}>{item.name || item.path}</li>
                ))}
                {summary.droppedFiles.length === 0 ? <li>暂无落地文件。</li> : null}
              </ul>
            </div>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
