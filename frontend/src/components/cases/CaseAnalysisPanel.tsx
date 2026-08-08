import { useEffect, useMemo, useState } from "react";
import { IconAlertTriangle, IconExternalLink, IconFocus2, IconMinus, IconNetwork, IconPlus, IconTimeline } from "@tabler/icons-react";
import { getCaseAnalysis } from "../../lib/api";
import type { CaseAnalysis, CaseAnalysisEvent, CaseAnalysisNode } from "../../types";

const riskLabel: Record<string, string> = { unknown: "未定级", low: "低危", medium: "中危", high: "高危", critical: "严重" };
const typeLabel: Record<string, string> = { case: "Case", sample: "样本", process: "进程", domain: "域名", ip: "IP", url: "URL", file: "文件", attack: "ATT&CK", behavior: "行为", network: "网络", ioc: "IOC", created: "Case 事件" };
const sourceLabel: Record<string, string> = { case: "Case", cape: "CAPE", ioc: "IOC", attack: "ATT&CK" };
const formatTime = (value: string | null) => value ? new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "medium" }).format(new Date(value)) : "时间未知";
const evidenceLink = (item: Pick<CaseAnalysisEvent, "evidence"> | Pick<CaseAnalysisNode, "evidence">) => item.evidence ? <a className="analysis-evidence" href={item.evidence.href}><IconExternalLink size={13}/>{item.evidence.label}</a> : null;

function Timeline({ data }: { data: CaseAnalysis }) {
  const [filters, setFilters] = useState({ from: "", to: "", type: "", source: "", risk: "" });
  const types = useMemo(() => [...new Set(data.events.map(item => item.type))].sort(), [data]);
  const sources = useMemo(() => [...new Set(data.events.map(item => item.source))].sort(), [data]);
  const visible = useMemo(() => data.events.filter(item => {
    const stamp = item.occurredAt ? new Date(item.occurredAt).getTime() : 0;
    return (!filters.from || stamp >= new Date(filters.from).getTime()) && (!filters.to || stamp <= new Date(filters.to).getTime()) && (!filters.type || item.type === filters.type) && (!filters.source || item.source === filters.source) && (!filters.risk || item.risk === filters.risk);
  }), [data, filters]);
  return <section className="case-analysis__section" aria-labelledby="analysis-timeline-title">
    <div className="case-analysis__title"><div><IconTimeline size={17}/><h3 id="analysis-timeline-title">安全分析时间线</h3></div><span>{visible.length} / {data.events.length} 事件</span></div>
    <div className="analysis-filters"><label>起始时间<input aria-label="起始时间" type="datetime-local" value={filters.from} onChange={event => setFilters(value => ({ ...value, from: event.target.value }))}/></label><label>结束时间<input aria-label="结束时间" type="datetime-local" value={filters.to} onChange={event => setFilters(value => ({ ...value, to: event.target.value }))}/></label><label>事件类型<select aria-label="事件类型" value={filters.type} onChange={event => setFilters(value => ({ ...value, type: event.target.value }))}><option value="">全部类型</option>{types.map(type => <option value={type} key={type}>{typeLabel[type] ?? type}</option>)}</select></label><label>来源<select aria-label="来源" value={filters.source} onChange={event => setFilters(value => ({ ...value, source: event.target.value }))}><option value="">全部来源</option>{sources.map(source => <option value={source} key={source}>{sourceLabel[source] ?? source}</option>)}</select></label><label>风险等级<select aria-label="风险等级" value={filters.risk} onChange={event => setFilters(value => ({ ...value, risk: event.target.value }))}><option value="">全部风险</option>{Object.entries(riskLabel).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label></div>
    <div className="analysis-coverage"><IconAlertTriangle size={14}/><span>精确时间 {data.coverage.exactTimes} 条，推定时间 {data.coverage.estimatedTimes} 条。推定时间以虚线标识。</span></div>
    {visible.length ? <ol className="analysis-timeline">{visible.map(item => <li id={`case-event-${item.id.replace("case:", "")}`} className={`is-${item.risk} ${item.timeAccuracy === "estimated" ? "is-estimated" : ""}`} key={item.id}><span className="analysis-timeline__dot"/><article><div><span>{typeLabel[item.type] ?? item.type}</span><em>{riskLabel[item.risk]}</em></div><strong>{item.title}</strong>{item.detail ? <p>{item.detail}</p> : null}<footer><time>{formatTime(item.occurredAt)}{item.timeAccuracy === "estimated" ? " · 推定" : ""}</time><span title={item.timeNote ?? undefined}>{item.sourceLabel}</span>{evidenceLink(item)}</footer></article></li>)}</ol> : <div className="analysis-empty"><IconTimeline size={24}/><strong>没有符合条件的事件</strong><span>调整时间范围或筛选条件查看其他证据。</span></div>}
  </section>;
}

function Graph({ data }: { data: CaseAnalysis }) {
  const [zoom, setZoom] = useState(1); const [selected, setSelected] = useState<CaseAnalysisNode | null>(null);
  const nodes = data.graph.nodes; const width = 760; const height = 430; const centerX = width / 2; const centerY = height / 2;
  const positions = useMemo(() => new Map(nodes.map((node, index) => { const caseNode = node.type === "case"; const angle = (Math.PI * 2 * index) / Math.max(nodes.length - 1, 1) - Math.PI / 2; const radius = 145 + (index % 3) * 32; return [node.id, { x: caseNode ? centerX : centerX + Math.cos(angle) * radius, y: caseNode ? centerY : centerY + Math.sin(angle) * radius }]; })), [nodes]);
  return <section className="case-analysis__section" aria-labelledby="analysis-graph-title"><div className="case-analysis__title"><div><IconNetwork size={17}/><h3 id="analysis-graph-title">事件关系图</h3></div><span>{nodes.length} 节点 · {data.graph.edges.length} 关联</span></div>
    {nodes.length > 1 ? <div className="analysis-graph-shell"><div className="analysis-graph-tools" aria-label="图谱缩放"><button aria-label="放大" onClick={() => setZoom(value => Math.min(1.8, value + .2))}><IconPlus size={15}/></button><button aria-label="缩小" onClick={() => setZoom(value => Math.max(.6, value - .2))}><IconMinus size={15}/></button><button aria-label="重置缩放" onClick={() => setZoom(1)}><IconFocus2 size={15}/></button><span>{Math.round(zoom * 100)}%</span></div><div className="analysis-graph-viewport"><div className="analysis-graph" style={{ width, height, transform: `scale(${zoom})` }}><svg width={width} height={height} aria-hidden="true">{data.graph.edges.map(edge => { const from = positions.get(edge.source); const to = positions.get(edge.target); return from && to ? <g key={edge.id}><line x1={from.x} y1={from.y} x2={to.x} y2={to.y}/><text x={(from.x + to.x) / 2} y={(from.y + to.y) / 2}>{edge.relation}</text></g> : null; })}</svg>{nodes.map(node => { const position = positions.get(node.id)!; return <button key={node.id} className={`analysis-node is-${node.type} is-${node.risk}${selected?.id === node.id ? " is-selected" : ""}`} style={{ left: position.x, top: position.y }} onClick={() => setSelected(node)}><span>{typeLabel[node.type] ?? node.type}</span><strong title={node.label}>{node.label}</strong></button>; })}</div></div>{selected ? <aside className="analysis-node-detail"><div><span>{typeLabel[selected.type] ?? selected.type}</span><em>{riskLabel[selected.risk]}</em></div><strong>{selected.label}</strong>{Object.entries(selected.detail).filter(([, value]) => value !== null && value !== "").slice(0, 6).map(([key, value]) => <p key={key}><span>{key}</span><b>{typeof value === "object" ? JSON.stringify(value) : String(value)}</b></p>)}{evidenceLink(selected)}</aside> : <aside className="analysis-node-detail is-empty"><IconNetwork size={21}/><span>选择节点查看属性和原始证据</span></aside>}</div> : <div className="analysis-empty"><IconNetwork size={24}/><strong>暂无可绘制的关联</strong><span>关联 CAPE 样本或同步 IOC 后，这里会展示实体关系。</span></div>}
  </section>;
}

export function CaseAnalysisPanel({ caseId }: { caseId: number }) {
  const [data, setData] = useState<CaseAnalysis | null>(null); const [error, setError] = useState<string | null>(null);
  useEffect(() => { setData(null); setError(null); void getCaseAnalysis(caseId).then(setData).catch(reason => setError(reason instanceof Error ? reason.message : "安全分析数据加载失败")); }, [caseId]);
  if (error) return <section className="case-analysis"><div className="analysis-empty is-error"><IconAlertTriangle size={24}/><strong>安全分析加载失败</strong><span>{error}</span></div></section>;
  if (!data) return <section className="case-analysis" aria-label="安全分析加载中"><div className="analysis-loading"/><div className="analysis-loading"/></section>;
  return <section className="case-analysis"><Timeline data={data}/><Graph data={data}/></section>;
}
