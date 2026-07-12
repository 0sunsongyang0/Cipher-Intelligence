import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AuthGuard } from "./components/AuthGuard";
import { AppShell } from "./components/webllm/AppShell";
import { useFrontendVersionRefresh } from "./hooks/useFrontendVersionRefresh";
import { checkSession, login, logout, register } from "./lib/api";
import { LoginPage, type AuthMode } from "./pages/LoginPage";
import type { AuthUser, SessionStatus } from "./types";

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return "登录失败，请稍后重试。";
}

function isAuthenticatedUserSession(session: SessionStatus): session is SessionStatus & { authenticated: true; user: AuthUser } {
  return session.authenticated && session.user !== null;
}

function getInvalidAuthSessionMessage(mode: AuthMode): string {
  return mode === "login"
    ? "Login succeeded but did not return an authenticated session."
    : "Registration succeeded but did not return an authenticated session.";
}

export function App() {
  useFrontendVersionRefresh();

  const navigate = useNavigate();
  const [sessionKnown, setSessionKnown] = useState(false);
  const [sessionAuthenticated, setSessionAuthenticated] = useState(false);
  const [viewer, setViewer] = useState<AuthUser | null>(null);
  const [mode, setMode] = useState<AuthMode>("login");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const authenticated = sessionAuthenticated && viewer !== null;

  function applySession(session: SessionStatus) {
    setSessionAuthenticated(session.authenticated);
    setViewer(session.user);
  }

  function rejectInvalidAuthSession(mode: AuthMode) {
    setSessionAuthenticated(false);
    setViewer(null);
    setError(getInvalidAuthSessionMessage(mode));
  }

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      try {
        const session = await checkSession();
        if (!active) {
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

      if (!isAuthenticatedUserSession(session)) {
        rejectInvalidAuthSession("login");
        return;
      }

      applySession(session);
      navigate("/chat", { replace: true });
    } catch (nextError) {
      setSessionAuthenticated(false);
      setViewer(null);
      setError(getErrorMessage(nextError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleRegister(payload: {
    username: string;
    password: string;
    confirmPassword: string;
    inviteCode: string;
  }) {
    if (payload.password !== payload.confirmPassword) {
      setError("两次输入的密码不一致。");
      return;
    }

    setError(null);
    setIsSubmitting(true);

    try {
      const session = await register({
        username: payload.username,
        password: payload.password,
        inviteCode: payload.inviteCode,
      });

      if (!isAuthenticatedUserSession(session)) {
        rejectInvalidAuthSession("register");
        return;
      }

      applySession(session);
      navigate("/chat", { replace: true });
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
      navigate("/", { replace: true });
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    }
  }

  if (!sessionKnown) {
    return (
      <main className="shell shell--centered">
        <section className="panel panel--loading">
          <p className="eyebrow">访问验证</p>
          <h1>正在恢复会话</h1>
          <p className="muted">正在检查当前登录状态，马上为你恢复聊天界面。</p>
        </section>
      </main>
    );
  }

  return (
    <Routes>
      <Route
        path="/"
        element={
          authenticated ? (
            <Navigate to="/chat" replace />
          ) : (
            <LoginPage
              mode={mode}
              onModeChange={(nextMode) => {
                setMode(nextMode);
                setError(null);
              }}
              error={error}
              isSubmitting={isSubmitting}
              onLogin={handleLogin}
              onRegister={handleRegister}
            />
          )
        }
      />
      <Route
        path="/chat"
        element={
          <AuthGuard authenticated={authenticated}>
            <AppShell onLogout={handleLogout} sessionError={error} />
          </AuthGuard>
        }
      />
      <Route path="*" element={<Navigate to={authenticated ? "/chat" : "/"} replace />} />
    </Routes>
  );
}
