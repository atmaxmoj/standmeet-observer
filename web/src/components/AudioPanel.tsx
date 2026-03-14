import { useEffect, useState } from "react";
import { api, type AudioFrame } from "@/lib/api";
import { timeAgo, fmtTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Pagination } from "@/components/Pagination";

const PAGE_SIZE = 30;

export function AudioPanel() {
  const [frames, setFrames] = useState<AudioFrame[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = async (p: number) => {
    setLoading(true);
    try {
      const data = await api.audio(PAGE_SIZE, (p - 1) * PAGE_SIZE);
      setFrames(data.audio ?? []);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { load(1); }, []);

  return (
    <div className="space-y-4 pb-16" data-testid="audio-panel">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => load(1)}>
          Refresh
        </Button>
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
            <Card key={a.id} data-testid="audio-card">
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

      <div className="fixed bottom-0 left-0 right-0 bg-background/80 backdrop-blur-sm border-t py-2 flex justify-center z-50">
        <Pagination page={page} totalPages={totalPages} onPageChange={load} />
      </div>
    </div>
  );
}
