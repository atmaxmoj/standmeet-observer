import { useCallback, useEffect, useState } from "react";
import { api, type Episode } from "@/lib/api";
import { fmtTime, timeAgo } from "@/lib/utils";
import { useSelection } from "@/hooks/useSelection";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Pagination } from "@/components/Pagination";
import { SelectionBar } from "@/components/SelectionBar";
import { SearchInput } from "@/components/SearchInput";

const PAGE_SIZE = 20;

function parseSummary(raw: string): string {
  try { return JSON.parse(raw).summary || raw; } catch { return raw; }
}

export function EpisodesPanel() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = useCallback(async (p: number = 1) => {
    setLoading(true);
    try {
      const data = await api.episodes(PAGE_SIZE, (p - 1) * PAGE_SIZE, search);
      setEpisodes(data.episodes);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [search]);

  const sel = useSelection("episodes", () => load(page));
  useEffect(() => { load(1); }, [load]);

  return (
    <div data-testid="episodes-panel">
      <div className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <SearchInput onSearch={setSearch} />
          <Button variant="outline" size="sm" onClick={() => load(1)}>Refresh</Button>
        </div>

        {loading ? (
        <p className="text-muted-foreground text-center py-12">Loading...</p>
      ) : !episodes.length ? (
        <div className="text-muted-foreground text-center py-12">
          <p>No episodes yet</p>
          <p className="text-xs mt-2">Episodes are created when an idle gap (&gt;5min) closes a capture window</p>
        </div>
      ) : (
        <div className="space-y-3">
          {episodes.map((e) => (
            <Card key={e.id} data-testid="episode-card"
              className={`cursor-pointer transition-colors ${sel.selected.has(e.id) ? "ring-1 ring-primary bg-primary/5" : "hover:bg-accent/50"}`}
              onClick={() => sel.toggle(e.id)} onContextMenu={(ev) => { ev.preventDefault(); sel.toggle(e.id); }}
            >
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-normal">{parseSummary(e.summary)}</CardTitle>
                <CardDescription className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                  <span data-testid="episode-id">#{e.id}</span>
                  <span>{e.app_names}</span>
                  <span>{e.frame_count} frames</span>
                  <span>{fmtTime(e.started_at)} — {fmtTime(e.ended_at)}</span>
                  <span>{timeAgo(e.created_at)}</span>
                </CardDescription>
              </CardHeader>
            </Card>
          ))}
        </div>
        )}
      </div>

      {sel.active ? (
        <SelectionBar count={sel.selected.size} allCount={episodes.length}
          onSelectAll={() => sel.toggleAll(episodes.map((e) => e.id))} onClear={sel.clear}
          onDelete={sel.deleteSelected} deleting={sel.deleting} />
      ) : (
        <div className="sticky bottom-0 bg-background/80 backdrop-blur-sm border-t py-2 flex justify-center">
          <Pagination page={page} totalPages={totalPages} onPageChange={load} />
        </div>
      )}
    </div>
  );
}
