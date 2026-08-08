import { IconBiohazard, IconRefresh, IconUpload } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";

import { CapeReportNotReadyError, getCapeTaskStatus, getCapeTaskSummary, submitCapeSample } from "../../lib/api";
import type { CapeAnalysisSummary, CapeTaskStatus } from "../../types";

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

export function AdminCapePanel() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [taskStatus, setTaskStatus] = useState<CapeTaskStatus | null>(null);
  const [summary, setSummary] = useState<CapeAnalysisSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!taskStatus || (taskStatus.completed && summary)) {
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
  }, [summary, taskStatus]);

  async function handleSubmit() {
    if (!selectedFile) {
      setError("请先选择一个样本文件。");
      return;
    }

    setLoading(true);
    setError(null);
    setNotice(null);
    setSummary(null);

    try {
      const submission = await submitCapeSample(selectedFile);
      if (submission.reusedExistingTask) {
        setNotice(`已复用正在分析的 CAPE 任务 #${submission.taskId}，不用重复排队。`);
      }
      const nextStatus = await getCapeTaskStatus(submission.taskId);
      setTaskStatus(nextStatus);

      if (nextStatus.completed) {
        await fetchSummaryIfReady(nextStatus.taskId);
      }
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "提交 CAPE 样本失败。");
    } finally {
      setLoading(false);
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
    <div className="admin-panel-stack">
      <section className="admin-card admin-card--wide">
        <div className="admin-card__header">
          <div>
            <p className="eyebrow">CAPE</p>
            <h2>本地沙箱提交</h2>
          </div>
          <IconBiohazard size={18} stroke={1.8} aria-hidden="true" />
        </div>

        <p className="admin-card__copy">
          把样本直接提交到本机 `127.0.0.1:8080` 的 CAPE，再在这里查看任务状态和摘要结果。
        </p>

        {error ? (
          <p className="status-banner status-banner--error" role="alert">
            {error}
          </p>
        ) : null}

        {notice ? <p className="status-banner">{notice}</p> : null}

        <div className="admin-cape-upload-row">
          <input
            ref={fileInputRef}
            className="sr-only"
            type="file"
            onChange={(event) => {
              setSelectedFile(event.target.files?.[0] ?? null);
              setError(null);
            }}
          />
          <button type="button" className="secondary-button" onClick={() => fileInputRef.current?.click()}>
            <IconUpload size={16} stroke={1.8} aria-hidden="true" />
            选择样本
          </button>
          <button type="button" className="secondary-button" disabled={loading} onClick={() => void handleSubmit()}>
            <IconBiohazard size={16} stroke={1.8} aria-hidden="true" />
            {loading ? "正在提交..." : "提交到 CAPE"}
          </button>
          <button
            type="button"
            className="secondary-button secondary-button--soft"
            disabled={!taskStatus || refreshing}
            onClick={() => void handleRefresh()}
          >
            <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
            {refreshing ? "刷新中..." : "刷新状态"}
          </button>
        </div>

        <p className="admin-card__meta">
          {selectedFile ? `当前文件：${selectedFile.name}` : "还没有选择样本文件。"}
        </p>
      </section>

      {taskStatus ? (
        <section className="admin-card admin-card--wide">
          <div className="admin-card__header">
            <div>
              <p className="eyebrow">任务</p>
              <h2>CAPE 任务状态</h2>
            </div>
            <span
              className={`admin-status-chip${
                taskStatus.completed ? " admin-status-chip--ready" : " admin-status-chip--idle"
              }`}
            >
              {getCapeStatusLabel(taskStatus.status)}
            </span>
          </div>

          <dl className="admin-meta-list">
            <div>
              <dt>任务 ID</dt>
              <dd>{taskStatus.taskId}</dd>
            </div>
            <div>
              <dt>样本名</dt>
              <dd>{taskStatus.targetFilename ?? "等待 CAPE 返回"}</dd>
            </div>
            <div>
              <dt>分析机</dt>
              <dd>{taskStatus.machine ?? "未返回"}</dd>
            </div>
            <div>
              <dt>评分</dt>
              <dd>{taskStatus.score ?? "未返回"}</dd>
            </div>
          </dl>
        </section>
      ) : null}

      {summary ? (
        <section className="admin-card admin-card--wide">
          <div className="admin-card__header">
            <div>
              <p className="eyebrow">摘要</p>
              <h2>分析结果速览</h2>
            </div>
          </div>

          <div className="admin-card-grid">
            <section className="admin-card admin-card--compact">
              <p className="eyebrow">IOC</p>
              <h3>网络指标</h3>
              <p className="admin-card__meta">
                域名 {formatCount(summary.iocs.domains.length)} / IP {formatCount(summary.iocs.ips.length)} / URL{" "}
                {formatCount(summary.iocs.urls.length)}
              </p>
            </section>
            <section className="admin-card admin-card--compact">
              <p className="eyebrow">ATT&CK</p>
              <h3>战术线索</h3>
              <p className="admin-card__meta">{formatCount(summary.tactics.length)} 条映射</p>
            </section>
            <section className="admin-card admin-card--compact">
              <p className="eyebrow">Dropped</p>
              <h3>落地文件</h3>
              <p className="admin-card__meta">{formatCount(summary.droppedFiles.length)} 个文件</p>
            </section>
          </div>

          <div className="admin-cape-columns">
            <div>
              <h3 className="admin-cape-subtitle">IOC 预览</h3>
              <ul className="admin-cape-list">
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
              <h3 className="admin-cape-subtitle">ATT&CK / 行为</h3>
              <ul className="admin-cape-list">
                {summary.tactics.slice(0, 5).map((item) => (
                  <li key={`${item.technique}-${item.signature}`}>
                    {item.technique} · {item.signature}
                  </li>
                ))}
                {summary.tactics.length === 0 ? <li>暂无 TTP 映射。</li> : null}
              </ul>
            </div>

            <div>
              <h3 className="admin-cape-subtitle">落地文件</h3>
              <ul className="admin-cape-list">
                {summary.droppedFiles.slice(0, 5).map((item) => (
                  <li key={`${item.path}-${item.sha256}`}>{item.name || item.path}</li>
                ))}
                {summary.droppedFiles.length === 0 ? <li>暂无落地文件。</li> : null}
              </ul>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  );
}
