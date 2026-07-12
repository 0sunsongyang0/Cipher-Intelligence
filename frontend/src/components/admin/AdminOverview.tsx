import { IconBolt, IconLink, IconPlayerPause, IconPlayerPlay } from "@tabler/icons-react";
import type { AdminOverview as AdminOverviewData } from "../../types";

export function AdminOverview({
  overview,
  busyTarget,
  onToggle,
}: {
  overview: AdminOverviewData;
  busyTarget: "backend" | "tunnel" | null;
  onToggle: (target: "backend" | "tunnel", running: boolean) => Promise<void>;
}) {
  const serviceCards = [
    {
      key: "backend" as const,
      title: "聊天服务",
      state: overview.services.backend,
    },
    {
      key: "tunnel" as const,
      title: "Cloudflare 隧道",
      state: overview.services.tunnel,
    },
  ];

  function getStatusLabel(label: string | null | undefined, running: boolean) {
    if (label === "running") {
      return "运行中";
    }
    if (label === "stopped") {
      return "已停止";
    }
    return label ?? (running ? "运行中" : "已停止");
  }

  return (
    <section className="admin-panel-stack">
      <section className="admin-card admin-card--wide">
        <div className="admin-card__header">
          <div>
            <p className="eyebrow">访问</p>
            <h2>访问状态</h2>
          </div>
          <IconLink size={18} stroke={1.8} aria-hidden="true" />
        </div>
        <dl className="admin-meta-list">
          <div>
            <dt>本地聊天地址</dt>
            <dd>{overview.access.localUrl}</dd>
          </div>
          <div>
            <dt>公网聊天地址</dt>
            <dd>{overview.access.publicUrl}</dd>
          </div>
          <div>
            <dt>隧道自启</dt>
            <dd>{overview.services.autostartEnabled ? "已启用" : "未启用"}</dd>
          </div>
        </dl>
      </section>

      <div className="admin-card-grid">
        {serviceCards.map((service) => {
          const isRunning = service.state.running;
          const isBusy = busyTarget === service.key;

          return (
            <section key={service.key} className="admin-card">
              <div className="admin-card__header">
                <div>
                  <p className="eyebrow">服务</p>
                  <h2>{service.title}</h2>
                </div>
                <span
                  className={`admin-status-chip admin-status-chip--${isRunning ? "ready" : "idle"}`}
                >
                  <IconBolt size={14} stroke={1.8} aria-hidden="true" />
                  {getStatusLabel(service.state.label, isRunning)}
                </span>
              </div>

              <p className="admin-card__copy">{service.state.detail ?? "状态暂不可用。"}</p>
              <p className="admin-card__meta">PID: {service.state.pid ?? "未检测到"}</p>

              <button
                type="button"
                className={`admin-action-button admin-action-button--${isRunning ? "danger" : "primary"}`}
                disabled={isBusy}
                aria-label={`${isRunning ? "停止" : "启动"}${service.title}`}
                onClick={() => void onToggle(service.key, isRunning)}
              >
                {isBusy ? (
                  "正在执行..."
                ) : isRunning ? (
                  <>
                    <IconPlayerPause size={16} stroke={1.8} aria-hidden="true" />
                    停止
                  </>
                ) : (
                  <>
                    <IconPlayerPlay size={16} stroke={1.8} aria-hidden="true" />
                    启动
                  </>
                )}
              </button>
            </section>
          );
        })}
      </div>
    </section>
  );
}
