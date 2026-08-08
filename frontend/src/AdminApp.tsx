import { useEffect, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AuroraBackground } from "./components/AuroraBackground";
import { CasdoorEmbeddedLogin } from "./components/CasdoorEmbeddedLogin";
import { ThemeToggle } from "./components/ThemeToggle";
import { useFrontendVersionRefresh } from "./hooks/useFrontendVersionRefresh";
import { checkSession, getCasdoorAuthConfig, logout } from "./lib/api";
import { AdminPage } from "./pages/AdminPage";
import type { AuthUser, CasdoorAuthConfig, SessionStatus } from "./types";

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return "登录失败，请稍后重试。";
}

function isAuthenticatedAdminSession(
  session: SessionStatus
): session is SessionStatus & { authenticated: true; user: AuthUser & { isAdmin: true } } {
  return session.authenticated && session.user !== null && session.user.isAdmin;
}

function AdminLoginPage({
  error,
  casdoor,
  onCasdoorAuthenticated,
  onCasdoorError,
}: {
  error: string | null;
  casdoor: CasdoorAuthConfig;
  onCasdoorAuthenticated: () => Promise<void> | void;
  onCasdoorError: (message: string) => void;
}) {
  return (
    <main className="auth-shell aurora-shell">
      <AuroraBackground testId="aurora-background" />
      <ThemeToggle className="theme-toggle--auth" />
      <section className="auth-shell__frame">
        <section className="auth-panel glass-panel-card">
          <div className="auth-panel__brand">
            <span className="brand-mark" aria-hidden="true">
              Cipher Admin
            </span>
            <span className="status-dot">独立管理入口</span>
          </div>

          <div className="auth-panel__intro">
            <p className="eyebrow">Admin Access</p>
            <h1>进入管理后台</h1>
            <p className="lead">使用统一身份认证登录后，继续管理系统服务、模型和身份权限。</p>
          </div>

          {casdoor.enabled ? (
            <CasdoorEmbeddedLogin
              displayName={casdoor.displayName}
              onAuthenticated={onCasdoorAuthenticated}
              onError={onCasdoorError}
            />
          ) : (
            <p className="status-banner status-banner--error" role="alert">
              统一身份认证当前不可用，请检查 Casdoor 配置。
            </p>
          )}

          {error ? (
            <p className="status-banner status-banner--error" role="alert">
              {error}
            </p>
          ) : null}
        </section>
      </section>
    </main>
  );
}

export function AdminApp() {
  useFrontendVersionRefresh();
  const location = useLocation();

  const [sessionKnown, setSessionKnown] = useState(false);
  const [sessionAuthenticated, setSessionAuthenticated] = useState(false);
  const [viewer, setViewer] = useState<AuthUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [casdoor, setCasdoor] = useState<CasdoorAuthConfig>({
    enabled: false,
    provider: "casdoor",
    displayName: "Casdoor",
    managementUrl: "",
  });
  const authenticated = sessionAuthenticated && viewer !== null && viewer.isAdmin;

  function applySession(session: SessionStatus) {
    setSessionAuthenticated(session.authenticated);
    setViewer(session.user);
  }

  function rejectAdminSession() {
    setSessionAuthenticated(false);
    setViewer(null);
    setError("当前 Casdoor 账号没有 Cipher 管理权限。");
  }

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      const casdoorError = new URLSearchParams(location.search).get("casdoor_error");
      try {
        const session = await checkSession();
        if (!active) {
          return;
        }

        if (!session.authenticated || session.user === null) {
          setSessionAuthenticated(false);
          setViewer(null);
          if (casdoorError) {
            setError(casdoorError);
          }
          return;
        }

        if (!session.user.isAdmin) {
          rejectAdminSession();
          return;
        }

        applySession(session);
      } catch (nextError) {
        if (!active) {
          return;
        }

        setSessionAuthenticated(false);
        setViewer(null);
        setError(getErrorMessage(nextError));
      } finally {
        if (active) {
          setSessionKnown(true);
        }
      }
    }

    void restoreSession();

    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    let active = true;

    getCasdoorAuthConfig()
      .then((config) => {
        if (active) {
          setCasdoor(config);
        }
      })
      .catch(() => {
        setError("无法读取 Casdoor 配置，请检查身份服务是否可用。");
      });

    return () => {
      active = false;
    };
  }, []);

  async function handleCasdoorAuthenticated() {
    setError(null);

    try {
      const session = await checkSession();
      if (!isAuthenticatedAdminSession(session)) {
        rejectAdminSession();
        return;
      }

      applySession(session);
    } catch (nextError) {
      setSessionAuthenticated(false);
      setViewer(null);
      setError(getErrorMessage(nextError));
    }
  }

  async function handleLogout() {
    setError(null);

    try {
      await logout();
      setSessionAuthenticated(false);
      setViewer(null);
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    }
  }

  if (!sessionKnown) {
    return (
      <main className="shell shell--centered">
        <section className="panel panel--loading">
          <p className="eyebrow">Admin Access</p>
          <h1>正在恢复后台会话</h1>
          <p className="muted">正在检查当前登录状态，马上为你恢复管理界面。</p>
        </section>
      </main>
    );
  }

  return (
    <Routes>
      <Route
        path="/*"
        element={
          authenticated ? (
            <AdminPage
              onLogout={handleLogout}
              sessionError={error}
              casdoorManagementUrl={casdoor.managementUrl}
            />
          ) : (
            <AdminLoginPage
              error={error}
              casdoor={casdoor}
              onCasdoorAuthenticated={handleCasdoorAuthenticated}
              onCasdoorError={setError}
            />
          )
        }
      />
    </Routes>
  );
}
