import type { WebLlmSettings } from "../../types";

type SettingsDrawerProps = {
  onClose: () => void;
  open: boolean;
  settings: WebLlmSettings;
};

export function SettingsDrawer({
  onClose,
  open,
  settings
}: SettingsDrawerProps) {
  if (!open) {
    return null;
  }

  return (
    <aside aria-label="Settings">
      <div>
        <h2>Settings</h2>
        <button type="button" onClick={onClose}>
          Close settings
        </button>
      </div>
      <p>Read-only runtime details</p>
      <dl>
        <dt>Model</dt>
        <dd>{settings.modelId}</dd>
        <dt>System prompt</dt>
        <dd>{settings.systemPrompt || "Not set"}</dd>
      </dl>
    </aside>
  );
}
