import { useEffect, useRef, useState } from "react";
import { ChatError, sendChat } from "./api.js";
import { newSessionId } from "./session.js";
import AssistantMessage from "./components/AssistantMessage.jsx";

const SLOW_HINT_AFTER_MS = 5000;

export default function App() {
  // New session on every page load (state is never persisted).
  const [sessionId] = useState(() => newSessionId());
  const [items, setItems] = useState([]); // {id, kind: "user"|"assistant"|"error", ...}
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptLocked, setPromptLocked] = useState(false);
  const [pending, setPending] = useState(false);
  const [slow, setSlow] = useState(false);
  const nextId = useRef(0);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [items, pending]);

  useEffect(() => {
    if (!pending) {
      setSlow(false);
      return undefined;
    }
    const t = setTimeout(() => setSlow(true), SLOW_HINT_AFTER_MS);
    return () => clearTimeout(t);
  }, [pending]);

  const add = (item) => setItems((prev) => [...prev, { id: nextId.current++, ...item }]);

  async function send() {
    if (pending) return; // no duplicate sends
    const text = input;
    if (!text.trim()) return; // whitespace-only blocked client-side
    setInput(""); // cleared immediately, success or failure
    add({ kind: "user", content: text.trim() });
    setPending(true);
    try {
      // The system prompt is sent until the first successful reply fixes it
      // for the session (a failed request stores nothing on the server).
      const data = await sendChat({
        sessionId,
        message: text,
        systemPrompt: promptLocked ? undefined : systemPrompt,
      });
      add({ kind: "assistant", reply: data.reply, metadata: data.metadata });
      setPromptLocked(true);
    } catch (err) {
      const message = err instanceof ChatError ? err.message : "Something went wrong. Please try again.";
      add({ kind: "error", content: message });
    } finally {
      setPending(false);
      inputRef.current?.focus();
    }
  }

  function onSubmit(e) {
    e.preventDefault();
    send();
  }

  function onKeyDown(e) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1 className="header__title">Lyftr Chat</h1>
          <p className="header__sub">Multi-key LLM gateway with response caching</p>
        </div>
        <p className="header__session" title="A new session starts on every page load">
          Session <code>{sessionId.slice(0, 10)}…</code>
        </p>
      </header>

      <details className="system-prompt">
        <summary>System prompt {promptLocked ? "(locked for this session)" : "(optional)"}</summary>
        <label htmlFor="system-prompt" className="visually-hidden">
          System prompt
        </label>
        <textarea
          id="system-prompt"
          data-testid="system-prompt-input"
          className="system-prompt__input"
          placeholder="e.g. You are a concise assistant that answers in one paragraph."
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          disabled={promptLocked}
          rows={2}
        />
        <p className="system-prompt__hint">
          {promptLocked
            ? "Fixed by the first reply. Reload the page to start a new session with a different prompt."
            : "Applied to this session with your first message. Leave empty for the default."}
        </p>
      </details>

      <main className="log" role="log" aria-live="polite" aria-label="Conversation">
        {items.length === 0 && !pending && (
          <div className="empty">
            <p className="empty__title">Start a conversation</p>
            <p>Each reply shows whether it came from live inference or the cache, the model, latency and token usage.</p>
          </div>
        )}
        {items.map((item) => {
          if (item.kind === "user") {
            return (
              <div key={item.id} className="bubble bubble--user">
                <p className="bubble__text">{item.content}</p>
              </div>
            );
          }
          if (item.kind === "assistant") {
            return <AssistantMessage key={item.id} reply={item.reply} metadata={item.metadata} />;
          }
          return (
            <div key={item.id} className="bubble bubble--error" role="alert" data-testid="error-message">
              <p className="bubble__text">{item.content}</p>
            </div>
          );
        })}
        {pending && (
          <div className="pending" role="status">
            <span className="dots" aria-hidden="true">
              <span />
              <span />
              <span />
            </span>
            <span>{slow ? "The server may be waking up (free hosting cold start). Still waiting…" : "Thinking…"}</span>
          </div>
        )}
        <div ref={endRef} />
      </main>

      <form className="composer" onSubmit={onSubmit}>
        <label htmlFor="chat-input" className="visually-hidden">
          Message
        </label>
        <textarea
          id="chat-input"
          ref={inputRef}
          data-testid="chat-input"
          className="composer__input"
          placeholder="Type a message…"
          title="Enter to send, Shift+Enter for a new line"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          rows={1}
          autoFocus
        />
        <button
          type="submit"
          data-testid="send-button"
          className="composer__send"
          disabled={pending || !input.trim()}
        >
          {pending ? "Sending…" : "Send"}
        </button>
      </form>
    </div>
  );
}
