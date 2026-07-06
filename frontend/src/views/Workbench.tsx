import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  api,
  credibilityLabel,
  reliabilityMeta,
  type AchScore,
  type BriefMode,
  type BriefOut,
  type EvidenceOut,
} from "../api";

const EXAMPLES = [
  "What is driving instability in the Sahel?",
  "Assess tensions in the South China Sea",
  "Who is behind the recent edge-VPN exploitation wave?",
];

type Mode = BriefMode | "evidence";

/** Honest stage labels per mode — quick is one model pass, deliberate is the full panel. */
const STAGES: Record<Mode, string[]> = {
  auto: [
    "Retrieving source-rated evidence",
    "Collecting fresh reporting if coverage is thin",
    "Routing analytic effort (quick vs full panel)",
    "Producing the cited brief",
  ],
  quick: ["Retrieving source-rated evidence", "Drafting the cited brief — one model pass"],
  deliberate: [
    "Retrieving source-rated evidence",
    "Framing competing hypotheses",
    "Analyst ⇄ Red Team deliberation",
    "ACH adjudication + calibrating confidence",
    "Assembling the cited brief",
  ],
  evidence: ["Retrieving source-rated evidence"],
};

type Msg =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "brief"; data: BriefOut }
  | { id: number; role: "evidence"; query: string; items: EvidenceOut[] }
  | { id: number; role: "error"; text: string };

function confTone(c: string | null): string {
  const v = (c ?? "").toLowerCase();
  if (v.includes("high")) return "conf-high";
  if (v.includes("low")) return "conf-low";
  return "conf-moderate";
}

/** Admiralty reliability x credibility, e.g. "B3", coloured by reliability grade. */
function Rating({ rating, reliability, credibility }: Pick<EvidenceOut, "rating" | "reliability" | "credibility">) {
  const meta = reliabilityMeta(reliability);
  return (
    <div className={`rating ${meta.tone}`} title={`${meta.label} · ${credibilityLabel(credibility)}`}>
      <span className="rv">{rating || reliability}</span>
      <span className="rk">Admiralty</span>
    </div>
  );
}

function EvidenceCard({ e }: { e: EvidenceOut }) {
  const cyber = e.doc_id.startsWith("sentinel-cyber:") || e.source === "sentinel-cyber";
  return (
    <article className={`ev${cyber ? " cyber" : ""}`}>
      <div className="ev-top">
        <Rating rating={e.rating} reliability={e.reliability} credibility={e.credibility} />
        <div className="ev-body">
          <div className="ev-title">
            {e.url ? (
              <a href={e.url} target="_blank" rel="noreferrer">{e.title}</a>
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

function Section({ label, sat, children }: { label: string; sat?: string; children: ReactNode }) {
  return (
    <div className="sect">
      <p className="sect-h">
        {label}
        {sat && <span className="sat" title="Structured Analytic Technique">{sat}</span>}
      </p>
      {children}
    </div>
  );
}

function AchMatrix({ rows }: { rows: AchScore[] }) {
  return (
    <div className="ach">
      {rows.map((h, i) => (
        <div key={i} className={`ach-row${i === 0 ? " lead" : ""}`}>
          <div className="ach-h">
            {h.hypothesis}
            {i === 0 && <span className="lead-tag">least-disconfirmed</span>}
          </div>
          <div className="ach-score">
            <span className="sv">{h.inconsistency.toFixed(2)}</span>
            <span className="sk">inconsistency</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function BriefCard({ b }: { b: BriefOut }) {
  const [raw, setRaw] = useState(false);

  // Triage responses (help text / collection guidance) are chat messages, not intelligence
  // products — render just the message, no tradecraft sections or citation footer.
  if (b.backend === "triage") {
    return (
      <section className="panel">
        <div className="brief-head">
          <span className="brief-q">{b.query}</span>
          <span className="backend-tag">instant</span>
        </div>
        <p className="brief-body" style={{ display: "block" }}>{b.body}</p>
      </section>
    );
  }

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
          {b.mode && (
            <span className="backend-tag" title={b.mode_reason ?? undefined}>
              {b.mode === "panel" ? "deliberated" : "quick"}
            </span>
          )}
          {b.backend && <span className="backend-tag">{b.backend}</span>}
        </span>
      </div>

      {(b.mode_reason || (b.auto_collected ?? 0) > 0) && (
        <p className="muted" style={{ margin: "2px 0 10px", fontSize: 12 }}>
          {(b.auto_collected ?? 0) > 0 && <>auto-collected {b.auto_collected} fresh documents · </>}
          {b.mode_reason && <>routed: {b.mode_reason}</>}
        </p>
      )}

      {b.key_judgments.length > 0 ? (
        <ul className="kj">
          {b.key_judgments.map((k, i) => <li key={i}>{k}</li>)}
        </ul>
      ) : (
        // No structured judgments parsed from this model's output — show the raw answer
        // inline rather than hiding it behind the adjudicator-output toggle.
        b.body && <p className="brief-body" style={{ display: "block" }}>{b.body}</p>
      )}

      {b.ach_ranking.length > 0 && (
        <Section label="Competing hypotheses" sat="ACH">
          <AchMatrix rows={b.ach_ranking} />
        </Section>
      )}

      {b.key_assumptions.length > 0 && (
        <Section label="Key assumptions" sat="KAC">
          <ul>{b.key_assumptions.map((a, i) => <li key={i}>{a}</li>)}</ul>
        </Section>
      )}

      {b.indicators.length > 0 && (
        <Section label="Indicators & warnings" sat="I&W">
          <ul>{b.indicators.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </Section>
      )}

      {b.alternatives && (
        <Section label="Most credible alternative">
          <p>{b.alternatives}</p>
        </Section>
      )}

      {b.critique_response && (
        <Section label="Answer to the red team">
          <p>{b.critique_response}</p>
        </Section>
      )}

      {b.gaps && (
        <Section label="Intelligence gaps">
          <p className="gap-txt">{b.gaps}</p>
        </Section>
      )}

      {b.evidence.length > 0 && (
        <Section label={`Cited evidence · ${b.evidence.length} source-rated`}>
          {b.evidence.map((e) => <EvidenceCard key={e.doc_id} e={e} />)}
        </Section>
      )}

      <div className="brief-foot">
        <span>{b.evidence.length === 0 && b.citations.length > 0 ? `${b.citations.length} citations` : "every citation resolves to a real ingested document"}</span>
        {b.body && (
          <button className="raw-toggle" onClick={() => setRaw((v) => !v)}>
            {/* honest label: only the deliberation path has an adjudicator */}
            {raw ? "hide" : "show"} {b.mode === "panel" ? "adjudicator output" : "raw model output"}
          </button>
        )}
      </div>
      {raw && b.body && <p className="brief-body">{b.body}</p>}
    </section>
  );
}

function Deliberating({ mode }: { mode: Mode }) {
  const [stage, setStage] = useState(0);
  const stages = STAGES[mode];
  useEffect(() => {
    if (stages.length < 2) return;
    // Pace the (cosmetic) stage ticker to the mode's real cost: the deliberate panel runs
    // for minutes, quick for tens of seconds.
    const ms = mode === "deliberate" ? 20000 : 8000;
    const t = setInterval(() => setStage((s) => Math.min(s + 1, stages.length - 1)), ms);
    return () => clearInterval(t);
  }, [mode, stages.length]);
  return (
    <section className="panel deliberating">
      {stages.map((label, i) => (
        <div key={i} className={`delib-row ${i < stage ? "done" : i === stage ? "on" : ""}`}>
          <span className="dot" />
          {label}
          {i < stage && " ✓"}
        </div>
      ))}
      {mode === "deliberate" && (
        <p className="muted" style={{ margin: "10px 0 0", fontSize: 12 }}>
          Full panel deliberation runs several minutes on a local model — switch to Quick for a
          chat-speed single-pass brief.
        </p>
      )}
    </section>
  );
}

export function Workbench() {
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  // Auto is the chat default: the effort router decides when a question earns the panel.
  const [mode, setMode] = useState<Mode>("auto");
  const idRef = useRef(0);
  const endRef = useRef<HTMLDivElement>(null);

  const brief = useMutation({
    mutationFn: ({ q, m }: { q: string; m: BriefMode }) => api.brief(q, m),
    onSuccess: (data) => setMessages((m) => [...m, { id: idRef.current++, role: "brief", data }]),
    onError: (e) => setMessages((m) => [...m, { id: idRef.current++, role: "error", text: (e as Error).message }]),
  });
  const retrieve = useMutation({
    mutationFn: (q: string) => api.retrieve(q, 10),
    onSuccess: (items, q) => setMessages((m) => [...m, { id: idRef.current++, role: "evidence", query: q, items }]),
    onError: (e) => setMessages((m) => [...m, { id: idRef.current++, role: "error", text: (e as Error).message }]),
  });

  const busy = brief.isPending || retrieve.isPending;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  function send(text?: string) {
    const q = (text ?? input).trim();
    if (!q || busy) return;
    setMessages((m) => [...m, { id: idRef.current++, role: "user", text: q }]);
    setInput("");
    if (mode === "evidence") retrieve.mutate(q);
    else brief.mutate({ q, m: mode });
  }

  return (
    <div className="chat">
      <div className="thread">
        {messages.length === 0 && !busy && (
          <div className="empty-chat">
            <svg className="eye" viewBox="0 0 24 24" width="34" height="34" aria-hidden="true">
              <path d="M2.5 12 C5 7.6 8.5 5.7 12 5.7 S19 7.6 21.5 12 C19 16.4 15.5 18.3 12 18.3 S5 16.4 2.5 12 Z" fill="none" stroke="currentColor" strokeWidth="1.2" opacity="0.6" />
              <circle cx="12" cy="12" r="3.4" fill="none" stroke="currentColor" strokeWidth="1.3" />
              <circle cx="12" cy="12" r="1.4" fill="currentColor" />
            </svg>
            <p className="section-note" style={{ margin: "0 auto 16px", textAlign: "center" }}>
              Ask an intelligence question and get a <b>cited brief</b> — every judgment backed by
              source-rated evidence. <b>Auto</b> routes each question itself: chat-speed single pass for
              descriptive asks, the multi-agent ACH panel where it matters (attribution, contested or
              low-reliability sourcing) — and collects fresh reporting when the corpus is thin.
            </p>
            <div className="examples" style={{ justifyContent: "center" }}>
              {EXAMPLES.map((ex) => (
                <button key={ex} onClick={() => send(ex)}>{ex}</button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => {
          if (m.role === "user") return <div key={m.id} className="msg-user">{m.text}</div>;
          if (m.role === "error") return <div key={m.id} className="error">{m.text}</div>;
          if (m.role === "brief") return <div key={m.id} className="msg-argus"><BriefCard b={m.data} /></div>;
          return (
            <div key={m.id} className="msg-argus">
              <p className="turn-q">Evidence for “{m.query}” — {m.items.length} rated items, best-matching first.</p>
              {m.items.length === 0 && <p className="muted">No evidence in the corpus for this query.</p>}
              {m.items.map((e) => <EvidenceCard key={e.doc_id} e={e} />)}
            </div>
          );
        })}

        {busy && <div className="msg-argus"><Deliberating mode={mode} /></div>}
        <div ref={endRef} />
      </div>

      <div className="composer">
        <div className="composer-box">
          <textarea
            rows={1}
            value={input}
            placeholder={mode === "evidence" ? "Retrieve rated evidence for…" : "Ask ARGUS an intelligence question…"}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <button className="primary send" onClick={() => send()} disabled={!input.trim() || busy}>
            {busy ? "…" : mode === "evidence" ? "Retrieve" : "Brief"}
          </button>
        </div>
        <div className="composer-hint">
          <span>Enter to send · Shift+Enter for a newline</span>
          <span className="mode-seg">
            <button className={mode === "auto" ? "on" : ""} onClick={() => setMode("auto")} title="The effort router decides: quick for descriptive questions, the full panel for attribution / contested / low-reliability sourcing — and collects fresh reporting when coverage is thin">Auto</button>
            <button className={mode === "quick" ? "on" : ""} onClick={() => setMode("quick")} title="One model pass — chat-speed cited brief (~1 min)">Quick</button>
            <button className={mode === "deliberate" ? "on" : ""} onClick={() => setMode("deliberate")} title="Full multi-agent ACH deliberation — the deep assessment (minutes)">Deliberate</button>
            <button className={mode === "evidence" ? "on" : ""} onClick={() => setMode("evidence")} title="Fast retrieval, no model">Evidence only</button>
          </span>
        </div>
      </div>
    </div>
  );
}
