import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import {
  api,
  credibilityLabel,
  reliabilityMeta,
  type BriefOut,
  type EvidenceOut,
} from "../api";

const EXAMPLES = [
  "What is driving instability in the Sahel?",
  "Assess tensions in the South China Sea",
  "Who is behind the recent edge-VPN exploitation wave?",
];

function confTone(c: string | null): string {
  const v = (c ?? "").toLowerCase();
  if (v.includes("high")) return "conf-high";
  if (v.includes("low")) return "conf-low";
  return "conf-moderate";
}

/** Admiralty reliability x credibility, e.g. "B3", coloured by reliability grade. */
function Rating({ rating, reliability, credibility }: Pick<EvidenceOut, "rating" | "reliability" | "credibility">) {
  const meta = reliabilityMeta(reliability);
  const title = `${meta.label} · ${credibilityLabel(credibility)}`;
  return (
    <div className={`rating ${meta.tone}`} title={title}>
      <span className="rv">{rating || reliability}</span>
      <span className="rk">Admiralty</span>
    </div>
  );
}

function EvidenceCard({ e }: { e: EvidenceOut }) {
  // Cyber-fusion evidence (pulled from the sibling SENTINEL graph) carries a campaign id.
  const cyber = e.doc_id.startsWith("campaign:") || e.source === "sentinel";
  return (
    <article className={`ev${cyber ? " cyber" : ""}`}>
      <div className="ev-top">
        <Rating rating={e.rating} reliability={e.reliability} credibility={e.credibility} />
        <div className="ev-body">
          <div className="ev-title">
            {e.url ? (
              <a href={e.url} target="_blank" rel="noreferrer">
                {e.title}
              </a>
            ) : (
              e.title
            )}
          </div>
          <div className="ev-meta">
            <span className="ev-src">{e.source}</span>
            {e.published && <span>{e.published.slice(0, 10)}</span>}
            {cyber && <span className="badge cyber">cyber-fusion</span>}
          </div>
          {e.summary && <p className="ev-summary">{e.summary}</p>}
        </div>
      </div>
    </article>
  );
}

function Brief({ b }: { b: BriefOut }) {
  return (
    <section className="panel">
      <div className="brief-head">
        <span className="brief-q">{b.query}</span>
        <span style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {b.confidence && (
            <span className={`conf ${confTone(b.confidence)}`}>
              <span className="conf-dot" />
              {b.confidence} confidence
            </span>
          )}
          {b.backend && <span className="backend-tag">{b.backend}</span>}
        </span>
      </div>
      {b.key_judgments.length > 0 && (
        <ul className="kj">
          {b.key_judgments.map((k, i) => (
            <li key={i}>{k}</li>
          ))}
        </ul>
      )}
      {b.body && <p className="brief-body">{b.body}</p>}
      {b.citations.length > 0 && (
        <div className="cites">
          {b.citations.map((c) => (
            <span key={c} className="cite">
              {c}
            </span>
          ))}
        </div>
      )}
    </section>
  );
}

export function Workbench() {
  const [query, setQuery] = useState("");
  const retrieve = useMutation({ mutationFn: (q: string) => api.retrieve(q, 8) });
  const brief = useMutation({ mutationFn: (q: string) => api.brief(q) });

  const q = query.trim();
  const busy = retrieve.isPending || brief.isPending;
  const error = retrieve.error ?? brief.error;

  return (
    <div>
      <p className="section-note">
        Ask an intelligence question. <b>Retrieve evidence</b> returns the source-rated open-source
        picture instantly (no model). <b>Generate brief</b> runs the multi-agent ACH panel into a
        cited brief with key judgments and a calibrated confidence — and never overstates a
        low-reliability source.
      </p>

      <div className="ask">
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="e.g. What is driving instability in the Sahel?"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && q) brief.mutate(q);
          }}
        />
        <div className="ask-actions">
          <button onClick={() => q && retrieve.mutate(q)} disabled={!q || busy}>
            {retrieve.isPending ? "Retrieving…" : "Retrieve evidence"}
          </button>
          <button className="primary" onClick={() => q && brief.mutate(q)} disabled={!q || busy}>
            {brief.isPending ? "Briefing…" : "Generate brief"}
          </button>
        </div>
      </div>
      <div className="examples">
        {EXAMPLES.map((ex) => (
          <button key={ex} onClick={() => setQuery(ex)} disabled={busy}>
            {ex}
          </button>
        ))}
      </div>

      {error && <div className="error">{(error as Error).message}</div>}

      {brief.data && <Brief b={brief.data} />}

      {retrieve.data && (
        <div>
          <p className="section-note" style={{ marginBottom: 10 }}>
            <b>{retrieve.data.length}</b> rated evidence items, best-matching first. The badge is the{" "}
            <b>NATO Admiralty rating</b> — source reliability (A–F) × information credibility (1–6).
          </p>
          {retrieve.data.length === 0 && <p className="muted">No evidence in the corpus for this query.</p>}
          {retrieve.data.map((e) => (
            <EvidenceCard key={e.doc_id} e={e} />
          ))}
        </div>
      )}
    </div>
  );
}
