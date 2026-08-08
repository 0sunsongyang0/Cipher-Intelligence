import { IconActivityHeartbeat, IconRefresh } from "@tabler/icons-react";
import { useEffect, useState } from "react";

import { getAdminObservability } from "../../lib/api";
import type { AdminObservability } from "../../types";

function duration(value: number | null): string {
  if (value === null) return "--";
  return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
}

function number(value: number): string {
  return new Intl.NumberFormat("zh-CN").format(value);
}

export function AdminObservabilityPanel() {
  const [days, setDays] = useState(30);
  const [data, setData] = useState<AdminObservability | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      setData(await getAdminObservability(days));
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError.message : "加载可观测性数据失败。");
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
          <p className="eyebrow">可观测性</p>
          <h2>系统运行统计</h2>
        </div>
        <div className="admin-quality__actions">
          <div className="admin-quality__period" aria-label="统计周期">
            {[7, 30, 90].map((value) => (
              <button key={value} type="button" aria-pressed={days === value} onClick={() => setDays(value)}>
                {value} 天
              </button>
            ))}
          </div>
          <button type="button" className="admin-quality__refresh" onClick={() => void load()} aria-label="刷新可观测性数据">
            <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
          </button>
        </div>
      </div>

      {error ? <p className="status-banner status-banner--error" role="alert">{error}</p> : null}
      {loading && !data ? <p className="admin-card__copy">正在汇总请求、模型、CAPE、文件和计费事件...</p> : null}

      {data ? (
        <>
          <dl className="admin-quality__summary">
            <div><dt>请求成功率</dt><dd>{data.requestSuccessRate}%</dd></div>
            <div><dt>平均响应</dt><dd>{duration(data.averageResponseTimeMs)}</dd></div>
            <div><dt>模型失败率</dt><dd>{data.modelFailureRate}%</dd></div>
            <div><dt>Token 消耗</dt><dd>{number(data.tokenUsage.total)}</dd></div>
            <div><dt>CAPE 平均耗时</dt><dd>{duration(data.capeTaskAverageDurationMs)}</dd></div>
            <div><dt>活跃用户</dt><dd>{number(data.activeUsers)}</dd></div>
          </dl>

          <div className="admin-observability__details">
            <span><IconActivityHeartbeat size={15} stroke={1.8} aria-hidden="true" /> 事件总数 {number(data.events)}</span>
            <span>输入 Token {number(data.tokenUsage.input)}</span>
            <span>输出 Token {number(data.tokenUsage.output)}</span>
          </div>
        </>
      ) : null}
    </section>
  );
}
