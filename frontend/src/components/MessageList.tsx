import type { Message } from "../types";

type MessageListProps = {
  isLoading: boolean;
  isStreaming: boolean;
  messages: Message[];
};

export function MessageList({
  isLoading,
  isStreaming,
  messages
}: MessageListProps) {
  if (isLoading) {
    return (
      <section className="message-list message-list--state" aria-live="polite">
        <p className="muted">{"\u6b63\u5728\u8bfb\u53d6\u5f53\u524d\u5bf9\u8bdd\u2026"}</p>
      </section>
    );
  }

  if (messages.length === 0) {
    return (
      <section className="message-list message-list--state" aria-live="polite">
        <div className="empty-state">
          <p className="eyebrow">Ready To Chat</p>
          <h2>{"\u4ece\u4e00\u4e2a\u95ee\u9898\u5f00\u59cb"}</h2>
          <p className="muted">
            {"\u4f60\u53ef\u4ee5\u5148\u65b0\u5efa\u5bf9\u8bdd\uff0c\u4e5f\u53ef\u4ee5\u76f4\u63a5\u5728\u4e0b\u65b9\u8f93\u5165\u95ee\u9898\uff0c\u6211\u4eec\u4f1a\u81ea\u52a8\u7eed\u4e0a\u672c\u8f6e\u4f1a\u8bdd\u3002"}
          </p>
        </div>
      </section>
    );
  }

  return (
    <section className="message-list" aria-live="polite">
      <ol className="message-thread">
        {messages.map((message) => (
          <li
            key={message.id}
            className={`message-item message-item--${message.role}`}
          >
            <article className="message-card">
              <p className="message-card__role">
                {message.role === "user" ? "\u4f60" : "\u52a9\u624b"}
              </p>
              <p className="message-card__content">{message.content || "\u2026"}</p>
            </article>
          </li>
        ))}
      </ol>

      {isStreaming ? (
        <p className="streaming-indicator">{"\u52a9\u624b\u6b63\u5728\u6301\u7eed\u751f\u6210\u56de\u590d\u2026"}</p>
      ) : null}
    </section>
  );
}