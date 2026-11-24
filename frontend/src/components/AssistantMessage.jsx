// Each meta-* element holds ONLY its value; labels live in sibling <dt>s.
export default function AssistantMessage({ reply, metadata }) {
  const cached = metadata.resolution_source === "LLM_CACHE";
  return (
    <article className="bubble bubble--assistant" data-testid="assistant-message">
      <p className="bubble__text">{reply}</p>
      <dl className="meta" aria-label="Request metadata">
        <div className="meta__item">
          <dt>Source</dt>
          <dd>
            <span className={`badge ${cached ? "badge--cache" : "badge--live"}`} data-testid="meta-source">
              {metadata.resolution_source}
            </span>
          </dd>
        </div>
        <div className="meta__item">
          <dt>Model</dt>
          <dd data-testid="meta-model">{metadata.model}</dd>
        </div>
        <div className="meta__item">
          <dt>Latency</dt>
          <dd data-testid="meta-latency">{`${metadata.latency_ms} ms`}</dd>
        </div>
        <div className="meta__item">
          <dt>Input tokens</dt>
          <dd data-testid="meta-input-tokens">{metadata.input_tokens}</dd>
        </div>
        <div className="meta__item">
          <dt>Output tokens</dt>
          <dd data-testid="meta-output-tokens">{metadata.output_tokens}</dd>
        </div>
        <div className="meta__item">
          <dt>Key</dt>
          <dd>{metadata.key_id ?? "none (cache)"}</dd>
        </div>
        <div className="meta__item">
          <dt>Fallbacks</dt>
          <dd>{metadata.fallback_attempts}</dd>
        </div>
      </dl>
    </article>
  );
}
