import { useState } from "react";
import { useServerChat } from "../../hooks/useServerChat";
import { ChatViewport } from "./ChatViewport";
import { ConversationSidebar } from "./ConversationSidebar";
import { PromptComposer } from "./PromptComposer";
import { RuntimePanel } from "./RuntimePanel";
import { SettingsDrawer } from "./SettingsDrawer";

type AppShellProps = {
  onLogout: () => Promise<void> | void;
  sessionError?: string | null;
};

export function AppShell({ onLogout, sessionError = null }: AppShellProps) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const {
    activeConversation,
    activeConversationId,
    conversations,
    error,
    isGenerating,
    runtimeStatus,
    sendMessage,
    setActiveConversationId,
    settings
  } = useServerChat();

  return (
    <main className="webllm-shell">
      <header className="shell-header">
        <div className="shell-header__copy">
          <p className="eyebrow">Campus deployment</p>
          <h1>DeepSeek campus chat</h1>
          <p className="shell-header__lead">
            Use the shared campus backend for DeepSeek-assisted conversations in this workspace.
          </p>
        </div>
        <div className="shell-header__actions">
          <button
            className="secondary-button"
            type="button"
            onClick={() => setSettingsOpen(true)}
          >
            Settings
          </button>
          <button className="secondary-button" type="button" onClick={() => void onLogout()}>
            Logout
          </button>
        </div>
      </header>

      {sessionError ? (
        <p className="status-banner status-banner--error" role="alert">
          {sessionError}
        </p>
      ) : null}

      <div className="shell-layout">
        <ConversationSidebar
          activeConversationId={activeConversationId}
          conversations={conversations}
          disabled={isGenerating}
          onNewConversation={() => setActiveConversationId(null)}
          onSelectConversation={setActiveConversationId}
        />

        <section className="workspace-shell">
          <RuntimePanel
            error={runtimeStatus === "error" ? error : null}
            runtimeStatus={runtimeStatus}
          />

          <ChatViewport
            activeConversation={activeConversation}
            error={runtimeStatus === "error" ? null : error}
            isGenerating={isGenerating}
          />

          <PromptComposer
            disabled={isGenerating}
            isGenerating={isGenerating}
            onSubmit={sendMessage}
          />
        </section>
      </div>

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings}
      />
    </main>
  );
}
