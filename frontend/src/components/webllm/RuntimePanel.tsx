import type { RuntimeStatus } from "../../types";

type RuntimePanelProps = {
  error: string | null;
  runtimeStatus: RuntimeStatus;
};

function getStatusTitle(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Backend responding";
    case "ready":
      return "Backend ready";
    case "error":
      return "Backend needs attention";
    default:
      return "Backend pending";
  }
}

function getStatusBody(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "DeepSeek is streaming a response from the shared campus backend.";
    case "ready":
      return "The shared backend is available for new DeepSeek prompts.";
    case "error":
      return "The campus backend could not complete the last request. Review the error and try another prompt.";
    default:
      return "Waiting for the campus chat backend to become available.";
  }
}

function getActionLabel(runtimeStatus: RuntimePanelProps["runtimeStatus"]): string {
  switch (runtimeStatus) {
    case "loading":
      return "Backend responding";
    case "error":
      return "Backend unavailable";
    case "ready":
      return "Backend ready";
    default:
      return "Backend pending";
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
          <p className="eyebrow">Backend</p>
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

      <button className="secondary-button" type="button" disabled>
        {getActionLabel(runtimeStatus)}
      </button>
    </section>
  );
}
