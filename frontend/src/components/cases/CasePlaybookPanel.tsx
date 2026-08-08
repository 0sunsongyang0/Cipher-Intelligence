import { useEffect, useMemo, useState } from "react";
import { IconCheck, IconClipboardCheck, IconPlayerPlay, IconRefresh, IconRoute } from "@tabler/icons-react";
import { approvePlaybookStep, createCasePlaybook, executePlaybookStep, listCasePlaybooks, listPlaybookTemplates, retryPlaybookStep } from "../../lib/api";
import type { InvestigationPlaybook, PlaybookStepStatus, PlaybookTemplate } from "../../types";

const labels: Record<PlaybookStepStatus, string> = { pending: "待执行", running: "执行中", waiting_approval: "待审批", completed: "已完成", failed: "失败" };

export function CasePlaybookPanel({ caseId }: { caseId: number }) {
  const [templates, setTemplates] = useState<PlaybookTemplate[]>([]);
  const [items, setItems] = useState<InvestigationPlaybook[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [templateId, setTemplateId] = useState("malware-triage");
  const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const selected = useMemo(() => items.find(item => item.id === selectedId) ?? items[0] ?? null, [items, selectedId]);
  async function load(preferred?: number) { try { const [available, data] = await Promise.all([listPlaybookTemplates(), listCasePlaybooks(caseId)]); setTemplates(available); setItems(data.items); setSelectedId(preferred ?? data.items[0]?.id ?? null); setError(null); } catch (e) { setError(e instanceof Error ? e.message : "Playbook 加载失败"); } }
  useEffect(() => { void load(); }, [caseId]);
  async function create() { setBusy(true); try { const item = await createCasePlaybook(caseId, templateId); await load(item.id); } catch (e) { setError(e instanceof Error ? e.message : "启动失败"); } finally { setBusy(false); } }
  async function mutate(action: () => Promise<InvestigationPlaybook>) { setBusy(true); try { const item = await action(); setItems(values => values.map(value => value.id === item.id ? item : value)); setSelectedId(item.id); setError(null); } catch (e) { setError(e instanceof Error ? e.message : "步骤操作失败"); } finally { setBusy(false); } }
  async function retryAndRun(playbookId: number, stepId: number) { await retryPlaybookStep(caseId, playbookId, stepId); return executePlaybookStep(caseId, playbookId, stepId); }
  const next = selected?.steps.find(step => step.status !== "completed");
  return <section className="playbook-panel"><div className="playbook-panel__head"><div><h3>调查 Playbook</h3><span>可重复执行、可追踪、需审批的调查流程</span></div><div><select value={templateId} onChange={e => setTemplateId(e.target.value)}>{templates.map(item => <option value={item.id} key={item.id}>{item.title}</option>)}</select><button disabled={busy} onClick={() => void create()}><IconRoute size={15}/>启动</button></div></div>
    {error ? <p className="ioc-error">{error}</p> : null}
    {!selected ? <div className="playbook-empty"><IconClipboardCheck size={25}/><strong>尚未启动 Playbook</strong><span>选择模板，将调查过程固化为逐步可审计的工作流。</span></div> : <><div className="playbook-switcher">{items.map(item => <button className={item.id === selected.id ? "is-active" : ""} key={item.id} onClick={() => setSelectedId(item.id)}><span>{item.title}</span><b>{item.progress}%</b></button>)}</div><div className="playbook-progress"><span style={{ width: `${selected.progress}%` }}/></div><ol className="playbook-steps">{selected.steps.map(step => { const enabled = next?.id === step.id; return <li className={`is-${step.status}`} key={step.id}><span className="playbook-step__index">{step.status === "completed" ? <IconCheck size={14}/> : step.position}</span><div><strong>{step.title}</strong><small>{labels[step.status]}{step.attemptCount ? ` · ${step.attemptCount} 次执行` : ""}</small>{step.error ? <p>{step.error}</p> : null}{Object.keys(step.output).length ? <details><summary>查看产出</summary><pre>{JSON.stringify(step.output, null, 2)}</pre></details> : null}</div><div className="playbook-step__actions">{step.status === "failed" ? <button disabled={busy} title="重新执行该失败步骤" onClick={() => void mutate(() => retryAndRun(selected.id, step.id))}><IconRefresh size={14}/>重试</button> : step.requiresApproval ? <button disabled={busy || !enabled} onClick={() => void mutate(() => approvePlaybookStep(caseId, selected.id, step.id))}><IconClipboardCheck size={14}/>审批</button> : <button disabled={busy || !enabled} onClick={() => void mutate(() => executePlaybookStep(caseId, selected.id, step.id))}><IconPlayerPlay size={14}/>执行</button>}</div></li>; })}</ol></>}
  </section>;
}
