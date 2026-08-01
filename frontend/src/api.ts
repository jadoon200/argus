/** Typed client for the ARGUS read-only knowledge-graph + agent API. */

// Same-origin in a production build (FastAPI serves this SPA and the API from one host, so
// relative URLs need no CORS and no baked-in hostname); localhost:8000 in dev (`make ui` on
// :5173 talks to `make api` on :8000). VITE_API_URL overrides both — e.g. a split deploy
// where the static site and the API live on different origins.
const BASE = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? "" : "http://localhost:8000");

export interface Health {
  status: string;
  version: string;
}

export interface ModelInfo {
  configured: string; // ARGUS_LLM_BACKEND
  active: string; // the backend that would actually run a brief
  ollama_models: string[];
  /** False on the slim deploy: enrichment needs an embedding model it does not ship. */
  can_ingest: boolean;
}

export interface Stats {
  documents: number;
  sources: number;
  events: number;
  narratives: number;
  briefs: number;
}

export interface SourceOut {
  label: string;
  name: string | null;
  kind: string | null;
  reliability: string; // NATO Admiralty source reliability A-F
}

export interface EventOut {
  event_id: string;
  title: string;
  occurred: string | null;
  doc_count: number;
  source_count: number;
  /** Framing divergence [0,1] across the event's sources — the contested-event signal. */
  divergence?: number | null;
}

/** A DISARM influence-ops technique a narrative's framing resembles (advisory). */
export interface DisarmTag {
  technique_id: string; // DISARM Red Framework id, e.g. "T0086.002"
  name: string;
  phase: string; // Plan | Prepare | Execute | Assess
  score: number;
}

export interface NarrativeOut {
  narrative_id: string;
  label: string;
  doc_count: number;
  source_count: number;
  coordination: number | null; // human-review signal in [0,1], not a verdict
  /** DISARM techniques the framing resembles — human-review signal, never a verdict. */
  disarm: DisarmTag[];
  first_seen: string | null;
  last_seen: string | null;
}

/** One competing hypothesis's ACH score — lower inconsistency = less disconfirmed = stronger. */
export interface AchScore {
  hypothesis: string;
  inconsistency: number;
  consistent: number;
  inconsistent: number;
}

export interface BriefOut {
  brief_id: number;
  query: string;
  confidence: string | null;
  backend: string | null;
  key_judgments: string[];
  citations: string[];
  // Structured Analytic Technique sections — the full intelligence product.
  key_assumptions: string[];
  indicators: string[];
  hypotheses: string[];
  ach_ranking: AchScore[];
  alternatives: string | null;
  gaps: string | null;
  critique_response: string | null;
  /** Cited evidence with Admiralty ratings (incl. cyber-fusion items), in citation
   *  order. Populated on a fresh POST /brief; [] for persisted listings. */
  evidence: EvidenceOut[];
  /** Adaptive-path transparency (fresh POST /brief only): mode that actually ran, the
   *  router's reason, and how many docs collect-on-demand fetched for this question. */
  mode?: string | null;
  mode_reason?: string | null;
  auto_collected?: number | null;
  /** Domain workers actually consulted by the deterministic fusion supervisor. */
  lanes_consulted: string[];
  lane_reason?: string | null;
  body: string;
  created_at: string | null;
}

/** A source-rated open-source evidence item (Admiralty reliability x credibility). */
export interface EvidenceOut {
  doc_id: string;
  title: string;
  source: string;
  reliability: string; // A-F
  credibility: number | null; // 1-6
  rating: string; // compact Admiralty code, e.g. "B2"
  summary: string | null;
  published: string | null;
  url: string | null;
}

export interface OverviewLaneOut {
  lane: string;
  label: string;
  status: "ready" | "unreachable" | "disabled";
  configured: boolean;
  reachable: boolean;
  count: number | null;
  count_label: string;
  last_item: EvidenceOut | null;
  detail: string | null;
}

export interface FusionPreviewOut {
  lanes_consulted: string[];
  lane_reason: string;
  lane_counts: Record<string, number>;
  evidence: EvidenceOut[];
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json() as Promise<T>;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    // Surface the API's structured guards (422 too-long, 429 rate-limited, 503 busy).
    const detail = await res
      .json()
      .then((b) => (b as { detail?: string }).detail)
      .catch(() => null);
    throw new Error(detail ?? `${path}: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** "auto" = the effort router decides; "quick" = one model pass; "deliberate" = full panel. */
export type BriefMode = "auto" | "quick" | "deliberate";

export interface IngestResult {
  fetched: number; // articles GDELT returned for the query
  new: number; // documents actually added
  documents: number; // corpus size after ingest + enrich
}

export const api = {
  health: () => get<Health>("/health"),
  model: () => get<ModelInfo>("/model"),
  stats: () => get<Stats>("/stats"),
  overview: () => get<OverviewLaneOut[]>("/overview"),
  sources: () => get<SourceOut[]>("/sources"),
  events: (limit = 50) => get<EventOut[]>(`/events?limit=${limit}`),
  contested: (limit = 20) => get<EventOut[]>(`/contested?limit=${limit}`),
  narratives: (limit = 50) => get<NarrativeOut[]>(`/narratives?limit=${limit}`),
  briefs: (limit = 20) => get<BriefOut[]>(`/briefs?limit=${limit}`),
  /** Precomputed-brief lookup by exact question — the snapshot path for the model-less
   *  demo deploy. Returns [] when no persisted brief matches. */
  briefLookup: (q: string) => get<BriefOut[]>(`/briefs?q=${encodeURIComponent(q)}&limit=1`),
  retrieve: (query: string, k = 8) => post<EvidenceOut[]>("/retrieve", { query, k }),
  fusionPreview: (query: string, k = 5) =>
    post<FusionPreviewOut>("/fusion/preview", { query, k }),
  brief: (query: string, mode: BriefMode = "auto") => post<BriefOut>("/brief", { query, mode }),
  ingest: (query: string) => post<IngestResult>("/ingest", { query }),
};

/** Admiralty source reliability A-F → human label + severity bucket for badge colour. */
export function reliabilityMeta(grade: string): { label: string; tone: string } {
  const g = (grade || "F").toUpperCase()[0];
  const map: Record<string, { label: string; tone: string }> = {
    A: { label: "Completely reliable", tone: "rel-a" },
    B: { label: "Usually reliable", tone: "rel-b" },
    C: { label: "Fairly reliable", tone: "rel-c" },
    D: { label: "Not usually reliable", tone: "rel-d" },
    E: { label: "Unreliable", tone: "rel-e" },
    F: { label: "Cannot be judged", tone: "rel-f" },
  };
  return map[g] ?? map.F;
}

/** Admiralty information credibility 1-6 → human label. ARGUS scores credibility as a
 *  *corroboration* proxy (how many independent sources reported it), NOT a truth verdict —
 *  so the labels mirror nlp/reliability.py rather than the classic "doubtful/improbable". */
export function credibilityLabel(c: number | null): string {
  if (c == null) return "Not rated";
  return (
    [
      "",
      "Confirmed by other sources",
      "Probably true",
      "Possibly true",
      "Uncorroborated (single source)",
      "Improbable",
      "Cannot be judged",
    ][c] ?? `Level ${c}`
  );
}
