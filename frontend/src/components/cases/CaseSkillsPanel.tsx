import { useEffect, useState } from "react";
import { IconPlayerPlay, IconSparkles } from "@tabler/icons-react";
import { getCaseEvidenceChain, getSkills, listCaseIndicators, runSkill } from "../../lib/api";
import type { CaseEvidence, InvestigationCase, SkillPackage } from "../../types";
import { createSkillInitialInput, SkillInputForm } from "../skills/SkillInputForm";

function seedForCase(skill: SkillPackage, currentCase: InvestigationCase, iocs: string[], evidence: CaseEvidence[] = []) {
  const cape = currentCase.capeCases.find(item => item.summary)?.summary;
  const common = { caseId: currentCase.id };
  if (skill.key === "ioc-enrichment") return { ...common, iocs };
  if (skill.key === "sigma-rule-builder") return { ...common, title: `${currentCase.title} IOC detection`, logsource: "proxy", indicators: iocs };
  if (skill.key === "yara-rule-builder") return { ...common, name: `cipher_case_${currentCase.id}`, author: "Cipher Intelligence", strings: [] };
  if (skill.key === "cape-to-stix") return { ...common, report: cape ? { ...cape.iocs, hashes: cape.sha256 ? [cape.sha256] : [], sha256: cape.sha256 } : {} };
  if (skill.key === "attack-technique-mapper") return { ...common, behaviors: cape?.tactics.map(item => `${item.signature}: ${item.description}`) ?? [] };
  if (skill.key === "firewall-blocklist-builder") return { ...common, indicators: iocs, expiresHours: 24 };
  if (skill.key === "incident-brief-builder") return { ...common, title: currentCase.title, severity: currentCase.severity, summary: currentCase.summary ?? "", indicators: iocs, actions: [] };
  if (skill.key === "evidence-integrity-checker") return { ...common, evidence: evidence.map(item => ({ id: item.id, title: item.title, reviewStatus: item.reviewStatus, contentHash: item.contentHash, confidence: item.confidence, sourceTrust: item.sourceTrust })) };
  if (skill.key === "phishing-triage") return { ...common, sender: "", subject: currentCase.title, authentication: "", urls: iocs.filter(value => value.startsWith("http")), attachments: [], body: currentCase.summary ?? "" };
  if (skill.key === "capa-capability-review") return { ...common, capabilities: cape?.tactics.map(item => `${item.signature}: ${item.description}`) ?? [] };
  if (skill.key === "lolbas-command-analyzer" || skill.key === "gtfobins-command-analyzer") return { ...common, commands: [] };
  if (skill.key === "nuclei-template-planner") return { ...common, assets: iocs.filter(value => value.startsWith("http") || (!value.includes(":") && value.includes("."))), severities: ["critical", "high"], tags: [], rateLimit: 10, authorizationConfirmed: false };
  return common;
}

export function CaseSkillsPanel({ currentCase, onCompleted }: {
  currentCase: InvestigationCase; onCompleted: () => void;
}) {
  const [skills, setSkills] = useState<SkillPackage[]>([]);
  const [selected, setSelected] = useState<SkillPackage | null>(null);
  const [input, setInput] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([getSkills(), listCaseIndicators(currentCase.id), getCaseEvidenceChain(currentCase.id)]).then(([catalog, indicators, chain]) => {
      if (!active) return;
      const available = catalog.items.filter(item =>
        item.installed && item.enabled && item.reviewStatus === "verified"
      );
      setSkills(available);
      const initial = available[0] ?? null;
      setSelected(initial);
      setInput(initial ? createSkillInitialInput(initial, seedForCase(initial, currentCase, indicators.items.map(item => item.value), chain.evidence)) : {});
    }).catch(error => setNotice(error instanceof Error ? error.message : "Skill 加载失败"));
    return () => { active = false; };
  }, [currentCase.id]);

  async function choose(skill: SkillPackage) {
    setSelected(skill); setNotice(null);
    try {
      const [indicators, chain] = await Promise.all([listCaseIndicators(currentCase.id), getCaseEvidenceChain(currentCase.id)]);
      setInput(createSkillInitialInput(skill, seedForCase(skill, currentCase, indicators.items.map(item => item.value), chain.evidence)));
    } catch { setInput(createSkillInitialInput(skill, { caseId: currentCase.id })); }
  }

  async function execute() {
    if (!selected || !selected.entitlement.allowed) return;
    setBusy(true); setNotice(null);
    try {
      const result = await runSkill(selected.id, input);
      const summary = typeof result.output.summary === "string" ? result.output.summary : `运行记录 #${result.id}`;
      setNotice(summary); onCompleted();
    } catch (error) { setNotice(error instanceof Error ? error.message : "Skill 运行失败"); }
    finally { setBusy(false); }
  }

  return <section className="case-detail__section case-skills"><div className="ioc-workbench__head"><div><h3>Case Skills</h3><span>自动带入当前案件上下文</span></div><IconSparkles size={18}/></div>
    <div className="case-skills__tabs">{skills.map(skill => <button key={skill.id} className={selected?.id === skill.id ? "is-active" : ""} onClick={() => void choose(skill)}>{skill.name}{!skill.entitlement.allowed ? " · 需升级" : ""}</button>)}</div>
    {selected ? <><SkillInputForm skill={selected} value={input} onChange={setInput}/><button className="cases-primary" disabled={busy || !selected.entitlement.allowed} onClick={() => void execute()}><IconPlayerPlay size={16}/>{!selected.entitlement.allowed ? "当前套餐不可用" : busy ? "执行中…" : "在此 Case 中运行"}</button></> : <p>暂无已安装 Skill，请先前往 Skills 市场安装。</p>}
    {notice ? <p className="admin-notice-banner" role="status">{notice}</p> : null}
  </section>;
}
