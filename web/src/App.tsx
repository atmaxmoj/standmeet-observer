import { useState, useEffect, useMemo, type ComponentType } from "react";
import { Button } from "@/components/ui/button";
import { EpisodesPanel } from "@/components/EpisodesPanel";
import { PlaybooksPanel } from "@/components/PlaybooksPanel";
import { RoutinesPanel } from "@/components/RoutinesPanel";
import { UsagePanel } from "@/components/UsagePanel";
import { LogsPanel } from "@/components/LogsPanel";
import { ManagePanel } from "@/components/ManagePanel";
import { SourceDataPanel } from "@/components/SourceDataPanel";
import { InsightsPanel } from "@/components/InsightsPanel";
import { api, type SourceManifest } from "@/lib/api";

const staticPanels: Record<string, ComponentType> = {
  episodes: EpisodesPanel,
  playbooks: PlaybooksPanel,
  routines: RoutinesPanel,
  insights: InsightsPanel,
  usage: UsagePanel,
  logs: LogsPanel,
  chat: ManagePanel,
};

const memorySidebarItems = [
  { key: "episodes", label: "Episodes" },
  { key: "playbooks", label: "Playbooks" },
  { key: "routines", label: "Routines" },
  { key: "insights", label: "Insights" },
];

const systemSidebarItems = [
  { key: "usage", label: "Usage" },
  { key: "logs", label: "Logs" },
  { key: "chat", label: "Manage" },
];

function PipelineToggle({ online, captureAlive, paused, toggling, onToggle }: {
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
    online: false, episodes: 0, playbooks: 0, routines: 0, cost: 0, captureAlive: false,
  });
  const [paused, setPaused] = useState(false);
  const [toggling, setToggling] = useState(false);

  useEffect(() => {
    const load = async () => {
      try {
        const [s, u, p] = await Promise.all([api.status(), api.usage(30), api.pipeline()]);
        setStatus({
          online: true,
          episodes: s.episode_count,
          playbooks: s.playbook_count,
          routines: s.routine_count ?? 0,
          cost: u.total_cost_usd,
          captureAlive: s.capture_alive,
        });
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
    <header className="shrink-0 flex items-center justify-between px-6 py-4 border-b bg-background" data-testid="header">
      <h1 className="text-sm font-semibold tracking-wider">OBSERVER</h1>
      <div className="flex items-center gap-5 text-xs text-muted-foreground">
        <PipelineToggle online={status.online} captureAlive={status.captureAlive} paused={paused} toggling={toggling} onToggle={togglePipeline} />
        <span data-testid="episode-count">{status.episodes} episodes</span>
        <span data-testid="playbook-count">{status.playbooks} playbooks</span>
        <span data-testid="routine-count">{status.routines} routines</span>
        <span className="font-medium text-primary" data-testid="total-cost">${status.cost.toFixed(4)}</span>
      </div>
    </header>
  );
}

function getHashPanel(): string {
  const hash = window.location.hash.slice(1);
  return hash || "episodes";
}

export default function App() {
  const [active, setActive] = useState(getHashPanel);
  const [sources, setSources] = useState<SourceManifest[]>([]);

  const sourceManifestMap = useMemo(
    () => new Map(sources.map(s => [`source:${s.name}`, s])),
    [sources],
  );

  // Sync hash ↔ active panel
  useEffect(() => {
    window.location.hash = active;
  }, [active]);

  useEffect(() => {
    const onHashChange = () => setActive(getHashPanel());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    api.sources().then(data => setSources(data.sources)).catch(() => {});
  }, []);

  // When sources load, set active to first source if no active selection yet
  useEffect(() => {
    if (sources.length > 0 && !sourceManifestMap.has(active) && !staticPanels[active]) {
      setActive(`source:${sources[0].name}`);
    }
  }, [sources, sourceManifestMap, active]);

  const captureSidebarItems = sources.map(s => ({ key: `source:${s.name}`, label: s.display_name }));

  const sidebarGroups = [
    ...(captureSidebarItems.length > 0 ? [{ label: "Sources", items: captureSidebarItems }] : []),
    { label: "Memory", items: memorySidebarItems },
    { label: "System", items: systemSidebarItems },
  ];

  const renderPanel = () => {
    const manifest = sourceManifestMap.get(active);
    if (manifest) return <div className="flex-1 overflow-y-auto"><SourceDataPanel manifest={manifest} /></div>;
    if (active === "chat") return <ManagePanel />;
    const StaticPanel = staticPanels[active];
    if (StaticPanel) return <div className="flex-1 overflow-y-auto"><StaticPanel /></div>;
    return <p className="p-6 text-muted-foreground">Select a panel</p>;
  };

  return (
    <div className="h-screen flex flex-col bg-background text-foreground">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-48 shrink-0 border-r p-3 space-y-4 overflow-y-auto" data-testid="sidebar">
          {sidebarGroups.map((group) => (
            <div key={group.label}>
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-widest mb-1 px-2">{group.label}</p>
              {group.items.map((item) => (
                <Button
                  key={item.key}
                  variant={active === item.key ? "secondary" : "ghost"}
                  className="w-full justify-start h-8 text-xs"
                  onClick={() => setActive(item.key)}
                  data-testid={`nav-${item.key}`}
                >
                  {item.label}
                </Button>
              ))}
            </div>
          ))}
        </aside>
        <main className="flex-1 flex flex-col overflow-hidden">
          {renderPanel()}
        </main>
      </div>
    </div>
  );
}
