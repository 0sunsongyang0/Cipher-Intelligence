import { useState, type FormEvent } from "react";

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
  const trimmedPassword = password.trim();
  const isSubmitDisabled = isSubmitting || trimmedPassword.length === 0;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (trimmedPassword.length === 0) {
      return;
    }

    await onSubmit(trimmedPassword);
  }

  return (
    <main className="shell shell--centered">
      <section className="panel">
        <p className="eyebrow">Campus LLM Assistant</p>
        <h1>兔兔炸弹的大模型助手</h1>
        <p className="lead">输入统一访问口令后即可进入校园专用对话入口。</p>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="password">访问口令</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              disabled={isSubmitting}
            />
          </div>

          {error ? (
            <p className="error-message" role="alert">
              {error}
            </p>
          ) : null}

          <button className="submit-button" type="submit" disabled={isSubmitDisabled}>
            {isSubmitting ? "正在进入..." : "进入助手"}
          </button>
        </form>
      </section>
    </main>
  );
}