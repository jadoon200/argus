import { useQuery } from "@tanstack/react-query";
import { api, reliabilityMeta, type SourceOut } from "../api";

function SourceRow({ s }: { s: SourceOut }) {
  const meta = reliabilityMeta(s.reliability);
  const grade = (s.reliability || "F").toUpperCase()[0];
  return (
    <div className="src-row">
      <div className={`src-grade ${meta.tone}`} title={meta.label}>
        <span className="rv" style={{ color: "inherit" }}>
          {grade}
        </span>
      </div>
      <div className="src-main">
        <div className="src-name">{s.name ?? s.label}</div>
        <div className="src-rel">
          {meta.label}
          {s.kind ? ` · ${s.kind}` : ""}
        </div>
      </div>
      <code>{s.label}</code>
    </div>
  );
}

export function Collection() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  const model = useQuery({ queryKey: ["model"], queryFn: api.model });
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });

  const metrics = stats.data
    ? [
        { ml: "Documents", mv: stats.data.documents, mh: "open-source collected" },
        { ml: "Sources", mv: stats.data.sources, mh: "rated publishers" },
        { ml: "Events", mv: stats.data.events, mh: "corroborated clusters" },
        { ml: "Narratives", mv: stats.data.narratives, mh: "framing clusters" },
        { ml: "Briefs", mv: stats.data.briefs, mh: "produced" },
      ]
    : [];

  return (
    <div>
      <p className="section-note">
        The corpus and how much to trust it. Every source carries a <b>NATO Admiralty reliability
        grade</b> (A–F) — conservative by design: no open source is graded A, and an unknown
        publisher defaults to F.
      </p>

      {stats.error && <div className="error">{(stats.error as Error).message}</div>}
      {metrics.length > 0 && (
        <div className="metric-row">
          {metrics.map((m) => (
            <div className="metric" key={m.ml}>
              <div className="ml">{m.ml}</div>
              <div className="mv">{m.mv}</div>
              <div className="mh">{m.mh}</div>
            </div>
          ))}
        </div>
      )}

      <section className="panel">
        <h2>Inference backend</h2>
        {model.isLoading && <p className="muted">Loading…</p>}
        {model.error && <div className="error">{(model.error as Error).message}</div>}
        {model.data && (
          <>
            <div className="kv">
              <span className="k">Active backend</span>
              <span className="v">
                <span className="pill active">{model.data.active}</span>
                <span className="hint">the backend that would actually run a brief</span>
              </span>
            </div>
            <div className="kv">
              <span className="k">Configured</span>
              <span className="v mono">{model.data.configured}</span>
            </div>
            <div className="kv">
              <span className="k">Local Ollama models</span>
              <span className="v">
                {model.data.ollama_models.length === 0 ? (
                  <span className="hint">none reachable — deterministic template fallback</span>
                ) : (
                  model.data.ollama_models.map((m) => (
                    <span className="pill" key={m}>
                      {m}
                    </span>
                  ))
                )}
              </span>
            </div>
          </>
        )}
      </section>

      <section className="panel">
        <h2>
          Source roster
          {sources.data && <span className="hint">{sources.data.length} publishers</span>}
        </h2>
        {sources.isLoading && <p className="muted">Loading sources…</p>}
        {sources.error && <div className="error">{(sources.error as Error).message}</div>}
        {sources.data?.map((s) => (
          <SourceRow key={s.label} s={s} />
        ))}
      </section>
    </div>
  );
}
