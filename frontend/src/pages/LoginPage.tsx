import {
  IconActivity,
  IconBinaryTree2,
  IconShieldCheck,
} from "@tabler/icons-react";
import { useState } from "react";

import { CasdoorEmbeddedLogin } from "../components/CasdoorEmbeddedLogin";
import { GradientWaves } from "../components/GradientWaves";
import { ThemeToggle } from "../components/ThemeToggle";
import cipherLogo from "../assets/cipher-mark.svg";
import { useTheme } from "../theme";

type LoginPageProps = {
  error: string | null;
  casdoorEnabled?: boolean;
  casdoorDisplayName?: string;
  onCasdoorAuthenticated: () => Promise<void> | void;
  onCasdoorError: (message: string) => void;
};

export function LoginPage({
  error,
  casdoorEnabled = false,
  casdoorDisplayName = "Casdoor",
  onCasdoorAuthenticated,
  onCasdoorError,
}: LoginPageProps) {
  const { theme } = useTheme();
  return (
    <main className="auth-shell auth-gradient-shell">
      <div
        className="auth-gradient-waves"
        data-testid="gradient-waves-background"
        aria-hidden="true"
      >
        <GradientWaves
          horizonColor={theme === "dark" ? "#251744" : "#B8CCE8"}
          waveColor={theme === "dark" ? "#895EE8" : "#376FBC"}
          crestColor={theme === "dark" ? "#F4EDFF" : "#78A0D2"}
          speed={0.22}
          amplitude={2.8}
          waveScale={0.58}
          waveRatio={0.92}
          swell={28}
          turbulence={14}
          tilt={1.13}
          zoom={0.94}
          height={6.2}
          fogDepth={24}
          detail="low"
          brightness={theme === "dark" ? 0.96 : 1}
          opacity={theme === "dark" ? 0.82 : 0.95}
          mouseInteraction
          parallaxStrength={0.18}
          grain={false}
        />
      </div>
      <ThemeToggle className="theme-toggle--auth" />
      <section className="auth-shell__frame">
        <aside className="auth-brief" aria-label="Cipher Intelligence">
          <div className="auth-brief__brand">
            <span className="auth-brief__mark"><img src={cipherLogo} alt="" /></span>
            <span>Cipher Intelligence</span>
          </div>
          <div className="auth-brief__copy">
            <h1>
              <span>把复杂线索，</span>
              <span>变成清晰行动。</span>
            </h1>
            <p>研判样本、关联行为，在同一处沉淀调查上下文。</p>
          </div>
          <div className="auth-brief__signals" aria-label="平台能力">
            <span><IconShieldCheck size={18} stroke={1.7} />威胁研判</span>
            <span><IconBinaryTree2 size={18} stroke={1.7} />行为关联</span>
            <span><IconActivity size={18} stroke={1.7} />持续分析</span>
          </div>
        </aside>

        <section className="auth-login-surface" data-testid="login-auth-surface" aria-label="登录 Cipher">
          {casdoorEnabled ? (
            <CasdoorEmbeddedLogin
              displayName={casdoorDisplayName}
              onAuthenticated={onCasdoorAuthenticated}
              onError={onCasdoorError}
            />
          ) : (
            <p className="status-banner status-banner--error" role="alert">
              Casdoor 统一身份认证未配置，请检查服务端 CASDOOR_ENABLED 及应用凭据。
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
