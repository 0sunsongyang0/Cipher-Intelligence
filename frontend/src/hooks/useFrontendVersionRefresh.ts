import { useEffect } from "react";

type UseFrontendVersionRefreshOptions = {
  enabled?: boolean;
  intervalMs?: number;
  reload?: () => void;
};

function getActiveEntryScript(documentRef: Document): string | null {
  const script = documentRef.querySelector<HTMLScriptElement>('script[type="module"][src^="/assets/"]');

  if (!script?.src) {
    return null;
  }

  return new URL(script.src, window.location.origin).toString();
}

function extractEntryScriptFromHtml(html: string): string | null {
  const parsedDocument = new DOMParser().parseFromString(html, "text/html");
  return getActiveEntryScript(parsedDocument);
}

export function useFrontendVersionRefresh(options: UseFrontendVersionRefreshOptions = {}) {
  const {
    enabled = import.meta.env.MODE !== "test" && !import.meta.env.DEV,
    intervalMs = 45000,
    reload = () => window.location.reload()
  } = options;

  useEffect(() => {
    if (!enabled || typeof window === "undefined" || typeof document === "undefined") {
      return;
    }

    let disposed = false;
    let checking = false;
    let reloading = false;
    const currentEntryScript = getActiveEntryScript(document);

    if (!currentEntryScript) {
      return;
    }

    async function checkForNewFrontend() {
      if (disposed || checking || reloading || document.visibilityState === "hidden") {
        return;
      }

      checking = true;

      try {
        const response = await fetch(window.location.pathname, {
          credentials: "same-origin",
          cache: "no-store",
          headers: {
            Accept: "text/html"
          }
        });

        if (!response.ok) {
          return;
        }

        const nextEntryScript = extractEntryScriptFromHtml(await response.text());

        if (!nextEntryScript || nextEntryScript === currentEntryScript) {
          return;
        }

        reloading = true;
        reload();
      } catch {
        // Ignore transient refresh check failures and keep the current page usable.
      } finally {
        checking = false;
      }
    }

    const intervalId = window.setInterval(() => {
      void checkForNewFrontend();
    }, intervalMs);

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        void checkForNewFrontend();
      }
    };

    const handleFocus = () => {
      void checkForNewFrontend();
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    window.addEventListener("focus", handleFocus);
    void checkForNewFrontend();

    return () => {
      disposed = true;
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("focus", handleFocus);
    };
  }, [enabled, intervalMs, reload]);
}
