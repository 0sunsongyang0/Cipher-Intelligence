import { IconShieldCog } from "@tabler/icons-react";
import { useState } from "react";

type CasdoorManagementPanelProps = {
  managementUrl: string;
};

export function CasdoorManagementPanel({ managementUrl }: CasdoorManagementPanelProps) {
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const source = managementUrl.trim();

  if (!source) {
    return (
      <section className="casdoor-management casdoor-management--empty">
        <span className="casdoor-management__icon" aria-hidden="true">
          <IconShieldCog size={24} stroke={1.7} />
        </span>
        <p className="eyebrow">统一身份管理</p>
        <h2>Casdoor 管理地址尚未配置</h2>
        <p className="admin-card__copy">
          请检查后端的 Casdoor Endpoint 配置，配置生效后即可在这里管理用户、组织、角色和应用。
        </p>
      </section>
    );
  }

  return (
    <section className="casdoor-management">
      <div
        className="casdoor-management__viewport"
        data-state={failed ? "error" : loading ? "loading" : "ready"}
        aria-busy={loading}
      >
        {loading && !failed ? (
          <div className="casdoor-management__loading" role="status">
            <span />
            <span />
            <span />
            <p>正在载入 Casdoor 管理控制台…</p>
          </div>
        ) : null}

        {failed ? (
          <div className="casdoor-management__error" role="alert">
            <IconShieldCog size={26} stroke={1.7} aria-hidden="true" />
            <strong>无法载入 Casdoor 管理控制台</strong>
            <span>请确认 Casdoor 正在运行，并允许被 Cipher 页面嵌入。</span>
          </div>
        ) : (
          <iframe
            className="casdoor-management__frame"
            src={source}
            title="Casdoor 身份管理"
            sandbox="allow-downloads allow-forms allow-modals allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts"
            onLoad={() => setLoading(false)}
            onError={() => {
              setLoading(false);
              setFailed(true);
            }}
          />
        )}
      </div>
    </section>
  );
}
