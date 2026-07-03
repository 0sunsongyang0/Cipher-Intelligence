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
    <form className="prompt-composer" aria-label="Prompt composer" onSubmit={handleSubmit}>
      <label className="prompt-composer__label" htmlFor="prompt-composer-message">
        Message
      </label>
      <textarea
        className="prompt-composer__input"
        id="prompt-composer-message"
        name="message"
        rows={4}
        value={content}
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Ask WebLLM something..."
        disabled={disabled}
      />
      <div className="prompt-composer__footer">
        <p className="prompt-composer__hint">Press Enter to send, Shift+Enter for a new line.</p>
        <button className="primary-button" type="submit" disabled={isSubmitDisabled}>
          {isGenerating ? "Sending..." : "Send"}
        </button>
      </div>
    </form>
  );
}
