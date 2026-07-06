import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, reliabilityMeta, type SourceOut } from "../api";

/** Fill the corpus from the dashboard: GDELT ingest + enrichment on a topic. */
function IngestBox() {
  const [topic, setTopic] = useState("");
  const qc = useQueryClient();
  const ingest = useMutation({
    mutationFn: (q: string) => api.ingest(q),
    onSuccess: () => {
      // Corpus changed — refresh the metrics and any evidence-backed views.
      void qc.invalidateQueries({ queryKey: ["stats"] });
      void qc.invalidateQueries({ queryKey: ["sources"] });
    },
  });

  function run() {
    const q = topic.trim();
    if (q && !ingest.isPending) ingest.mutate(q);
  }

  return (
    <section className="panel">
      <h2>Ingest a topic</h2>
      <p className="section-note" style={{ marginTop: 4 }}>
        Pull open-source reporting (GDELT global news) on a topic into the corpus, then enrich it
        — entities, events, Admiralty credibility. Takes ~30–60s.
      </p>
      <div className="composer-box" style={{ marginTop: 8 }}>
        <textarea
          rows={1}
          value={topic}
          placeholder='e.g. "South China Sea", "Sahel coup", "undersea cable sabotage"'
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              run();
            }
          }}
        />
        <button className="primary send" onClick={run} disabled={!topic.trim() || ingest.isPending}>
          {ingest.isPending ? "Ingesting…" : "Ingest"}
        </button>
      </div>
      {ingest.isPending && <p className="muted">Fetching + enriching — this runs the embedding model, hang on…</p>}
      {ingest.error && <div className="error">{(ingest.error as Error).message}</div>}
      {ingest.data && (
        <p className="section-note" style={{ marginTop: 8 }}>
          Fetched <b>{ingest.data.fetched}</b> articles · <b>{ingest.data.new}</b> new documents added ·
          corpus now <b>{ingest.data.documents}</b> documents. Ask the Workbench about it.
        </p>
      )}
    </section>
  );
}

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

      <IngestBox />

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
