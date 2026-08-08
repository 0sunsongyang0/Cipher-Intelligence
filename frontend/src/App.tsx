import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { AuthGuard } from "./components/AuthGuard";
import { AppShell } from "./components/webllm/AppShell";
import { useFrontendVersionRefresh } from "./hooks/useFrontendVersionRefresh";
import { checkSession, getCasdoorAuthConfig, logout } from "./lib/api";
import { LoginPage } from "./pages/LoginPage";
import { AccountPage } from "./pages/AccountPage";
import { CasesPage } from "./pages/CasesPage";
import { SkillsPage } from "./pages/SkillsPage";
import { JobsPage } from "./pages/JobsPage";
import type { AuthUser, CasdoorAuthConfig, SessionStatus } from "./types";

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return "登录失败，请稍后重试。";
}

function isAuthenticatedUserSession(session: SessionStatus): session is SessionStatus & { authenticated: true; user: AuthUser } {
  return session.authenticated && session.user !== null;
}

export function App() {
  useFrontendVersionRefresh();

  const navigate = useNavigate();
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
  const authenticated = sessionAuthenticated && viewer !== null;

  function applySession(session: SessionStatus) {
    setSessionAuthenticated(session.authenticated);
    setViewer(session.user);
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

        applySession(session);
        if (!session.authenticated && casdoorError) {
          setError(casdoorError);
        }
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
      if (!isAuthenticatedUserSession(session)) {
        setSessionAuthenticated(false);
        setViewer(null);
        setError("Casdoor 登录成功，但 Cipher 会话未能建立。请重试。");
        return;
      }

      applySession(session);
      navigate("/chat", { replace: true });
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
              error={error}
              casdoorEnabled={casdoor.enabled}
              casdoorDisplayName={casdoor.displayName}
              onCasdoorAuthenticated={handleCasdoorAuthenticated}
              onCasdoorError={setError}
            />
          )
        }
      />
      <Route
        path="/chat"
        element={
          <AuthGuard authenticated={authenticated}>
            <AppShell
              viewer={viewer}
              onOpenAccount={() => navigate("/account")}
              onOpenCases={() => navigate("/cases")}
              onOpenSkills={() => navigate("/skills")}
              onOpenJobs={() => navigate("/jobs")}
              onLogout={handleLogout}
              sessionError={error}
            />
          </AuthGuard>
        }
      />
      <Route
        path="/cases"
        element={
          <AuthGuard authenticated={authenticated}>
            <CasesPage onBack={() => navigate("/chat")} />
          </AuthGuard>
        }
      />
      <Route
        path="/account"
        element={
          <AuthGuard authenticated={authenticated}>
            {viewer ? (
              <AccountPage
                viewer={viewer}
                onBack={() => navigate("/chat")}
                onViewerChange={setViewer}
              />
            ) : null}
          </AuthGuard>
        }
      />
      <Route path="/skills" element={<AuthGuard authenticated={authenticated}><SkillsPage onBack={() => navigate("/chat")} /></AuthGuard>} />
      <Route path="/jobs" element={<AuthGuard authenticated={authenticated}><JobsPage onBack={() => navigate("/chat")} /></AuthGuard>} />
      <Route path="*" element={<Navigate to={authenticated ? "/chat" : "/"} replace />} />
    </Routes>
  );
}
