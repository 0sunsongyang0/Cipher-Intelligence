import { useState, type FormEvent, type KeyboardEvent } from "react";

type ChatComposerProps = {
  disabled: boolean;
  isStreaming: boolean;
  onSubmit: (content: string) => Promise<void> | void;
};

export function ChatComposer({
  disabled,
  isStreaming,
  onSubmit
}: ChatComposerProps) {
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
    <form className="chat-composer" onSubmit={handleSubmit}>
      <label className="chat-composer__label" htmlFor="chat-input">
        {"\u8f93\u5165\u6d88\u606f"}
      </label>
      <textarea
        id="chat-input"
        className="chat-composer__input"
        name="content"
        rows={3}
        placeholder={"\u8f93\u5165\u4f60\u60f3\u95ee\u7684\u95ee\u9898\u2026"}
        value={content}
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={disabled}
      />
      <div className="chat-composer__footer">
        <p className="chat-composer__hint">
          {"Enter \u53d1\u9001\uff0cShift + Enter \u6362\u884c"}
        </p>
        <button className="submit-button" type="submit" disabled={isSubmitDisabled}>
          {isStreaming ? "\u751f\u6210\u4e2d\u2026" : "\u53d1\u9001"}
        </button>
      </div>
    </form>
  );
}