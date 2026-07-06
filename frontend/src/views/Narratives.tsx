import { useQuery } from "@tanstack/react-query";
import { api, type EventOut, type NarrativeOut } from "../api";

function coordBucket(c: number | null): { tone: string; pct: number } {
  const v = c ?? 0;
  const tone = v >= 0.6 ? "coord-high" : v >= 0.3 ? "coord-mid" : "coord-low";
  return { tone, pct: Math.round(v * 100) };
}

function span(first: string | null, last: string | null): string {
  const f = first?.slice(0, 10);
  const l = last?.slice(0, 10);
  if (f && l && f !== l) return `${f} → ${l}`;
  return f ?? l ?? "—";
}

function NarrativeCard({ n }: { n: NarrativeOut }) {
  const { tone, pct } = coordBucket(n.coordination);
  return (
    <article className="narr">
      <div className="narr-head">
        <div className="narr-main">
          <div className="narr-label">{n.label}</div>
          <div className="narr-meta">
            <span>{n.doc_count} documents</span>
            <span>{n.source_count} sources</span>
            <span>{span(n.first_seen, n.last_seen)}</span>
          </div>
          {n.disarm.length > 0 && (
            <div className="narr-meta" style={{ marginTop: 6, flexWrap: "wrap", gap: 6 }}>
              {n.disarm.map((t) => (
                <span
                  key={t.technique_id}
                  className="backend-tag"
                  title={`DISARM ${t.phase} technique · similarity ${t.score.toFixed(2)} — advisory human-review signal, not a verdict`}
                >
                  {t.technique_id} {t.name}
                </span>
              ))}
            </div>
          )}
        </div>
        <div className={`coord ${tone}`}>
          <div className="coord-val">{n.coordination == null ? "—" : n.coordination.toFixed(2)}</div>
          <div className="coord-k">coordination</div>
        </div>
      </div>
      <div className="coord-bar">
        <span className={tone} style={{ width: `${pct}%` }} />
      </div>
    </article>
  );
}

function ContestedCard({ e }: { e: EventOut }) {
  const div = e.divergence ?? 0;
  const tone = div >= 0.5 ? "coord-high" : "coord-mid";
  return (
    <article className="narr">
      <div className="narr-head">
        <div className="narr-main">
          <div className="narr-label">{e.title}</div>
          <div className="narr-meta">
            <span>{e.doc_count} documents</span>
            <span>{e.source_count} sources</span>
            {e.occurred && <span>{e.occurred.slice(0, 10)}</span>}
          </div>
        </div>
        <div className={`coord ${tone}`}>
          <div className="coord-val">{div.toFixed(2)}</div>
          <div className="coord-k">divergence</div>
        </div>
      </div>
      <div className="coord-bar">
        <span className={tone} style={{ width: `${Math.round(div * 100)}%` }} />
      </div>
    </article>
  );
}

export function Narratives() {
  const narratives = useQuery({ queryKey: ["narratives"], queryFn: () => api.narratives(50) });
  const contested = useQuery({ queryKey: ["contested"], queryFn: () => api.contested(20) });

  return (
    <div>
      <p className="section-note">
        Narrative clusters group documents by shared <b>framing</b>, ranked by a transparent{" "}
        <b>coordination signal</b> in [0,1] = burstiness × (0.5 + 0.5 × low-reliability share), so
        organic breaking-news bursts are dampened and a synchronized, state-affiliated-heavy push
        scores highest. Tags show <b>DISARM influence-ops techniques</b> the framing resembles.
        All of it is <b>decision support for a human reviewer</b>, never an automated verdict of
        inauthenticity — a high score flags a story worth a closer look, not a confirmed influence
        operation.
      </p>

      {narratives.isLoading && <p className="center muted">Loading narratives…</p>}
      {narratives.error && <div className="error">{(narratives.error as Error).message}</div>}
      {narratives.data && narratives.data.length === 0 && (
        <p className="muted">
          No narratives yet — ingest a topic in the <b>Collection</b> view (or just ask the
          Workbench a question: collection and narrative analysis run automatically).
        </p>
      )}
      {narratives.data?.map((n) => (
        <NarrativeCard key={n.narrative_id} n={n} />
      ))}

      <section style={{ marginTop: 28 }}>
        <h2>Contested events</h2>
        <p className="section-note">
          Events whose sources <b>disagree in framing</b> (divergence = 1 − minimum pairwise
          similarity across the event's reporting) — contradictions are where deception, error,
          or a developing story surface. Human-review signal.
        </p>
        {contested.isLoading && <p className="center muted">Loading contested events…</p>}
        {contested.error && <div className="error">{(contested.error as Error).message}</div>}
        {contested.data && contested.data.length === 0 && (
          <p className="muted">No contested events in the current corpus.</p>
        )}
        {contested.data?.map((e) => (
          <ContestedCard key={e.event_id} e={e} />
        ))}
      </section>
    </div>
  );
}
