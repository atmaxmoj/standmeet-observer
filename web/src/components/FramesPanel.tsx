import { useEffect, useState } from "react";
import { api, type Frame } from "@/lib/api";
import { timeAgo, fmtTime } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Pagination } from "@/components/Pagination";

const PAGE_SIZE = 30;

export function FramesPanel() {
  const [frames, setFrames] = useState<Frame[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [expandedIds, setExpandedIds] = useState<Set<number>>(new Set());

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = async (p: number) => {
    setLoading(true);
    try {
      const data = await api.frames(PAGE_SIZE, (p - 1) * PAGE_SIZE);
      setFrames(data.frames);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { load(1); }, []);

  const toggle = (id: number) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  return (
    <div className="space-y-4 pb-16" data-testid="frames-panel">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => load(1)}>
          Refresh
        </Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-center py-12">Loading...</p>
      ) : !frames.length ? (
        <p className="text-muted-foreground text-center py-12">No frames captured yet</p>
      ) : (
        <div className="space-y-2">
          {frames.map((f) => (
            <Card
              key={f.id}
              className="cursor-pointer hover:bg-accent/50 transition-colors"
              onClick={() => toggle(f.id)}
              data-testid="frame-card"
            >
              <CardContent className="p-3">
                <div className="flex items-start gap-4">
                  <div className="shrink-0 w-40">
                    <div className="text-xs text-muted-foreground">{fmtTime(f.timestamp)}</div>
                    <div className="text-[10px] text-muted-foreground/60">{timeAgo(f.timestamp)}</div>
                  </div>
                  <div className="shrink-0 w-36">
                    <div className="text-xs font-medium text-primary truncate">{f.app_name}</div>
                    <div className="text-[10px] text-muted-foreground truncate">{f.window_name}</div>
                    <Badge variant="secondary" className="mt-1 text-[10px]">
                      display {f.display_id}
                    </Badge>
                  </div>
                  <div
                    className={`text-xs text-foreground/80 whitespace-pre-wrap break-words flex-1 ${
                      expandedIds.has(f.id) ? "" : "max-h-12 overflow-hidden"
                    }`}
                  >
                    {f.text}
                  </div>
                </div>
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
