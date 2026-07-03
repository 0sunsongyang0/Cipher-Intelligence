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
    <aside aria-label="Conversations">
      <div>
        <h2>Conversations</h2>
        <button type="button" onClick={onNewConversation} disabled={disabled}>
          New chat
        </button>
      </div>

      {conversations.length === 0 ? (
        <p>No saved conversations yet.</p>
      ) : (
        <ul>
          {conversations.map((conversation) => {
            const isActive = conversation.id === activeConversationId;

            return (
              <li key={conversation.id}>
                <button
                  type="button"
                  onClick={() => onSelectConversation(conversation.id)}
                  disabled={disabled}
                  aria-pressed={isActive}
                >
                  <span>{conversation.title}</span>
                  <span>{formatTimestamp(conversation.updatedAt)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </aside>
  );
}
