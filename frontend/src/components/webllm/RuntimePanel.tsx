import type { RuntimeStatus } from "../../types";

type RuntimePanelProps = {
  error: string | null;
  runtimeStatus: RuntimeStatus;
};

function getStatusTitle(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Responding";
    case "ready":
      return "Ready";
    case "error":
      return "Needs attention";
    default:
      return "Pending";
  }
}

function getStatusBody(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Cipher is streaming a response from the shared campus runtime.";
    case "ready":
      return "Shared campus runtime is available for new prompts.";
    case "error":
      return "The campus runtime could not complete the last request. Review the error and try again.";
    default:
      return "Waiting for the campus runtime.";
  }
}

function getActionLabel(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Responding";
    case "error":
      return "Unavailable";
    case "ready":
      return "Ready";
    default:
      return "Pending";
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
  runtimeStatus
}: RuntimePanelProps) {
  return (
    <section className="runtime-panel" aria-label="Runtime">
      <div className="runtime-panel__header">
        <div>
          <p className="eyebrow">Campus runtime</p>
          <h2>{getStatusTitle(runtimeStatus)}</h2>
        </div>
        <span className={`status-pill${getStatusTone(runtimeStatus)}`}>{runtimeStatus}</span>
      </div>

      <p className="runtime-panel__body">{getStatusBody(runtimeStatus)}</p>

      {error ? (
        <p className="status-banner status-banner--error" role="alert">
          {error}
        </p>
      ) : null}

      <p className="runtime-panel__status" aria-live="polite">
        {getActionLabel(runtimeStatus)}
      </p>
    </section>
  );
}
