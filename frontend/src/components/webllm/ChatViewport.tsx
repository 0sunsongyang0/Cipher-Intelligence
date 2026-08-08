import type { LocalConversation } from "../../types";

type ChatViewportProps = {
  activeConversation: LocalConversation | null;
  error: string | null;
  isGenerating: boolean;
};

export function ChatViewport({
  activeConversation,
  error,
  isGenerating
}: ChatViewportProps) {
  const messages = activeConversation?.messages ?? [];

  return (
    <section className="chat-viewport chat-viewport--aurora" aria-label="Messages" role="log" aria-live="polite">
      <header className="chat-viewport__header">
        <div>
          <p className="eyebrow">Primary thread</p>
          <h2>{activeConversation?.title ?? "New conversation"}</h2>
        </div>
        <p className="chat-viewport__meta">
          {messages.length === 0
            ? "Send a prompt to begin this campus conversation."
            : `${messages.length} messages in this conversation.`}
        </p>
      </header>

      {error ? (
        <p className="status-banner status-banner--error" role="alert">
          {error}
        </p>
      ) : null}

      {messages.length === 0 ? (
        <div className="empty-state">
          <p className="eyebrow">Ready when you are</p>
          <h3>No messages yet</h3>
          <p>Ask for a summary, brainstorm, or draft to start a Cipher conversation.</p>
        </div>
      ) : (
        <ol className="message-thread">
          {messages.map((message) => {
            const roleLabel =
              message.role === "user" ? "You" : message.role === "assistant" ? "Assistant" : "System";

            return (
              <li
                key={message.id}
                className={`message-item message-item--${message.role === "assistant" ? "assistant" : message.role}`}
              >
                {message.role === "assistant" ? (
                  <div className="message-avatar message-avatar--assistant" aria-hidden="true">
                    B
                  </div>
                ) : null}

                <article className="message-card">
                  <p className="message-card__role">{roleLabel}</p>
                  <p className="message-card__content">{message.content || "..."}</p>
                </article>

                {message.role === "user" ? (
                  <div className="message-avatar message-avatar--user" aria-hidden="true">
                    U
                  </div>
                ) : null}
              </li>
            );
          })}
        </ol>
      )}

      {isGenerating ? <p className="streaming-indicator">Cipher is responding...</p> : null}
    </section>
  );
}
