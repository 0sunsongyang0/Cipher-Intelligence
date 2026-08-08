import { IconDownload, IconPlayerPlay, IconPlus, IconRefresh, IconShieldCheck } from "@tabler/icons-react";
import { useEffect, useMemo, useState } from "react";

import {
  addAdminEvalTestCase,
  createAdminEvalTestSet,
  exportAdminEvaluationRun,
  getAdminEvaluations,
  runAdminEvaluation
} from "../../lib/api";
import type { AdminEvalCenter, AdminEvalGateThresholds, AdminEvalTestCase } from "../../types";

const DEFAULT_THRESHOLDS: AdminEvalGateThresholds = {
  accuracy: 0.85,
  citationCoverage: 0.8,
  falsePositiveRate: 0.05,
  formatCompliance: 0.95,
  firstTokenMs: 2500,
  durationMs: 15000,
  costMicrousd: 5000
};

const EMPTY_CASE: Omit<AdminEvalTestCase, "id" | "createdAt"> = {
  title: "",
  category: "安全问答",
  input: "",
  expectedAnswer: "",
  expectedCitations: [],
  requiredFormat: "markdown",
  falsePositiveTerms: [],
  tags: [],
  sanitized: true,
  authorized: true,
  source: "manual"
};

function percent(value: number) {
  return `${Math.round(value * 100)}%`;
}

function splitList(value: string) {
  return value.split(/[,\n]/u).map((item) => item.trim()).filter(Boolean);
}

export function AdminEvaluationPanel() {
  const [center, setCenter] = useState<AdminEvalCenter | null>(null);
  const [selectedSetId, setSelectedSetId] = useState<number | "">("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [newSet, setNewSet] = useState({ name: "", description: "", authorizationNote: "" });
  const [caseDraft, setCaseDraft] = useState(EMPTY_CASE);
  const [caseLists, setCaseLists] = useState({ expectedCitations: "", falsePositiveTerms: "", tags: "" });
  const [runDraft, setRunDraft] = useState({
    modelId: "deepseek-v4-flash",
    routeStrategy: "direct",
    promptVersion: "current"
  });
  const [thresholds, setThresholds] = useState(DEFAULT_THRESHOLDS);

  const selectedSet = useMemo(
    () => center?.testSets.find((item) => item.id === selectedSetId) ?? center?.testSets[0] ?? null,
    [center, selectedSetId]
  );

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const payload = await getAdminEvaluations();
      setCenter(payload);
      setSelectedSetId((current) => current || payload.testSets[0]?.id || "");
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载评测中心失败。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function handleCreateSet() {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await createAdminEvalTestSet({
        name: newSet.name,
        description: newSet.description || null,
        authorizationNote: newSet.authorizationNote
      });
      setNotice("测试集已创建。");
      setNewSet({ name: "", description: "", authorizationNote: "" });
      setSelectedSetId(created.id);
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "创建测试集失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddCase() {
    if (!selectedSet) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await addAdminEvalTestCase(selectedSet.id, {
        ...caseDraft,
        expectedCitations: splitList(caseLists.expectedCitations),
        falsePositiveTerms: splitList(caseLists.falsePositiveTerms),
        tags: splitList(caseLists.tags)
      });
      setNotice("脱敏授权用例已加入测试集。");
      setCaseDraft(EMPTY_CASE);
      setCaseLists({ expectedCitations: "", falsePositiveTerms: "", tags: "" });
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "添加测试用例失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleRun() {
    if (!selectedSet) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const run = await runAdminEvaluation({ testSetId: selectedSet.id, ...runDraft, gateThresholds: thresholds });
      setNotice(run.gatePassed ? "评测完成，已通过发布门槛。" : "评测完成，但未通过发布门槛。");
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "运行评测失败。");
    } finally {
      setBusy(false);
    }
  }

  if (loading && !center) {
    return (
      <section className="admin-card admin-card--wide">
        <p className="eyebrow">模型评测</p>
        <h2>正在加载评测中心</h2>
        <p className="admin-card__copy">正在读取脱敏测试集、历史运行和发布门槛。</p>
      </section>
    );
  }

  return (
    <div className="admin-panel-stack admin-eval">
      {error ? <p className="status-banner status-banner--error" role="alert">{error}</p> : null}
      {notice ? <p className="admin-notice-banner" role="status">{notice}</p> : null}

      <section className="admin-card admin-card--wide">
        <div className="admin-card__header">
          <div>
            <p className="eyebrow">模型与提示词评测</p>
            <h2>评测中心</h2>
          </div>
          <button type="button" className="admin-quality__refresh" onClick={() => void load()} aria-label="刷新评测中心">
            <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
          </button>
        </div>
        <div className="admin-eval__policy">
          <IconShieldCheck size={18} stroke={1.8} aria-hidden="true" />
          <span>线上敏感对话不会自动进入测试集；每条用例必须先脱敏，并记录明确授权。</span>
        </div>
      </section>

      <section className="admin-card admin-card--wide admin-eval__grid">
        <div>
          <p className="eyebrow">测试集</p>
          <select value={selectedSet?.id ?? ""} onChange={(event) => setSelectedSetId(Number(event.target.value))}>
            {center?.testSets.length ? center.testSets.map((item) => (
              <option key={item.id} value={item.id}>{item.name}（{item.caseCount}）</option>
            )) : <option value="">暂无测试集</option>}
          </select>
          {selectedSet ? (
            <dl className="admin-quality__summary admin-eval__summary">
              <div><dt>用例</dt><dd>{selectedSet.caseCount}</dd></div>
              <div><dt>脱敏</dt><dd>{selectedSet.sanitizedCaseCount}</dd></div>
              <div><dt>授权</dt><dd>{selectedSet.authorizedCaseCount}</dd></div>
            </dl>
          ) : null}
        </div>

        <div>
          <p className="eyebrow">批量运行</p>
          <div className="admin-eval__form-grid">
            <input value={runDraft.modelId} onChange={(event) => setRunDraft({ ...runDraft, modelId: event.target.value })} placeholder="模型 ID" />
            <input value={runDraft.routeStrategy} onChange={(event) => setRunDraft({ ...runDraft, routeStrategy: event.target.value })} placeholder="路由策略" />
            <input value={runDraft.promptVersion} onChange={(event) => setRunDraft({ ...runDraft, promptVersion: event.target.value })} placeholder="Prompt 版本" />
          </div>
          <div className="admin-eval__thresholds">
            {Object.entries(thresholds).map(([key, value]) => (
              <label key={key}>
                <span>{key}</span>
                <input type="number" step={key.includes("Rate") || key.includes("Coverage") || key === "accuracy" || key === "formatCompliance" ? "0.01" : "100"} value={value} onChange={(event) => setThresholds({ ...thresholds, [key]: Number(event.target.value) })} />
              </label>
            ))}
          </div>
          <button type="button" className="admin-action-button admin-action-button--primary" onClick={() => void handleRun()} disabled={busy || !selectedSet || selectedSet.caseCount === 0}>
            <IconPlayerPlay size={16} stroke={1.8} aria-hidden="true" />
            运行评测
          </button>
        </div>
      </section>

      <section className="admin-card admin-card--wide admin-eval__grid">
        <div>
          <p className="eyebrow">新建测试集</p>
          <input value={newSet.name} onChange={(event) => setNewSet({ ...newSet, name: event.target.value })} placeholder="测试集名称" />
          <input value={newSet.description} onChange={(event) => setNewSet({ ...newSet, description: event.target.value })} placeholder="说明" />
          <textarea value={newSet.authorizationNote} onChange={(event) => setNewSet({ ...newSet, authorizationNote: event.target.value })} placeholder="明确授权说明" />
          <button type="button" className="admin-action-button" onClick={() => void handleCreateSet()} disabled={busy}>
            <IconPlus size={16} stroke={1.8} aria-hidden="true" />
            创建测试集
          </button>
        </div>
        <div>
          <p className="eyebrow">添加脱敏用例</p>
          <input value={caseDraft.title} onChange={(event) => setCaseDraft({ ...caseDraft, title: event.target.value })} placeholder="用例标题" />
          <textarea value={caseDraft.input} onChange={(event) => setCaseDraft({ ...caseDraft, input: event.target.value })} placeholder="脱敏后的输入" />
          <textarea value={caseDraft.expectedAnswer} onChange={(event) => setCaseDraft({ ...caseDraft, expectedAnswer: event.target.value })} placeholder="期望答案" />
          <input value={caseLists.expectedCitations} onChange={(event) => setCaseLists({ ...caseLists, expectedCitations: event.target.value })} placeholder="期望引用，逗号分隔" />
          <div className="admin-eval__checks">
            <label><input type="checkbox" checked={caseDraft.sanitized} onChange={(event) => setCaseDraft({ ...caseDraft, sanitized: event.target.checked })} /> 已脱敏</label>
            <label><input type="checkbox" checked={caseDraft.authorized} onChange={(event) => setCaseDraft({ ...caseDraft, authorized: event.target.checked })} /> 已授权</label>
          </div>
          <button type="button" className="admin-action-button" onClick={() => void handleAddCase()} disabled={busy || !selectedSet}>
            <IconPlus size={16} stroke={1.8} aria-hidden="true" />
            添加用例
          </button>
        </div>
      </section>

      <section className="admin-card admin-card--wide">
        <div className="admin-card__header">
          <div>
            <p className="eyebrow">结果比较</p>
            <h2>历史评测运行</h2>
          </div>
        </div>
        <div className="admin-quality__table-wrap">
          <table className="admin-quality__table">
            <thead><tr><th>运行</th><th>准确性</th><th>引用</th><th>误报</th><th>格式</th><th>首 Token</th><th>耗时</th><th>成本</th><th>门槛</th><th>导出</th></tr></thead>
            <tbody>
              {center?.runs.length ? center.runs.map((run) => (
                <tr key={run.id}>
                  <td><span><strong>{run.modelId}</strong></span><small>{run.routeStrategy} / {run.promptVersion}</small></td>
                  <td>{percent(run.summary.accuracy)}</td>
                  <td>{percent(run.summary.citationCoverage)}</td>
                  <td>{percent(run.summary.falsePositiveRate)}</td>
                  <td>{percent(run.summary.formatCompliance)}</td>
                  <td>{Math.round(run.summary.firstTokenMs)} ms</td>
                  <td>{Math.round(run.summary.durationMs)} ms</td>
                  <td>{run.summary.costMicrousd}</td>
                  <td>{run.gatePassed ? "通过" : "阻断"}</td>
                  <td><button type="button" className="admin-quality__refresh" onClick={() => exportAdminEvaluationRun(run.id)} aria-label="导出评测结果"><IconDownload size={15} stroke={1.8} /></button></td>
                </tr>
              )) : <tr><td colSpan={10}>还没有评测运行。</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
