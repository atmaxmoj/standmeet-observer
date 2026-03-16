import { useEffect, useState } from "react";
import { FramesPanel } from "@/components/FramesPanel";
import { AudioPanel } from "@/components/AudioPanel";
import { EpisodesPanel } from "@/components/EpisodesPanel";
import { PlaybooksPanel } from "@/components/PlaybooksPanel";
import { OsEventsPanel } from "@/components/OsEventsPanel";
import { UsagePanel } from "@/components/UsagePanel";
import { LogsPanel } from "@/components/LogsPanel";
import { api } from "@/lib/api";

/* ── sidebar nav structure ── */

type NavItem = { key: string; label: string };
type NavGroup = { title: string; items: NavItem[] };

const NAV: NavGroup[] = [
  {
    title: "Capture",
    items: [
      { key: "frames", label: "Screen" },
      { key: "audio", label: "Audio" },
      { key: "os-events", label: "OS Events" },
    ],
  },
  {
    title: "Memory",
    items: [
      { key: "episodes", label: "Episodes" },
      { key: "playbooks", label: "Playbook" },
    ],
  },
  {
    title: "Usage",
    items: [{ key: "usage", label: "Cost & Tokens" }],
  },
  {
    title: "Logs",
    items: [{ key: "logs", label: "Pipeline Logs" }],
  },
];

const PANELS: Record<string, React.FC> = {
  frames: FramesPanel,
  audio: AudioPanel,
  "os-events": OsEventsPanel,
  episodes: EpisodesPanel,
  playbooks: PlaybooksPanel,
  usage: UsagePanel,
  logs: LogsPanel,
};

/* ── header ── */

function PipelineToggle({
  online, captureAlive, paused, toggling, onToggle,
}: {
  online: boolean; captureAlive: boolean; paused: boolean; toggling: boolean; onToggle: () => void;
}) {
  const off = paused || !online || !captureAlive;
  return (
    <button
      onClick={onToggle}
      disabled={toggling || !online}
      data-testid="pipeline-toggle"
      className={`flex items-center gap-2 px-2.5 py-1 rounded-full border transition-colors disabled:opacity-50 ${
        !online || !captureAlive ? "border-destructive/40"
          : paused ? "border-yellow-500/40"
          : "border-green-500/40"
      }`}
    >
      <span className="flex items-center gap-1.5" data-testid="engine-status">
        <span className={`w-2 h-2 rounded-full ${
          !online ? "bg-destructive"
            : !captureAlive ? "bg-destructive animate-pulse"
            : paused ? "bg-yellow-500"
            : "bg-green-500 animate-pulse"
        }`} />
        <span className="text-[10px]">
          {!online ? "Offline" : !captureAlive ? "Capture down" : paused ? "Paused" : "Recording"}
        </span>
      </span>
      <span className={`relative w-7 h-3.5 rounded-full transition-colors ${off ? "bg-muted" : "bg-green-500"}`}>
        <span className={`absolute top-0.5 w-2.5 h-2.5 rounded-full bg-white shadow transition-transform ${off ? "left-0.5" : "left-[14px]"}`} />
      </span>
    </button>
  );
}

function Header() {
  const [status, setStatus] = useState({
    online: false, episodes: 0, playbooks: 0, cost: 0, captureAlive: false,
  });
  const [paused, setPaused] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        const [s, u, p] = await Promise.all([api.status(), api.usage(30), api.pipeline()]);
        setStatus({ online: true, episodes: s.episode_count, playbooks: s.playbook_count, cost: u.total_cost_usd, captureAlive: s.capture_alive });
        setPaused(p.paused);
      } catch {
        setStatus((prev) => ({ ...prev, online: false }));
      }
    };
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, []);

  const togglePipeline = async () => {
    setToggling(true);
    try {
      const res = paused ? await api.pipelineResume() : await api.pipelinePause();
      setPaused(res.paused);
    } finally {
      setToggling(false);
    }
  };

  return (
    <header className="fixed top-0 left-0 right-0 z-20 flex items-center justify-between px-6 py-4 border-b bg-background" data-testid="header">
      <h1 className="text-sm font-semibold tracking-wider">OBSERVER</h1>
      <div className="flex items-center gap-5 text-xs text-muted-foreground">
        <PipelineToggle online={status.online} captureAlive={status.captureAlive} paused={paused} toggling={toggling} onToggle={togglePipeline} />
        <span data-testid="episode-count">{status.episodes} episodes</span>
        <span data-testid="playbook-count">{status.playbooks} playbooks</span>
        <span className="font-medium text-primary" data-testid="total-cost">${status.cost.toFixed(4)}</span>
      </div>
    </header>
  );
}

/* ── sidebar ── */

function Sidebar({
  active,
  onSelect,
}: {
  active: string;
  onSelect: (key: string) => void;
}) {
  return (
    <nav className="fixed top-[53px] left-0 bottom-0 w-48 border-r overflow-y-auto py-4 bg-background z-10" data-testid="sidebar">
      {NAV.map((group) => (
        <div key={group.title} className="mb-4">
          <div className="px-4 mb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            {group.title}
          </div>
          {group.items.map((item) => (
            <button
              key={item.key}
              onClick={() => onSelect(item.key)}
              data-testid={`nav-${item.key}`}
              className={`w-full text-left px-4 py-1.5 text-sm transition-colors ${
                active === item.key
                  ? "bg-accent text-accent-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

/* ── app ── */

function readHash(fallback: string) {
  const h = window.location.hash.slice(1);
  return h in PANELS ? h : fallback;
}

function useHashNav(fallback: string) {
  const [active, setActive] = useState(() => readHash(fallback));
  useEffect(() => {
    const onHash = () => setActive(readHash(fallback));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, [fallback]);
  const navigate = (key: string) => { window.location.hash = key; };
  return [active, navigate] as const;
}

export default function App() {
  const [active, setActive] = useHashNav("frames");
  const Panel = PANELS[active];

  return (
    <div className="min-h-screen bg-background pt-[53px]">
      <Header />
      <Sidebar active={active} onSelect={setActive} />
      <main className="ml-48 p-6">
        {Panel && <Panel />}
      </main>
    </div>
  );
}
