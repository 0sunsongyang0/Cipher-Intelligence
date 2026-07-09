import { useState, type FormEvent } from "react";
import { AuroraBackground } from "../components/AuroraBackground";

export type AuthMode = "login" | "register";

type LoginCredentials = {
  username: string;
  password: string;
};

type RegisterCredentials = LoginCredentials & {
  confirmPassword: string;
  inviteCode: string;
};

type LoginPageProps = {
  mode: AuthMode;
  error: string | null;
  isSubmitting: boolean;
  onModeChange: (mode: AuthMode) => void;
  onLogin: (payload: LoginCredentials) => Promise<void> | void;
  onRegister: (payload: RegisterCredentials) => Promise<void> | void;
};

const COPY = {
  status: "网络安全·AI Agent",
  eyebrow: "访问验证",
  title: "进入聊天界面",
  lead: "使用账号登录，或凭邀请码创建新账号后进入你的专属网络安全对话空间。",
  loginTab: "登录",
  registerTab: "注册",
  usernameLabel: "用户名",
  usernamePlaceholder: "请输入用户名",
  passwordLabel: "密码",
  passwordPlaceholder: "请输入密码",
  confirmPasswordLabel: "确认密码",
  confirmPasswordPlaceholder: "请再次输入密码",
  inviteCodeLabel: "邀请码",
  inviteCodePlaceholder: "请输入邀请码",
  loginSubmit: "登录",
  loginSubmitting: "登录中...",
  registerSubmit: "创建账号",
  registerSubmitting: "创建中...",
} as const;

export function LoginPage({
  mode,
  error,
  isSubmitting,
  onModeChange,
  onLogin,
  onRegister,
}: LoginPageProps) {
  const [loginForm, setLoginForm] = useState<LoginCredentials>({
    username: "",
    password: "",
  });
  const [registerForm, setRegisterForm] = useState<RegisterCredentials>({
    username: "",
    password: "",
    confirmPassword: "",
    inviteCode: "",
  });

  const isLoginDisabled =
    isSubmitting || loginForm.username.trim().length === 0 || loginForm.password.trim().length === 0;
  const isRegisterDisabled =
    isSubmitting ||
    registerForm.username.trim().length === 0 ||
    registerForm.password.trim().length === 0 ||
    registerForm.confirmPassword.trim().length === 0 ||
    registerForm.inviteCode.trim().length === 0;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (mode === "login") {
      if (isLoginDisabled) {
        return;
      }

      await onLogin(loginForm);
      return;
    }

    if (isRegisterDisabled) {
      return;
    }

    await onRegister(registerForm);
  }

  return (
    <main className="auth-shell aurora-shell">
      <AuroraBackground testId="aurora-background" />
      <section className="auth-shell__frame">
        <section className="auth-panel auth-panel--login glass-panel-card" data-testid="login-shell-card">
          <div className="auth-panel__brand">
            <span className="brand-mark" aria-hidden="true">
              Cipher AI
            </span>
            <span className="status-dot">{COPY.status}</span>
          </div>

          <div className="auth-panel__intro">
            <p className="eyebrow">{COPY.eyebrow}</p>
            <h1>{COPY.title}</h1>
            <p className="lead">{COPY.lead}</p>
          </div>

          <div className="auth-mode-toggle" role="tablist" aria-label="认证模式">
            <button
              type="button"
              aria-pressed={mode === "login"}
              onClick={() => onModeChange("login")}
              disabled={isSubmitting}
            >
              {COPY.loginTab}
            </button>
            <button
              type="button"
              aria-pressed={mode === "register"}
              onClick={() => onModeChange("register")}
              disabled={isSubmitting}
            >
              {COPY.registerTab}
            </button>
          </div>

          <form className="login-form" onSubmit={handleSubmit}>
            <div className="field">
              <label htmlFor={`${mode}-username`}>{COPY.usernameLabel}</label>
              <input
                id={`${mode}-username`}
                name="username"
                type="text"
                autoComplete={mode === "login" ? "username" : "new-password"}
                value={mode === "login" ? loginForm.username : registerForm.username}
                onChange={(event) => {
                  const username = event.target.value;
                  if (mode === "login") {
                    setLoginForm((current) => ({ ...current, username }));
                    return;
                  }

                  setRegisterForm((current) => ({ ...current, username }));
                }}
                placeholder={COPY.usernamePlaceholder}
                disabled={isSubmitting}
              />
            </div>

            <div className="field">
              <label htmlFor={`${mode}-password`}>{COPY.passwordLabel}</label>
              <input
                id={`${mode}-password`}
                name="password"
                type="password"
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                value={mode === "login" ? loginForm.password : registerForm.password}
                onChange={(event) => {
                  const password = event.target.value;
                  if (mode === "login") {
                    setLoginForm((current) => ({ ...current, password }));
                    return;
                  }

                  setRegisterForm((current) => ({ ...current, password }));
                }}
                placeholder={COPY.passwordPlaceholder}
                disabled={isSubmitting}
              />
            </div>

            {mode === "register" ? (
              <>
                <div className="field">
                  <label htmlFor="register-confirm-password">{COPY.confirmPasswordLabel}</label>
                  <input
                    id="register-confirm-password"
                    name="confirmPassword"
                    type="password"
                    autoComplete="new-password"
                    value={registerForm.confirmPassword}
                    onChange={(event) =>
                      setRegisterForm((current) => ({
                        ...current,
                        confirmPassword: event.target.value,
                      }))
                    }
                    placeholder={COPY.confirmPasswordPlaceholder}
                    disabled={isSubmitting}
                  />
                </div>

                <div className="field">
                  <label htmlFor="register-invite-code">{COPY.inviteCodeLabel}</label>
                  <input
                    id="register-invite-code"
                    name="inviteCode"
                    type="text"
                    value={registerForm.inviteCode}
                    onChange={(event) =>
                      setRegisterForm((current) => ({
                        ...current,
                        inviteCode: event.target.value,
                      }))
                    }
                    placeholder={COPY.inviteCodePlaceholder}
                    disabled={isSubmitting}
                  />
                </div>
              </>
            ) : null}

            {error ? (
              <p className="status-banner status-banner--error" role="alert">
                {error}
              </p>
            ) : null}

            <button
              className="primary-button primary-button--aurora"
              type="submit"
              disabled={mode === "login" ? isLoginDisabled : isRegisterDisabled}
            >
              {mode === "login"
                ? isSubmitting
                  ? COPY.loginSubmitting
                  : COPY.loginSubmit
                : isSubmitting
                  ? COPY.registerSubmitting
                  : COPY.registerSubmit}
            </button>
          </form>
        </section>
      </section>
    </main>
  );
}
