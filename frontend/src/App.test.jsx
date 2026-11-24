import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import App from "./App.jsx";

const OK = {
  session_id: "ignored",
  reply: "The capital of France is Paris.",
  metadata: {
    resolution_source: "LIVE_INFERENCE",
    model: "gemini/gemini-3.5-flash-lite",
    latency_ms: 812,
    input_tokens: 42,
    output_tokens: 9,
    key_id: "key_1",
    fallback_attempts: 0,
  },
};

function jsonResponse(status, body) {
  return Promise.resolve(
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }),
  );
}

function type(text) {
  fireEvent.change(screen.getByTestId("chat-input"), { target: { value: text } });
}

function bodies(fetchMock) {
  return fetchMock.mock.calls.map(([, init]) => JSON.parse(init.body));
}

let fetchMock;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("selectors and value-only metadata", () => {
  it("renders the required inputs", () => {
    render(<App />);
    expect(screen.getByTestId("chat-input")).toBeTruthy();
    expect(screen.getByTestId("send-button")).toBeTruthy();
    expect(screen.getByTestId("system-prompt-input")).toBeTruthy();
  });

  it("shows a reply with exact meta-* values and clears the input", async () => {
    fetchMock.mockReturnValueOnce(jsonResponse(200, OK));
    render(<App />);
    type("What is the capital of France?");
    fireEvent.click(screen.getByTestId("send-button"));
    expect(screen.getByTestId("chat-input").value).toBe(""); // cleared immediately

    const msg = await screen.findByTestId("assistant-message");
    const q = (id) => within(msg).getByTestId(id).textContent;
    expect(q("meta-source")).toBe("LIVE_INFERENCE");
    expect(q("meta-model")).toBe("gemini/gemini-3.5-flash-lite");
    expect(q("meta-latency")).toBe("812 ms");
    expect(q("meta-input-tokens")).toBe("42");
    expect(q("meta-output-tokens")).toBe("9");
    expect(msg.textContent).toContain("The capital of France is Paris.");
    expect(screen.queryByTestId("error-message")).toBeNull();
  });

  it("renders LLM_CACHE as the source value", async () => {
    fetchMock.mockReturnValueOnce(
      jsonResponse(200, { ...OK, metadata: { ...OK.metadata, resolution_source: "LLM_CACHE", key_id: null } }),
    );
    render(<App />);
    type("hi");
    fireEvent.click(screen.getByTestId("send-button"));
    const msg = await screen.findByTestId("assistant-message");
    expect(within(msg).getByTestId("meta-source").textContent).toBe("LLM_CACHE");
  });

  it("Enter sends; Shift+Enter does not", async () => {
    fetchMock.mockImplementation(() => jsonResponse(200, OK));
    render(<App />);
    type("line one");
    fireEvent.keyDown(screen.getByTestId("chat-input"), { key: "Enter", shiftKey: true });
    expect(fetchMock).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByTestId("chat-input"), { key: "Enter" });
    await screen.findByTestId("assistant-message");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("request contract", () => {
  it("sends only the newest message, and system_prompt only until the first success", async () => {
    fetchMock.mockImplementation(() => jsonResponse(200, OK));
    render(<App />);
    fireEvent.change(screen.getByTestId("system-prompt-input"), { target: { value: "Be brief." } });
    type("first");
    fireEvent.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");
    type("second");
    fireEvent.click(screen.getByTestId("send-button"));
    await waitFor(() => expect(screen.getAllByTestId("assistant-message")).toHaveLength(2));

    const [b1, b2] = bodies(fetchMock);
    expect(b1).toEqual({ session_id: b1.session_id, message: "first", system_prompt: "Be brief." });
    expect(b2).toEqual({ session_id: b1.session_id, message: "second" });
    expect(b1.session_id).toMatch(/^s-[A-Za-z0-9-]+$/);
    expect(screen.getByTestId("system-prompt-input").disabled).toBe(true);
  });

  it("starts a new session id on every load", async () => {
    fetchMock.mockImplementation(() => jsonResponse(200, OK));
    const first = render(<App />);
    type("a");
    fireEvent.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");
    first.unmount();
    render(<App />);
    type("b");
    fireEvent.click(screen.getByTestId("send-button"));
    await screen.findByTestId("assistant-message");
    const [b1, b2] = bodies(fetchMock);
    expect(b1.session_id).not.toBe(b2.session_id);
  });

  it("blocks whitespace-only sends client-side", () => {
    render(<App />);
    type("   ");
    fireEvent.keyDown(screen.getByTestId("chat-input"), { key: "Enter" });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("errors render as error-message, never assistant-message", () => {
  const cases = [
    [
      "422",
      () =>
        jsonResponse(422, {
          detail: [{ type: "value_error", loc: ["body", "message"], msg: "Value error, message must not be empty" }],
        }),
      "Request rejected: message must not be empty.",
    ],
    ["503", () => jsonResponse(503, { detail: "all providers unavailable" }), "All AI providers are unavailable"],
    ["500", () => jsonResponse(500, { detail: "internal server error" }), "internal error"],
    ["network", () => Promise.reject(new TypeError("Failed to fetch")), "Could not reach the server"],
  ];

  it.each(cases)("%s", async (_name, respond, expected) => {
    fetchMock.mockImplementationOnce(respond);
    render(<App />);
    type("hello");
    fireEvent.click(screen.getByTestId("send-button"));
    const err = await screen.findByTestId("error-message");
    expect(err.textContent).toContain(expected);
    expect(screen.queryByTestId("assistant-message")).toBeNull();
    expect(screen.getByTestId("chat-input").value).toBe("");
  });
});
