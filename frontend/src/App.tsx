import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "./api";
import { Workbench } from "./views/Workbench";
import { Narratives } from "./views/Narratives";
import { Collection } from "./views/Collection";

function EngineStatus() {
  const { data, isError } = useQuery({ queryKey: ["model"], queryFn: api.model, staleTime: 30_000 });
  if (isError) return <span className="statusbar"><span className="live off" />API offline</span>;
  if (!data) return <span className="statusbar"><span className="live" style={{ opacity: 0.4 }} />connecting…</span>;
  return (
    <span className="statusbar" title={`configured: ${data.configured}`}>
      <span className="live" />
      engine: {data.active}
    </span>
  );
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 60_000, retry: 1 } },
});

const TABS = [
  { id: "ask", label: "Workbench", sub: "ask a question, get a cited brief" },
  { id: "narr", label: "Narrative watch", sub: "which framings are coordinated?" },
  { id: "coll", label: "Collection", sub: "what's in the corpus, how reliable?" },
] as const;
type Tab = (typeof TABS)[number]["id"];

export default function App() {
  const [tab, setTab] = useState<Tab>("ask");
  return (
    <QueryClientProvider client={queryClient}>
      <div className="shell">
        <header className="masthead">
          <div className="brand">
            <svg className="brand-mark" viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
              <path
                d="M2.5 12 C5 7.6 8.5 5.7 12 5.7 S19 7.6 21.5 12 C19 16.4 15.5 18.3 12 18.3 S5 16.4 2.5 12 Z"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.3"
                opacity="0.55"
              />
              <circle cx="12" cy="12" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
              <circle cx="12" cy="12" r="1.5" fill="currentColor" />
            </svg>
            <h1>ARGUS</h1>
          </div>
          <p className="tagline">All-source analyst workbench — open-source evidence, rated and cited.</p>
          <div style={{ marginTop: 10 }}><EngineStatus /></div>
        </header>
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t.id} className={t.id === tab ? "active" : ""} onClick={() => setTab(t.id)}>
              {t.label}
              <em>{t.sub}</em>
            </button>
          ))}
        </nav>
        {/* Keep every view mounted and toggle visibility — switching tabs must never wipe
            the chat thread or an in-flight brief (live-reported bug). */}
        <div hidden={tab !== "ask"}><Workbench /></div>
        <div hidden={tab !== "narr"}><Narratives /></div>
        <div hidden={tab !== "coll"}><Collection /></div>
      </div>
    </QueryClientProvider>
  );
}
