import { useEffect, useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { FramesPanel } from "@/components/FramesPanel";
import { AudioPanel } from "@/components/AudioPanel";
import { EpisodesPanel } from "@/components/EpisodesPanel";
import { PlaybooksPanel } from "@/components/PlaybooksPanel";
import { OsEventsPanel } from "@/components/OsEventsPanel";
import { UsagePanel } from "@/components/UsagePanel";
import { api } from "@/lib/api";

function Header() {
  const [status, setStatus] = useState({
    online: false,
    episodes: 0,
    playbooks: 0,
    cost: 0,
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
          cost: u.total_cost_usd,
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
    <header className="flex items-center justify-between px-6 py-4 border-b" data-testid="header">
      <h1 className="text-sm font-semibold tracking-wider">BISIMULATOR</h1>
      <div className="flex items-center gap-5 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5" data-testid="engine-status">
          <span
            className={`w-2 h-2 rounded-full ${
              status.online ? (paused ? "bg-yellow-500" : "bg-green-500") : "bg-destructive"
            }`}
          />
          Engine
        </span>
        <button
          onClick={togglePipeline}
          disabled={toggling || !status.online}
          data-testid="pipeline-toggle"
          className={`px-2 py-0.5 rounded text-[10px] font-medium transition-colors ${
            paused
              ? "bg-green-500/15 text-green-400 hover:bg-green-500/25"
              : "bg-yellow-500/15 text-yellow-400 hover:bg-yellow-500/25"
          } disabled:opacity-50`}
        >
          {paused ? "Resume" : "Pause"}
        </button>
        <span data-testid="episode-count">{status.episodes} episodes</span>
        <span data-testid="playbook-count">{status.playbooks} playbooks</span>
        <span className="font-medium text-primary" data-testid="total-cost">${status.cost.toFixed(4)}</span>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-background">
      <Header />
      <div className="p-6">
        <Tabs defaultValue="frames">
          <TabsList>
            <TabsTrigger value="frames">Capture</TabsTrigger>
            <TabsTrigger value="audio">Audio</TabsTrigger>
            <TabsTrigger value="os-events">OS Events</TabsTrigger>
            <TabsTrigger value="episodes">Episodes</TabsTrigger>
            <TabsTrigger value="playbooks">Playbook</TabsTrigger>
            <TabsTrigger value="usage">Usage</TabsTrigger>
          </TabsList>
          <div className="mt-4">
            <TabsContent value="frames"><FramesPanel /></TabsContent>
            <TabsContent value="audio"><AudioPanel /></TabsContent>
            <TabsContent value="os-events"><OsEventsPanel /></TabsContent>
            <TabsContent value="episodes"><EpisodesPanel /></TabsContent>
            <TabsContent value="playbooks"><PlaybooksPanel /></TabsContent>
            <TabsContent value="usage"><UsagePanel /></TabsContent>
          </div>
        </Tabs>
      </div>
    </div>
  );
}
