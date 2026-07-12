import { useEffect, useState } from "react";
import { Route, Routes } from "react-router-dom";
import { AuroraBackground } from "./components/AuroraBackground";
import { useFrontendVersionRefresh } from "./hooks/useFrontendVersionRefresh";
import { checkSession, login, logout } from "./lib/api";
import { AdminPage } from "./pages/AdminPage";
import type { AuthUser, SessionStatus } from "./types";

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
  isSubmitting,
  onSubmit,
}: {
  error: string | null;
  isSubmitting: boolean;
  onSubmit: (credentials: { username: string; password: string }) => Promise<void> | void;
}) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const disabled = isSubmitting || username.trim().length === 0 || password.trim().length === 0;

  return (
    <main className="auth-shell aurora-shell">
      <AuroraBackground testId="aurora-background" />
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
            <p className="lead">使用管理员账号登录后继续管理服务、模型、文件和隧道。</p>
          </div>

          <form
            className="login-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (!disabled) {
                void onSubmit({ username, password });
              }
            }}
          >
            <div className="field">
              <label htmlFor="admin-username">用户名</label>
              <input
                id="admin-username"
                name="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                placeholder="请输入管理员用户名"
                disabled={isSubmitting}
              />
            </div>

            <div className="field">
              <label htmlFor="admin-password">密码</label>
              <input
                id="admin-password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入管理员密码"
                disabled={isSubmitting}
              />
            </div>

            {error ? (
              <p className="status-banner status-banner--error" role="alert">
                {error}
              </p>
            ) : null}

            <button className="primary-button primary-button--aurora" type="submit" disabled={disabled}>
              {isSubmitting ? "登录中..." : "进入后台"}
            </button>
          </form>
        </section>
      </section>
    </main>
  );
}

export function AdminApp() {
  useFrontendVersionRefresh();

  const [sessionKnown, setSessionKnown] = useState(false);
  const [sessionAuthenticated, setSessionAuthenticated] = useState(false);
  const [viewer, setViewer] = useState<AuthUser | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const authenticated = sessionAuthenticated && viewer !== null && viewer.isAdmin;

  function applySession(session: SessionStatus) {
    setSessionAuthenticated(session.authenticated);
    setViewer(session.user);
  }

  function rejectAdminSession() {
    setSessionAuthenticated(false);
    setViewer(null);
    setError("Admin access required");
  }

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      try {
        const session = await checkSession();
        if (!active) {
          return;
        }

        if (!isAuthenticatedAdminSession(session)) {
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

  async function handleLogin(credentials: { username: string; password: string }) {
    setError(null);
    setIsSubmitting(true);

    try {
      const session = await login(credentials);
      if (!isAuthenticatedAdminSession(session)) {
        rejectAdminSession();
        return;
      }

      applySession(session);
    } catch (nextError) {
      setSessionAuthenticated(false);
      setViewer(null);
      setError(getErrorMessage(nextError));
    } finally {
      setIsSubmitting(false);
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
            <AdminPage onLogout={handleLogout} sessionError={error} />
          ) : (
            <AdminLoginPage error={error} isSubmitting={isSubmitting} onSubmit={handleLogin} />
          )
        }
      />
    </Routes>
  );
}
