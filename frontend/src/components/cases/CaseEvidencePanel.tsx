import { useEffect, useState } from "react";
import { IconAlertTriangle, IconCertificate, IconDownload, IconLink, IconPlus, IconRobot, IconShieldCheck } from "@tabler/icons-react";
import { createCaseConclusion, crossCheckCaseConclusion, exportCaseEvidenceChain, getCaseEvidenceChain, reviewCaseEvidence, signCaseEvidenceChain, updateCaseConclusion } from "../../lib/api";
import { DEEPSEEK_MODEL_OPTIONS, type CaseEvidenceChain, type DeepSeekModelId, type EvidenceReviewStatus } from "../../types";

const statusText: Record<EvidenceReviewStatus, string> = { pending: "待验证", verified: "已验证", rejected: "被否定" };

export function CaseEvidencePanel({ caseId, onChanged }: { caseId: number; onChanged?: () => void }) {
  const [chain, setChain] = useState<CaseEvidenceChain | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [conflicts, setConflicts] = useState<number[]>([]);
  const [statement, setStatement] = useState("");
  const [claimType, setClaimType] = useState<"fact" | "inference">("inference");
  const [confidence, setConfidence] = useState(70);
  const [confidenceRationale, setConfidenceRationale] = useState("");
  const [modelId, setModelId] = useState("");
  const [crossCheckRationale, setCrossCheckRationale] = useState("");
  const [crossCheckVerdict, setCrossCheckVerdict] = useState<"supports" | "contradicts" | "inconclusive">("supports");
  const [reviewModel, setReviewModel] = useState<DeepSeekModelId>("claude-sonnet-4-6-az");
  const [signer, setSigner] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function load() { setError(null); try { setChain(await getCaseEvidenceChain(caseId)); } catch (e) { setError(e instanceof Error ? e.message : "证据链加载失败"); } }
  useEffect(() => { setSelected([]); setConflicts([]); setStatement(""); void load(); }, [caseId]);
  async function review(id: number, status: EvidenceReviewStatus) {
    const item = chain?.evidence.find(evidence => evidence.id === id); if (!item) return;
    setBusy(true); setError(null);
    try {
      await reviewCaseEvidence(caseId, id, { reviewStatus: status, sourceTrust: item.sourceTrust, confidence: item.confidence, acquiredAt: item.acquiredAt, contentHash: item.contentHash, snapshotUrl: item.snapshotUrl, reviewNote: item.reviewNote });
      await load(); onChanged?.();
    } catch (e) { setError(e instanceof Error ? e.message : "审核失败"); } finally { setBusy(false); }
  }
  async function addConclusion() {
    if (!statement.trim()) return; setBusy(true); setError(null);
    try {
      const crossChecks = modelId.trim() && crossCheckRationale.trim() ? [{ modelId: modelId.trim(), verdict: crossCheckVerdict, confidence, rationale: crossCheckRationale.trim(), checkedAt: new Date().toISOString() }] : [];
      setChain(await createCaseConclusion(caseId, { statement: statement.trim(), status: "draft", confidence, claimType, confidenceRationale: confidenceRationale.trim() || null, evidenceIds: selected, conflictEvidenceIds: conflicts, crossChecks }));
      setStatement(""); setSelected([]); setConflicts([]); setConfidenceRationale(""); setModelId(""); setCrossCheckRationale(""); onChanged?.();
    }
    catch (e) { setError(e instanceof Error ? e.message : "结论创建失败"); } finally { setBusy(false); }
  }
  async function setConclusionStatus(id: number, status: "verified" | "rejected") {
    setBusy(true); setError(null);
    try { setChain(await updateCaseConclusion(caseId, id, { status })); onChanged?.(); }
    catch (e) { setError(e instanceof Error ? e.message : "结论审核失败"); } finally { setBusy(false); }
  }
  async function runCrossCheck(id: number) {
    setBusy(true); setError(null);
    try { setChain(await crossCheckCaseConclusion(caseId, id, reviewModel)); onChanged?.(); }
    catch (e) { setError(e instanceof Error ? e.message : "跨模型复核失败"); } finally { setBusy(false); }
  }
  async function sign() {
    if (!signer.trim()) return; setBusy(true); setError(null);
    try { setChain(await signCaseEvidenceChain(caseId, { signer: signer.trim() })); onChanged?.(); }
    catch (e) { setError(e instanceof Error ? e.message : "签署失败"); } finally { setBusy(false); }
  }
  const validSignature = chain?.signatures.find(item => item.isValid);
  return <section className="evidence-panel">
    <div className="evidence-panel__head"><div><h3>证据质量与研判签署</h3><span>{chain?.evidence.length ?? 0} 条证据 · {chain?.conclusions.length ?? 0} 条结论</span></div><button title="导出完整证据链" onClick={() => exportCaseEvidenceChain(caseId)}><IconDownload size={15}/>导出</button></div>
    {error ? <p className="evidence-panel__error"><IconAlertTriangle size={14}/>{error}</p> : null}
    {chain?.contradictions.length ? <div className="evidence-conflicts"><IconAlertTriangle size={15}/><span>检测到 {chain.contradictions.length} 组来源矛盾</span></div> : null}
    <div className="evidence-list">{chain?.evidence.map(item => <article key={item.id} className={`is-${item.reviewStatus}`}>
      <label className="evidence-select" title="标记为支撑证据"><input type="checkbox" checked={selected.includes(item.id)} onChange={() => setSelected(values => values.includes(item.id) ? values.filter(id => id !== item.id) : [...values, item.id])}/><span>{item.citation}</span></label>
      <div className="evidence-main"><strong>{item.title}</strong><p>{item.snippet || item.locator || "无证据摘要"}</p><small>来源可信度 {item.sourceTrust}% · 证据置信度 {item.confidence}%{item.contentHash ? ` · SHA-256 ${item.contentHash.slice(0, 10)}…` : ""}</small></div>
      <label className="evidence-conflict-select"><input type="checkbox" checked={conflicts.includes(item.id)} onChange={() => setConflicts(values => values.includes(item.id) ? values.filter(id => id !== item.id) : [...values, item.id])}/>冲突</label>
      <select value={item.reviewStatus} disabled={busy} onChange={event => void review(item.id, event.target.value as EvidenceReviewStatus)} aria-label={`审核 ${item.title}`}><option value="pending">待验证</option><option value="verified">已验证</option><option value="rejected">被否定</option></select>
    </article>)}</div>
    {!chain?.evidence.length ? <p className="evidence-empty">关联对话产生引用后，证据会自动汇入此处。</p> : null}
    <div className="conclusion-compose conclusion-compose--explainable">
      <div className="conclusion-compose__controls"><select aria-label="结论类型" value={claimType} onChange={event => setClaimType(event.target.value as "fact" | "inference")}><option value="fact">已确认事实</option><option value="inference">模型推断</option></select><label>置信度 <input aria-label="结论置信度" type="number" min="0" max="100" value={confidence} onChange={event => setConfidence(Math.max(0, Math.min(100, Number(event.target.value))))}/>%</label></div>
      <textarea value={statement} onChange={event => setStatement(event.target.value)} placeholder="填写研判结论，并勾选上方支撑证据"/>
      <textarea value={confidenceRationale} onChange={event => setConfidenceRationale(event.target.value)} placeholder="说明置信度依据，例如来源可靠性、证据一致性和仍存在的不确定性"/>
      <details><summary><IconRobot size={14}/>添加跨模型复核结果</summary><div className="cross-check-compose"><input value={modelId} onChange={event => setModelId(event.target.value)} placeholder="复核模型，例如 claude-sonnet"/><select value={crossCheckVerdict} onChange={event => setCrossCheckVerdict(event.target.value as typeof crossCheckVerdict)}><option value="supports">支持结论</option><option value="contradicts">反驳结论</option><option value="inconclusive">无法判断</option></select><textarea value={crossCheckRationale} onChange={event => setCrossCheckRationale(event.target.value)} placeholder="记录复核模型的依据"/></div></details>
      <button onClick={() => void addConclusion()} disabled={busy || !statement.trim()}><IconPlus size={15}/>添加结论</button>
    </div>
    <div className="conclusion-list">{chain?.conclusions.map(item => <article key={item.id} className={`conclusion-card is-${item.status}`}>
      <div className="conclusion-card__head"><span className={`claim-type is-${item.claimType}`}>{item.claimType === "fact" ? "事实" : "模型推断"}</span><strong>{item.statement}</strong></div>
      <div className="conclusion-card__confidence"><span>置信度 <b>{item.confidence}%</b></span><div><i style={{ width: `${item.confidence}%` }}/></div></div>
      <p>{item.confidenceRationale || "尚未说明置信度影响因素。"}</p>
      <div className="conclusion-card__evidence"><IconLink size={14}/><span>支撑：{item.evidenceIds.length ? item.evidenceIds.map(id => chain.evidence.find(e => e.id === id)?.citation ?? `#${id}`).join("、") : "未绑定"}</span>{item.conflictEvidenceIds.length ? <span className="is-conflict"><IconAlertTriangle size={13}/>冲突：{item.conflictEvidenceIds.map(id => chain.evidence.find(e => e.id === id)?.citation ?? `#${id}`).join("、")}</span> : null}</div>
      {item.crossChecks.length ? <div className="cross-check-list">{item.crossChecks.map((check, index) => <div key={`${check.modelId}-${index}`}><IconRobot size={14}/><strong>{check.modelId}</strong><span className={`is-${check.verdict}`}>{check.verdict === "supports" ? "支持" : check.verdict === "contradicts" ? "反驳" : "存疑"} · {check.confidence}%</span><p>{check.rationale}</p></div>)}</div> : <small>尚未进行跨模型复核</small>}
      <div className="automatic-cross-check"><select aria-label="选择复核模型" value={reviewModel} onChange={event => setReviewModel(event.target.value as DeepSeekModelId)}>{DEEPSEEK_MODEL_OPTIONS.map(model => <option key={model.id} value={model.id}>{model.groupLabel} · {model.label}</option>)}</select><button disabled={busy} onClick={() => void runCrossCheck(item.id)}><IconRobot size={14}/>{busy ? "复核中…" : "自动复核"}</button></div>
      <footer><small>{item.reviewedBy ? `由 ${item.reviewedBy} 人工${item.status === "verified" ? "确认" : "驳回"}` : "等待人工审核"}</small>{item.status === "draft" ? <div><button disabled={busy} onClick={() => void setConclusionStatus(item.id, "rejected")}>驳回</button><button disabled={busy} onClick={() => void setConclusionStatus(item.id, "verified")}><IconShieldCheck size={14}/>确认</button></div> : <span>{statusText[item.status]}</span>}</footer>
    </article>)}</div>
    <div className="signature-bar"><IconCertificate size={18}/><div><strong>{validSignature ? `已由 ${validSignature.signer} 签署` : "等待分析员签署"}</strong><small>{validSignature ? `摘要 ${validSignature.digest.slice(0, 12)}…` : "签署将固化当前结论与证据摘要"}</small></div>{!validSignature ? <><input value={signer} onChange={event => setSigner(event.target.value)} placeholder="签署人"/><button onClick={() => void sign()} disabled={busy || !signer.trim()}>签署</button></> : null}</div>
  </section>;
}
