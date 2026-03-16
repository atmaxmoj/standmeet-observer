import { Button } from "@/components/ui/button";

export function SelectionBar({ count, allCount, onSelectAll, onClear, onDelete, deleting }: {
  count: number; allCount: number; onSelectAll: () => void; onClear: () => void; onDelete: () => void; deleting: boolean;
}) {
  if (count === 0) return null;
  const allSelected = count === allCount && allCount > 0;
  return (
    <div className="sticky bottom-0 flex justify-center pb-3 px-4 pointer-events-none">
      <div className="pointer-events-auto flex items-center gap-3 px-4 py-2.5 rounded-lg border border-border bg-background shadow-lg">
        <span className="text-xs tabular-nums text-muted-foreground" data-testid="selection-count">{count} selected</span>
        <div className="w-px h-4 bg-border" />
        <button onClick={allSelected ? onClear : onSelectAll} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
          {allSelected ? "Deselect all" : `Select all ${allCount}`}
        </button>
        <div className="w-px h-4 bg-border" />
        <Button variant="destructive" size="sm" className="h-7 text-xs" onClick={onDelete} disabled={deleting}>
          {deleting ? "Deleting..." : "Delete"}
        </Button>
        <button onClick={onClear} data-testid="selection-cancel" className="text-xs text-muted-foreground hover:text-foreground transition-colors ml-1">
          Cancel
        </button>
      </div>
    </div>
  );
}
