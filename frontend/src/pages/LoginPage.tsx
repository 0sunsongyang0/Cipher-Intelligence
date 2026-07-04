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
    <main className="auth-shell">
      <section className="auth-panel">
        <div className="auth-panel__intro">
          <p className="eyebrow">Campus access</p>
          <h1>Enter the campus chat</h1>
          <p className="lead">
            Sign in with the shared passphrase to open the DeepSeek-backed campus assistant.
          </p>
        </div>

        <div className="auth-panel__meta" aria-hidden="true">
          <span>Private session</span>
          <span>Shared backend</span>
          <span>DeepSeek mode</span>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="password">Access passphrase</label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Enter passphrase"
              disabled={isSubmitting}
            />
          </div>

          {error ? (
            <p className="status-banner status-banner--error" role="alert">
              {error}
            </p>
          ) : null}

          <button className="primary-button" type="submit" disabled={isSubmitDisabled}>
            {isSubmitting ? "Opening chat..." : "Open chat"}
          </button>
        </form>
      </section>
    </main>
  );
}
