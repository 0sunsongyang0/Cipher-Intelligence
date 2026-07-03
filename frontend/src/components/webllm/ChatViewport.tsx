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
    <section aria-label="Messages" role="log" aria-live="polite">
      <header>
        <h2>{activeConversation?.title ?? "New conversation"}</h2>
        <p>
          {messages.length === 0
            ? "Send a prompt to begin this local conversation."
            : `${messages.length} messages in this conversation.`}
        </p>
      </header>

      {error ? <p role="alert">{error}</p> : null}

      {messages.length === 0 ? (
        <p>No messages yet.</p>
      ) : (
        <ol>
          {messages.map((message) => (
            <li key={message.id}>
              <article>
                <p>{message.role === "user" ? "You" : message.role === "assistant" ? "Assistant" : "System"}</p>
                <p>{message.content || "…"}</p>
              </article>
            </li>
          ))}
        </ol>
      )}

      {isGenerating ? <p>Generating response…</p> : null}
    </section>
  );
}
