import type { LocalConversation } from "../../types";

type ConversationSidebarProps = {
  activeConversationId: string | null;
  conversations: LocalConversation[];
  disabled?: boolean;
  onNewConversation: () => void;
  onSelectConversation: (conversationId: string) => void;
};

function formatTimestamp(value: string): string {
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function ConversationSidebar({
  activeConversationId,
  conversations,
  disabled = false,
  onNewConversation,
  onSelectConversation
}: ConversationSidebarProps) {
  return (
    <aside className="conversation-sidebar conversation-sidebar--aurora" aria-label="Conversations">
      <div className="conversation-sidebar__header">
        <div>
          <p className="eyebrow">Conversation history</p>
          <h2>Conversations</h2>
        </div>
        <button className="secondary-button secondary-button--soft" type="button" onClick={onNewConversation} disabled={disabled}>
          New chat
        </button>
      </div>

      <div className="conversation-sidebar__body">
        {conversations.length === 0 ? (
          <div className="empty-state">
            <p className="eyebrow">No saved threads</p>
            <h3>Start a new chat</h3>
            <p className="empty-copy">New campus conversations will appear here in this browser.</p>
          </div>
        ) : (
          <ul className="conversation-list">
            {conversations.map((conversation) => {
              const isActive = conversation.id === activeConversationId;

              return (
                <li key={conversation.id}>
                  <button
                    className={`conversation-item${isActive ? " conversation-item--active" : ""}`}
                    type="button"
                    onClick={() => onSelectConversation(conversation.id)}
                    disabled={disabled}
                    aria-pressed={isActive}
                  >
                    <span className="conversation-item__title">{conversation.title}</span>
                    <span className="conversation-item__meta">{formatTimestamp(conversation.updatedAt)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </aside>
  );
}
