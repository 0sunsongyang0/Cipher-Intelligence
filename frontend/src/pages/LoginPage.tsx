import { useState, type FormEvent } from "react";
import { AuroraBackground } from "../components/AuroraBackground";

type LoginPageProps = {
  error: string | null;
  isSubmitting: boolean;
  onSubmit: (password: string) => Promise<void> | void;
};

export function LoginPage({
  error,
  isSubmitting,
  onSubmit
}: LoginPageProps) {
  const [password, setPassword] = useState("");
  const isBlankPassword = password.trim().length === 0;
  const isSubmitDisabled = isSubmitting || isBlankPassword;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isBlankPassword) {
      return;
    }

    await onSubmit(password);
  }

  return (
    <main className="auth-shell aurora-shell">
      <AuroraBackground testId="aurora-background" />
      <section className="auth-shell__frame">
        <section className="auth-panel glass-panel-card" data-testid="login-shell-card">
          <div className="auth-panel__brand">
            <span className="brand-mark" aria-hidden="true">
              Bomb AI
            </span>
            <span className="status-dot">校园控制台</span>
          </div>

          <div className="auth-panel__intro">
            <p className="eyebrow">访问验证</p>
            <h1>进入聊天界面</h1>
            <p className="lead">
              输入共享访问密码，进入你的专属对话空间。
            </p>
          </div>

          <div className="auth-panel__meta" aria-hidden="true">
            <span>私有工作区访问</span>
            <span>共享 DeepSeek 后端</span>
          </div>

          <form className="login-form" onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor="password">访问密码</label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder="请输入访问密码"
                disabled={isSubmitting}
              />
            </div>

            {error ? (
              <p className="status-banner status-banner--error" role="alert">
                {error}
              </p>
            ) : null}

            <button className="primary-button primary-button--aurora" type="submit" disabled={isSubmitDisabled}>
              {isSubmitting ? "正在进入..." : "进入聊天"}
            </button>
          </form>
        </section>
      </section>
    </main>
  );
}
