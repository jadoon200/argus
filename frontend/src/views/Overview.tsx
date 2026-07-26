import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { api, type OverviewLaneOut } from "../api";
import { EvidenceCard } from "./Workbench";

const LANE_COPY: Record<string, string> = {
  osint: "News + agency reporting",
  sky: "HORUS air-domain awareness",
  ocean: "PHAROS maritime awareness",
  cyber: "SENTINEL cyber knowledge graph",
};

function LaneCard({ lane }: { lane: OverviewLaneOut }) {
  return (
    <article className={`lane-card ${lane.lane}`}>
      <div className="lane-head">
        <div>
          <span className="lane-key">{lane.lane}</span>
          <h3>{lane.label}</h3>
        </div>
        <span className={`lane-state ${lane.status}`}>
          <span />
          {lane.status}
        </span>
      </div>
      <p>{lane.detail ?? LANE_COPY[lane.lane]}</p>
      <div className="lane-count">
        <strong>{lane.count ?? "—"}</strong>
        <span>{lane.count_label}</span>
      </div>
      {lane.last_item ? (
        <div className="lane-last">
          <span>latest</span>
          {lane.last_item.url ? (
            <a href={lane.last_item.url} target="_blank" rel="noreferrer">
              {lane.last_item.title}
            </a>
          ) : (
            lane.last_item.title
          )}
        </div>
      ) : (
        <div className="lane-last muted">
          {lane.configured ? "No current item returned" : "Set the lane URL to enable"}
        </div>
      )}
    </article>
  );
}

export function Overview() {
  const lanes = useQuery({
    queryKey: ["overview"],
    queryFn: api.overview,
    staleTime: 60_000,
  });
  const [query, setQuery] = useState("");
  const preview = useMutation({ mutationFn: (q: string) => api.fusionPreview(q) });

  function gather(event: FormEvent) {
    event.preventDefault();
    const value = query.trim();
    if (value && !preview.isPending) preview.mutate(value);
  }

  return (
    <div>
      <p className="section-note">
        One supervisor routes each question to the relevant source-domain workers, then hands
        their source-rated evidence to ARGUS&apos;s single synthesis panel. Routing and gathering
        are deterministic and model-free; the expensive reasoning still happens only once.
      </p>

      {lanes.isPending && <div className="center muted">Checking source lanes…</div>}
      {lanes.isError && <div className="error">Could not load the fusion overview.</div>}
      {lanes.data && <div className="lane-grid">{lanes.data.map((lane) => <LaneCard key={lane.lane} lane={lane} />)}</div>}

      <section className="panel fusion-preview">
        <h2>Supervisor gather preview</h2>
        <p className="section-note">
          Ask a question to see which mini-agents wake up and what they gather before any LLM
          synthesis runs.
        </p>
        <form className="composer-box" onSubmit={gather}>
          <textarea
            rows={2}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="e.g. Assess GNSS jamming affecting regional aviation"
            aria-label="Fusion preview question"
          />
          <button className="primary" disabled={!query.trim() || preview.isPending}>
            {preview.isPending ? "Gathering…" : "Route + gather"}
          </button>
        </form>
        {preview.isError && <div className="error">{(preview.error as Error).message}</div>}
        {preview.data && (
          <div className="preview-result">
            <div className="lane-chips">
              {preview.data.lanes_consulted.map((lane) => (
                <span key={lane} className={`lane-chip ${lane}`}>
                  {lane} · {preview.data.lane_counts[lane] ?? 0}
                </span>
              ))}
            </div>
            <p className="muted">{preview.data.lane_reason}</p>
            {preview.data.evidence.length > 0 ? (
              preview.data.evidence.map((item) => <EvidenceCard key={item.doc_id} e={item} />)
            ) : (
              <p className="muted">The selected workers returned no matching evidence.</p>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
