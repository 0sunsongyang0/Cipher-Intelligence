import { useEffect, useState } from "react";
import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { AuthGuard } from "./components/AuthGuard";
import { checkSession, login } from "./lib/api";
import { ChatPage } from "./pages/ChatPage";
import { LoginPage } from "./pages/LoginPage";

function getErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }

  return "暂时无法登录，请稍后重试。";
}

export function App() {
  const navigate = useNavigate();
  const [sessionKnown, setSessionKnown] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;

    async function restoreSession() {
      try {
        const hasSession = await checkSession();
        if (!active) {
          return;
        }

        setAuthenticated(hasSession);
      } catch {
        if (!active) {
          return;
        }

        setAuthenticated(false);
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

  async function handleLogin(password: string) {
    setError(null);
    setIsSubmitting(true);

    try {
      await login(password);
      setAuthenticated(true);
      navigate("/chat", { replace: true });
    } catch (nextError) {
      setError(getErrorMessage(nextError));
      setAuthenticated(false);
    } finally {
      setIsSubmitting(false);
    }
  }

  if (!sessionKnown) {
    return (
      <main className="shell shell--centered">
        <section className="panel panel--loading">
          <p className="eyebrow">校园专用入口</p>
          <h1>正在恢复访问会话</h1>
          <p className="muted">请稍候，我们正在检查是否已有可用登录状态。</p>
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
              isSubmitting={isSubmitting}
              onSubmit={handleLogin}
            />
          )
        }
      />
      <Route
        path="/chat"
        element={
          <AuthGuard authenticated={authenticated}>
            <ChatPage />
          </AuthGuard>
        }
      />
      <Route
        path="*"
        element={<Navigate to={authenticated ? "/chat" : "/"} replace />}
      />
    </Routes>
  );
}
