import { useCallback, useEffect, useState } from "react";
import { api, type AudioFrame } from "@/lib/api";
import { timeAgo, fmtTime } from "@/lib/utils";
import { useSelection } from "@/hooks/useSelection";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Pagination } from "@/components/Pagination";
import { SelectionBar } from "@/components/SelectionBar";
import { SearchInput } from "@/components/SearchInput";

const PAGE_SIZE = 30;

export function AudioPanel() {
  const [frames, setFrames] = useState<AudioFrame[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = useCallback(async (p: number = 1) => {
    setLoading(true);
    try {
      const data = await api.audio(PAGE_SIZE, (p - 1) * PAGE_SIZE, search);
      setFrames(data.audio ?? []);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [search]);

  const sel = useSelection("audio_frames", () => load(page));
  useEffect(() => { load(1); }, [load]);

  return (
    <div className="space-y-4" data-testid="audio-panel">
      <div className="flex items-center justify-between">
        <SearchInput onSearch={setSearch} />
        <Button variant="outline" size="sm" onClick={() => load(1)}>Refresh</Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-center py-12">Loading...</p>
      ) : !frames.length ? (
        <div className="text-muted-foreground text-center py-12">
          <p>No audio transcriptions yet</p>
          <p className="text-xs mt-2">First chunk arrives after 5 minutes of recording</p>
        </div>
      ) : (
        <div className="space-y-2">
          {frames.map((a) => (
            <Card key={a.id} data-testid="audio-card"
              className={`cursor-pointer transition-colors ${sel.selected.has(a.id) ? "ring-1 ring-primary bg-primary/5" : "hover:bg-accent/50"}`}
              onClick={() => sel.active ? sel.toggle(a.id) : sel.toggle(a.id)}
              onContextMenu={(e) => { e.preventDefault(); sel.toggle(a.id); }}
            >
              <CardContent className="p-3">
                <div className="flex items-center gap-3 mb-2">
                  <span className="text-xs text-muted-foreground">{fmtTime(a.timestamp)}</span>
                  <span className="text-[10px] text-muted-foreground/60">{timeAgo(a.timestamp)}</span>
                  <Badge variant={a.source === "speaker" ? "default" : "outline"}>
                    {a.source === "speaker" ? "🔊" : "🎤"}
                  </Badge>
                  <Badge variant="outline">{a.language || "?"}</Badge>
                  <span className="text-[10px] text-muted-foreground">{a.duration_seconds.toFixed(0)}s</span>
                </div>
                <p className="text-sm text-foreground/80 whitespace-pre-wrap">{a.text}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {sel.active ? (
        <SelectionBar count={sel.selected.size} allCount={frames.length}
          onSelectAll={() => sel.toggleAll(frames.map((f) => f.id))} onClear={sel.clear}
          onDelete={sel.deleteSelected} deleting={sel.deleting} />
      ) : (
        <div className="sticky bottom-0 bg-background/80 backdrop-blur-sm border-t py-2 flex justify-center">
          <Pagination page={page} totalPages={totalPages} onPageChange={load} />
        </div>
      )}
    </div>
  );
}
