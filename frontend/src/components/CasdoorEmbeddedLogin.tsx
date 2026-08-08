import { IconRefresh, IconShieldLock } from "@tabler/icons-react";
import { useEffect, useRef, useState } from "react";

import { useTheme } from "../theme";

export const CASDOOR_EMBEDDED_RETURN_TO = "/auth/casdoor/embedded";

type CasdoorAuthMessage = {
  type: "cipher:casdoor-auth";
  status: "success" | "error";
  message?: string | null;
};

type CasdoorReadyMessage = {
  type: "cipher:casdoor-ready";
};

type CasdoorViewMessage = {
  type: "cipher:casdoor-view";
  view: "password" | "code";
};

type CasdoorTheme = "light" | "dark";

type CasdoorEmbeddedLoginProps = {
  displayName: string;
  loginPath?: string;
  onAuthenticated: () => Promise<void> | void;
  onError: (message: string) => void;
};

type EmbeddedFrame = {
  id: number;
  source: string;
};

function isCasdoorAuthMessage(value: unknown): value is CasdoorAuthMessage {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const candidate = value as Partial<CasdoorAuthMessage>;
  return (
    candidate.type === "cipher:casdoor-auth" &&
    (candidate.status === "success" || candidate.status === "error") &&
    (candidate.message === undefined ||
      candidate.message === null ||
      typeof candidate.message === "string")
  );
}

function isCasdoorReadyMessage(value: unknown): value is CasdoorReadyMessage {
  return typeof value === "object" && value !== null &&
    (value as Partial<CasdoorReadyMessage>).type === "cipher:casdoor-ready";
}

function isCasdoorViewMessage(value: unknown): value is CasdoorViewMessage {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Partial<CasdoorViewMessage>;
  return candidate.type === "cipher:casdoor-view" &&
    (candidate.view === "password" || candidate.view === "code");
}

export function CasdoorEmbeddedLogin({
  displayName,
  loginPath = "/api/auth/casdoor/login",
  onAuthenticated,
  onError,
}: CasdoorEmbeddedLoginProps) {
  const { theme } = useTheme();
  const sourceForTheme = (mode: CasdoorTheme) => `${loginPath}?${new URLSearchParams({
    return_to: CASDOOR_EMBEDDED_RETURN_TO,
    theme: mode,
  }).toString()}`;
  const [source] = useState(() => sourceForTheme(theme));
  const activeFrameRef = useRef<HTMLIFrameElement | null>(null);
  const frameRefs = useRef(new Map<number, HTMLIFrameElement>());
  const readyFrameIds = useRef(new Set<number>());
  const activeView = useRef<CasdoorViewMessage["view"]>("password");
  const currentTheme = useRef<CasdoorTheme>(theme);
  currentTheme.current = theme;
  const nextFrameId = useRef(1);
  const [frames, setFrames] = useState<EmbeddedFrame[]>(() => [{ id: 0, source }]);
  const [activeFrameId, setActiveFrameId] = useState(0);
  const [loading, setLoading] = useState(true);
  const [completing, setCompleting] = useState(false);
  const [frameError, setFrameError] = useState<string | null>(null);

  useEffect(() => {
    frameRefs.current.forEach((frame) => {
      frame.contentWindow?.postMessage({
        type: "cipher:casdoor-set-theme",
        theme,
      }, "*");
    });
  }, [theme]);

  useEffect(() => {
    function handleMessage(event: MessageEvent<unknown>) {
      const frameEntry = Array.from(frameRefs.current.entries()).find(
        ([, frame]) => event.source === frame.contentWindow
      );
      if (frameEntry && isCasdoorReadyMessage(event.data)) {
        frameEntry[1].contentWindow?.postMessage({
          type: "cipher:casdoor-set-theme",
          theme,
        }, "*");
        frameEntry[1].contentWindow?.postMessage({
          type: "cipher:casdoor-set-view",
          view: activeView.current,
        }, "*");
        handleFrameReady(frameEntry[0]);
        return;
      }
      if (
        frameEntry?.[0] === activeFrameId &&
        isCasdoorViewMessage(event.data)
      ) {
        const view = event.data.view;
        activeView.current = view;
        frameRefs.current.forEach((frame, frameId) => {
          if (frameId !== activeFrameId) {
            frame.contentWindow?.postMessage({
              type: "cipher:casdoor-set-view",
              view,
            }, "*");
          }
        });
        return;
      }
      if (
        event.origin !== window.location.origin ||
        event.source !== activeFrameRef.current?.contentWindow ||
        !isCasdoorAuthMessage(event.data)
      ) {
        return;
      }

      if (event.data.status === "success") {
        setCompleting(true);
        setFrameError(null);
        void onAuthenticated();
        return;
      }

      const message = event.data.message?.trim() || "Casdoor 登录未完成，请重试。";
      setCompleting(false);
      setFrameError(message);
      onError(message);
    }

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [activeFrameId, frames, onAuthenticated, onError, source, theme]);

  function retry() {
    const replacement = { id: nextFrameId.current++, source };
    readyFrameIds.current.clear();
    setFrameError(null);
    setCompleting(false);
    setLoading(true);
    setActiveFrameId(replacement.id);
    setFrames([replacement]);
  }

  function handleFrameReady(frameId: number) {
    readyFrameIds.current.add(frameId);
    setLoading(false);
    setActiveFrameId(frameId);
  }

  function handleFrameLoad(frameId: number) {
    const frame = frameRefs.current.get(frameId);
    frame?.contentWindow?.postMessage({
      type: "cipher:casdoor-set-theme",
      theme: currentTheme.current,
    }, "*");
    frame?.contentWindow?.postMessage({
      type: "cipher:casdoor-set-view",
      view: activeView.current,
    }, "*");
  }

  function handleFrameError(frameId: number) {
    if (frameId !== activeFrameId) {
      readyFrameIds.current.delete(frameId);
      return;
    }
    const message = "无法载入 Casdoor 登录页面，请检查身份服务是否运行。";
    setLoading(false);
    setFrameError(message);
    onError(message);
  }

  return (
    <section className="casdoor-embed" aria-label={`${displayName} 统一身份认证`}>
      <div
        className="casdoor-embed__viewport"
        aria-busy={loading || completing}
        data-state={frameError ? "error" : completing ? "completing" : loading ? "loading" : "ready"}
      >
        {loading && !frameError ? (
          <div className="casdoor-embed__loading" role="status">
            <span />
            <span />
            <span />
            <p>正在载入统一登录…</p>
          </div>
        ) : null}

        {completing ? (
          <div className="casdoor-embed__completion" role="status">
            <IconShieldLock size={24} stroke={1.7} aria-hidden="true" />
            <strong>身份验证成功</strong>
            <span>正在建立 Cipher 会话…</span>
          </div>
        ) : null}

        {frameError ? (
          <div className="casdoor-embed__error" role="alert">
            <strong>统一登录未完成</strong>
            <span>{frameError}</span>
            <button type="button" className="secondary-button" onClick={retry}>
              <IconRefresh size={16} stroke={1.8} aria-hidden="true" />
              重新载入
            </button>
          </div>
        ) : frames.map((frame) => {
          const active = frame.id === activeFrameId;
          return (
            <iframe
              key={frame.id}
              ref={(element) => {
                if (element) {
                  frameRefs.current.set(frame.id, element);
                  if (active) activeFrameRef.current = element;
                } else {
                  frameRefs.current.delete(frame.id);
                }
              }}
              className={`casdoor-embed__frame${active ? " is-active" : " is-buffering"}`}
              src={frame.source}
              title={`${displayName} 登录${active ? "" : "（主题切换中）"}`}
              scrolling="no"
              sandbox="allow-forms allow-popups allow-popups-to-escape-sandbox allow-same-origin allow-scripts allow-top-navigation-by-user-activation"
              aria-hidden={!active}
              tabIndex={active ? undefined : -1}
              onLoad={() => handleFrameLoad(frame.id)}
              onError={() => handleFrameError(frame.id)}
            />
          );
        })}
      </div>
    </section>
  );
}
