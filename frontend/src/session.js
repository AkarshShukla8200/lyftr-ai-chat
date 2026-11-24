// A new session id on every page load. Never persisted (no localStorage /
// sessionStorage), so a reload always starts a new conversation.
// Format: "s-" + UUID v4 -> only [A-Za-z0-9-], 38 chars (backend allows 1-128).
export function newSessionId() {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `s-${crypto.randomUUID()}`;
  }
  // Fallback for non-secure contexts where randomUUID is unavailable.
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `s-${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
