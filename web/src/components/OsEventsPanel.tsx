import { useCallback, useEffect, useState } from "react";
import { api, type OsEvent } from "@/lib/api";
import { timeAgo, fmtTime } from "@/lib/utils";
import { useSelection } from "@/hooks/useSelection";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Pagination } from "@/components/Pagination";
import { SelectionBar } from "@/components/SelectionBar";
import { SearchInput } from "@/components/SearchInput";

const PAGE_SIZE = 50;

const SOURCE_LABELS: Record<string, string> = {
  zsh: "Terminal", bash: "Terminal", powershell: "PowerShell",
  chrome: "Chrome", safari: "Safari", edge: "Edge",
  macos: "macOS",
};

const TYPE_COLORS: Record<string, "default" | "secondary" | "outline"> = {
  shell_command: "default", browser_url: "secondary", os_log: "outline",
};

function EventCard({ event, selected, onSelect }: { event: OsEvent; selected: boolean; onSelect: () => void }) {
  return (
    <Card data-testid="os-event-card"
      className={`cursor-pointer transition-colors ${selected ? "ring-1 ring-primary bg-primary/5" : "hover:bg-accent/50"}`}
      onClick={onSelect} onContextMenu={(e) => { e.preventDefault(); onSelect(); }}
    >
      <CardContent className="p-2 px-3">
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted-foreground shrink-0 w-32">{fmtTime(event.timestamp)}</span>
          <span className="text-[10px] text-muted-foreground/60 shrink-0 w-16">{timeAgo(event.timestamp)}</span>
          <Badge variant={TYPE_COLORS[event.event_type] || "outline"} className="shrink-0 text-[10px]">
            {SOURCE_LABELS[event.source] || event.source}
          </Badge>
          <span className="text-xs text-foreground/80 font-mono truncate flex-1">{event.data}</span>
        </div>
      </CardContent>
    </Card>
  );
}

export function OsEventsPanel() {
  const [events, setEvents] = useState<OsEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = useCallback(async (p: number = 1, eventType = filter) => {
    setLoading(true);
    try {
      const data = await api.osEvents(PAGE_SIZE, (p - 1) * PAGE_SIZE, eventType, search);
      setEvents(data.events ?? []);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [filter, search]);

  const sel = useSelection("os_events", () => load(page));
  useEffect(() => { load(1); }, [load]);

  const setFilterAndLoad = (f: string) => { setFilter(f); load(1, f); };

  return (
    <div data-testid="os-events-panel">
      <div className="p-6 space-y-4">
        <div className="flex justify-between items-center gap-2">
          <div className="flex items-center gap-3">
            <SearchInput onSearch={setSearch} />
            <div className="flex gap-1">
              {[["", "All"], ["shell_command", "Commands"], ["browser_url", "URLs"], ["os_log", "OS Events"]].map(([val, label]) => (
                <Button key={val} variant={filter === val ? "default" : "outline"} size="sm" onClick={() => setFilterAndLoad(val)}>
                  {label}
                </Button>
              ))}
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => load(1)}>Refresh</Button>
        </div>

        {loading ? (
          <p className="text-muted-foreground text-center py-12">Loading...</p>
        ) : !events.length ? (
          <div className="text-muted-foreground text-center py-12">
            <p>No OS events captured yet</p>
            <p className="text-xs mt-2">Shell commands and browser URLs will appear here</p>
          </div>
        ) : (
          <div className="space-y-1">
            {events.map((e) => <EventCard key={e.id} event={e} selected={sel.selected.has(e.id)} onSelect={() => sel.toggle(e.id)} />)}
          </div>
        )}
      </div>

      {sel.active ? (
        <SelectionBar count={sel.selected.size} allCount={events.length}
          onSelectAll={() => sel.toggleAll(events.map((e) => e.id))} onClear={sel.clear}
          onDelete={sel.deleteSelected} deleting={sel.deleting} />
      ) : (
        <div className="sticky bottom-0 bg-background/80 backdrop-blur-sm border-t py-2 flex justify-center">
          <Pagination page={page} totalPages={totalPages} onPageChange={load} />
        </div>
      )}
    </div>
  );
}
