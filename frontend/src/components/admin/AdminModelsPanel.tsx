import { IconCpu } from "@tabler/icons-react";
import type { AdminOverview } from "../../types";

export function AdminModelsPanel({
  providers,
}: {
  providers: AdminOverview["models"]["providers"];
}) {
  return (
    <section className="admin-card admin-card--wide">
      <div className="admin-card__header">
        <div>
          <p className="eyebrow">模型</p>
          <h2>模型概览</h2>
        </div>
        <IconCpu size={18} stroke={1.8} aria-hidden="true" />
      </div>

      <ul className="admin-provider-list">
        {providers.map((provider) => (
          <li key={provider.provider} className="admin-provider-item">
            <div>
              <strong>{provider.provider}</strong>
              <p>{provider.healthy}/{provider.total} 可用</p>
            </div>
            <span className="admin-status-chip admin-status-chip--ready">已接入</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
