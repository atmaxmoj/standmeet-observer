import { useCallback, useEffect, useState } from "react";
import { api, frameImageUrl, type Frame } from "@/lib/api";
import { timeAgo, fmtTime } from "@/lib/utils";
import { useSelection } from "@/hooks/useSelection";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Pagination } from "@/components/Pagination";
import { SelectionBar } from "@/components/SelectionBar";
import { SearchInput } from "@/components/SearchInput";

const PAGE_SIZE = 30;

function FrameDetail({ frame, onClose }: { frame: Frame; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose} data-testid="frame-detail">
      <div className="bg-background rounded-lg border shadow-xl max-w-4xl w-full mx-4 max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b">
          <div className="flex items-center gap-3">
            <span className="text-xs text-muted-foreground">{fmtTime(frame.timestamp)}</span>
            <span className="text-xs font-medium text-primary">{frame.app_name}</span>
            <span className="text-xs text-muted-foreground">{frame.window_name}</span>
            <Badge variant="secondary" className="text-[10px]">display {frame.display_id}</Badge>
          </div>
          <button onClick={onClose} data-testid="frame-detail-close" className="text-muted-foreground hover:text-foreground text-lg leading-none px-2">×</button>
        </div>
        {frame.image_path && (
          <img src={frameImageUrl(frame.id)} alt="" className="w-full border-b" loading="lazy" />
        )}
        <pre className="p-4 text-xs whitespace-pre-wrap text-foreground/80">{frame.text}</pre>
      </div>
    </div>
  );
}

function FrameCard({ frame, selected, onSelect, onOpen }: {
  frame: Frame; selected: boolean; onSelect: () => void; onOpen: () => void;
}) {
  return (
    <Card
      className={`cursor-pointer transition-colors ${selected ? "ring-1 ring-primary bg-primary/5" : "hover:bg-accent/50"}`}
      onClick={onSelect}
      onContextMenu={(e) => { e.preventDefault(); onSelect(); }}
      data-testid="frame-card"
    >
      <CardContent className="p-3">
        <div className="flex items-start gap-4">
          <div className="shrink-0 w-40">
            <div className="text-xs text-muted-foreground">{fmtTime(frame.timestamp)}</div>
            <div className="text-[10px] text-muted-foreground/60">{timeAgo(frame.timestamp)}</div>
          </div>
          <div className="shrink-0 w-36">
            <div className="text-xs font-medium text-primary truncate">{frame.app_name}</div>
            <div className="text-[10px] text-muted-foreground truncate">{frame.window_name}</div>
            <Badge variant="secondary" className="mt-1 text-[10px]">display {frame.display_id}</Badge>
          </div>
          <div className="text-xs text-foreground/80 whitespace-pre-wrap break-words flex-1 max-h-12 overflow-hidden">
            {frame.text}
          </div>
          {frame.image_path ? (
            <img src={frameImageUrl(frame.id)} alt=""
              className="shrink-0 w-20 h-14 object-cover rounded border hover:ring-2 hover:ring-primary transition-shadow"
              loading="lazy"
              onClick={(e) => { e.stopPropagation(); onOpen(); }}
            />
          ) : (
            <button onClick={(e) => { e.stopPropagation(); onOpen(); }}
              className="shrink-0 w-20 h-14 rounded border border-dashed flex items-center justify-center text-[10px] text-muted-foreground hover:bg-accent/50 transition-colors">
              OCR
            </button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function FramesPanel() {
  const [frames, setFrames] = useState<Frame[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [detailFrame, setDetailFrame] = useState<Frame | null>(null);
  const [search, setSearch] = useState("");

  const totalPages = Math.ceil(total / PAGE_SIZE);

  const load = useCallback(async (p: number = 1) => {
    setLoading(true);
    try {
      const data = await api.frames(PAGE_SIZE, (p - 1) * PAGE_SIZE, search);
      setFrames(data.frames);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [search]);

  const sel = useSelection("frames", () => load(page));
  useEffect(() => { load(1); }, [load]);

  return (
    <div className="space-y-4 pb-16" data-testid="frames-panel">
      <div className="flex items-center justify-between">
        <SearchInput onSearch={setSearch} />
        <Button variant="outline" size="sm" onClick={() => load(1)}>Refresh</Button>
      </div>
      {loading ? (
        <p className="text-muted-foreground text-center py-12">Loading...</p>
      ) : !frames.length ? (
        <p className="text-muted-foreground text-center py-12">No frames captured yet</p>
      ) : (
        <div className="space-y-2">
          {frames.map((f) => (
            <FrameCard key={f.id} frame={f} selected={sel.selected.has(f.id)}
              onSelect={() => sel.toggle(f.id)} onOpen={() => setDetailFrame(f)} />
          ))}
        </div>
      )}
      {sel.active ? (
        <SelectionBar count={sel.selected.size} allCount={frames.length}
          onSelectAll={() => sel.toggleAll(frames.map((f) => f.id))} onClear={sel.clear}
          onDelete={sel.deleteSelected} deleting={sel.deleting} />
      ) : (
        <div className="fixed bottom-0 left-48 right-0 bg-background/80 backdrop-blur-sm border-t py-2 flex justify-center z-50">
          <Pagination page={page} totalPages={totalPages} onPageChange={load} />
        </div>
      )}
      {detailFrame && <FrameDetail frame={detailFrame} onClose={() => setDetailFrame(null)} />}
    </div>
  );
}
