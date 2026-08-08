import { useEffect, useMemo, useState } from "react";
import { IconAlertTriangle, IconArrowLeft, IconBriefcase, IconChevronRight, IconClock, IconGitMerge, IconMessage, IconPlus, IconRefresh, IconSearch, IconShieldCheck, IconTestPipe } from "@tabler/icons-react";
import { createInvestigationCase, getInvestigationCase, listAnalysisTemplates, listInvestigationCases, mergeInvestigationCase, updateInvestigationCase } from "../lib/api";
import type { AnalysisTemplate, CaseSeverity, CaseStatus, InvestigationCase, InvestigationCaseList } from "../types";
import { AnalysisTemplatePicker } from "../components/AnalysisTemplatePicker";
import { CaseIndicatorsPanel } from "../components/cases/CaseIndicatorsPanel";
import { CaseDetectionRulesPanel } from "../components/cases/CaseDetectionRulesPanel";
import { CasePlaybookPanel } from "../components/cases/CasePlaybookPanel";
import { CaseEvidencePanel } from "../components/cases/CaseEvidencePanel";
import { CaseSkillsPanel } from "../components/cases/CaseSkillsPanel";
import { CaseCollaborationPanel } from "../components/cases/CaseCollaborationPanel";
import { CaseAnalysisPanel } from "../components/cases/CaseAnalysisPanel";

const STATUS: Array<{ value: CaseStatus; label: string }> = [
  { value: "open", label: "新建" }, { value: "triage", label: "分诊" }, { value: "investigating", label: "调查中" },
  { value: "review", label: "待复核" }, { value: "confirmed", label: "已确认" }, { value: "contained", label: "已处置" },
  { value: "remediating", label: "处置中" }, { value: "closed", label: "已关闭" }
];
const SEVERITY: Array<{ value: CaseSeverity | ""; label: string }> = [
  { value: "", label: "全部严重度" }, { value: "critical", label: "严重" }, { value: "high", label: "高危" },
  { value: "medium", label: "中危" }, { value: "low", label: "低危" }, { value: "unknown", label: "未定级" }
];
const statusLabel = (value: string) => STATUS.find(item => item.value === value)?.label ?? value;
const severityLabel = (value: string) => SEVERITY.find(item => item.value === value)?.label ?? value;
const time = (value: string | null) => value ? new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value)) : "未设置";

export function CasesPage({ onBack }: { onBack: () => void }) {
  const [data, setData] = useState<InvestigationCaseList | null>(null);
  const [selected, setSelected] = useState<InvestigationCase | null>(null);
  const [filters, setFilters] = useState({ status: "", severity: "", assignee: "", tag: "", sort: "priority", overdue: "" });
  const [query, setQuery] = useState(""); const [loading, setLoading] = useState(true); const [error, setError] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const [templates, setTemplates] = useState<AnalysisTemplate[]>([]); const [templatePickerOpen, setTemplatePickerOpen] = useState(false);
  async function load(preferredId?: number) {
    setLoading(true); setError(null);
    try {
      const next = await listInvestigationCases(filters); setData(next);
      const id = preferredId ?? selected?.id ?? next.items[0]?.id;
      if (id && next.items.some(item => item.id === id)) setSelected(await getInvestigationCase(id)); else setSelected(null);
    } catch (e) { setError(e instanceof Error ? e.message : "Case 数据加载失败"); } finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, [filters.status, filters.severity, filters.assignee, filters.tag, filters.sort, filters.overdue]);
  useEffect(() => { listAnalysisTemplates().then(result => setTemplates(result.items)).catch(() => undefined); }, []);
  const visible = useMemo(() => (data?.items ?? []).filter(item => `${item.title} ${item.tags.join(" ")} ${item.assignee ?? ""}`.toLowerCase().includes(query.toLowerCase())), [data, query]);
  async function createCase(templateId: number | null) { setTemplatePickerOpen(false); const title = window.prompt("Case 标题"); if (!title?.trim()) return; setBusy(true); try { const item = await createInvestigationCase({ title, ...(templateId ? { templateId } : {}) }); await load(item.id); } finally { setBusy(false); } }
  async function patchCase(payload: Parameters<typeof updateInvestigationCase>[1]) { if (!selected) return; setBusy(true); try { const item = await updateInvestigationCase(selected.id, payload); setSelected(item); await load(item.id); } catch (e) { setError(e instanceof Error ? e.message : "更新失败"); } finally { setBusy(false); } }
  async function mergeCase() { if (!selected) return; const raw = window.prompt("合并至 Case ID（当前 Case 将关闭）"); const target = Number(raw); if (!Number.isInteger(target) || !window.confirm(`确认将 Case #${selected.id} 合并至 #${target}？`)) return; setBusy(true); try { const item = await mergeInvestigationCase(selected.id, target); await load(item.id); } catch (e) { setError(e instanceof Error ? e.message : "合并失败"); } finally { setBusy(false); } }
  return <main className="cases-page">
    {templatePickerOpen ? <AnalysisTemplatePicker templates={templates} title="为 Case 选择分析模板" onSelect={templateId => void createCase(templateId)} onClose={() => setTemplatePickerOpen(false)} /> : null}
    <header className="cases-page__header"><button className="cases-icon-button" onClick={onBack} aria-label="返回聊天"><IconArrowLeft size={19}/></button><div><p>CIPHER / INCIDENT OPERATIONS</p><h1>Case 中心</h1></div><div className="cases-page__header-actions"><button className="cases-icon-button" onClick={() => void load()} aria-label="刷新"><IconRefresh size={18}/></button><button className="cases-primary" onClick={() => setTemplatePickerOpen(true)} disabled={busy}><IconPlus size={17}/>新建 Case</button></div></header>
    <section className="cases-summary" aria-label="Case 状态概览">{STATUS.map(item => <button key={item.value} className={filters.status === item.value ? "is-active" : ""} onClick={() => setFilters(v => ({ ...v, status: v.status === item.value ? "" : item.value }))}><span>{item.label}</span><strong>{data?.counts[item.value] ?? 0}</strong></button>)}<div className="cases-summary__sla"><IconAlertTriangle size={18}/><span>SLA 超时</span><strong>{data?.items.filter(item => item.overdue).length ?? 0}</strong></div></section>
    <section className="cases-toolbar"><label><IconSearch size={16}/><input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索标题、标签或负责人" /></label><select value={filters.severity} onChange={e => setFilters(v => ({ ...v, severity: e.target.value }))}>{SEVERITY.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select><input value={filters.assignee} onChange={e => setFilters(v => ({ ...v, assignee: e.target.value }))} placeholder="负责人"/><input value={filters.tag} onChange={e => setFilters(v => ({ ...v, tag: e.target.value }))} placeholder="标签"/><select value={filters.overdue} onChange={e => setFilters(v => ({ ...v, overdue: e.target.value }))}><option value="">全部 SLA</option><option value="true">仅超时</option></select><select value={filters.sort} onChange={e => setFilters(v => ({ ...v, sort: e.target.value }))}><option value="priority">优先级</option><option value="sla">SLA</option><option value="updated">最近更新</option></select></section>
    {error ? <div className="cases-error"><IconAlertTriangle size={18}/>{error}<button onClick={() => void load()}>重试</button></div> : null}
    <div className={`cases-workspace${selected ? " has-selection" : ""}`}>
      <section className="cases-list" aria-label="Case 列表">{loading ? Array.from({length:5},(_,i)=><div className="cases-skeleton" key={i}/>) : visible.length === 0 ? <div className="cases-empty"><IconBriefcase size={28}/><strong>没有符合条件的 Case</strong><span>调整筛选条件，或创建一个新的调查事件。</span></div> : visible.map(item => <button key={item.id} className={`case-row${selected?.id === item.id ? " is-selected" : ""}`} onClick={async()=>setSelected(await getInvestigationCase(item.id))}><span className={`case-row__severity is-${item.severity}`}/><span className="case-row__main"><span><b>#{item.id}</b><strong>{item.title}</strong></span><small>{item.assignee || "未分配"} · 更新于 {time(item.updatedAt)}</small><span className="case-row__tags">{item.tags.slice(0,3).map(tag=><i key={tag}>{tag}</i>)}</span></span><span className="case-row__metrics"><em className={`status is-${item.status}`}>{statusLabel(item.status)}</em>{item.overdue ? <em className="overdue"><IconClock size={13}/>已超时</em> : <small>SLA {time(item.slaDueAt)}</small>}<small>{item.conversationCount} 对话 · {item.capeTaskCount} 任务</small></span><IconChevronRight size={17}/></button>)}</section>
      <aside className="case-detail">{selected ? <><div className="case-detail__head"><div><span>CASE #{selected.id}</span><h2>{selected.title}</h2></div><button className="cases-icon-button" onClick={() => setSelected(null)} aria-label="关闭详情">×</button></div><div className="case-detail__controls"><label>状态<select value={selected.status} onChange={e=>void patchCase({status:e.target.value as CaseStatus})} disabled={busy}>{STATUS.map(i=><option key={i.value} value={i.value}>{i.label}</option>)}</select></label><label>严重度<select value={selected.severity} onChange={e=>void patchCase({severity:e.target.value as CaseSeverity})} disabled={busy}>{SEVERITY.filter(i=>i.value).map(i=><option key={i.value} value={i.value}>{i.label}</option>)}</select></label><label>优先级<select value={selected.priority} onChange={e=>void patchCase({priority:Number(e.target.value)})} disabled={busy}>{[1,2,3,4,5].map(i=><option key={i} value={i}>P{i}</option>)}</select></label></div><p className="case-detail__summary">{selected.summary || "尚未填写研判摘要。"}</p><div className="case-detail__facts"><span><IconMessage size={16}/><b>{selected.conversationCount}</b> 对话</span><span><IconTestPipe size={16}/><b>{selected.sampleCount}</b> 样本</span><span><IconShieldCheck size={16}/><b>{selected.iocCount}</b> IOC</span></div>
      <CasePlaybookPanel caseId={selected.id}/>
      <CaseSkillsPanel currentCase={selected} onCompleted={() => void load(selected.id)}/>
      <CaseIndicatorsPanel caseId={selected.id} onCountChange={iocCount => setSelected(current => current && current.id === selected.id ? { ...current, iocCount } : current)}/>
      <CaseDetectionRulesPanel caseId={selected.id}/>
      <CaseEvidencePanel caseId={selected.id} onChanged={() => void load(selected.id)}/>
      <CaseCollaborationPanel caseId={selected.id}/>
      <CaseAnalysisPanel caseId={selected.id}/>
      <section className="case-detail__section"><h3>关联调查</h3>{selected.conversations.length ? selected.conversations.map(c=><a href={`/chat?conversation=${c.id}`} key={c.id}><span><IconMessage size={15}/><strong>{c.title}</strong></span><small>{c.messageCount} 消息 · {c.sampleCount} CAPE</small></a>) : <p>尚未关联对话</p>}</section>
      <div className="case-detail__relations"><span>父 Case：{selected.parentCaseId ? `#${selected.parentCaseId}` : "无"}</span><span>子 Case：{selected.childCaseIds.length ? selected.childCaseIds.map(id=>`#${id}`).join("、") : "无"}</span><button onClick={()=>void mergeCase()} disabled={busy}><IconGitMerge size={15}/>合并重复 Case</button></div></> : <div className="cases-empty"><IconBriefcase size={28}/><strong>选择一个 Case</strong><span>查看其调查上下文、CAPE 任务和处置时间线。</span></div>}</aside>
    </div>
  </main>;
}
