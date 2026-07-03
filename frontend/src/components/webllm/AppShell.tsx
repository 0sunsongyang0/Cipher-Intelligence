import { useEffect, useState } from "react";
import { useWebLLMChat } from "../../hooks/useWebLLMChat";
import { ChatViewport } from "./ChatViewport";
import { ConversationSidebar } from "./ConversationSidebar";
import { PromptComposer } from "./PromptComposer";
import { RuntimePanel } from "./RuntimePanel";
import { SettingsDrawer } from "./SettingsDrawer";

export function AppShell() {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const {
    activeConversation,
    activeConversationId,
    conversations,
    error,
    initializeEngine,
    initProgress,
    isGenerating,
    runtimeStatus,
    sendMessage,
    setActiveConversationId,
    settings
  } = useWebLLMChat();

  useEffect(() => {
    void initializeEngine().catch(() => {
      return;
    });
  }, [initializeEngine]);

  return (
    <main>
      <header>
        <div>
          <p>WebLLM chat</p>
          <h1>WebLLM App Shell</h1>
        </div>
        <button type="button" onClick={() => setSettingsOpen(true)}>
          Settings
        </button>
      </header>

      <ConversationSidebar
        activeConversationId={activeConversationId}
        conversations={conversations}
        disabled={isGenerating}
        onNewConversation={() => setActiveConversationId(null)}
        onSelectConversation={setActiveConversationId}
      />

      <RuntimePanel
        error={runtimeStatus === "error" ? error : null}
        initProgress={initProgress}
        onInitialize={initializeEngine}
        runtimeStatus={runtimeStatus}
      />

      <ChatViewport
        activeConversation={activeConversation}
        error={runtimeStatus === "error" ? null : error}
        isGenerating={isGenerating}
      />

      <PromptComposer
        disabled={runtimeStatus !== "ready" || isGenerating}
        isGenerating={isGenerating}
        onSubmit={sendMessage}
      />

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings}
      />
    </main>
  );
}
