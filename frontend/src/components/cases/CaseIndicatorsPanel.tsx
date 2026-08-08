import { useEffect, useState } from "react";
import { IconDatabaseSearch, IconDownload, IconExternalLink, IconRefresh, IconSearch, IconShieldCheck } from "@tabler/icons-react";
import { bulkUpdateCaseIndicators, enrichCaseIndicator, exportCaseIndicators, listCaseIndicators, syncCaseIndicators, updateCaseIndicator } from "../../lib/api";
import type { CaseIndicator, CaseIndicatorList, IndicatorRisk, IndicatorStatus, ThreatIntelResult } from "../../types";

const statuses: Array<[IndicatorStatus, string]> = [["pending", "待确认"], ["malicious", "恶意"], ["suspicious", "可疑"], ["false_positive", "误报"], ["blocked", "已封禁"]];
const risks: Array<[IndicatorRisk, string]> = [["unknown", "未定级"], ["low", "低危"], ["medium", "中危"], ["high", "高危"], ["critical", "严重"]];
const typeLabel = { domain: "DOMAIN", ip: "IP", url: "URL", md5: "MD5", sha1: "SHA-1", sha256: "SHA-256" };

function formatTime(value: string | null) {
  if (!value) return "时间未知";
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function Verdict({ result }: { result: ThreatIntelResult }) {
  const label = result.malicious === true ? "恶意" : result.malicious === false ? "未发现恶意" : "未知";
  return <article className={`ioc-intel ioc-intel--${result.malicious === true ? "bad" : result.malicious === false ? "clean" : "unknown"}`}>
    <div className="ioc-intel__head"><strong>{result.source}</strong><span>{result.confidence}% · {label}</span>
      {result.externalUrl ? <a href={result.externalUrl} target="_blank" rel="noreferrer" aria-label={`在 ${result.source} 查看`}><IconExternalLink size={13}/></a> : null}
    </div>
    <div className="ioc-intel__meta"><span>{formatTime(result.updatedAt)}</span>{result.cached ? <span>{result.stale ? "过期缓存 / 降级" : "缓存"}</span> : <span>实时</span>}</div>
    {result.tags.length ? <div className="ioc-intel__tags">{result.tags.slice(0, 5).map(tag => <span key={tag}>{tag}</span>)}</div> : null}
  </article>;
}

export function CaseIndicatorsPanel({ caseId, onCountChange }: { caseId: number; onCountChange: (count: number) => void }) {
  const [data, setData] = useState<CaseIndicatorList | null>(null); const [filters, setFilters] = useState({ query: "", type: "", status: "", risk: "" });
  const [selected, setSelected] = useState<number[]>([]); const [busy, setBusy] = useState(false); const [enrichingId, setEnrichingId] = useState<number | null>(null); const [error, setError] = useState<string | null>(null);
  async function load() { try { const next = await listCaseIndicators(caseId, filters); setData(next); onCountChange(next.total); setError(null); } catch (e) { setError(e instanceof Error ? e.message : "IOC 加载失败"); } }
  useEffect(() => { setSelected([]); void load(); }, [caseId, filters.query, filters.type, filters.status, filters.risk]);
  async function sync() { setBusy(true); try { const next = await syncCaseIndicators(caseId); setData(next); onCountChange(next.total); setError(null); } catch (e) { setError(e instanceof Error ? e.message : "同步失败"); } finally { setBusy(false); } }
  async function enrich(item: CaseIndicator) { setEnrichingId(item.id); try { const next = await enrichCaseIndicator(caseId, item.id); setData(current => current ? { ...current, items: current.items.map(value => value.id === item.id ? next : value) } : current); setError(null); } catch (e) { setError(e instanceof Error ? e.message : "情报查询失败"); } finally { setEnrichingId(null); } }
  async function patch(id: number, payload: { status?: IndicatorStatus; riskLevel?: IndicatorRisk; confidence?: number }) { setBusy(true); try { await updateCaseIndicator(caseId, id, payload); await load(); } finally { setBusy(false); } }
  async function bulk(status: IndicatorStatus) { if (!selected.length) return; setBusy(true); try { setData(await bulkUpdateCaseIndicators(caseId, selected, status)); setSelected([]); } finally { setBusy(false); } }
  const allSelected = Boolean(data?.items.length) && data!.items.every(item => selected.includes(item.id));
  return <section className="ioc-workbench"><div className="ioc-workbench__head"><div><h3>IOC 情报中心</h3><span>{data?.total ?? 0} 个已去重指标</span></div><button onClick={() => void sync()} disabled={busy}><IconRefresh size={15}/>同步 CAPE</button></div>
    <div className="ioc-stats">{(["domain", "ip", "url", "md5", "sha1", "sha256"] as const).map(type => <button key={type} className={filters.type === type ? "is-active" : ""} onClick={() => setFilters(value => ({ ...value, type: value.type === type ? "" : type }))}><b>{data?.counts.type[type] ?? 0}</b><span>{typeLabel[type]}</span></button>)}</div>
    <div className="ioc-toolbar"><label><IconSearch size={14}/><input value={filters.query} onChange={event => setFilters(value => ({ ...value, query: event.target.value }))} placeholder="搜索 IOC"/></label><select value={filters.status} onChange={event => setFilters(value => ({ ...value, status: event.target.value }))}><option value="">全部状态</option>{statuses.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><select value={filters.risk} onChange={event => setFilters(value => ({ ...value, risk: event.target.value }))}><option value="">全部风险</option>{risks.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></div>
    {selected.length ? <div className="ioc-bulk"><span>已选 {selected.length} 项</span>{statuses.slice(1).map(([value, label]) => <button disabled={busy} key={value} onClick={() => void bulk(value)}>{label}</button>)}</div> : null}{error ? <p className="ioc-error" role="alert">{error}</p> : null}
    <div className="ioc-table"><div className="ioc-table__row is-head"><input aria-label="选择全部 IOC" type="checkbox" checked={allSelected} onChange={() => setSelected(allSelected ? [] : (data?.items.map(item => item.id) ?? []))}/><span>指标 / 来源</span><span>风险 / 置信度</span><span>状态</span></div>{data?.items.map(item => <div className="ioc-table__item" key={item.id}><div className="ioc-table__row"><input aria-label={`选择 ${item.value}`} type="checkbox" checked={selected.includes(item.id)} onChange={() => setSelected(ids => ids.includes(item.id) ? ids.filter(id => id !== item.id) : [...ids, item.id])}/><div className="ioc-value"><small>{typeLabel[item.type]}</small><strong title={item.value}>{item.value}</strong><span>{item.sampleName || item.sourceType}</span></div><div className="ioc-risk"><select aria-label={`${item.value} 风险`} value={item.riskLevel} disabled={busy} onChange={event => void patch(item.id, { riskLevel: event.target.value as IndicatorRisk })}>{risks.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><input aria-label={`${item.value} 置信度`} type="number" min="0" max="100" value={item.confidence} disabled={busy} onChange={event => void patch(item.id, { confidence: Number(event.target.value) })}/></div><select aria-label={`${item.value} 状态`} value={item.status} disabled={busy} onChange={event => void patch(item.id, { status: event.target.value as IndicatorStatus })}>{statuses.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>
      <div className="ioc-intel-panel"><div className="ioc-intel-panel__action"><button onClick={() => void enrich(item)} disabled={enrichingId !== null}><IconDatabaseSearch size={14}/>{enrichingId === item.id ? "查询中…" : item.enrichment.results?.length ? "刷新情报" : "查询情报"}</button>{item.enrichment.queriedAt ? <span>查询于 {formatTime(item.enrichment.queriedAt)}</span> : null}</div>
        {item.enrichment.results?.map(result => <Verdict result={result} key={result.provider}/>)}
        {item.enrichment.errors?.length ? <p className="ioc-intel-panel__warning">部分来源失败：{item.enrichment.errors.map(value => value.provider).join("、")}</p> : null}
      </div></div>)}</div>
    {!data?.items.length ? <div className="ioc-empty"><IconShieldCheck size={25}/><strong>暂无 IOC</strong><span>同步关联 CAPE 任务以提取指标</span></div> : null}<div className="ioc-exports"><span><IconDownload size={14}/>处置清单</span>{(["csv", "firewall", "dns", "edr"] as const).map(format => <button key={format} onClick={() => exportCaseIndicators(caseId, format)}>{format.toUpperCase()}</button>)}</div></section>;
}
