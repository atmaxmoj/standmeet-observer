import { useCallback, useEffect, useState } from "react";
import { api, sourceImageUrl, type SourceManifest, type SourceRecord } from "@/lib/api";
import { timeAgo, fmtTime } from "@/lib/utils";
import { useSelection } from "@/hooks/useSelection";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Pagination } from "@/components/Pagination";
import { SelectionBar } from "@/components/SelectionBar";
import { SearchInput } from "@/components/SearchInput";

const PAGE_SIZE = 50;

const BADGE_COLUMNS = new Set(["language", "source", "category", "event_type", "display_id"]);

function RecordDetail({ record, manifest, onClose }: { record: SourceRecord; manifest: SourceManifest; onClose: () => void }) {
  const allColumns = [...manifest.ui.visible_columns, ...manifest.ui.detail_columns];
  const uniqueColumns = [...new Set(allColumns)];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose} data-testid="record-detail">
      <div className="bg-background rounded-lg border shadow-xl max-w-3xl w-full mx-4 max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b">
          <h3 className="text-sm font-medium">{manifest.display_name}</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-lg leading-none px-2" data-testid="record-detail-close">&times;</button>
        </div>
        {/* Show image if there's an image_path */}
        {typeof record.image_path === "string" && record.image_path !== "" && (
          <img src={sourceImageUrl(manifest.name, record.id)} alt="" className="w-full border-b" loading="lazy" />
        )}
        <div className="p-4 space-y-3">
          {uniqueColumns.map((col) => {
            const val = record[col];
            if (val === undefined || val === null || val === "") return null;
            return (
              <div key={col}>
                <span className="text-[10px] uppercase text-muted-foreground">{col}</span>
                <pre className="text-xs whitespace-pre-wrap text-foreground/80 mt-0.5">{String(val)}</pre>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function CellValue({ col, val }: { col: string; val: string }) {
  if (col === "timestamp") {
    return (
      <div className="shrink-0 w-36">
        <div className="text-xs text-muted-foreground">{fmtTime(val)}</div>
        <div className="text-[10px] text-muted-foreground/60">{timeAgo(val)}</div>
      </div>
    );
  }
  if (BADGE_COLUMNS.has(col) && val) {
    return <Badge variant="outline" className="shrink-0 text-[10px]">{val}</Badge>;
  }
  if (col === "url" && val) {
    return (
      <span className="text-xs text-foreground/80 font-mono truncate flex-1" title={val}>
        {val}
      </span>
    );
  }
  if (col === "duration_seconds" && val) {
    return <span className="text-xs text-muted-foreground shrink-0">{Number(val).toFixed(0)}s</span>;
  }
  // Default: text column
  return (
    <span className="text-xs text-foreground/80 truncate flex-1">{val}</span>
  );
}

function RecordCard({ r, manifest, selected, hasImage, onSelect, onOpen }: {
  r: SourceRecord; manifest: SourceManifest; selected: boolean; hasImage: boolean;
  onSelect: () => void; onOpen: () => void;
}) {
  const columns = manifest.ui.visible_columns;
  return (
    <Card
      className={`cursor-pointer transition-colors ${selected ? "ring-1 ring-primary bg-primary/5" : "hover:bg-accent/50"}`}
      onClick={onSelect} onContextMenu={(e) => { e.preventDefault(); onSelect(); }}
      data-testid="source-record-card"
    >
      <CardContent className="p-2 px-3">
        <div className="flex items-start gap-3">
          {columns.map((col) => (
            <CellValue key={col} col={col} val={String(r[col] ?? "")} />
          ))}
          {hasImage && typeof r.image_path === "string" && r.image_path !== "" ? (
            <img src={sourceImageUrl(manifest.name, r.id)} alt=""
              className="shrink-0 w-20 h-14 object-cover rounded border hover:ring-2 hover:ring-primary transition-shadow"
              loading="lazy"
              onClick={(e) => { e.stopPropagation(); onOpen(); }}
            />
          ) : hasImage ? (
            <button onClick={(e) => { e.stopPropagation(); onOpen(); }}
              className="shrink-0 w-20 h-14 rounded border border-dashed flex items-center justify-center text-[10px] text-muted-foreground hover:bg-accent/50 transition-colors">
              OCR
            </button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function SourceDataPanel({ manifest }: { manifest: SourceManifest }) {
  const [records, setRecords] = useState<SourceRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [detailRecord, setDetailRecord] = useState<SourceRecord | null>(null);

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const hasImage = manifest.ui.detail_columns.includes("image_path");

  const load = useCallback(async (p: number = 1) => {
    setLoading(true);
    try {
      const data = await api.sourceData(manifest.name, PAGE_SIZE, (p - 1) * PAGE_SIZE, search);
      setRecords(data.records);
      setTotal(data.total ?? 0);
      setPage(p);
    } catch (e) { console.error(e); }
    setLoading(false);
  }, [manifest.name, search]);

  const sel = useSelection(manifest.db.table, () => load(page));
  useEffect(() => { load(1); }, [load]);

  return (
    <div data-testid={`source-panel-${manifest.name}`}>
      <div className="p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {manifest.ui.searchable_columns.length > 0 && <SearchInput onSearch={setSearch} />}
          </div>
          <Button variant="outline" size="sm" onClick={() => load(1)}>Refresh</Button>
        </div>

        {loading ? (
          <p className="text-muted-foreground text-center py-12">Loading...</p>
        ) : !records.length ? (
          <div className="text-muted-foreground text-center py-12">
            <p>No {manifest.display_name.toLowerCase()} data yet</p>
            <p className="text-xs mt-2">{manifest.description}</p>
          </div>
        ) : (
          <div className="space-y-1">
            {records.map((r) => (
              <RecordCard key={r.id} r={r} manifest={manifest} hasImage={hasImage}
                selected={sel.selected.has(r.id)}
                onSelect={() => sel.toggle(r.id)}
                onOpen={() => setDetailRecord(r)}
              />
            ))}
          </div>
        )}
      </div>

      {sel.active ? (
        <SelectionBar count={sel.selected.size} allCount={records.length}
          onSelectAll={() => sel.toggleAll(records.map((r) => r.id))} onClear={sel.clear}
          onDelete={sel.deleteSelected} deleting={sel.deleting} />
      ) : (
        <div className="sticky bottom-0 bg-background/80 backdrop-blur-sm border-t py-2 flex justify-center">
          <Pagination page={page} totalPages={totalPages} onPageChange={load} />
        </div>
      )}
      {detailRecord && <RecordDetail record={detailRecord} manifest={manifest} onClose={() => setDetailRecord(null)} />}
    </div>
  );
}
