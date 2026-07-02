/** Typed client for the ARGUS read-only knowledge-graph + agent API. */

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface Health {
  status: string;
  version: string;
}

export interface ModelInfo {
  configured: string; // ARGUS_LLM_BACKEND
  active: string; // the backend that would actually run a brief
  ollama_models: string[];
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
}

export interface NarrativeOut {
  narrative_id: string;
  label: string;
  doc_count: number;
  source_count: number;
  coordination: number | null; // human-review signal in [0,1], not a verdict
  first_seen: string | null;
  last_seen: string | null;
}

export interface BriefOut {
  brief_id: number;
  query: string;
  confidence: string | null;
  backend: string | null;
  key_judgments: string[];
  citations: string[];
  /** Cited evidence with Admiralty ratings (incl. cyber-fusion items), in citation
   *  order. Populated on a fresh POST /brief; [] for persisted listings. */
  evidence: EvidenceOut[];
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

export const api = {
  health: () => get<Health>("/health"),
  model: () => get<ModelInfo>("/model"),
  stats: () => get<Stats>("/stats"),
  sources: () => get<SourceOut[]>("/sources"),
  events: (limit = 50) => get<EventOut[]>(`/events?limit=${limit}`),
  narratives: (limit = 50) => get<NarrativeOut[]>(`/narratives?limit=${limit}`),
  briefs: (limit = 20) => get<BriefOut[]>(`/briefs?limit=${limit}`),
  retrieve: (query: string, k = 8) => post<EvidenceOut[]>("/retrieve", { query, k }),
  brief: (query: string) => post<BriefOut>("/brief", { query }),
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

/** Admiralty information credibility 1-6 → human label. */
export function credibilityLabel(c: number | null): string {
  if (c == null) return "Not rated";
  return (
    [
      "",
      "Confirmed",
      "Probably true",
      "Possibly true",
      "Doubtful",
      "Improbable",
      "Cannot be judged",
    ][c] ?? `Level ${c}`
  );
}
