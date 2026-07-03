import type { WebLlmInitProgress } from "../../types";

type RuntimePanelProps = {
  error: string | null;
  initProgress: WebLlmInitProgress | null;
  onInitialize: () => Promise<void> | void;
  runtimeStatus: "idle" | "loading" | "ready" | "error";
};

function getStatusTitle(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Preparing local runtime";
    case "ready":
      return "Runtime ready";
    case "error":
      return "Runtime needs attention";
    default:
      return "Runtime not started";
  }
}

function getStatusBody(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Downloading and warming the model so prompts can run entirely in this browser.";
    case "ready":
      return "The model is loaded and ready to answer new prompts.";
    case "error":
      return "The local model could not finish loading. Review the error and retry initialization.";
    default:
      return "Initialize the runtime to enable local responses in this session.";
  }
}

function getActionLabel(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Runtime starting";
    case "error":
      return "Retry runtime";
    case "ready":
      return "Runtime ready";
    default:
      return "Initialize runtime";
  }
}

function getStatusTone(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "ready":
      return " status-pill--ready";
    case "error":
      return " status-pill--error";
    case "loading":
      return " status-pill--loading";
    default:
      return "";
  }
}

export function RuntimePanel({
  error,
  initProgress,
  onInitialize,
  runtimeStatus
}: RuntimePanelProps) {
  return (
    <section className="runtime-panel" aria-label="Runtime">
      <div className="runtime-panel__header">
        <div>
          <p className="eyebrow">Runtime</p>
          <h2>{getStatusTitle(runtimeStatus)}</h2>
        </div>
        <span className={`status-pill${getStatusTone(runtimeStatus)}`}>{runtimeStatus}</span>
      </div>

      <p className="runtime-panel__body">{getStatusBody(runtimeStatus)}</p>

      {initProgress ? (
        <p className="runtime-panel__progress">
          {initProgress.text} ({Math.round(initProgress.progress * 100)}%)
        </p>
      ) : null}

      {error ? (
        <p className="status-banner status-banner--error" role="alert">
          {error}
        </p>
      ) : null}

      <button
        className="secondary-button"
        type="button"
        onClick={() => void onInitialize()}
        disabled={runtimeStatus === "loading" || runtimeStatus === "ready"}
      >
        {getActionLabel(runtimeStatus)}
      </button>
    </section>
  );
}
