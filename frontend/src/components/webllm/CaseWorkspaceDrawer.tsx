import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import {
  IconBiohazard,
  IconBriefcase,
  IconDownload,
  IconFileText,
  IconLink,
  IconShieldCheck,
  IconX
} from "@tabler/icons-react";

import type {
  CapeExportFormat,
  CaseMetadataUpdate,
  CaseSeverity,
  CaseStatus,
  LocalConversation,
  MessageEvidence
} from "../../types";

type CaseWorkspaceDrawerProps = {
  conversation: LocalConversation | null;
  onClose: () => void;
  onExport: (caseId: number, format: CapeExportFormat) => Promise<void>;
  onUpdate: (conversationId: string, metadata: CaseMetadataUpdate) => Promise<void>;
  openerRef?: RefObject<HTMLButtonElement | null>;
  open: boolean;
};

const STATUS_OPTIONS: Array<{ value: CaseStatus; label: string }> = [
  { value: "open", label: "待研判" },
  { value: "investigating", label: "研判中" },
  { value: "contained", label: "已遏制" },
  { value: "closed", label: "已关闭" }
];

const SEVERITY_OPTIONS: Array<{ value: CaseSeverity; label: string }> = [
  { value: "unknown", label: "未定级" },
  { value: "low", label: "低" },
  { value: "medium", label: "中" },
  { value: "high", label: "高" },
  { value: "critical", label: "严重" }
];

const EXPORT_ACTIONS: Array<{ format: CapeExportFormat; label: string }> = [
  { format: "bundle", label: "完整证据包" },
  { format: "markdown", label: "SOC 报告" },
  { format: "html", label: "HTML 报告" },
  { format: "pdf", label: "PDF 报告" },
  { format: "ioc-csv", label: "IOC CSV" },
  { format: "json", label: "原始 JSON" },
  { format: "sigma", label: "Sigma 初稿" },
  { format: "yara", label: "YARA 初稿" }
];

function evidenceIcon(sourceType: string) {
  if (sourceType === "web") {
    return <IconLink size={16} stroke={1.8} aria-hidden="true" />;
  }
  if (sourceType === "cape") {
    return <IconBiohazard size={16} stroke={1.8} aria-hidden="true" />;
  }
  return <IconFileText size={16} stroke={1.8} aria-hidden="true" />;
}

function uniqueEvidence(conversation: LocalConversation): MessageEvidence[] {
  const items = conversation.messages.flatMap((message) => message.evidence ?? []);
  return items.filter(
    (item, index) =>
      items.findIndex(
        (candidate) =>
          candidate.citation === item.citation &&
          candidate.title === item.title &&
          candidate.url === item.url
      ) === index
  );
}

export function CaseWorkspaceDrawer({
  conversation,
  onClose,
  onExport,
  onUpdate,
  openerRef,
  open
}: CaseWorkspaceDrawerProps) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const lastConversationIdRef = useRef<string | null>(null);
  const [caseStatus, setCaseStatus] = useState<CaseStatus>("open");
  const [severity, setSeverity] = useState<CaseSeverity>("unknown");
  const [assignee, setAssignee] = useState("");
  const [tags, setTags] = useState("");
  const [caseSummary, setCaseSummary] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState<string | null>(null);

  useEffect(() => {
    if (!open) {
      lastConversationIdRef.current = null;
      openerRef?.current?.focus();
      return;
    }
    closeButtonRef.current?.focus();
    if (!conversation || lastConversationIdRef.current === conversation.id) {
      return;
    }
    lastConversationIdRef.current = conversation.id;
    setCaseStatus(conversation.caseStatus ?? "open");
    setSeverity(conversation.severity ?? "unknown");
    setAssignee(conversation.assignee ?? "");
    setTags((conversation.tags ?? []).join(", "));
    setCaseSummary(conversation.caseSummary ?? "");
    setError(null);
    setSaved(false);
  }, [conversation, open, openerRef]);

  const evidence = useMemo(() => (conversation ? uniqueEvidence(conversation) : []), [conversation]);
  const capeCases = conversation?.capeCases ?? [];
  const iocCount = capeCases.reduce((count, capeCase) => {
    const iocs = capeCase.summary?.iocs;
    return count + (iocs ? iocs.domains.length + iocs.ips.length + iocs.urls.length : 0);
  }, 0);

  if (!open) {
    return null;
  }

  async function handleSave() {
    if (!conversation || saving) {
      return;
    }
    const normalizedTags = tags
      .split(/[,，]/u)
      .map((item) => item.trim())
      .filter(Boolean)
      .filter((item, index, items) => items.indexOf(item) === index)
      .slice(0, 12);

    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      await onUpdate(conversation.id, {
        caseStatus,
        severity,
        assignee: assignee.trim(),
        tags: normalizedTags,
        caseSummary: caseSummary.trim()
      });
      setSaved(true);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "保存 Case 信息失败。");
    } finally {
      setSaving(false);
    }
  }

  async function handleExport(caseId: number, format: CapeExportFormat) {
    const key = `${caseId}:${format}`;
    setExporting(key);
    setError(null);
    try {
      await onExport(caseId, format);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "导出 CAPE 证据失败。");
    } finally {
      setExporting(null);
    }
  }

  return (
    <aside
      className="case-workspace-drawer"
      role="dialog"
      aria-modal="true"
      aria-label="Case 工作区"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          onClose();
        }
      }}
    >
      <header className="case-workspace-drawer__header">
        <div>
          <p className="eyebrow">Investigation workspace</p>
          <h2><IconBriefcase size={20} stroke={1.8} aria-hidden="true" /> Case 工作区</h2>
          <p>{conversation?.title ?? "尚未创建 Case"}</p>
        </div>
        <button ref={closeButtonRef} type="button" onClick={onClose} aria-label="关闭 Case 工作区">
          <IconX size={18} stroke={1.9} aria-hidden="true" />
        </button>
      </header>

      {!conversation ? (
        <div className="case-workspace-drawer__empty">
          <IconBriefcase size={24} stroke={1.5} aria-hidden="true" />
          <h3>先发起一次分析</h3>
          <p>发送消息或提交 CAPE 样本后，当前对话会自动成为一个可管理的 Case。</p>
        </div>
      ) : (
        <div className="case-workspace-drawer__body">
          <section className="case-workspace-drawer__stats" aria-label="Case 摘要">
            <div><strong>{conversation.messages.length}</strong><span>消息</span></div>
            <div><strong>{capeCases.length}</strong><span>CAPE</span></div>
            <div><strong>{iocCount}</strong><span>IOC</span></div>
            <div><strong>{evidence.length}</strong><span>引用证据</span></div>
          </section>

          <section className="case-workspace-drawer__section">
            <div className="case-workspace-drawer__section-heading">
              <div>
                <p className="eyebrow">Case control</p>
                <h3>研判状态</h3>
              </div>
              <span className={`case-workspace-drawer__severity case-workspace-drawer__severity--${severity}`}>
                {SEVERITY_OPTIONS.find((option) => option.value === severity)?.label}
              </span>
            </div>

            <div className="case-workspace-drawer__fields">
              <label>
                <span>状态</span>
                <select value={caseStatus} onChange={(event) => { setCaseStatus(event.target.value as CaseStatus); setSaved(false); }}>
                  {STATUS_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label>
                <span>严重度</span>
                <select value={severity} onChange={(event) => { setSeverity(event.target.value as CaseSeverity); setSaved(false); }}>
                  {SEVERITY_OPTIONS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
              </label>
              <label>
                <span>负责人</span>
                <input value={assignee} maxLength={80} placeholder="例如：SOC 一线" onChange={(event) => { setAssignee(event.target.value); setSaved(false); }} />
              </label>
              <label>
                <span>标签</span>
                <input value={tags} placeholder="恶意软件, 高优先级" onChange={(event) => { setTags(event.target.value); setSaved(false); }} />
              </label>
              <label className="case-workspace-drawer__summary-field">
                <span>研判摘要</span>
                <textarea value={caseSummary} maxLength={4000} rows={4} placeholder="记录已确认事实、待验证假设与下一步动作…" onChange={(event) => { setCaseSummary(event.target.value); setSaved(false); }} />
              </label>
            </div>
            <div className="case-workspace-drawer__save-row">
              {saved ? <span role="status"><IconShieldCheck size={15} stroke={1.9} aria-hidden="true" /> 已保存</span> : <span />}
              <button type="button" className="primary-button" disabled={saving} onClick={() => void handleSave()}>
                {saving ? "保存中…" : "保存 Case"}
              </button>
            </div>
          </section>

          <section className="case-workspace-drawer__section">
            <div className="case-workspace-drawer__section-heading">
              <div><p className="eyebrow">Evidence ledger</p><h3>证据台账</h3></div>
              <span>{evidence.length}</span>
            </div>
            {evidence.length > 0 ? (
              <ul className="case-workspace-drawer__evidence-list">
                {evidence.slice(0, 12).map((item, index) => (
                  <li key={`${item.citation}-${item.url ?? item.title}-${index}`}>
                    <span className="case-workspace-drawer__evidence-icon">{evidenceIcon(item.sourceType)}</span>
                    <div>
                      <strong>[{item.citation}] {item.title}</strong>
                      <span>{item.locator ?? item.snippet ?? "已关联到当前回答"}</span>
                    </div>
                    {item.url ? <a href={item.url} target="_blank" rel="noreferrer" aria-label={`打开证据 ${item.title}`}>↗</a> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="case-workspace-drawer__empty-copy">启用联网搜索、发送附件或基于 CAPE Case 提问后，引用来源会自动沉淀在这里。</p>
            )}
          </section>

          <section className="case-workspace-drawer__section">
            <div className="case-workspace-drawer__section-heading">
              <div><p className="eyebrow">CAPE export</p><h3>处置与导出</h3></div>
              <span>{capeCases.length}</span>
            </div>
            {capeCases.length > 0 ? capeCases.map((capeCase) => (
              <article key={capeCase.id} className="case-workspace-drawer__cape-case">
                <div>
                  <strong>Case #{capeCase.id} · {capeCase.sampleName}</strong>
                  <span>{capeCase.completed ? `Score ${capeCase.score ?? "-"} · 报告就绪` : "CAPE 分析中"}</span>
                </div>
                <div className="case-workspace-drawer__export-grid">
                  {EXPORT_ACTIONS.map((action) => {
                    const key = `${capeCase.id}:${action.format}`;
                    return (
                      <button
                        key={action.format}
                        type="button"
                        disabled={!capeCase.summary || exporting !== null}
                        onClick={() => void handleExport(capeCase.id, action.format)}
                      >
                        <IconDownload size={14} stroke={1.8} aria-hidden="true" />
                        {exporting === key ? "导出中…" : action.label}
                      </button>
                    );
                  })}
                </div>
              </article>
            )) : <p className="case-workspace-drawer__empty-copy">当前 Case 还没有 CAPE 样本。提交样本后可以导出报告、IOC 与检测规则初稿。</p>}
          </section>

          {error ? <p className="status-banner status-banner--error" role="alert">{error}</p> : null}
        </div>
      )}
    </aside>
  );
}
