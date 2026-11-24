// Backend client. Sends only the newest message; the backend owns history.

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || "http://localhost:8000").replace(/\/+$/, "");

export const REQUEST_TIMEOUT_MS = 90_000; // > keys x LLM_TIMEOUT_SECONDS (2 x 30 s)

export class ChatError extends Error {
  constructor(message, { status = null, kind = "http" } = {}) {
    super(message);
    this.name = "ChatError";
    this.status = status;
    this.kind = kind; // "http" | "network" | "timeout" | "invalid-response"
  }
}

// FastAPI 422: detail is a list of {loc, msg, ...}; our own 422s use a string.
export function describe422(detail) {
  if (typeof detail === "string" && detail.trim()) return `Request rejected: ${detail}`;
  if (Array.isArray(detail) && detail.length) {
    const parts = detail.map((item) => {
      const loc = Array.isArray(item?.loc) ? item.loc.filter((p) => p !== "body") : [];
      const field = loc.length ? String(loc[loc.length - 1]) : "request";
      const msg = String(item?.msg || "is invalid").replace(/^Value error,\s*/i, "");
      if (field === "request" || /json/i.test(item?.type || "")) return msg;
      return msg.toLowerCase().startsWith(field.toLowerCase()) ? msg : `${field}: ${msg}`;
    });
    return `Request rejected: ${parts.join("; ")}.`;
  }
  return "Request rejected: the message could not be validated.";
}

export function describeError(status, body) {
  const detail = body && typeof body === "object" ? body.detail : undefined;
  if (status === 422) return describe422(detail);
  if (status === 503) {
    return "All AI providers are unavailable right now (every API key failed). Please try again in a moment.";
  }
  if (status === 500) return "The server hit an internal error. Please try again.";
  if (typeof detail === "string" && detail) return `Error ${status}: ${detail}`;
  return `Unexpected response from the server (HTTP ${status}).`;
}

function isValidChatResponse(data) {
  const m = data?.metadata;
  return (
    data &&
    typeof data.reply === "string" &&
    data.reply.trim() !== "" &&
    m &&
    (m.resolution_source === "LIVE_INFERENCE" || m.resolution_source === "LLM_CACHE") &&
    typeof m.model === "string" &&
    Number.isInteger(m.latency_ms) &&
    Number.isInteger(m.input_tokens) &&
    Number.isInteger(m.output_tokens)
  );
}

export async function sendChat({ sessionId, message, systemPrompt }) {
  const body = { session_id: sessionId, message };
  if (systemPrompt && systemPrompt.trim()) body.system_prompt = systemPrompt;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let response;
  try {
    response = await fetch(`${API_BASE_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
  } catch (err) {
    if (err?.name === "AbortError") {
      throw new ChatError("The server took too long to respond (over 90 seconds). Please try again.", {
        kind: "timeout",
      });
    }
    throw new ChatError("Could not reach the server. Check your connection and try again.", { kind: "network" });
  } finally {
    clearTimeout(timer);
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new ChatError(describeError(response.status, data), { status: response.status });
  }
  if (!isValidChatResponse(data)) {
    throw new ChatError("The server sent an unexpected response.", { status: response.status, kind: "invalid-response" });
  }
  return data;
}
