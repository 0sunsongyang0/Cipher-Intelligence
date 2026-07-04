import type { PersistedChatState } from "../../types";

type SettingsDrawerProps = {
  onClose: () => void;
  open: boolean;
  settings: PersistedChatState["settings"];
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
    <aside className="settings-drawer" aria-label="Settings">
      <div className="settings-drawer__header">
        <div>
          <p className="eyebrow">Read-only</p>
          <h2>Settings</h2>
        </div>
        <button className="secondary-button" type="button" onClick={onClose}>
          Close settings
        </button>
      </div>
      <p className="settings-drawer__lead">Read-only backend details</p>
      <dl className="settings-drawer__details">
        <dt>Provider</dt>
        <dd>DeepSeek campus backend</dd>
        <dt>Model</dt>
        <dd>{settings.modelId ?? "DeepSeek campus model"}</dd>
        <dt>System prompt</dt>
        <dd>{settings.systemPrompt || "Not set"}</dd>
      </dl>
    </aside>
  );
}
