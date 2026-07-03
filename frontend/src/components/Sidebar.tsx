import type { Conversation } from "../types";

type SidebarProps = {
  conversations: Conversation[];
  activeConversationId: number | null;
  disabled: boolean;
  isCreatingConversation: boolean;
  isLoading: boolean;
  onCreateConversation: () => Promise<void> | void;
  onSelectConversation: (conversationId: number) => void;
};

function formatUpdatedAt(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function Sidebar({
  conversations,
  activeConversationId,
  disabled,
  isCreatingConversation,
  isLoading,
  onCreateConversation,
  onSelectConversation
}: SidebarProps) {
  return (
    <aside className="chat-sidebar">
      <div className="chat-sidebar__header">
        <div>
          <p className="eyebrow">Campus LLM Assistant</p>
          <h2>{"\u4f60\u7684\u5bf9\u8bdd"}</h2>
        </div>

        <button
          className="sidebar-action"
          type="button"
          onClick={() => void onCreateConversation()}
          disabled={disabled || isCreatingConversation}
        >
          {isCreatingConversation ? "\u521b\u5efa\u4e2d\u2026" : "\u65b0\u5efa\u5bf9\u8bdd"}
        </button>
      </div>

      <div className="chat-sidebar__body">
        {isLoading ? (
          <p className="sidebar-state">{"\u6b63\u5728\u52a0\u8f7d\u4f1a\u8bdd\u5217\u8868\u2026"}</p>
        ) : conversations.length === 0 ? (
          <p className="sidebar-state">
            {"\u8fd8\u6ca1\u6709\u5bf9\u8bdd\uff0c\u70b9\u51fb\u4e0a\u65b9\u6309\u94ae\u5f00\u59cb\u7b2c\u4e00\u8f6e\u4ea4\u6d41\u3002"}
          </p>
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
                  >
                    <span className="conversation-item__title">{conversation.title}</span>
                    <span className="conversation-item__meta">
                      {formatUpdatedAt(conversation.updated_at)}
                    </span>
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