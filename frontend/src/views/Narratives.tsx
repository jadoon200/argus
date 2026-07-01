import { useQuery } from "@tanstack/react-query";
import { api, type NarrativeOut } from "../api";

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

export function Narratives() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["narratives"],
    queryFn: () => api.narratives(50),
  });

  return (
    <div>
      <p className="section-note">
        Narrative clusters group documents by shared <b>framing</b>, ranked by a transparent{" "}
        <b>coordination signal</b> in [0,1] = burstiness × low-reliability share. It is{" "}
        <b>decision support for a human reviewer</b>, never an automated verdict of inauthenticity —
        a high score flags a story worth a closer look, not a confirmed influence operation.
      </p>

      {isLoading && <p className="center muted">Loading narratives…</p>}
      {error && <div className="error">{(error as Error).message}</div>}
      {data && data.length === 0 && (
        <p className="muted">
          No narratives yet — run <code>make narratives</code> over an enriched corpus.
        </p>
      )}
      {data?.map((n) => (
        <NarrativeCard key={n.narrative_id} n={n} />
      ))}
    </div>
  );
}
