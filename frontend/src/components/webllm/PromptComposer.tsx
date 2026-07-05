import { useState, type FormEvent, type KeyboardEvent } from "react";

type PromptComposerProps = {
  disabled?: boolean;
  isGenerating: boolean;
  onSubmit: (content: string) => Promise<void> | void;
};

export function PromptComposer({
  disabled = false,
  isGenerating,
  onSubmit
}: PromptComposerProps) {
  const [content, setContent] = useState("");
  const isBlank = content.trim().length === 0;
  const isSubmitDisabled = disabled || isBlank;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (isSubmitDisabled) {
      return;
    }

    await onSubmit(content);
    setContent("");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <form className="prompt-composer prompt-composer--aurora" aria-label="Prompt composer" onSubmit={handleSubmit} data-testid="chat-input-dock">
      <label className="prompt-composer__label sr-only" htmlFor="prompt-composer-message">
        Message
      </label>
      <div className="prompt-composer__surface">
        <button className="prompt-composer__tool" type="button" aria-hidden="true" tabIndex={-1}>
          +
        </button>
        <textarea
          className="prompt-composer__input"
          id="prompt-composer-message"
          name="message"
          rows={1}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask the campus assistant something..."
          disabled={disabled}
        />
        <button
          className="primary-button primary-button--icon"
          type="submit"
          aria-label="Send message"
          disabled={isSubmitDisabled}
        >
          {isGenerating ? "Stop" : "Send"}
        </button>
      </div>
      <div className="prompt-composer__footer">
        <p className="prompt-composer__hint">
          Press Enter to send to DeepSeek, Shift+Enter for a new line.
        </p>
      </div>
    </form>
  );
}
