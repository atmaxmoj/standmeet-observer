import { useEffect, useState } from "react";
import { api, type Episode } from "@/lib/api";
import { fmtTime, timeAgo } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Pagination } from "@/components/Pagination";

const PAGE_SIZE = 20;

function parseSummary(raw: string): string {
  try {
    const parsed = JSON.parse(raw);
    return parsed.summary || raw;
  } catch {
    return raw;
  }
}

export function EpisodesPanel() {
  const [episodes, setEpisodes] = useState<Episode[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = async (p: number) => {
    setLoading(true);
    try {
      const data = await api.episodes(PAGE_SIZE, (p - 1) * PAGE_SIZE);
      setEpisodes(data.episodes);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { load(1); }, []);

  return (
    <div className="space-y-4 pb-16" data-testid="episodes-panel">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => load(1)}>
          Refresh
        </Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-center py-12">Loading...</p>
      ) : !episodes.length ? (
        <div className="text-muted-foreground text-center py-12">
          <p>No episodes yet</p>
          <p className="text-xs mt-2">First episode after 30min window completes</p>
        </div>
      ) : (
        <div className="space-y-3">
          {episodes.map((e) => (
            <Card key={e.id} data-testid="episode-card">
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

      <div className="fixed bottom-0 left-0 right-0 bg-background/80 backdrop-blur-sm border-t py-2 flex justify-center z-50">
        <Pagination page={page} totalPages={totalPages} onPageChange={load} />
      </div>
    </div>
  );
}
