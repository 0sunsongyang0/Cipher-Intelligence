import { useEffect, useMemo, useState, type ChangeEvent } from "react";
import {
  IconCheck,
  IconCode,
  IconDownload,
  IconPlayerPlay,
  IconRefresh,
  IconShieldCheck,
  IconTestPipe
} from "@tabler/icons-react";

import {
  exportDetectionRule,
  generateDetectionRules,
  listDetectionRules,
  testDetectionRule,
  updateDetectionRule,
  validateDetectionRule
} from "../../lib/api";
import type { DetectionRule, DetectionRuleList, DetectionRuleStatus } from "../../types";

const statusLabels: Record<DetectionRuleStatus, string> = {
  draft: "草稿",
  validated: "已验证",
  approved: "已批准",
  deployed: "已部署"
};

export function CaseDetectionRulesPanel({ caseId }: { caseId: number }) {
  const [data, setData] = useState<DetectionRuleList | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const selected = useMemo(
    () => data?.items.find((rule) => rule.id === selectedId) ?? data?.items[0] ?? null,
    [data, selectedId]
  );

  async function load(preferredId?: number) {
    try {
      const next = await listDetectionRules(caseId);
      setData(next);
      setSelectedId(preferredId ?? next.items[0]?.id ?? null);
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "检测规则加载失败");
    }
  }

  useEffect(() => {
    void load();
  }, [caseId]);

  useEffect(() => {
    setDraft(selected?.content ?? "");
  }, [selected?.id, selected?.content]);

  async function generate() {
    setBusy(true);
    try {
      const next = await generateDetectionRules(caseId);
      setData(next);
      setSelectedId(next.items[0]?.id ?? null);
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "规则生成失败");
    } finally {
      setBusy(false);
    }
  }

  async function mutate(action: () => Promise<DetectionRule>) {
    setBusy(true);
    try {
      const rule = await action();
      await load(rule.id);
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "规则操作失败");
    } finally {
      setBusy(false);
    }
  }

  async function runTests(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (!selected || files.length === 0) return;
    setBusy(true);
    try {
      await testDetectionRule(caseId, selected.id, files);
      await load(selected.id);
      setError(null);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "规则测试失败");
    } finally {
      setBusy(false);
    }
  }

  const conversions = selected?.validation.conversions ?? {};
  const latestTest = selected?.testRuns[0];
  const contentChanged = Boolean(selected && draft.trim() !== selected.content.trim());

  return (
    <section className="rule-workbench">
      <div className="rule-workbench__head">
        <div><h3>检测规则验证</h3><span>生成、验证、测试、批准并部署 Sigma / YARA</span></div>
        <button onClick={() => void generate()} disabled={busy}><IconRefresh size={15}/>从 CAPE 生成</button>
      </div>

      <div className="rule-flow" aria-label="检测规则状态">
        {(["draft", "validated", "approved", "deployed"] as DetectionRuleStatus[]).map((status) => (
          <span key={status} className={(data?.counts[status] ?? 0) > 0 ? "is-active" : ""}>
            <b>{data?.counts[status] ?? 0}</b>{statusLabels[status]}
          </span>
        ))}
      </div>

      {error ? <p className="ioc-error">{error}</p> : null}
      {!data?.items.length ? (
        <div className="rule-empty"><IconShieldCheck size={26}/><strong>还没有检测规则</strong><span>关联完成的 CAPE 报告后生成 Sigma 与 YARA 初稿。</span></div>
      ) : (
        <div className="rule-workbench__layout">
          <nav className="rule-list" aria-label="检测规则列表">
            {data.items.map((rule) => (
              <button key={rule.id} className={selected?.id === rule.id ? "is-active" : ""} onClick={() => setSelectedId(rule.id)}>
                <span><b>{rule.ruleType.toUpperCase()}</b><em>{statusLabels[rule.status]}</em></span>
                <strong>{rule.title}</strong>
                <small>v{rule.version} · {rule.validationStatus === "valid" ? "验证通过" : rule.validationStatus === "invalid" ? "验证失败" : "待验证"}</small>
              </button>
            ))}
          </nav>

          {selected ? <div className="rule-editor">
            <div className="rule-editor__toolbar">
              <span><IconCode size={15}/>{selected.ruleType.toUpperCase()} · v{selected.version}</span>
              <button disabled={busy || !contentChanged} onClick={() => void mutate(() => updateDetectionRule(caseId, selected.id, { content: draft }))}>保存新版本</button>
              <button disabled={busy || contentChanged} onClick={() => void mutate(() => validateDetectionRule(caseId, selected.id))}><IconCheck size={14}/>验证</button>
              <label className={selected.validationStatus !== "valid" || busy ? "is-disabled" : ""}><IconTestPipe size={14}/>测试文件<input type="file" multiple disabled={selected.validationStatus !== "valid" || busy} onChange={(event) => void runTests(event)}/></label>
            </div>
            <textarea aria-label="规则内容" value={draft} onChange={(event) => setDraft(event.target.value)} spellCheck={false}/>

            <div className="rule-editor__actions">
              <button disabled={busy || selected.validationStatus !== "valid" || selected.status === "approved" || selected.status === "deployed"} onClick={() => void mutate(() => updateDetectionRule(caseId, selected.id, { status: "approved" }))}>批准规则</button>
              <button disabled={busy || selected.status !== "approved"} onClick={() => void mutate(() => updateDetectionRule(caseId, selected.id, { status: "deployed" }))}><IconPlayerPlay size={14}/>标记已部署</button>
              <span className={`rule-validation is-${selected.validationStatus}`}>{selected.validationStatus === "valid" ? "语法验证通过" : selected.validationStatus === "invalid" ? "语法验证失败" : "尚未验证"}</span>
            </div>

            {selected.validation.errors?.length || selected.validation.warnings?.length ? <div className="rule-findings">
              {selected.validation.errors?.map((item) => <p className="is-error" key={item}>{item}</p>)}
              {selected.validation.warnings?.map((item) => <p key={item}>{item}</p>)}
            </div> : null}

            {Object.keys(conversions).length ? <div className="rule-conversions"><h4>目标 SIEM 转换</h4>{Object.entries(conversions).map(([name, query]) => <details key={name}><summary>{name.toUpperCase()}</summary><pre>{query}</pre></details>)}</div> : null}

            <div className="rule-results">
              <span><b>{latestTest?.matchedArtifacts ?? 0}/{latestTest?.totalArtifacts ?? 0}</b>最近测试命中</span>
              <span><b>{latestTest?.falsePositiveCount ?? 0}</b>误报样本</span>
              <span><b>{selected.versions.length}</b>历史版本</span>
              <span><b>{selected.validation.attack_techniques?.length ?? 0}</b>ATT&CK 技术</span>
            </div>

            <div className="rule-exports"><span><IconDownload size={14}/>导出结果</span>{(["raw", "html", "pdf"] as const).map((format) => <button key={format} onClick={() => exportDetectionRule(caseId, selected.id, format)}>{format.toUpperCase()}</button>)}</div>
          </div> : null}
        </div>
      )}
    </section>
  );
}
