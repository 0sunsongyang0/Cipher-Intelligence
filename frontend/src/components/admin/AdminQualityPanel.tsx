import { IconChartBar, IconRefresh } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { getAdminQuality } from "../../lib/api";
import type { AdminQuality } from "../../types";

function duration(value: number | null): string {
  if (value === null) return "--";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

export function AdminQualityPanel() {
  const [days, setDays] = useState(30);
  const [quality, setQuality] = useState<AdminQuality | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setQuality(await getAdminQuality(days));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载模型质量数据失败。");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [days]);

  return (
    <section className="admin-card admin-card--wide admin-quality">
      <div className="admin-card__header">
        <div>
          <p className="eyebrow">质量与性能</p>
          <h2>模型质量监控</h2>
        </div>
        <div className="admin-quality__actions">
          <div className="admin-quality__period" aria-label="统计周期">
            {[7, 30, 90].map((value) => (
              <button key={value} type="button" aria-pressed={days === value} onClick={() => setDays(value)}>
                {value} 天
              </button>
            ))}
          </div>
          <button type="button" className="admin-quality__refresh" onClick={() => void load()} aria-label="刷新质量数据">
            <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
          </button>
        </div>
      </div>

      {error ? <p className="status-banner status-banner--error" role="alert">{error}</p> : null}
      {loading && !quality ? <p className="admin-card__copy">正在汇总请求、延迟和反馈数据…</p> : null}

      {quality ? (
        <>
          <dl className="admin-quality__summary">
            <div><dt>请求总量</dt><dd>{quality.totalRequests}</dd></div>
            <div><dt>成功率</dt><dd>{quality.successRate}%</dd></div>
            <div><dt>平均首字</dt><dd>{duration(quality.avgFirstTokenMs)}</dd></div>
            <div><dt>平均耗时</dt><dd>{duration(quality.avgDurationMs)}</dd></div>
            <div><dt>错误 / 中止</dt><dd>{quality.errorRequests} / {quality.cancelledRequests}</dd></div>
            <div><dt>好评 / 差评</dt><dd>{quality.feedback.up ?? 0} / {quality.feedback.down ?? 0}</dd></div>
          </dl>

          <div className="admin-quality__table-wrap">
            <table className="admin-quality__table">
              <thead><tr><th>模型</th><th>请求</th><th>成功率</th><th>首字</th><th>总耗时</th><th>反馈</th></tr></thead>
              <tbody>
                {quality.models.length === 0 ? (
                  <tr><td colSpan={6}>当前周期还没有模型请求数据。</td></tr>
                ) : quality.models.map((model) => (
                  <tr key={model.model}>
                    <td><span><IconChartBar size={15} stroke={1.8} aria-hidden="true" /><strong>{model.model}</strong></span><small>{model.provider}</small></td>
                    <td>{model.requests}</td>
                    <td>{model.successRate}%</td>
                    <td>{duration(model.avgFirstTokenMs)}</td>
                    <td>{duration(model.avgDurationMs)}</td>
                    <td>{model.thumbsUp} / {model.thumbsDown}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}
