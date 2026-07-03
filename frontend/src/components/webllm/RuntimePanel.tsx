import type { WebLlmInitProgress } from "../../types";

type RuntimePanelProps = {
  error: string | null;
  initProgress: WebLlmInitProgress | null;
  onInitialize: () => Promise<void> | void;
  runtimeStatus: "idle" | "loading" | "ready" | "error";
};

function getStatusCopy(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Starting WebLLM runtime";
    case "ready":
      return "Runtime ready";
    case "error":
      return "Runtime unavailable";
    default:
      return "Runtime idle";
  }
}

export function RuntimePanel({
  error,
  initProgress,
  onInitialize,
  runtimeStatus
}: RuntimePanelProps) {
  return (
    <section aria-label="Runtime">
      <h2>Runtime</h2>
      <p>{getStatusCopy(runtimeStatus)}</p>
      {initProgress ? (
        <p>
          {initProgress.text} ({Math.round(initProgress.progress * 100)}%)
        </p>
      ) : null}
      {error ? <p role="alert">{error}</p> : null}
      <button
        type="button"
        onClick={() => void onInitialize()}
        disabled={runtimeStatus === "loading" || runtimeStatus === "ready"}
      >
        {runtimeStatus === "error" ? "Retry runtime" : "Initialize runtime"}
      </button>
    </section>
  );
}
